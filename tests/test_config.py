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
    assert s.max_runs == 3
    assert s.max_cross_exam_rounds == 1
    assert s.has_api_key is False
    assert s.db_path == (PROJECT_ROOT / "logs" / "ragnarok.db").resolve()
    with pytest.raises(RuntimeError):
        s.require_api_key()


def test_secret_never_exposed():
    s = Settings(_env_file=None, anthropic_api_key="sk-test-secret-value")
    assert s.has_api_key
    assert "sk-test-secret-value" not in repr(s)
    assert "sk-test-secret-value" not in str(s.public_summary())
    assert "anthropic_api_key" not in s.public_summary()


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
