from pathlib import Path

import pytest
from pydantic import ValidationError

from ragnarok.api import app
from ragnarok.config import PROJECT_ROOT, Settings, get_settings


def test_settings_load_from_project_env():
    s = get_settings()
    assert s.model_fast and s.model_advocate and s.model_judge
    assert s.max_runs >= 1
    assert s.packs_dir.is_absolute()


def test_defaults_without_env_file():
    s = Settings(_env_file=None)
    assert s.max_runs == 2
    assert s.max_cross_exam_rounds == 1
    assert s.has_api_key is False
    assert s.db_path == (PROJECT_ROOT / "logs" / "ragnarok.db").resolve()
    with pytest.raises(RuntimeError):
        s.require_api_key()


def test_secret_never_exposed():
    s = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="sk-test-secret-value")
    assert s.has_api_key
    assert "sk-test-secret-value" not in repr(s)
    assert "sk-test-secret-value" not in str(s.public_summary())
    assert "anthropic_api_key" not in s.public_summary()
    g = Settings(_env_file=None, gemini_api_key="gm-test-secret-value")
    assert g.llm_provider == "gemini" and g.has_api_key and g.api_key_name == "GEMINI_API_KEY"
    assert "gm-test-secret-value" not in repr(g) and "gm-test-secret-value" not in str(g.public_summary())
    assert "gemini_api_key" not in g.public_summary()


def test_provider_selects_models_and_key():
    g = Settings(_env_file=None, anthropic_api_key="a-key")
    assert not g.has_api_key  # the Gemini key is the one that counts under the default provider
    assert g.model_for("advocate").startswith("gemini-") and g.model_for("judge").startswith("gemini-")
    a = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="a-key")
    assert a.has_api_key and a.model_for("judge") == a.model_judge
    with pytest.raises(ValueError):
        a.model_for("boss")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider="openai")


def test_env_override_and_absolute_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAX_RUNS", "2")
    monkeypatch.setenv("PACKS_DIR", str(tmp_path))
    s = Settings(_env_file=None)
    assert s.max_runs == 2
    assert s.packs_dir == tmp_path


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_runs": 0},
        {"max_runs": 99},
        {"max_runs": 4},
        {"max_retries": -1},
        {"request_timeout_s": 0},
        {"max_tool_calls_per_agent": 50, "max_tool_calls_per_case": 10},
        {"max_tokens_per_agent": 900_000, "max_tokens_per_case": 10_000},
    ],
)
def test_invalid_limits_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_api_starts_and_health_has_no_secrets():
    from fastapi.testclient import TestClient

    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "sk-" not in r.text
