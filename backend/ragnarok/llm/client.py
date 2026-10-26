"""LLM wrapper used by every agent (provider: Gemini or Anthropic, see make_backend).

- Structured output only: every call returns a validated Pydantic object.
  Schema validation plus an optional semantic validator. Schema failures (and
  "essential" semantic problems) get ONE repair call, then a controlled
  LLMOutputError. With allow_residual and REPAIR_MODE=residual_first, problems
  in optional parts are not repaired: the output is returned at once and the
  caller drops the invalid parts in code (logged).
- Bounded retries (SDK retries transient errors MAX_RETRIES times), a request
  timeout, and refusals reported as errors (never parsed as content).
- Token accounting per agent and per case, and a hard cap on model requests per
  case (MAX_LLM_CALLS_PER_CASE); budgets are checked before every call and
  LimitHit is raised when a call would start over budget.
- Every request is recorded (agent, label, stage, repair, tokens) in the ledger.
- Model chain (Gemini): each model has its own daily quota. When the model in use
  reports its daily quota as used up (or keeps failing), the same request goes to
  the next model in the chain; used-up models are skipped until their reset time
  (persisted in SQLite, shared by all processes). Every switch is logged. When the
  whole chain is used up the case pauses (QuotaPause) instead of failing.
- Optional response cache scoped to ONE case: replies are stored per case and
  read back only when the same case is resumed, so finished steps replay
  without API calls. Never shared across cases.
- The backend is injectable so tests run with a scripted (mocked) model.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ragnarok.config import Settings
from ragnarok.models import AgentName

T = TypeVar("T", bound=BaseModel)
Validator = Callable[[Any], list[str]]  # returns a list of problems; [] = valid


class LLMError(RuntimeError):
    """The model call failed in a controlled way (API error, refusal, invalid output)."""


class LLMOutputError(LLMError):
    """Output still invalid after the single repair attempt."""


class QuotaExhausted(LLMError):
    """A model's daily request quota is used up (raised by a backend without retrying)."""

    def __init__(self, model: str, retry_after_s: float | None, message: str) -> None:
        super().__init__(message)
        self.model, self.retry_after_s = model, retry_after_s


class ModelUnavailable(LLMError):
    """A model kept failing (server errors / timeouts) after the backend's bounded retries."""

    def __init__(self, model: str, message: str) -> None:
        super().__init__(message)
        self.model = model


class QuotaPause(RuntimeError):
    """Every model in the chain has used up its daily quota: the case pauses and can be
    resumed after `resume_after` (finished steps then replay from the case cache).
    Deliberately not an LLMError, so no agent treats it as its own failure."""

    def __init__(self, resume_after: datetime, models: list[str]) -> None:
        super().__init__(f"daily request quota used up for {', '.join(models)}; resumable after "
                         f"{resume_after.strftime('%Y-%m-%d %H:%M')} UTC")
        self.resume_after, self.models = resume_after, models


class LimitHit(RuntimeError):
    def __init__(self, what: str, used: int, limit: int) -> None:
        super().__init__(f"{what} limit reached ({used}/{limit})")
        self.what, self.used, self.limit = what, used, limit


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class BackendResult(Generic[T]):
    parsed: T | None
    raw_text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    model: str
    error: str | None = None  # validation error text when parsing failed
    cached: bool = False  # replayed from the case's response cache (no API request)


class Backend(Protocol):
    def call(self, *, model: str, system: str, user: str, schema: type[T], effort: str,
             max_tokens: int, agent: AgentName) -> BackendResult[T]: ...


class AnthropicBackend:
    """Real API backend: messages.parse with a Pydantic output_format."""

    FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")  # server-side refusal fallback supported

    def __init__(self, settings: Settings) -> None:
        import anthropic

        self._anthropic = anthropic
        self.settings = settings
        self.client = anthropic.Anthropic(api_key=settings.require_api_key(), timeout=settings.request_timeout_s,
                                          max_retries=settings.max_retries)

    def call(self, *, model, system, user, schema, effort, max_tokens, agent):
        a = self._anthropic
        kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, system=system,
                                      messages=[{"role": "user", "content": user}], output_format=schema,
                                      output_config={"effort": effort})
        try:
            if self.settings.llm_refusal_fallback and model in self.FALLBACK_MODELS:
                resp = self.client.beta.messages.parse(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.parse(**kwargs)
        except (ValidationError, ValueError) as exc:  # the reply did not validate against the schema
            return BackendResult(parsed=None, raw_text="", input_tokens=0, output_tokens=0, stop_reason="invalid",
                                 model=model, error=str(exc)[:2000])
        except a.APITimeoutError as exc:
            raise LLMError(f"request timed out after retries: {exc}") from exc
        except a.RateLimitError as exc:
            raise LLMError(f"rate limited after retries: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise LLMError(f"connection failed after retries: {exc}") from exc
        except a.BadRequestError as exc:
            raise LLMError(f"bad request (not retried): {exc.message}") from exc
        except a.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        return BackendResult(parsed=getattr(resp, "parsed_output", None), raw_text=text,
                             input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                             stop_reason=resp.stop_reason, model=resp.model)


def make_backend(settings: Settings) -> Backend:
    """The real backend for the configured provider (LLM_PROVIDER)."""
    if settings.llm_provider == "gemini":
        from ragnarok.llm.gemini import GeminiBackend

        return GeminiBackend(settings)
    return AnthropicBackend(settings)


@dataclass
class TokenLedger:
    per_agent_limit: int
    per_case_limit: int
    call_limit: int | None = None  # model requests per case (cache replays do not count)
    by_agent: dict[str, Usage] = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)  # one per request, in order
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def case_total(self) -> int:
        return sum(u.total for u in self.by_agent.values())

    @property
    def calls_used(self) -> int:
        with self.lock:
            return sum(1 for r in self.records if not r["cached"])

    def check(self, agent: AgentName) -> None:
        with self.lock:
            used = self.by_agent.get(agent.value, Usage()).total
            if used >= self.per_agent_limit:
                raise LimitHit(f"token budget for {agent.value}", used, self.per_agent_limit)
            if self.case_total >= self.per_case_limit:
                raise LimitHit("token budget for the case", self.case_total, self.per_case_limit)
            calls = sum(1 for r in self.records if not r["cached"])
            if self.call_limit is not None and calls >= self.call_limit:
                raise LimitHit("LLM calls for the case", calls, self.call_limit)

    def add(self, agent: AgentName, inp: int, out: int) -> None:
        with self.lock:
            u = self.by_agent.setdefault(agent.value, Usage())
            u.input_tokens += inp
            u.output_tokens += out
            u.calls += 1

    def record(self, rec: dict) -> dict:
        with self.lock:
            rec = {"n": len(self.records) + 1, **rec}
            self.records.append(rec)
            return rec

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self.lock:
            return {k: {"input": v.input_tokens, "output": v.output_tokens, "calls": v.calls} for k, v in self.by_agent.items()}

    def call_summary(self) -> dict[str, Any]:
        """Requests by agent, stage and label (cache replays counted separately)."""
        with self.lock:
            recs = list(self.records)
        real = [r for r in recs if not r["cached"]]

        def count(key) -> dict[str, int]:
            out: dict[str, int] = {}
            for r in real:
                k = key(r)
                out[k] = out.get(k, 0) + 1
            return dict(sorted(out.items()))
        return {"calls_used": len(real), "calls_limit": self.call_limit, "cached_replays": len(recs) - len(real),
                "repairs": sum(1 for r in real if r["repair"]), "failed_requests": sum(1 for r in real if r.get("failed")),
                "by_model": count(lambda r: r.get("model", "")),
                "input_tokens": sum(r["input_tokens"] for r in real), "output_tokens": sum(r["output_tokens"] for r in real),
                "by_agent": count(lambda r: r["agent"]), "by_stage": count(lambda r: f"run {r['run']} {r['stage']}"),
                "by_label": count(lambda r: r["label"] + (" [repair]" if r["repair"] else ""))}


class ResponseCache:
    """Stage-level reply cache for ONE case (SQLite table llm_cache), keyed by
    sha256(model, system, user, schema name). Replies are always written; they are
    read only when `reading` is on, i.e. when the same case is resumed."""

    def __init__(self, db_path, case_id: str, reading: bool = False) -> None:
        self.db_path = db_path
        self.case_id = case_id
        self.reading = reading

    @staticmethod
    def key(model: str, system: str, user: str, schema_name: str) -> str:
        return hashlib.sha256(json.dumps([model, system, user, schema_name]).encode()).hexdigest()

    def get(self, key: str) -> tuple[str, int, int] | None:
        if not self.reading:
            return None
        from ragnarok.store.db import Store  # own connection: called from advocate threads

        with Store(self.db_path) as s:
            return s.llm_cache_get(self.case_id, key)

    def put(self, key: str, agent: str, label: str, schema_name: str, result_json: str, inp: int, out: int) -> None:
        from ragnarok.store.db import Store

        with Store(self.db_path) as s:
            s.llm_cache_put(self.case_id, key, agent, label, schema_name, result_json, inp, out)


class ModelPool:
    """Which models are currently unusable (daily quota used up, or repeated failures), and
    until when. Persisted in SQLite (table model_quota) when a db path is given, so the CLI,
    the API and later cases all skip a used-up model until its reset; in memory otherwise."""

    def __init__(self, db_path=None, scope: str = "") -> None:
        self.db_path = db_path
        self.scope = scope  # the API key's fingerprint: quotas belong to one key's project; a new key starts clean
        self.mem: dict[str, tuple[str, str]] = {}
        self.lock = threading.Lock()

    def _name(self, model: str) -> str:
        return f"{self.scope}|{model}" if self.scope else model

    def _all(self) -> dict[str, tuple[str, str]]:
        if self.db_path is None:
            rows = dict(self.mem)
        else:
            from ragnarok.store.db import Store

            with Store(self.db_path) as s:
                rows = s.model_unavailable()
        prefix = f"{self.scope}|" if self.scope else ""
        return {k[len(prefix):]: v for k, v in rows.items() if (k.startswith(prefix) if prefix else "|" not in k)}

    def blocked(self, now: datetime | None = None) -> dict[str, tuple[datetime, str]]:
        now = now or datetime.now(timezone.utc)
        out = {}
        for m, (until, why) in self._all().items():
            t = datetime.fromisoformat(until)
            if t > now:
                out[m] = (t, why)
        return out

    def mark(self, model: str, until: datetime, reason: str) -> None:
        with self.lock:
            if self.db_path is None:
                self.mem[self._name(model)] = (until.isoformat(), reason)
                return
            from ragnarok.store.db import Store

            with Store(self.db_path) as s:
                s.set_model_unavailable(self._name(model), until.isoformat(), reason)


class LLMClient:
    def __init__(self, settings: Settings, ledger: TokenLedger, backend: Backend | None = None,
                 on_event: Callable[[str, AgentName, str, dict], None] | None = None,
                 cache: ResponseCache | None = None, context: Callable[[], dict] | None = None,
                 pool: ModelPool | None = None) -> None:
        self.settings = settings
        self.ledger = ledger
        self.backend = backend or make_backend(settings)
        self.on_event = on_event or (lambda *a: None)
        self.cache = cache
        self.pool = pool or ModelPool()
        self.context = context or (lambda: {"stage": "", "run": 0})  # trial stage/run at call time (for the records)
        if hasattr(self.backend, "on_retry"):  # make provider retries visible in the audit log
            self.backend.on_retry = lambda summary, payload: self.on_event("retry", AgentName.SYSTEM, summary, payload)

    def role(self, agent: AgentName) -> str:
        return "judge" if agent == AgentName.ODIN else "advocate"

    def model_for(self, agent: AgentName) -> str:
        return self.settings.model_for(self.role(agent))

    def chain_for(self, agent: AgentName) -> list[str]:
        return self.settings.model_chain(self.role(agent))

    def _replay(self, agent, system, user, schema, base) -> BackendResult | None:
        """Resume: a reply this case already received for this exact prompt, from any model of the chain."""
        if self.cache is None or not self.cache.reading:
            return None
        for model in self.chain_for(agent):
            key = ResponseCache.key(model, system, user, schema.__name__)
            hit = self.cache.get(key)
            if hit is None:
                continue
            try:
                parsed = schema.model_validate_json(hit[0])
            except (ValidationError, ValueError):
                continue
            rec = self.ledger.record(base | {"model": model, "cached": True, "input_tokens": 0, "output_tokens": 0,
                                             "cached_tokens": hit[1] + hit[2], "stop_reason": "end_turn", "ms": 0})
            self.on_event("cache_hit", agent, f"{rec['label']}: reply replayed from this case's response cache "
                          "(no API request)", {"call": rec, "cache_key": key})
            return BackendResult(parsed=parsed, raw_text=hit[0], input_tokens=0, output_tokens=0,
                                 stop_reason="end_turn", model=model, cached=True)
        return None

    def _once(self, agent: AgentName, system: str, user: str, schema: type[T], effort: str, label: str = "",
              repair: bool = False) -> BackendResult[T]:
        ctx = self.context()
        chain = self.chain_for(agent)
        base = {"agent": agent.value, "label": label or schema.__name__, "schema": schema.__name__, "repair": repair,
                "stage": ctx.get("stage", ""), "run": ctx.get("run", 0), "model": chain[0]}
        replayed = self._replay(agent, system, user, schema, base)
        if replayed is not None:
            return replayed
        blocked = self.pool.blocked()
        tried: list[str] = []
        for model in chain:
            if model in blocked:
                continue
            self.ledger.check(agent)
            t0 = time.monotonic()
            try:
                res = self.backend.call(model=model, system=system, user=user, schema=schema, effort=effort,
                                        max_tokens=self.settings.llm_max_output_tokens, agent=agent)
            except (QuotaExhausted, ModelUnavailable) as exc:
                quota = isinstance(exc, QuotaExhausted)
                wait = (exc.retry_after_s or 3600.0) if quota else self.settings.model_cooldown_s
                until = datetime.now(timezone.utc) + timedelta(seconds=wait)
                self.pool.mark(model, until, "daily quota used up" if quota else f"unavailable: {str(exc)[:200]}")
                blocked[model] = (until, "")
                tried.append(model)
                self.ledger.record(base | {"model": model, "cached": False, "failed": "quota" if quota else "unavailable",
                                           "input_tokens": 0, "output_tokens": 0, "stop_reason": "error",
                                           "ms": int((time.monotonic() - t0) * 1000)})
                nxt = next((m for m in chain if m not in blocked), None)
                self.on_event("model_switch", agent, f"{base['label']}: {model} "
                              + ("daily request quota used up" if quota else "unavailable (server errors)")
                              + f" until {until.strftime('%Y-%m-%d %H:%M')} UTC; "
                              + (f"switching to {nxt}" if nxt else "no other model in the chain is available"),
                              {"model": model, "reason": "quota" if quota else "unavailable", "until": until.isoformat(),
                               "next_model": nxt, "chain": chain, "error": str(exc)[:300]})
                continue
            self.ledger.add(agent, res.input_tokens, res.output_tokens)
            self.ledger.record(base | {"model": model, "cached": False, "input_tokens": res.input_tokens,
                                       "output_tokens": res.output_tokens, "stop_reason": res.stop_reason,
                                       "ms": int((time.monotonic() - t0) * 1000)})
            if res.stop_reason == "refusal":
                raise LLMError(f"{agent.value}: the model refused the request")
            if self.cache is not None and res.parsed is not None and res.stop_reason not in ("max_tokens", "invalid"):
                try:
                    self.cache.put(ResponseCache.key(model, system, user, schema.__name__), agent.value, base["label"],
                                   schema.__name__, res.parsed.model_dump_json(), res.input_tokens, res.output_tokens)
                except Exception as exc:  # noqa: BLE001 - the cache is an optimisation; never break a call
                    self.on_event("cache_error", agent, f"{base['label']}: response cache write failed: {exc}"[:500], {})
            return res
        # nothing left in the chain
        # pause when a used-up quota is involved; resume as soon as the first model in the chain is free
        # again, which may be a model that is only cooling down after server errors
        blocked = {m: (t, why) for m, (t, why) in self.pool.blocked().items() if m in chain}
        if any("quota" in why for _, why in blocked.values()) and self.settings.quota_pause:
            raise QuotaPause(min(t for t, _ in blocked.values()), chain)
        raise LLMError(f"{agent.value}: no model available in the chain ({', '.join(chain)}): "
                       + "; ".join(f"{m} until {t.strftime('%H:%M')} UTC" for m, (t, _) in self.pool.blocked().items()
                                   if m in chain))

    def structured(self, agent: AgentName, system: str, user: str, schema: type[T], *, effort: str = "medium",
                   validate: Validator | None = None, label: str = "", allow_residual: bool = False,
                   essential: Validator | None = None) -> T:
        """One call, validated; at most one repair call; then LLMOutputError.

        allow_residual=True: semantic problems may remain; the caller must then drop the
        invalid parts (and log them). With REPAIR_MODE=residual_first such output is
        returned without a repair call unless `essential` reports a problem (a part the
        caller cannot drop, e.g. a missing ruling). Schema failures always get the one
        repair, then raise."""
        res = self._once(agent, system, user, schema, effort, label)
        problems = self._problems(res, validate)
        if not problems:
            return res.parsed  # type: ignore[return-value]
        if (allow_residual and self.settings.repair_mode == "residual_first" and res.parsed is not None
                and res.stop_reason != "max_tokens"):
            fatal = essential(res.parsed) if essential else []
            if not fatal:
                self.on_event("residual", agent, f"{label}: {len(problems)} problem(s) in optional parts; no repair call, "
                              "invalid parts will be dropped by code", {"problems": problems[:20], "repaired": False})
                return res.parsed  # type: ignore[return-value]
        self.on_event("repair", agent, f"{label}: output invalid, one repair attempt", {"problems": problems[:20]})
        previous = res.parsed.model_dump_json() if res.parsed is not None else res.raw_text[:6000]
        repair = (
            f"{user}\n\n<repair_request>\nYour previous answer could not be accepted. Problems:\n"
            + "\n".join(f"- {p}" for p in problems[:20])
            + f"\n\nYour previous answer was:\n{previous}\n\nReturn a corrected answer in the same schema. "
            "Fix only what the problems require; do not invent citations or numbers.\n</repair_request>"
        )
        res2 = self._once(agent, system, repair, schema, effort, label, repair=True)
        problems2 = self._problems(res2, validate)
        if problems2 and allow_residual and res2.parsed is not None and res2.stop_reason != "max_tokens":
            self.on_event("residual", agent, f"{label}: {len(problems2)} problem(s) remain after repair; invalid parts "
                          "will be dropped by code", {"problems": problems2[:20], "repaired": True})
            return res2.parsed  # type: ignore[return-value]
        if problems2:
            raise LLMOutputError(f"{agent.value} {label}: output invalid after one repair attempt: "
                                 + "; ".join(problems2[:8]))
        return res2.parsed  # type: ignore[return-value]

    @staticmethod
    def _problems(res: BackendResult, validate: Validator | None) -> list[str]:
        if res.stop_reason == "max_tokens":
            return ["the answer was cut off at the output token limit; be more concise"]
        if res.parsed is None:
            return [f"output did not match the schema: {res.error or 'unparseable'}"]
        return validate(res.parsed) if validate else []


def schema_json(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=None)[:4000]
