"""The organizer dev pack is present, complete and intact (fetch with scripts/fetch_dev_pack.py)."""

import hashlib
import json
from pathlib import Path

import pytest

from ragnarok.config import get_settings
from ragnarok.models import DocMeta

PACK = get_settings().packs_dir / "dev_pack_E5"
pytestmark = pytest.mark.skipif(not PACK.is_dir(), reason="dev pack not downloaded")


def _manifest() -> dict:
    return json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))


def test_required_files_present():
    for name in ("manifest.json", "hashes.sha256", "README.md", "sample_question.txt"):
        assert (PACK / name).is_file(), name
    assert (PACK / "docs").is_dir()


def test_file_count_matches_manifest():
    m = _manifest()
    on_disk = {p.name for p in (PACK / "docs").iterdir() if p.is_file()}
    listed = {d["file"] for d in m["documents"]}
    assert m["count"] == len(m["documents"]) == len(on_disk)
    assert listed == on_disk


def test_checksums_match():
    lines = [l for l in (PACK / "hashes.sha256").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == _manifest()["count"]
    for line in lines:
        digest, rel = line.split(None, 1)
        assert hashlib.sha256((PACK / rel.strip()).read_bytes()).hexdigest() == digest, rel


def test_all_three_formats_present():
    suffixes = {Path(d["file"]).suffix.lower() for d in _manifest()["documents"]}
    assert {".pdf", ".txt", ".docx"} <= suffixes


def test_every_manifest_entry_normalises():
    m = _manifest()
    metas = [DocMeta.from_raw(d) for d in m["documents"]]
    assert len({x.doc_id for x in metas}) == len(metas)
    for x in metas:
        assert x.reliability_tier in (1, 2, 3, 4)
        assert x.title and x.source_name
        # background docs normalise to event_id=None, event docs keep their id
        raw_event = next(v for k, v in x.raw.items() if k.upper() == "EVENT_ID")
        assert (x.event_id is None) == (raw_event.strip().upper() == "NONE")
