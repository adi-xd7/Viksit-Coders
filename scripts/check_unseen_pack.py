"""Check that an unseen pack is ingested correctly, end to end through the running API.

Zips the pack folder, uploads it with POST /ingest (exactly as a new pack is added from the dashboard),
then reads the results back through GET /feed, /docs and /trade and compares them with the
<pack>.expected.json written by scripts/build_random_pack.py. No LLM requests are made.

Usage: .venv/Scripts/python scripts/check_unseen_pack.py data/dryrun/random_s11 [--api http://127.0.0.1:8000]
Exit code 0 when every check passes.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import httpx


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pack", type=Path)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--no-upload", action="store_true", help="the pack is already ingested; only check")
    a = ap.parse_args()
    exp = json.loads((a.pack.parent / f"{a.pack.name}.expected.json").read_text(encoding="utf-8"))
    as_of = exp["as_of"]
    c = httpx.Client(base_url=a.api, timeout=300)
    results: list[tuple[bool, str]] = []

    def check(ok: bool, what: str) -> None:
        results.append((bool(ok), what))
        print(("PASS " if ok else "FAIL ") + what)

    if not a.no_upload:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(a.pack.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(a.pack).as_posix())
        r = c.post("/ingest", files={"file": (f"{a.pack.name}.zip", buf.getvalue(), "application/zip")})
        check(r.status_code == 200, f"POST /ingest accepted the pack zip (HTTP {r.status_code})")
        if r.status_code != 200:
            print(r.text[:500])
            return 1
        s = r.json()
        print(f"     ingest: {s['documents']} documents, {s['tables']} tables, {s['damaged']} damaged, "
              f"{s['injection_flags']} injection flags, {len(s['errors'])} errors")
        check(s["documents"] == exp["documents"], f"all {exp['documents']} documents ingested (got {s['documents']})")
        check(not s["errors"], f"no ingest errors {s['errors'][:3] if s['errors'] else ''}")
        check(s["tables"] >= len(exp["tables"]), f"{len(exp['tables'])} trade tables found (got {s['tables']})")

    feed = c.get("/feed", params={"as_of": as_of, "limit": 1000}).json()
    items = {i["doc_id"]: i for i in feed["items"]}
    b = lambda d: items.get(d, {}).get("badges", {})  # noqa: E731

    for d in exp["blocked_after_as_of"]:
        r = c.get(f"/docs/{d}", params={"as_of": as_of})
        check(d not in items and r.status_code == 403, f"{d} (published after the as-of date) is withheld from the feed and refused with 403 (HTTP {r.status_code})")
    for d in exp["injection_docs"]:
        doc = c.get(f"/docs/{d}", params={"as_of": as_of}).json()
        flagged = [p["ref"] for p in doc.get("paragraphs", []) if p["injection_flagged"]]
        check(bool(b(d).get("injection")) and flagged, f"{d}: embedded instruction flagged (paragraphs {flagged}), text kept as data")
    for dup, orig in exp["duplicate_pairs"]:
        check(orig in b(dup).get("duplicate_of", []), f"{dup} linked as an exact duplicate of {orig}")
    for corr, wrong in exp["correction_pairs"]:
        check(wrong in b(corr).get("corrects", []) and corr in b(wrong).get("corrected_by", []),
              f"{corr} linked as the correction of {wrong} (both kept)")
    for d, why in exp["damaged_docs"].items():
        check(bool(b(d).get("damaged")), f"{d} marked damaged ({why}): {b(d).get('damaged')}")
    d = exp["mixed_encoding_doc"]
    doc = c.get(f"/docs/{d}", params={"as_of": as_of}).json()
    text = " ".join(p["text"] for p in doc.get("paragraphs", []))
    check(len(doc.get("paragraphs", [])) >= 2 and "�" not in text and "Buyers" in text,
          f"{d}: ASCII header + UTF-16 body decoded ({len(doc.get('paragraphs', []))} paragraphs, no replacement characters)")
    for d in exp["no_markers_docs"]:
        doc = c.get(f"/docs/{d}", params={"as_of": as_of}).json()
        check(len(doc.get("paragraphs", [])) >= 2, f"{d}: no [Pn] markers, split into {len(doc.get('paragraphs', []))} paragraphs")
    for d in exp["alias_header_docs"]:
        i = items.get(d, {})
        check(i.get("reliability_tier") == 2 and i.get("event_id") == exp["event_id"] and i.get("pub_date"),
              f"{d}: header with lower-case / alias keys read (tier {i.get('reliability_tier')}, event {i.get('event_id')}, date {i.get('pub_date')})")
    for d in exp["decoy_docs"]:
        check(items.get(d, {}).get("event_id") not in (None, exp["event_id"]), f"{d}: other-event document keeps its own event ID ({items.get(d, {}).get('event_id')})")

    for tid, t in exp["tables"].items():
        r = c.get(f"/trade/{tid}", params={"as_of": as_of})
        if r.status_code != 200:
            check(False, f"table {tid} ({t['layout']}) readable (HTTP {r.status_code})")
            continue
        tab = r.json()
        rows = tab["rows"]
        bad = {x["period"]: x["status"] for x in rows if x["status"] != "valid"}
        good = [x for x in rows if x["status"] == "valid"]
        pair_ok = f"{tab['table']['origin']} -> {tab['table']['destination']}" == t["pair"]
        check(pair_ok, f"table {tid} ({t['layout']}): route {tab['table']['origin']} -> {tab['table']['destination']} (expected {t['pair']})")
        missed = [p for p in t["invalid_periods"] if p not in bad]
        check(not missed, f"table {tid} ({t['layout']}, {t['damage']}): damaged row(s) {list(t['invalid_periods'])} not used as valid; "
                          f"invalid: {bad}{'; MISSED ' + str(missed) if missed else ''}")
        extra = [p for p in bad if p not in t["invalid_periods"]]
        check(not extra and all(x["value"] is not None and x["volume"] is not None for x in good),
              f"table {tid}: the other {len(good)} rows are valid with value and volume{'; wrongly invalid: ' + str(extra) if extra else ''}")

    failed = [w for ok, w in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
