"""Gemini backend: request shape, parsing, finish reasons, retries and pacing.
Uses a fake client built from the SDK's own response/error types (no network)."""

from __future__ import annotations

import pytest
from google.genai import errors, types
from pydantic import BaseModel

from ragnarok.config import Settings
from ragnarok.llm.client import LLMClient, LLMError, LLMOutputError, TokenLedger, make_backend
from ragnarok.llm.gemini import GeminiBackend, _Pacer, retry_delay, thinking_config
from ragnarok.models import AgentName


class Out(BaseModel):
    answer: str
    n: int


def resp(text: str, finish: str = "STOP", block: str | None = None) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]),
                                    finish_reason=finish)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=120, candidates_token_count=30,
                                                                  thoughts_token_count=50),
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=block) if block else None)


def err(code: int, delay: str | None = None) -> errors.APIError:
    det = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}] if delay else []
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "message": "x", "status": "S", "details": det}})


class FakeModels:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeClient:
    def __init__(self, results):
        self.models = FakeModels(results)


@pytest.fixture()
def settings():
    return Settings(_env_file=None, gemini_api_key="test-key", llm_rate_limit_retries=3, max_retries=1)


def backend(settings, results):
    slept = []
    b = GeminiBackend(settings, client=FakeClient(results), sleep=slept.append)
    return b, b.client.models, slept


def call(b, schema=Out, effort="medium", model="gemini-3.5-flash"):
    return b.call(model=model, system="sys", user="question", schema=schema, effort=effort, max_tokens=999,
                  agent=AgentName.THOR)


def test_default_provider_builds_gemini_backend(settings):
    assert isinstance(make_backend(settings), GeminiBackend)
    assert LLMClient(settings, TokenLedger(10**6, 10**6), FakeClient([])).model_for(AgentName.ODIN) == settings.gemini_model_judge


def test_request_carries_schema_system_and_limits(settings):
    b, m, _ = backend(settings, [resp('{"answer": "ok", "n": 7}')])
    r = call(b)
    assert r.parsed == Out(answer="ok", n=7) and r.stop_reason == "end_turn"
    assert (r.input_tokens, r.output_tokens) == (120, 80)  # thinking tokens count as output
    cfg = m.calls[0]["config"]
    assert cfg.system_instruction == "sys" and cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema == Out.model_json_schema() and cfg.max_output_tokens == 999
    assert m.calls[0]["contents"] == "question" and m.calls[0]["model"] == "gemini-3.5-flash"


def test_thinking_mapping():
    assert thinking_config("gemini-3.5-flash", "medium", types).thinking_level.value.lower() == "low"
    assert thinking_config("gemini-3.5-flash", "high", types).thinking_level.value.lower() == "high"
    assert thinking_config("gemini-2.5-flash", "high", types).thinking_budget == 8192


def test_invalid_json_goes_to_repair_then_controlled_error(settings):
    b, _, _ = backend(settings, [resp('{"answer": "ok"}'), resp("not json")])
    c = LLMClient(settings, TokenLedger(10**6, 10**6), b)
    with pytest.raises(LLMOutputError):
        c.structured(AgentName.THOR, "s", "u", Out)


def test_safety_block_and_truncation(settings):
    b, _, _ = backend(settings, [resp("", finish="SAFETY")])
    with pytest.raises(LLMError, match="refused"):
        LLMClient(settings, TokenLedger(10**6, 10**6), b).structured(AgentName.ODIN, "s", "u", Out)
    b2, _, _ = backend(settings, [resp('{"answer":', finish="MAX_TOKENS")])
    assert call(b2).stop_reason == "max_tokens"
    b3, _, _ = backend(settings, [resp("", block="PROHIBITED_CONTENT")])
    assert call(b3).stop_reason == "refusal"


def test_rate_limit_retried_with_server_delay_then_succeeds(settings):
    b, m, slept = backend(settings, [err(429, "7s"), err(503), resp('{"answer": "ok", "n": 1}')])
    seen = []
    LLMClient(settings, TokenLedger(10**6, 10**6), b, on_event=lambda *a: seen.append(a))  # wires on_retry
    assert call(b).parsed.n == 1 and len(m.calls) == 3
    assert [a[0] for a in seen] == ["retry", "retry"] and "HTTP 429" in seen[0][2] and seen[1][3]["reason"] == "HTTP 503"
    assert slept[0] == 8.0 and slept[1] > 0  # server delay (+1 s), then backoff


def test_retries_are_bounded_and_end_in_a_controlled_error(settings):
    b, m, _ = backend(settings, [err(429, "1s")] * 10)
    with pytest.raises(LLMError, match="rate limited after 4 attempt"):
        call(b)
    assert len(m.calls) == 4  # llm_rate_limit_retries=3 -> 4 attempts, never unbounded


def test_client_errors_are_not_retried(settings):
    b, m, _ = backend(settings, [err(400), resp('{"answer": "x", "n": 1}')])
    with pytest.raises(LLMError, match="API error 400"):
        call(b)
    assert len(m.calls) == 1


def test_retry_delay_parsing():
    assert retry_delay(err(429, "23s")) == 23.0 and retry_delay(err(429)) is None


def test_pacer_spaces_request_starts():
    p, clock, slept = _Pacer(), [100.0], []

    def sleep(s):
        slept.append(s)
        clock[0] += s
    p.wait(13, sleep=sleep, now=lambda: clock[0])
    clock[0] += 2
    p.wait(13, sleep=sleep, now=lambda: clock[0])
    assert slept == [pytest.approx(11.0)]
    p.wait(0, sleep=sleep, now=lambda: clock[0])
    assert len(slept) == 1
