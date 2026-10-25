"""
Manifest loader — reads and normalises the dev-pack manifest.json.

The manifest has inconsistent casing (DOC_ID vs doc_id, etc.).
This module normalises every document entry to a consistent shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config


# ── Canonical key names (upper-case versions) ────────────────────────────────
_KEY_MAP = {
    "doc_id": "DOC_ID",
    "event_id": "EVENT_ID",
    "title": "TITLE",
    "source_name": "SOURCE_NAME",
    "source_type": "SOURCE_TYPE",
    "reliability": "RELIABILITY",
    "pub_date": "PUB_DATE",
    "pub_time": "PUB_TIME",
    "country": "COUNTRY",
    "sector": "SECTOR",
    "language": "LANGUAGE",
    "format": "FORMAT",
}


def _normalise_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Collapse duplicate keys to upper-case canon, coerce types."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        canon = _KEY_MAP.get(key.lower(), key.upper() if key.islower() else key)
        if canon not in out:          # upper-case key wins if both exist
            out[canon] = value
    # Ensure reliability is int
    if "RELIABILITY" in out:
        try:
            out["RELIABILITY"] = int(out["RELIABILITY"])
        except (ValueError, TypeError):
            out["RELIABILITY"] = 4    # assume worst if unparseable
    # Keep `file` as-is (lower-case, it's the filename)
    out["file"] = raw.get("file", "")
    return out


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """
    Load the manifest and return a dict with:
      - pack, event_id, name, as_of, count  (top-level metadata)
      - documents: list[dict]  (normalised per-document entries)
      - doc_index: dict[str, dict]  (DOC_ID → normalised entry)
    """
    path = path or config.MANIFEST_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    docs = [_normalise_entry(d) for d in raw.get("documents", [])]
    doc_index = {d["DOC_ID"]: d for d in docs}

    return {
        "pack": raw.get("pack", ""),
        "event_id": raw.get("event_id", ""),
        "name": raw.get("name", ""),
        "as_of": raw.get("as_of", ""),
        "count": raw.get("count", len(docs)),
        "documents": docs,
        "doc_index": doc_index,
    }


def get_doc_metadata(manifest: dict, doc_id: str) -> dict[str, Any] | None:
    """Look up a single document by DOC_ID."""
    return manifest.get("doc_index", {}).get(doc_id)


def filter_documents(manifest: dict, **filters: Any) -> list[dict]:
    """
    Filter manifest documents by arbitrary metadata fields.

    Supported filters:
      country, sector, event_id, source_type, reliability (exact match or <=),
      pub_date_before (string YYYY-MM-DD, inclusive upper bound).
    """
    results = []
    for doc in manifest["documents"]:
        match = True
        for key, value in filters.items():
            if key == "pub_date_before":
                if doc.get("PUB_DATE", "9999-99-99") > value:
                    match = False
                    break
            elif key == "reliability_max":
                if doc.get("RELIABILITY", 99) > value:
                    match = False
                    break
            else:
                doc_val = doc.get(key.upper(), doc.get(key, None))
                if doc_val is None or str(doc_val).lower() != str(value).lower():
                    match = False
                    break
        if match:
            results.append(doc)
    return results
