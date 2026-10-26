"""Model chain: a used-up daily quota (or a failing model) moves the request to the next
model; used-up models are skipped until their reset (persisted); a case whose whole chain is
used up pauses and resumes later with only the missing requests.

Models are scripted (tests/fake_llm.py) or the SDK's own error types: no API calls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from google.genai import errors
from pydantic import BaseModel

from conftest import SYNTH_PACK
from fake_llm import ScriptedBackend
from ragnarok.config import Settings
from ragnarok.ingest.pipeline import ingest_pack
from ragnarok.llm.client import (
    BackendResult,
    LLMClient,
    LLMError,
    ModelPool,
    ModelUnavailable,
    QuotaExhausted,
    QuotaPause,
    TokenLedger,
)
from ragnarok.llm.gemini import GeminiBackend
from ragnarok.models import AgentName, LogEventType
from ragnarok.retrieval.service import RetrievalService
from ragnarok.store.db import Store
from ragnarok.trial.machine import Stage, Trial
from ragnarok.trial.runner import CaseRunner, case_status
from test_trial import AS_OF, QUESTION

CHAIN = "model-a,model-b,model-c"


class Out(BaseModel):
    x: int


class ChainBackend:
    """Wraps the scripted model. `quota[model] = n`: that model's daily quota is used up after n
    successful requests; `down`: models that always fail with server errors. Records the model
    of every request (including refused ones)."""

    def __init__(self, inner=None, quota: dict[str, int] | None = None, down: set[str] | None = None):
        self.inner = inner or ScriptedBackend()
        self.quota = dict(quota or {})
        self.down = set(down or ())
        self.served: dict[str, int] = {}
        self.models: list[str] = []

    def call(self, *, model, **kw):
        self.models.append(model)
        if model in self.down:
            raise ModelUnavailable(model, f"{model}: API error 503 after 3 attempt(s)")
        if model in self.quota and self.served.get(model, 0) >= self.quota[model]:
            raise QuotaExhausted(model, 3600.0, f"{model}: daily request quota used up (429)")
        self.served[model] = self.served.get(model, 0) + 1
        return self.inner.call(model=model, **kw)


class Seq:
    def __init__(self, items):
        self.items = list(items)
        self.models = []

    def call(self, *, model, **kw):
        self.models.append(model)
        r = self.items.pop(0)
        if isinstance(r, Exception):
            raise r
        return BackendResult(parsed=r, raw_text="", input_tokens=10, output_tokens=10, stop_reason="end_turn", model=model)


@pytest.fixture()
def settings(tmp_path):
    return Settings(_env_file=None, cases_dir=tmp_path / "cases", gemini_api_key="test-key", gemini_model_chain=CHAIN)


def client(settings, backend, pool=None, events=None):
    ev = events if events is not None else []
    c = LLMClient(settings, TokenLedger(10**6, 10**6), backend, on_event=lambda *a: ev.append(a), pool=pool or ModelPool())
    return c, ev


# ------------------------------------------------------------ settings ---


def test_chain_settings():
    s = Settings(_env_file=None, gemini_model_chain=" m1, m2 ,m1,", gemini_model_judge="j")
    assert s.model_chain("advocate") == ["m1", "m2"] and s.model_chain("judge") == ["j", "m1", "m2"]
    assert Settings(_env_file=None, gemini_model_chain="m1,m2", gemini_judge_chain="m2").model_chain("judge") == ["m2"]
    plain = Settings(_env_file=None)
    assert plain.model_chain("advocate") == [plain.gemini_model_advocate]  # no chain set: the single model as before
    assert Settings(_env_file=None, llm_provider="anthropic", gemini_model_chain="m1").model_chain("advocate") == [
        Settings(_env_file=None).model_advocate]


# ------------------------------------------------------------ client ---


def test_daily_quota_moves_the_request_to_the_next_model(settings):
    b = Seq([QuotaExhausted("model-a", 7200, "a used up"), Out(x=1), Out(x=2)])
    pool = ModelPool()
    c, ev = client(settings, b, pool)
    assert c.structured(AgentName.THOR, "s", "u", Out, label="thor brief").x == 1
    assert b.models == ["model-a", "model-b"]
    switch = [e for e in ev if e[0] == "model_switch"]
    assert switch and switch[0][3]["model"] == "model-a" and switch[0][3]["next_model"] == "model-b"
    assert [(r["model"], r.get("failed")) for r in c.ledger.records] == [("model-a", "quota"), ("model-b", None)]
    until, why = pool.blocked()["model-a"]
    assert "quota" in why and until > datetime.now(timezone.utc) + timedelta(seconds=7000)
    # the next request skips the used-up model without asking it again
    assert c.structured(AgentName.LOKI, "s", "u2", Out).x == 2 and b.models == ["model-a", "model-b", "model-b"]
    assert c.ledger.call_summary()["failed_requests"] == 1 and c.ledger.call_summary()["by_model"] == {"model-a": 1, "model-b": 2}


def test_failing_model_is_skipped_for_a_cooldown(settings):
    b = Seq([ModelUnavailable("model-a", "503 x3"), Out(x=5)])
    pool = ModelPool()
    c, ev = client(settings.model_copy(update={"model_cooldown_s": 120}), b, pool)
    assert c.structured(AgentName.THOR, "s", "u", Out).x == 5 and b.models == ["model-a", "model-b"]
    until, why = pool.blocked()["model-a"]
    assert why.startswith("unavailable") and until < datetime.now(timezone.utc) + timedelta(seconds=130)


def test_whole_chain_used_up_pauses_or_fails(settings):
    q = lambda m: QuotaExhausted(m, 600 if m == "model-b" else 3000, f"{m} used up")  # noqa: E731
    c, _ = client(settings, Seq([q("model-a"), q("model-b"), q("model-c")]))
    with pytest.raises(QuotaPause) as exc:
        c.structured(AgentName.THOR, "s", "u", Out)
    assert exc.value.models == ["model-a", "model-b", "model-c"]
    assert exc.value.resume_after < datetime.now(timezone.utc) + timedelta(seconds=700)  # the earliest reset (model-b)
    assert not isinstance(exc.value, LLMError)  # never mistaken for one agent's failure
    off = settings.model_copy(update={"quota_pause": False})
    c2, _ = client(off, Seq([q("model-a"), q("model-b"), q("model-c")]))
    with pytest.raises(LLMError):
        c2.structured(AgentName.THOR, "s", "u", Out)


def test_pause_ends_when_the_first_model_is_free_again(settings):
    """Two models out of daily quota for hours, one only cooling down after server errors: the case
    resumes when the cooling-down model is free again, not at the daily reset."""
    q = lambda m: QuotaExhausted(m, 6 * 3600, f"{m} used up")  # noqa: E731
    s = settings.model_copy(update={"model_cooldown_s": 300})
    c, _ = client(s, Seq([q("model-a"), q("model-b"), ModelUnavailable("model-c", "503 x2")]))
    with pytest.raises(QuotaPause) as exc:
        c.structured(AgentName.THOR, "s", "u", Out)
    assert exc.value.resume_after < datetime.now(timezone.utc) + timedelta(seconds=310)


def test_used_up_models_are_remembered_across_processes(settings, tmp_path):
    db = tmp_path / "pool.db"
    Store(db).close()
    c1, _ = client(settings, Seq([QuotaExhausted("model-a", 3600, "x"), Out(x=1)]), ModelPool(db))
    c1.structured(AgentName.THOR, "s", "u", Out)
    b2 = Seq([Out(x=2)])
    c2, _ = client(settings, b2, ModelPool(db))  # e.g. the API process, or the next case
    assert c2.structured(AgentName.THOR, "s", "u", Out).x == 2 and b2.models == ["model-b"]
    ModelPool(db).mark("model-a", datetime.now(timezone.utc) - timedelta(seconds=1), "daily quota used up")  # reset passed
    b3 = Seq([Out(x=3)])
    c3, _ = client(settings, b3, ModelPool(db))
    c3.structured(AgentName.THOR, "s", "u", Out)
    assert b3.models == ["model-a"]  # after its reset the first model is used again


def test_model_blocks_belong_to_one_key(tmp_path):
    db = tmp_path / "pool.db"
    Store(db).close()
    until = datetime.now(timezone.utc) + timedelta(hours=8)
    old_key = ModelPool(db, scope=Settings(_env_file=None, gemini_api_key="key-one").key_fingerprint)
    old_key.mark("gemini-x", until, "daily quota used up")
    assert "gemini-x" in old_key.blocked()
    new_key = ModelPool(db, scope=Settings(_env_file=None, gemini_api_key="key-two").key_fingerprint)
    assert new_key.blocked() == {}  # a new key (another project) starts with its own fresh quotas
    fp = Settings(_env_file=None, gemini_api_key="key-one").key_fingerprint
    assert "key-one" not in fp and len(fp) == 12


# ------------------------------------------------------------ gemini backend ---


def quota_err(per_day: bool, delay: str = "36000s") -> errors.APIError:
    det = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier" if per_day else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]
    return errors.ClientError(429, {"error": {"code": 429, "message": "You exceeded your current quota", "status": "RESOURCE_EXHAUSTED",
                                              "details": det}})


class FakeModels:
    def __init__(self, results):
        self.results = list(results)
        self.n = 0

    def generate_content(self, *, model, contents, config):
        self.n += 1
        r = self.results.pop(0)
        raise r


class FakeClient:
    def __init__(self, results):
        self.models = FakeModels(results)


def test_gemini_daily_quota_is_not_retried():
    s = Settings(_env_file=None, gemini_api_key="k", llm_rate_limit_retries=6)
    slept = []
    b = GeminiBackend(s, client=FakeClient([quota_err(True)]), sleep=slept.append)
    with pytest.raises(QuotaExhausted) as exc:
        b.call(model="gemini-x", system="s", user="u", schema=Out, effort="low", max_tokens=10, agent=AgentName.THOR)
    assert exc.value.retry_after_s == 36000 and b.client.models.n == 1 and slept == []  # one request, no waiting


def test_gemini_per_minute_quota_still_waits_and_server_errors_move_on():
    s = Settings(_env_file=None, gemini_api_key="k", llm_rate_limit_retries=2, llm_server_retries=1)
    slept = []
    b = GeminiBackend(s, client=FakeClient([quota_err(False, "3s"), quota_err(False, "3s"), quota_err(False, "3s")]),
                      sleep=slept.append)
    with pytest.raises(LLMError) as exc:
        b.call(model="m", system="s", user="u", schema=Out, effort="low", max_tokens=10, agent=AgentName.THOR)
    assert not isinstance(exc.value, QuotaExhausted) and b.client.models.n == 3 and len(slept) == 2
    srv = lambda: errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})  # noqa: E731
    b2 = GeminiBackend(s, client=FakeClient([srv(), srv(), srv()]), sleep=slept.append)
    with pytest.raises(ModelUnavailable):
        b2.call(model="m", system="s", user="u", schema=Out, effort="low", max_tokens=10, agent=AgentName.THOR)
    assert b2.client.models.n == 2  # one retry, then the next model of the chain gets the request


# ------------------------------------------------------------ trial ---


@pytest.fixture()
def world(tmp_path, settings, embedder):
    store = Store(tmp_path / "t.db")
    ingest_pack(SYNTH_PACK, store, settings)
    svc = RetrievalService(store, settings, embedder)
    yield store, svc
    store.close()


def test_trial_switches_model_mid_case_and_finishes(world, settings):
    store, svc = world
    b = ChainBackend(quota={"model-a": 4})  # model-a's daily quota runs out after 4 requests
    t = Trial(QUESTION, AS_OF, store, settings, backend=b, service=svc)
    r = t.run()
    assert r.stage == Stage.DONE
    sw = [e for e in store.events(t.case_id) if e.type == LogEventType.MODEL_SWITCH]
    assert len(sw) == 1 and sw[0].payload["model"] == "model-a" and sw[0].payload["next_model"] == "model-b"
    assert "model-a" not in b.models[b.models.index("model-b"):]  # model-a is not asked again after its quota ran out
    calls = json.loads((r.case_dir / "llm_calls.json").read_text(encoding="utf-8"))["summary"]
    assert calls["by_model"]["model-a"] == 5 and calls["failed_requests"] == 1  # 4 answers + the refused request


def test_case_pauses_when_every_model_is_used_up_and_resumes_later(world, settings):
    store, svc = world
    b1 = ChainBackend(quota={"model-a": 3, "model-b": 3, "model-c": 2})  # 8 requests in total today
    t1 = Trial(QUESTION, AS_OF, store, settings, backend=b1, service=svc)
    r1 = t1.run()
    assert r1.stage == Stage.PAUSED and r1.history[-1] == "PAUSED"
    assert not (r1.case_dir / "briefing.json").exists() and not (r1.case_dir / "limitations.md").exists()
    st = case_status(settings, t1.case_id)
    assert st["status"] == "paused" and st["paused_until"] and "PAUSED" in st["history"]
    lim = [e for e in store.events(t1.case_id) if e.type == LogEventType.LIMIT_HIT and e.payload.get("what") == "daily model quota"]
    assert lim and lim[0].payload["models"] == ["model-a", "model-b", "model-c"]
    answered = sum(b1.served.values())
    # the next day: quotas reset (the pool's entries expire); the same case resumes
    pool = ModelPool(store.path, scope=settings.key_fingerprint)
    for m in ("model-a", "model-b", "model-c"):
        pool.mark(m, datetime.now(timezone.utc) - timedelta(seconds=1), "daily quota used up")
    b2 = ChainBackend()
    t2 = Trial(QUESTION, AS_OF, store, settings, backend=b2, service=svc, case_id=t1.case_id)
    r2 = t2.run()
    assert r2.stage == Stage.DONE and r2.briefing_status
    replays = [x for x in t2.ledger.records if x["cached"]]
    assert len(replays) == answered  # every answered request replayed, whichever model gave it
    assert {x["model"] for x in replays} >= {"model-b"} and len(b2.models) == t2.ledger.calls_used  # only the missing ones


def test_api_resumes_a_paused_case_by_itself(world, settings, tmp_path):
    store, svc = world
    s = settings.model_copy(update={"db_path": store.path})
    t1 = Trial(QUESTION, AS_OF, store, s, backend=ChainBackend(quota={"model-a": 2, "model-b": 2, "model-c": 2}),
               service=svc)
    assert t1.run().stage == Stage.PAUSED
    pool = ModelPool(store.path, scope=settings.key_fingerprint)
    for m in ("model-a", "model-b", "model-c"):
        pool.mark(m, datetime.now(timezone.utc) - timedelta(seconds=1), "daily quota used up")
    runner = CaseRunner(s, lambda: svc, backend_factory=lambda: ChainBackend())
    runner._schedule_resume(QUESTION, AS_OF, t1.case_id, t1.case_dir, delay=0.1)
    runner.timers[t1.case_id].join(5)
    runner.join(t1.case_id, 300)
    assert case_status(s, t1.case_id)["status"] in ("complete", "partial")
