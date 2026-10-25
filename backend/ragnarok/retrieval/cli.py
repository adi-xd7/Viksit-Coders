"""Command line search over the evidence store.

    python -m backend.search "<query>" --as-of YYYY-MM-DD [--country X] [--sector Y]
        [--event-id E] [--source-type T] [--max-reliability 2] [--date-from D] [--date-to D]
        [--limit N] [--agent heimdall] [--include-duplicates] [--case ID] [--db PATH] [--json]
    python -m backend.search --ingest <pack_dir>          hot-ingest a pack into the live index
    python -m backend.search --export-log out.jsonl [--case ID]
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from datetime import date
from pathlib import Path

from ragnarok.config import get_settings
from ragnarok.retrieval.service import ADHOC_CASE, RetrievalService
from ragnarok.retrieval.types import SearchFilters
from ragnarok.store.db import Store


def _print_result(res) -> None:
    f = {k: v for k, v in res.filters.model_dump(mode="json").items() if v not in (None, False)}
    print(f"Query: {res.query!r}  as_of {res.as_of}  agent {res.agent.value}  filters {f or 'none'}")
    print(f"{len(res.hits)} hit(s) from {res.candidates} candidate paragraph(s)"
          + (f"  [REUSED from query #{res.first_query_seq}]" if res.reused else f"  [query #{res.query_seq}]"))
    for n, h in enumerate(res.hits, 1):
        flags = []
        if h.damage:
            flags.append("damaged: " + ",".join(h.damage))
        if h.injection_flagged:
            flags.append("INJECTION-FLAGGED")
        if h.possible_duplicate_of:
            flags.append("possible duplicate of " + ",".join(h.possible_duplicate_of))
        if h.duplicate_of:
            flags.append("duplicate of " + h.duplicate_of)
        if h.corrected_by:
            flags.append("corrected by " + ",".join(h.corrected_by))
        if h.corrects:
            flags.append("corrects " + ",".join(h.corrects))
        s = h.scores
        print(f"\n[{n}] {h.chunk_id}  {h.pub_date}{' ' + h.pub_time.strftime('%H:%M') if h.pub_time else ''}  "
              f"tier {h.reliability_tier}  {h.source_type} / {h.source_name}  "
              f"{h.country or '-'} / {h.sector or '-'}{(' (table: ' + ','.join(h.table_sectors) + ')') if h.table_sectors else ''}"
              f"  event {h.event_id or 'background'}")
        print(f"    {h.title}")
        print(f"    rrf {s.rrf:.4f}  bm25 #{s.bm25_rank or '-'}  vector #{s.vector_rank} (cos {s.cosine:.3f})"
              + (f"  [{'; '.join(flags)}]" if flags else ""))
        print(textwrap.indent(textwrap.fill(h.text, 100), "    > "))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.search", description="Search Runemark evidence (as_of-gated).")
    ap.add_argument("query", nargs="?")
    ap.add_argument("--as-of", type=date.fromisoformat, help="mandatory for searches: YYYY-MM-DD")
    ap.add_argument("--country", action="append")
    ap.add_argument("--sector", action="append")
    ap.add_argument("--event-id", action="append")
    ap.add_argument("--source-type", action="append")
    ap.add_argument("--max-reliability", type=int)
    ap.add_argument("--date-from", type=date.fromisoformat)
    ap.add_argument("--date-to", type=date.fromisoformat)
    ap.add_argument("--include-duplicates", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--agent", default="heimdall")
    ap.add_argument("--case", default=None, help=f"case ID for the audit log (default {ADHOC_CASE!r})")
    ap.add_argument("--db", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ingest", type=Path, metavar="PACK_DIR", help="hot-ingest a pack into the live store and index")
    ap.add_argument("--export-log", type=Path, metavar="OUT.jsonl", help="export the audit log (optionally --case)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()
    with Store(args.db or settings.db_path) as store:
        svc = RetrievalService(store, settings)
        if args.export_log:
            n = store.export_jsonl(args.export_log, args.case)
            print(f"exported {n} event(s) to {args.export_log}")
            return 0
        if args.ingest:
            rep = svc.hot_ingest(args.ingest, case_id=args.case or ADHOC_CASE)
            print(f"hot-ingested pack {rep.pack_id}: {len(rep.documents)} document(s), {len(rep.errors)} error(s); "
                  f"index now {len(svc.index.chunks)} paragraphs")
            return 0 if not rep.errors else 1
        if not args.query:
            ap.error("a query is required (or use --ingest / --export-log)")
        if args.as_of is None:
            ap.error("--as-of is required: every search is bounded by an as-of date")
        filters = SearchFilters(country=args.country, sector=args.sector, event_id=args.event_id,
                                source_type=args.source_type, max_reliability=args.max_reliability,
                                date_from=args.date_from, date_to=args.date_to, include_duplicates=args.include_duplicates)
        res = svc.search(args.query, args.as_of, args.agent, filters, args.limit, case_id=args.case or ADHOC_CASE)
        if args.json:
            print(res.model_dump_json(indent=2))
        else:
            _print_result(res)
    return 0
