"""Application configuration loaded from .env (secrets) with safe defaults.

All limits that the trial must respect are defined here so they are enforced in
code, never left to prompts. Paths are resolved relative to the project root.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    # Secrets: never logged; SecretStr keeps the value out of repr().
    anthropic_api_key: SecretStr = SecretStr("")

    # Models (verified against the key's model list in Phase 0).
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
    max_runs: int = Field(3, ge=1, le=5)
    max_cross_exam_rounds: int = Field(1, ge=1, le=3)
    max_tool_calls_per_agent: int = Field(12, ge=1, le=100)
    max_tool_calls_per_case: int = Field(60, ge=1, le=500)
    max_tokens_per_agent: int = Field(150_000, ge=1_000)
    max_tokens_per_case: int = Field(600_000, ge=1_000)
    llm_max_output_tokens: int = Field(4096, ge=256, le=64_000)
    request_timeout_s: float = Field(120.0, gt=0, le=900)
    max_retries: int = Field(2, ge=0, le=5)
    max_upload_bytes: int = Field(20 * 1024 * 1024, ge=1024)
    max_evidence_per_query: int = Field(12, ge=1, le=100)
    max_evidence_per_case: int = Field(200, ge=1)

    @model_validator(mode="after")
    def _resolve_and_check(self) -> "Settings":
        for name in ("data_dir", "packs_dir", "index_dir", "processed_dir", "log_dir", "db_path"):
            p: Path = getattr(self, name)
            if not p.is_absolute():
                object.__setattr__(self, name, (PROJECT_ROOT / p).resolve())
        if self.max_tool_calls_per_agent > self.max_tool_calls_per_case:
            raise ValueError("max_tool_calls_per_agent cannot exceed max_tool_calls_per_case")
        if self.max_tokens_per_agent > self.max_tokens_per_case:
            raise ValueError("max_tokens_per_agent cannot exceed max_tokens_per_case")
        return self

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value().strip())

    def require_api_key(self) -> str:
        key = self.anthropic_api_key.get_secret_value().strip()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
        return key

    def public_summary(self) -> dict[str, object]:
        """Config snapshot safe to log or persist with a run (no secrets)."""
        data = self.model_dump(exclude={"anthropic_api_key"}, mode="json")
        data["has_api_key"] = self.has_api_key
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
