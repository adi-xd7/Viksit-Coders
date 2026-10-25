"""Metadata header parsing, value normalisation and header/manifest merging.

Rules:
- The header is a block of `KEY: value` lines at the start of the text, ended by
  a line of three or more dashes. Keys are matched case- and spacing-insensitively
  (`Doc Id`, `doc-id`, `DOC_ID` are the same key).
- Header values win over manifest values; the manifest fills gaps. The exception
  is DOC_ID: the manifest is the organiser's catalogue that citations are checked
  against, so its ID is kept and a header mismatch is recorded as a conflict.
- Every original value is kept in `raw` (prefixed `header.` / `manifest.`), and
  every disagreement is recorded as a MetadataConflict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ragnarok.models import MetadataConflict

_KEY_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _\-]{0,40}?)\s*[:=]\s*(.*?)\s*$")
_SEPARATOR = re.compile(r"^\s*-{3,}\s*$")

DOC_KEYS = (
    "DOC_ID", "EVENT_ID", "TITLE", "SOURCE_NAME", "SOURCE_TYPE", "RELIABILITY",
    "PUB_DATE", "PUB_TIME", "COUNTRY", "SECTOR", "LANGUAGE",
)
TABLE_KEYS = (
    "TABLE_ID", "COUNTRY_PAIR", "ORIGIN", "DESTINATION", "EXPORTER", "IMPORTER", "FROM", "TO",
    "UNIT", "UNITS", "CURRENCY", "PERIOD", "ROWS", "COMMODITY",
)
KNOWN_KEYS = frozenset(DOC_KEYS + TABLE_KEYS + ("FORMAT", "FILE"))

_ALIASES = {
    "DOCID": "DOC_ID", "DOCUMENT_ID": "DOC_ID", "ID": "DOC_ID",
    "EVENT": "EVENT_ID", "EVENTID": "EVENT_ID",
    "SOURCE": "SOURCE_NAME", "OUTLET": "SOURCE_NAME", "SOURCENAME": "SOURCE_NAME",
    "TYPE": "SOURCE_TYPE", "DOC_TYPE": "SOURCE_TYPE", "SOURCETYPE": "SOURCE_TYPE",
    "TIER": "RELIABILITY", "RELIABILITY_TIER": "RELIABILITY",
    "DATE": "PUB_DATE", "PUBLISHED": "PUB_DATE", "PUBLICATION_DATE": "PUB_DATE", "PUBDATE": "PUB_DATE",
    "TIME": "PUB_TIME", "PUBTIME": "PUB_TIME", "PUBLICATION_TIME": "PUB_TIME",
    "LANG": "LANGUAGE", "TABLEID": "TABLE_ID", "FILENAME": "FILE", "FILE_NAME": "FILE", "PATH": "FILE",
}


def canonical_key(key: str) -> str:
    k = re.sub(r"[\s\-]+", "_", str(key).strip()).upper()
    return _ALIASES.get(k, k)


def key_value(line: str) -> tuple[str, str] | None:
    """(canonical key, value) for a `KEY: value` line, else None."""
    m = _KEY_LINE.match(line)
    return (canonical_key(m.group(1)), m.group(2)) if m else None


@dataclass
class HeaderResult:
    fields: dict[str, str]  # canonical key -> value (first occurrence)
    raw_lines: list[str]
    body: str  # text after the header (whole text when no header was found)
    found: bool
    terminated: bool  # ended by a '---' line
    warnings: list[str] = field(default_factory=list)


def parse_header(text: str, max_lines: int = 60) -> HeaderResult:
    text = text.lstrip("﻿")
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    start = i
    candidates: list[tuple[int, str, str]] = []
    sep_at: int | None = None
    while i < len(lines) and i - start < max_lines:
        line = lines[i]
        if _SEPARATOR.match(line):
            sep_at = i
            break
        m = _KEY_LINE.match(line)
        if not m:
            break
        candidates.append((i, canonical_key(m.group(1)), m.group(2)))
        i += 1

    if sep_at is None:
        # Unterminated: accept only the leading run of known keys.
        kept: list[tuple[int, str, str]] = []
        for c in candidates:
            if c[1] not in KNOWN_KEYS:
                break
            kept.append(c)
        candidates = kept
    known = [c for c in candidates if c[1] in KNOWN_KEYS]
    if len(known) < 2:
        return HeaderResult(fields={}, raw_lines=[], body=text, found=False, terminated=False)

    fields: dict[str, str] = {}
    warnings: list[str] = []
    for _, key, value in candidates:
        if key in fields:
            if fields[key] != value:
                warnings.append(f"header key {key} repeated with a different value; first kept")
            continue
        fields[key] = value
    end = sep_at + 1 if sep_at is not None else candidates[-1][0] + 1
    if sep_at is None:
        warnings.append("header not terminated by a '---' line")
    return HeaderResult(
        fields=fields,
        raw_lines=lines[start:end],
        body="\n".join(lines[end:]),
        found=True,
        terminated=sep_at is not None,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Value normalisers. Each returns None when the value cannot be read.
# --------------------------------------------------------------------------- #

MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ]
    )
    for m in names
}


def norm_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?", s)
    if m:
        y, mo, d = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s):
        y, mo, d = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})", s):
        d, mo, y = int(m.group(1)), MONTHS.get(m.group(2).lower(), 0), int(m.group(3))
    elif m := re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s):
        mo, d, y = MONTHS.get(m.group(1).lower(), 0), int(m.group(2)), int(m.group(3))
    else:
        return None  # ambiguous forms such as 03/04/2026 are not guessed
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def norm_time(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    m = re.fullmatch(r"(\d{1,2})[:.h]?(\d{2})(?::\d{2})?\s*(?:UTC|Z|GMT)?", s, re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def norm_tier(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value) if float(value).is_integer() else None
    else:
        m = re.fullmatch(r"(?:tier|t|level)?\s*[-_ ]?\s*(\d+)(?:\.0+)?", str(value).strip(), re.I)
        n = int(m.group(1)) if m else None
    return n if n is not None and 1 <= n <= 4 else None


_NO_EVENT = {"", "none", "null", "n/a", "na", "background", "-", "no event", "no_event"}


def norm_event(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return None if s.lower() in _NO_EVENT else s


_ID_SAFE = re.compile(r"[^A-Za-z0-9_.\-]+")


def safe_id(value: Any) -> str | None:
    """A doc ID usable as a key, or None when the value is unusable."""
    if value is None:
        return None
    s = str(value).strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}", s):
        return s
    return None


def id_from_filename(stem: str) -> str:
    s = _ID_SAFE.sub("_", stem).strip("_.-") or "doc"
    return s[:64]


# --------------------------------------------------------------------------- #
# Manifest entry normalisation and merge
# --------------------------------------------------------------------------- #


def normalise_manifest_entry(entry: dict[str, Any]) -> tuple[dict[str, str], list[MetadataConflict]]:
    """Canonical keys; upper-case keys win over lower/mixed-case duplicates."""
    out: dict[str, str] = {}
    origin_upper: dict[str, bool] = {}
    conflicts: list[MetadataConflict] = []
    for k, v in entry.items():
        if isinstance(v, (dict, list)):
            continue
        ck = canonical_key(k)
        sv = "" if v is None else str(v).strip()
        is_upper = str(k).isupper()
        if ck in out:
            if out[ck] != sv:
                conflicts.append(
                    MetadataConflict(
                        field=ck, header_value=None, manifest_value=f"{out[ck]!r} vs {sv!r}",
                        resolution="manifest has duplicate keys with different values; upper-case key used",
                    )
                )
            if is_upper and not origin_upper[ck]:
                out[ck], origin_upper[ck] = sv, True
            continue
        out[ck], origin_upper[ck] = sv, is_upper
    return out, conflicts


_NORMALISERS = {"PUB_DATE": norm_date, "PUB_TIME": norm_time, "RELIABILITY": norm_tier, "EVENT_ID": norm_event}


def _comparable(key: str, value: str) -> Any:
    fn = _NORMALISERS.get(key)
    if fn is not None:
        n = fn(value)
        return n if n is not None else value.strip().casefold()
    return " ".join(value.split()).casefold()


@dataclass
class MergedMeta:
    values: dict[str, Any]  # normalised values ready for DocMeta
    raw: dict[str, str]
    conflicts: list[MetadataConflict]
    problems: list[str]  # unreadable values (become BAD_METADATA flags)


def merge_metadata(header: dict[str, str], manifest: dict[str, str] | None) -> MergedMeta:
    manifest = manifest or {}
    raw = {f"header.{k}": v for k, v in header.items()} | {f"manifest.{k}": v for k, v in manifest.items()}
    conflicts: list[MetadataConflict] = []
    chosen: dict[str, str] = {}
    for key in sorted(set(header) | set(manifest)):
        hv = header.get(key, "").strip()
        mv = manifest.get(key, "").strip()
        if hv and mv and _comparable(key, hv) != _comparable(key, mv):
            if key == "DOC_ID":
                chosen[key] = mv
                resolution = "manifest ID kept (citations are checked against the manifest)"
            else:
                chosen[key] = hv
                resolution = "header value used"
            conflicts.append(MetadataConflict(field=key, header_value=hv, manifest_value=mv, resolution=resolution))
        else:
            chosen[key] = hv or mv

    problems: list[str] = []
    values: dict[str, Any] = {}
    pub_date_raw = chosen.get("PUB_DATE", "")
    values["pub_date"] = norm_date(pub_date_raw)
    if values["pub_date"] is None:
        # The other source may still hold a readable date.
        alt = norm_date(manifest.get("PUB_DATE")) or norm_date(header.get("PUB_DATE"))
        values["pub_date"] = alt
        problems.append(f"PUB_DATE unreadable: {pub_date_raw!r}" if pub_date_raw else "PUB_DATE missing")
        if alt:
            problems[-1] += f"; used {alt} from the other metadata source"
    time_raw = chosen.get("PUB_TIME", "")
    values["pub_time"] = norm_time(time_raw)
    if time_raw and values["pub_time"] is None:
        problems.append(f"PUB_TIME unreadable: {time_raw!r}")
    tier_raw = chosen.get("RELIABILITY", "")
    values["reliability_tier"] = norm_tier(tier_raw)
    if values["reliability_tier"] is None:
        alt_tier = norm_tier(manifest.get("RELIABILITY")) or norm_tier(header.get("RELIABILITY"))
        values["reliability_tier"] = alt_tier
        problems.append(f"RELIABILITY unreadable or out of range 1-4: {tier_raw!r}" if tier_raw else "RELIABILITY missing")
    values["event_id"] = norm_event(chosen.get("EVENT_ID"))
    for key, name in (
        ("DOC_ID", "doc_id"), ("TITLE", "title"), ("SOURCE_NAME", "source_name"), ("SOURCE_TYPE", "source_type"),
        ("COUNTRY", "country"), ("SECTOR", "sector"), ("LANGUAGE", "language"), ("FILE", "file_name"),
    ):
        v = chosen.get(key, "").strip()
        values[name] = " ".join(v.split()) if v else None
    return MergedMeta(values=values, raw=raw, conflicts=conflicts, problems=problems)
