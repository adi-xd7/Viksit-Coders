"""Command line: ingest a pack and print a summary.

    python -m backend.ingest <pack_dir> [--db PATH] [--json]
    python -m ragnarok.ingest <pack_dir>      (with backend/ on PYTHONPATH)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from ragnarok.config import get_settings
from ragnarok.ingest.pipeline import IngestReport, ingest_pack
from ragnarok.models import DAMAGE_KINDS, DamageKind, RelationType, RowStatus
from ragnarok.store.db import Store


def summarise(rep: IngestReport) -> dict:
    docs = rep.documents
    fmt = Counter((d.meta.format.value if d.meta.format else "unreadable") for d in docs)
    damaged = {
        d.meta.doc_id: [f"{f.kind.value}: {f.detail}" for f in d.damage_flags if f.kind in DAMAGE_KINDS]
        for d in docs if d.is_damaged
    }
    exact = {d.meta.doc_id: r.target_doc_id for d in docs for r in d.relations if r.type == RelationType.DUPLICATE_OF}
    near = [f"{d.meta.doc_id} -> {r.target_doc_id} ({r.evidence})" for d in docs for r in d.relations
            if r.type == RelationType.NEAR_DUPLICATE_OF]
    corrections = [f"{d.meta.doc_id} {r.type.value} {r.target_doc_id} ({r.evidence})" for d in docs for r in d.relations
                   if r.type in {RelationType.CORRECTS, RelationType.RETRACTS}]
    injections = [
        f"{d.meta.doc_id}#{f.paragraph_ref or f.field}: {f.pattern} [{f.severity}] {f.excerpt[:90]!r}"
        for d in docs for f in d.injection_flags
    ]
    conflicts = [f"{d.meta.doc_id}: {f.detail}" for d in docs for f in d.damage_flags if f.kind == DamageKind.METADATA_CONFLICT]
    not_listed = [d.meta.doc_id for d in docs if any(f.kind == DamageKind.NOT_IN_MANIFEST for f in d.damage_flags)]
    encodings = {d.meta.doc_id: d.parser.encoding for d in docs
                 if d.parser.encoding and d.parser.encoding not in {"utf-8", "empty"}}
    rows = [r for t in rep.tables for r in t.rows]
    invalid = {r.row_id: f"{r.status.value}: {r.damage_reason}" for r in rows if r.status != RowStatus.VALID}
    row_warnings = {r.row_id: r.warnings for r in rows if r.warnings}
    table_flags = {t.table_id: [f"{f.kind.value}: {f.detail}" for f in t.damage_flags] for t in rep.tables if t.damage_flags}
    late: list[str] = []
    try:
        pack_as_of = date.fromisoformat(str(rep.pack_as_of)) if rep.pack_as_of else None
    except ValueError:
        pack_as_of = None
    if pack_as_of:
        late = [f"{d.meta.doc_id} ({d.meta.pub_date})" for d in docs if d.meta.pub_date and d.meta.pub_date > pack_as_of]
    undated = [d.meta.doc_id for d in docs if d.meta.pub_date is None]
    return {
        "pack_id": rep.pack_id,
        "pack_dir": str(rep.pack_dir),
        "manifest_count": rep.manifest_count,
        "documents": len(docs),
        "by_format": dict(sorted(fmt.items())),
        "valid": len(docs) - len(damaged),
        "damaged": damaged,
        "exact_duplicates": exact,
        "possible_duplicates": near,
        "corrections": corrections,
        "injection_flags": injections,
        "injection_flags_by_severity": dict(Counter(f.severity for d in docs for f in d.injection_flags)),
        "metadata_conflicts": conflicts,
        "not_in_manifest": not_listed,
        "non_utf8_encodings": encodings,
        "trade_tables": len(rep.tables),
        "trade_rows": {"total": len(rows), "valid": len(rows) - len(invalid), "invalid": len(invalid)},
        "invalid_rows": invalid,
        "row_warnings": row_warnings,
        "table_flags": table_flags,
        "pack_problems": rep.problems,
        "errors": rep.errors,
        "skipped": rep.skipped,
        "pack_as_of": str(pack_as_of) if pack_as_of else None,
        "published_after_pack_as_of": late,
        "undated": undated,
    }


def _print(s: dict) -> None:
    def section(title: str, items) -> None:
        print(f"\n{title} ({len(items)}):")
        if not items:
            print("  none")
        elif isinstance(items, dict):
            for k, v in items.items():
                if isinstance(v, list):
                    print(f"  {k}:")
                    for x in v:
                        print(f"    - {x}")
                else:
                    print(f"  {k}: {v}")
        else:
            for x in items:
                print(f"  - {x}")

    print(f"Pack {s['pack_id']}  ({s['pack_dir']})")
    print(f"Documents: {s['documents']} (manifest count {s['manifest_count']})  by format: "
          + ", ".join(f"{k}={v}" for k, v in s["by_format"].items()))
    print(f"Valid: {s['valid']}  Damaged: {len(s['damaged'])}")
    section("Damaged documents", s["damaged"])
    section("Exact duplicates (duplicate -> canonical)", s["exact_duplicates"])
    section("Possible duplicates (flagged, not merged)", s["possible_duplicates"])
    section("Corrections / retractions", s["corrections"])
    print(f"\nInjection flags by severity: {s['injection_flags_by_severity'] or 'none'}")
    section("Injection flags", s["injection_flags"])
    section("Metadata conflicts", s["metadata_conflicts"])
    section("Not in manifest", s["not_in_manifest"])
    section("Non-UTF-8 encodings", s["non_utf8_encodings"])
    section(f"Published after the pack's as_of {s['pack_as_of']} (stored; blocked by the as_of gate at retrieval)",
            s["published_after_pack_as_of"])
    if s["undated"]:
        section("Undated (no readable PUB_DATE; never pass an as_of gate)", s["undated"])
    tr = s["trade_rows"]
    print(f"\nTrade tables: {s['trade_tables']}  rows: {tr['total']} (valid {tr['valid']}, invalid {tr['invalid']})")
    section("Invalid trade rows", s["invalid_rows"])
    section("Row warnings (kept valid)", s["row_warnings"])
    section("Trade table flags", s["table_flags"])
    section("Pack problems", s["pack_problems"])
    section("Errors", s["errors"])
    if s["skipped"]:
        section("Skipped (ID already stored from another pack)", s["skipped"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.ingest", description="Ingest a Runemark pack into the evidence store.")
    ap.add_argument("pack_dir", type=Path, help="folder containing manifest.json (and docs/)")
    ap.add_argument("--db", type=Path, default=None, help="SQLite path (default: DB_PATH from config)")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = ap.parse_args(argv)
    settings = get_settings()
    db = args.db or settings.db_path
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        with Store(db) as store:
            rep = ingest_pack(args.pack_dir, store, settings)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    s = summarise(rep)
    if args.json:
        print(json.dumps(s, indent=2, default=str))
    else:
        _print(s)
        print(f"\nStored in {db}")
    return 0
