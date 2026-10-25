"""
Shared test fixtures for Heimdall tests.
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
from heimdall.logger import HeimdallLogger
from heimdall.memory import HeimdallMemory
from heimdall.manifest_loader import load_manifest


@pytest.fixture
def logger(tmp_path):
    """Logger that writes to a temp dir."""
    log_path = tmp_path / "test_heimdall.jsonl"
    return HeimdallLogger(log_path=log_path)


@pytest.fixture
def memory(tmp_path, logger):
    """Memory that writes to a temp dir."""
    mem_path = tmp_path / "test_memory.json"
    return HeimdallMemory(path=mem_path, logger=logger)


@pytest.fixture
def manifest():
    """Load the real manifest if available."""
    if config.MANIFEST_PATH.exists():
        return load_manifest()
    pytest.skip("Manifest not available — run download_corpus.py first")


@pytest.fixture
def sample_question():
    """The sample question from the dev pack."""
    return (
        "As of 25 January 2027, how exposed are Midgard and Tolan "
        "to the end of the Orvan corridor agreement? "
        "Give a low and high range for wheat"
    )


@pytest.fixture
def as_of_date():
    """The canonical as-of date."""
    return "2027-01-25"


@pytest.fixture
def doc_texts(manifest):
    """Parse all documents (requires corpus to be downloaded)."""
    if not config.DOCS_DIR.exists() or not any(config.DOCS_DIR.iterdir()):
        pytest.skip("Corpus not downloaded — run download_corpus.py first")
    from heimdall.document_parser import parse_all_documents
    return parse_all_documents(config.DOCS_DIR, manifest["documents"])


# ── Small fixture data for unit tests that don't need the full corpus ────

@pytest.fixture
def minimal_manifest():
    """A tiny manifest for fast unit tests."""
    return {
        "pack": "test_pack",
        "event_id": "E5",
        "name": "Test event",
        "as_of": "2027-01-25",
        "count": 4,
        "documents": [
            {
                "DOC_ID": "DOC-001",
                "EVENT_ID": "E5",
                "TITLE": "Corridor Agreement expires with no renewal",
                "SOURCE_NAME": "Realm Trade Ministry",
                "SOURCE_TYPE": "gov_notice",
                "RELIABILITY": 1,
                "PUB_DATE": "2026-09-10",
                "COUNTRY": "Orvan",
                "SECTOR": "Wheat",
                "file": "DOC-001.txt",
            },
            {
                "DOC_ID": "DOC-002",
                "EVENT_ID": "E5",
                "TITLE": "Orvan grain corridor renewed for a second year",
                "SOURCE_NAME": "Raven Wire",
                "SOURCE_TYPE": "news",
                "RELIABILITY": 2,
                "PUB_DATE": "2026-09-09",
                "COUNTRY": "Orvan",
                "SECTOR": "Wheat",
                "file": "DOC-002.txt",
            },
            {
                "DOC_ID": "DOC-003",
                "EVENT_ID": "E5",
                "TITLE": "Correction: Orvan corridor agreement was not renewed",
                "SOURCE_NAME": "Raven Wire",
                "SOURCE_TYPE": "correction",
                "RELIABILITY": 2,
                "PUB_DATE": "2026-09-10",
                "COUNTRY": "Orvan",
                "SECTOR": "Wheat",
                "file": "DOC-003.txt",
            },
            {
                "DOC_ID": "DOC-004",
                "EVENT_ID": "NONE",
                "TITLE": "FAMINE FEAR AS ORVAN GRAIN VANISHES",
                "SOURCE_NAME": "Daily Roar",
                "SOURCE_TYPE": "tabloid",
                "RELIABILITY": 4,
                "PUB_DATE": "2026-10-05",
                "COUNTRY": "Midgard",
                "SECTOR": "Wheat",
                "file": "DOC-004.txt",
            },
        ],
        "doc_index": {},
    }


@pytest.fixture
def minimal_doc_texts():
    """Minimal doc texts for unit tests."""
    return {
        "DOC-001": "The Corridor Agreement between Orvan and neighbouring states expired on 10 September 2026 with no renewal.",
        "DOC-002": "The Orvan grain corridor has been renewed for a second year.",
        "DOC-003": "Correction: The previous report that the Orvan corridor agreement was renewed is incorrect. The agreement was NOT renewed.",
        "DOC-004": "FAMINE FEAR AS ORVAN GRAIN VANISHES! Sources say the grain port is finished!",
    }
