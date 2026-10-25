"""Shared test fixtures. The embedder is the real local model (loaded once per session)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ragnarok.config import Settings

SYNTH_PACK = Path(__file__).parent / "fixtures" / "synth_pack"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture(scope="session")
def embedder(test_settings):
    from ragnarok.retrieval.embed import FastEmbedder

    return FastEmbedder(test_settings.embedding_model, test_settings.index_dir / "models")


def header(doc_id: str, title: str, *, date: str, source: str = "Test Ministry", stype: str = "trade_note",
           tier: int = 1, country: str = "Beta", sector: str = "Grain", event: str = "EVT") -> str:
    return (f"DOC_ID: {doc_id}\nEVENT_ID: {event}\nTITLE: {title}\nSOURCE_NAME: {source}\nSOURCE_TYPE: {stype}\n"
            f"RELIABILITY: {tier}\nPUB_DATE: {date}\nPUB_TIME: 09:00\nCOUNTRY: {country}\nSECTOR: {sector}\nLANGUAGE: en\n---\n")


def write_pack(root: Path, pack_id: str, docs: dict[str, str]) -> Path:
    """Write a minimal synthetic pack: {file name: full text}."""
    import json

    (root / "docs").mkdir(parents=True, exist_ok=True)
    entries = []
    for name, text in docs.items():
        (root / "docs" / name).write_text(text, encoding="utf-8")
        entries.append({"DOC_ID": name.rsplit(".", 1)[0], "file": name})
    (root / "manifest.json").write_text(json.dumps({"pack": pack_id, "documents": entries}), encoding="utf-8")
    return root
