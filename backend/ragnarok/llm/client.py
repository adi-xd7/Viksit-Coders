"""LLM wrapper used by every agent (provider: Gemini or Anthropic, see make_backend).

- Structured output only: every call returns a validated Pydantic object.
  Schema validation plus an optional semantic validator; on failure ONE repair
  call is made with the errors, then a controlled LLMOutputError.
- Bounded retries (SDK retries transient errors MAX_RETRIES times), a request
  timeout, and refusals reported as errors (never parsed as content).
- Token accounting per agent and per case; budgets are checked before every
  call and LimitHit is raised when a call would start over budget.
- The backend is injectable so tests run with a scripted (mocked) model.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
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
    by_agent: dict[str, Usage] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def case_total(self) -> int:
        return sum(u.total for u in self.by_agent.values())

    def check(self, agent: AgentName) -> None:
        with self.lock:
            used = self.by_agent.get(agent.value, Usage()).total
            if used >= self.per_agent_limit:
                raise LimitHit(f"token budget for {agent.value}", used, self.per_agent_limit)
            if self.case_total >= self.per_case_limit:
                raise LimitHit("token budget for the case", self.case_total, self.per_case_limit)

    def add(self, agent: AgentName, inp: int, out: int) -> None:
        with self.lock:
            u = self.by_agent.setdefault(agent.value, Usage())
            u.input_tokens += inp
            u.output_tokens += out
            u.calls += 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self.lock:
            return {k: {"input": v.input_tokens, "output": v.output_tokens, "calls": v.calls} for k, v in self.by_agent.items()}


class LLMClient:
    def __init__(self, settings: Settings, ledger: TokenLedger, backend: Backend | None = None,
                 on_event: Callable[[str, AgentName, str, dict], None] | None = None) -> None:
        self.settings = settings
        self.ledger = ledger
        self.backend = backend or make_backend(settings)
        self.on_event = on_event or (lambda *a: None)
        if hasattr(self.backend, "on_retry"):  # make provider retries visible in the audit log
            self.backend.on_retry = lambda summary, payload: self.on_event("retry", AgentName.SYSTEM, summary, payload)

    def model_for(self, agent: AgentName) -> str:
        return self.settings.model_for("judge" if agent == AgentName.ODIN else "advocate")

    def _once(self, agent: AgentName, system: str, user: str, schema: type[T], effort: str) -> BackendResult[T]:
        self.ledger.check(agent)
        res = self.backend.call(model=self.model_for(agent), system=system, user=user, schema=schema, effort=effort,
                                max_tokens=self.settings.llm_max_output_tokens, agent=agent)
        self.ledger.add(agent, res.input_tokens, res.output_tokens)
        if res.stop_reason == "refusal":
            raise LLMError(f"{agent.value}: the model refused the request")
        return res

    def structured(self, agent: AgentName, system: str, user: str, schema: type[T], *, effort: str = "medium",
                   validate: Validator | None = None, label: str = "", allow_residual: bool = False) -> T:
        """One call, validated; at most one repair call; then LLMOutputError.

        allow_residual=True: if the repaired output parses but still has semantic
        problems, return it anyway; the caller must then drop the invalid parts
        (and log them). Schema failures always raise."""
        res = self._once(agent, system, user, schema, effort)
        problems = self._problems(res, validate)
        if not problems:
            return res.parsed  # type: ignore[return-value]
        self.on_event("repair", agent, f"{label}: output invalid, one repair attempt", {"problems": problems[:20]})
        previous = res.parsed.model_dump_json() if res.parsed is not None else res.raw_text[:6000]
        repair = (
            f"{user}\n\n<repair_request>\nYour previous answer could not be accepted. Problems:\n"
            + "\n".join(f"- {p}" for p in problems[:20])
            + f"\n\nYour previous answer was:\n{previous}\n\nReturn a corrected answer in the same schema. "
            "Fix only what the problems require; do not invent citations or numbers.\n</repair_request>"
        )
        res2 = self._once(agent, system, repair, schema, effort)
        problems2 = self._problems(res2, validate)
        if problems2 and allow_residual and res2.parsed is not None and res2.stop_reason != "max_tokens":
            self.on_event("residual", agent, f"{label}: {len(problems2)} problem(s) remain after repair; invalid parts "
                          "will be dropped by code", {"problems": problems2[:20]})
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
