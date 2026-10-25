"""Application configuration loaded from .env (secrets) with safe defaults.

All limits that the trial must respect are defined here so they are enforced in
code, never left to prompts. Paths are resolved relative to the project root.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM provider: "gemini" (Google AI Studio) or "anthropic". Only the backend changes;
    # prompts, schemas, validation, budgets and the trial flow are identical for both.
    llm_provider: Literal["gemini", "anthropic"] = "gemini"

    # Secrets: never logged; SecretStr keeps the value out of repr().
    gemini_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")

    # Gemini models (verified with the AI Studio key on 2026-10-25: structured output works on
    # gemini-3.5-flash for every trial schema; pro models had no quota on that key).
    gemini_model_fast: str = "gemini-3.5-flash-lite"
    gemini_model_advocate: str = "gemini-3.5-flash"
    gemini_model_judge: str = "gemini-3.5-flash"
    # Pacing for rate-limited keys: minimum seconds between request starts (all agents together),
    # and how many times a 429 / 503 is retried after waiting (bounded).
    llm_min_interval_s: float = Field(0.0, ge=0, le=120)
    # Model chain: comma-separated models tried in order. Each model has its own daily quota; when one is used
    # up (or keeps failing) the next one answers the same request. Empty = just the single model above.
    gemini_model_chain: str = ""  # Heimdall, Thor, Loki
    gemini_judge_chain: str = ""  # Odin (empty = GEMINI_MODEL_JUDGE, then the main chain)
    llm_server_retries: int = Field(2, ge=0, le=6)  # retries of a 5xx / timeout on one model before moving on
    model_cooldown_s: float = Field(300.0, ge=0, le=86_400)  # skip a model this long after it kept failing
    quota_pause: bool = True  # every model's daily quota used up -> the case pauses (resumable), not fails
    auto_resume_paused: bool = True  # the API resumes a paused case when the quota resets
    llm_rate_limit_retries: int = Field(6, ge=0, le=12)
    llm_rate_limit_max_wait_s: float = Field(90.0, ge=1, le=600)
    gemini_request_timeout_s: float = Field(120.0, gt=0, le=900)  # per Gemini request; a hung call fails fast and is retried

    # Anthropic models (verified against that key's model list in Phase 0).
    model_fast: str = "claude-haiku-5-5"
    model_advocate: str = "claude-sonnet-5-5"
    model_judge: str = "claude-opus-5-5"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Paths (relative values are resolved against PROJECT_ROOT).
    data_dir: Path = Path("data")
    packs_dir: Path = Path("data/runemark")
    index_dir: Path = Path("data/index")
    processed_dir: Path = Path("data/processed")
    log_dir: Path = Path("logs")
    db_path: Path = Path("logs/ragnarok.db")

    # Limits: hard caps enforced in code.
    max_runs: int = Field(2, ge=1, le=3)  # investigation runs per case (run 1 + send-backs); never unbounded
    max_cross_exam_rounds: int = Field(1, ge=1, le=3)  # per run; round 2+ re-attacks claims defended in the round before
    # Sized from the first real trial (run 1: ~18 tool calls and ~165k tokens per advocate);
    # a second run adds roughly the same again.
    max_tool_calls_per_agent: int = Field(45, ge=1, le=100)
    max_tool_calls_per_case: int = Field(180, ge=1, le=500)
    max_tokens_per_agent: int = Field(450_000, ge=1_000)
    max_tokens_per_case: int = Field(1_500_000, ge=1_000)
    llm_max_output_tokens: int = Field(16_000, ge=256, le=64_000)  # thinking is always on: leave room
    request_timeout_s: float = Field(300.0, gt=0, le=900)
    max_retries: int = Field(2, ge=0, le=5)
    max_upload_bytes: int = Field(20 * 1024 * 1024, ge=1024)
    max_evidence_per_query: int = Field(12, ge=1, le=100)
    max_evidence_per_case: int = Field(400, ge=1)  # distinct paragraphs/rows retrieved per case (all agents)

    # Retrieval: Reciprocal Rank Fusion constant (score = sum 1 / (k + rank)).
    rrf_k: int = Field(60, ge=1, le=1000)

    # Trial
    llm_refusal_fallback: bool = True  # server-side refusal fallback on Opus 5.5 / Sonnet 5.5
    # Planning turns per agent per step. A further turn is allowed only while the agent's
    # required own searches are unmet (bounded: one extra).
    max_research_rounds: int = Field(1, ge=1, le=6)
    max_requests_per_round: int = Field(8, ge=1, le=12)  # tool requests one planning turn may make
    max_claims_per_advocate: int = Field(8, ge=1, le=12)
    max_attacks_per_advocate: int = Field(3, ge=1, le=6)
    effort_advocate: str = Field("medium", pattern="^(low|medium|high|xhigh|max)$")
    effort_judge: str = Field("high", pattern="^(low|medium|high|xhigh|max)$")
    max_sendback_queries_per_item: int = Field(2, ge=1, le=4)
    # LLM request economy (each keeps the official behaviour; false restores the older, costlier path)
    max_llm_calls_per_case: int = Field(30, ge=1, le=500)  # hard cap on model requests per case -> LIMIT_HIT
    heimdall_seed_searches: int = Field(4, ge=0, le=8)  # code-run searches from the parsed question (0 = off)
    share_seeds_with_advocates: bool = True  # advocates start from Heimdall's seed results (query cache) + case-file rows
    cross_exam_code_search: bool = True  # cross-exam searches derived in code, not a planning call
    cross_exam_reads_per_attack: int = Field(1, ge=0, le=3)  # defense: cited documents re-read in full
    odin_merged_call: bool = True  # rulings + assessment in one call (two-step fallback on failure)
    odin_research_round: bool = False  # Odin planning turn before ruling (citations/calcs are checked in code anyway)
    delta_run: bool = True  # run n >= 2: only revised/new claims are cross-examined and re-ruled
    sendback_followup_llm: bool = False  # send-back follow-up planning turn (default: code fetches the found tables)
    repair_mode: Literal["residual_first", "always"] = "residual_first"  # repair only what code cannot drop
    llm_response_cache: bool = True  # same-case reply cache: a resumed case replays finished steps
    # Private agent memory
    memory_enabled: bool = True
    memory_recall_limit: int = Field(5, ge=0, le=20)
    memory_baseline: bool = True  # record a no-memory plan too, so a memory-driven change is observable
    # combined: one call returns both the no-memory and the memory plan; separate: an extra baseline call
    memory_baseline_mode: Literal["combined", "separate"] = "combined"
    cases_dir: Path = Path("logs/cases")

    # API
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]  # local Vite dev server
    max_concurrent_cases: int = Field(1, ge=1, le=4)  # rate-limited LLM keys: one trial at a time by default
    max_upload_files: int = Field(2000, ge=1)  # files per uploaded pack zip

    @model_validator(mode="after")
    def _resolve_and_check(self) -> "Settings":
        for name in ("data_dir", "packs_dir", "index_dir", "processed_dir", "log_dir", "db_path", "cases_dir"):
            p: Path = getattr(self, name)
            if not p.is_absolute():
                object.__setattr__(self, name, (PROJECT_ROOT / p).resolve())
        if self.max_tool_calls_per_agent > self.max_tool_calls_per_case:
            raise ValueError("max_tool_calls_per_agent cannot exceed max_tool_calls_per_case")
        if self.max_tokens_per_agent > self.max_tokens_per_case:
            raise ValueError("max_tokens_per_agent cannot exceed max_tokens_per_case")
        return self

    @property
    def api_key_name(self) -> str:
        return "GEMINI_API_KEY" if self.llm_provider == "gemini" else "ANTHROPIC_API_KEY"

    def _key(self) -> str:
        k = self.gemini_api_key if self.llm_provider == "gemini" else self.anthropic_api_key
        return k.get_secret_value().strip()

    @property
    def key_fingerprint(self) -> str:
        """Short non-reversible tag of the provider + key (never the key): quota records belong to one key's project."""
        import hashlib

        return hashlib.sha256(f"{self.llm_provider}:{self._key()}".encode()).hexdigest()[:12]

    @property
    def has_api_key(self) -> bool:
        """True when the key for the selected provider is set."""
        return bool(self._key())

    def require_api_key(self) -> str:
        key = self._key()
        if not key:
            raise RuntimeError(f"{self.api_key_name} is not set in .env (LLM_PROVIDER={self.llm_provider})")
        return key

    def model_chain(self, role: str) -> list[str]:
        """Models for a role, in the order they are tried (first = model_for(role))."""
        if role not in ("fast", "advocate", "judge"):
            raise ValueError(f"unknown model role {role!r}")
        if self.llm_provider != "gemini":
            return [self.model_for(role)]
        split = lambda v: [m.strip() for m in v.split(",") if m.strip()]  # noqa: E731
        main = split(self.gemini_model_chain) or [self.gemini_model_advocate]
        if role == "judge":
            chain = split(self.gemini_judge_chain) or [self.gemini_model_judge] + main
        elif role == "fast":
            chain = [self.gemini_model_fast] + main
        else:
            chain = main
        return list(dict.fromkeys(chain))

    def model_for(self, role: str) -> str:
        """Model ID for a role ("fast", "advocate", "judge") under the selected provider."""
        if role not in ("fast", "advocate", "judge"):
            raise ValueError(f"unknown model role {role!r}")
        prefix = "gemini_model_" if self.llm_provider == "gemini" else "model_"
        return getattr(self, prefix + role)

    def public_summary(self) -> dict[str, object]:
        """Config snapshot safe to log or persist with a run (no secrets)."""
        data = self.model_dump(exclude={"anthropic_api_key", "gemini_api_key"}, mode="json")
        data["has_api_key"] = self.has_api_key
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
