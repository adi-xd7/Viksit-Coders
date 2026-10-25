"""Google AI Studio (Gemini) backend for LLMClient.

Same contract as AnthropicBackend: one structured call -> BackendResult. The
Pydantic schema is sent as the response JSON schema; the reply text is
validated against it in code (never trusted unparsed).

- Thinking: Gemini 3.x uses thinking_level, 2.x a thinking_budget; mapped from
  the role's effort setting.
- Finish reasons: MAX_TOKENS -> "max_tokens"; safety / blocklist / prohibited
  content and prompt blocks -> "refusal" (LLMClient turns that into LLMError).
- Rate limits: an optional minimum interval between request starts (shared by
  all agent threads), and bounded retries on 429 / 5xx / timeouts that honour
  the server's retryDelay. Other errors are not retried.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from pydantic import ValidationError

from ragnarok.config import Settings
from ragnarok.llm.client import BackendResult, LLMError

_REFUSAL = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}
_RETRY_CODES = {429, 500, 502, 503, 504}
_BUDGET = {"low": 1024, "medium": 4096, "high": 8192, "xhigh": 16384, "max": 24576}


def thinking_config(model: str, effort: str, types) -> Any:
    if re.match(r"gemini-(\d+)", model) and int(re.match(r"gemini-(\d+)", model).group(1)) >= 3:
        return types.ThinkingConfig(thinking_level="low" if effort in ("low", "medium") else "high")
    if "flash-lite" in model and effort == "low":
        return types.ThinkingConfig(thinking_budget=0)
    return types.ThinkingConfig(thinking_budget=_BUDGET.get(effort, 4096))


def retry_delay(exc: Exception) -> float | None:
    """The server-suggested wait (RetryInfo.retryDelay, e.g. "23s"), if any."""
    details = getattr(exc, "details", None) or {}
    for d in (details.get("error", {}) if isinstance(details, dict) else {}).get("details", []) or []:
        m = re.match(r"([\d.]+)s$", str(d.get("retryDelay", "")))
        if m:
            return float(m.group(1))
    return None


class _Pacer:
    """Minimum interval between request starts, across threads."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last = 0.0

    def wait(self, interval: float, sleep=time.sleep, now=time.monotonic) -> None:
        if interval <= 0:
            return
        with self.lock:
            delay = self.last + interval - now()
            if delay > 0:
                sleep(delay)
            self.last = now()


PACER = _Pacer()


class GeminiBackend:
    def __init__(self, settings: Settings, client: Any = None, sleep=time.sleep, on_retry=None) -> None:
        from google import genai
        from google.genai import errors, types

        self.settings = settings
        self.types, self.errors = types, errors
        self.sleep = sleep
        self.on_retry = on_retry or (lambda summary, payload: None)  # LLMClient logs each retry to the audit log
        self.client = client or genai.Client(api_key=settings.require_api_key(),
                                             http_options=types.HttpOptions(timeout=int(settings.gemini_request_timeout_s * 1000)))

    def _config(self, *, system, schema, effort, max_tokens, model):
        t = self.types
        return t.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                       response_json_schema=schema.model_json_schema(), max_output_tokens=max_tokens,
                                       thinking_config=thinking_config(model, effort, t))

    def _send(self, model, user, config):
        import httpx

        s = self.settings
        attempts = max(s.max_retries, s.llm_rate_limit_retries) + 1
        for i in range(attempts):
            PACER.wait(s.llm_min_interval_s, sleep=self.sleep)
            try:
                return self.client.models.generate_content(model=model, contents=user, config=config)
            except self.errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code not in _RETRY_CODES or i == attempts - 1:
                    kind = "rate limited" if code == 429 else f"API error {code}"
                    raise LLMError(f"{kind} after {i + 1} attempt(s): {str(exc)[:300]}") from exc
                wait = retry_delay(exc) or min(5.0 * 2 ** i, s.llm_rate_limit_max_wait_s)
                reason = f"HTTP {code}"
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if i >= s.max_retries:
                    raise LLMError(f"request failed after {i + 1} attempt(s): {type(exc).__name__}: {exc}") from exc
                wait = min(5.0 * 2 ** i, s.llm_rate_limit_max_wait_s)
                reason = type(exc).__name__
            pause = min(wait + 1.0, s.llm_rate_limit_max_wait_s)
            self.on_retry(f"{model}: attempt {i + 1}/{attempts} failed ({reason}); retrying in {pause:.0f} s",
                          {"model": model, "attempt": i + 1, "max_attempts": attempts, "reason": reason, "wait_s": pause})
            self.sleep(pause)
        raise LLMError("unreachable: retries exhausted")  # pragma: no cover

    def call(self, *, model, system, user, schema, effort, max_tokens, agent) -> BackendResult:
        resp = self._send(model, user, self._config(system=system, schema=schema, effort=effort,
                                                    max_tokens=max_tokens, model=model))
        u = getattr(resp, "usage_metadata", None)
        inp = (getattr(u, "prompt_token_count", 0) or 0) if u else 0
        out = ((getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0)) if u else 0
        fb = getattr(resp, "prompt_feedback", None)
        if fb is not None and getattr(fb, "block_reason", None):
            return BackendResult(parsed=None, raw_text="", input_tokens=inp, output_tokens=out, stop_reason="refusal",
                                 model=model, error=f"prompt blocked: {fb.block_reason}")
        cands = getattr(resp, "candidates", None) or []
        reason = str(getattr(cands[0], "finish_reason", "") or "").split(".")[-1].upper() if cands else ""
        stop = "max_tokens" if reason == "MAX_TOKENS" else "refusal" if reason in _REFUSAL else "end_turn"
        text = ""
        try:
            text = resp.text or ""
        except (ValueError, AttributeError):
            text = ""
        if stop != "end_turn":
            return BackendResult(parsed=None, raw_text=text[:2000], input_tokens=inp, output_tokens=out, stop_reason=stop,
                                 model=model, error=f"finish reason {reason}")
        try:
            parsed = schema.model_validate_json(text)
        except (ValidationError, ValueError) as exc:
            return BackendResult(parsed=None, raw_text=text[:6000], input_tokens=inp, output_tokens=out,
                                 stop_reason="invalid", model=model, error=str(exc)[:2000])
        return BackendResult(parsed=parsed, raw_text=text, input_tokens=inp, output_tokens=out, stop_reason="end_turn",
                             model=model)
