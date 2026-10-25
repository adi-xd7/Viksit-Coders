"""Run a trial from the command line.

    python -m backend.trial "<question>" --as-of YYYY-MM-DD [--db PATH] [--stop-after HEIMDALL|THOR_LOKI]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from ragnarok.config import get_settings
from ragnarok.store.db import Store
from ragnarok.trial.machine import Stage, Trial


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.trial", description="Run one Trial of the Nine Realms case.")
    ap.add_argument("question")
    ap.add_argument("--as-of", type=date.fromisoformat, required=True)
    ap.add_argument("--db", type=Path)
    ap.add_argument("--case-id")
    ap.add_argument("--stop-after", choices=[Stage.HEIMDALL.value, Stage.ADVOCATES.value, Stage.CROSS_EXAM.value])
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()
    if not settings.has_api_key:
        print("error: ANTHROPIC_API_KEY is not set in .env", file=sys.stderr)
        return 2
    with Store(args.db or settings.db_path) as store:
        trial = Trial(args.question, args.as_of, store, settings, case_id=args.case_id)
        print(f"case {trial.case_id}: running (logs in {trial.case_dir})", flush=True)
        r = trial.run(Stage(args.stop_after) if args.stop_after else None)
    print(f"\nstage: {r.stage.value}   path: {' -> '.join(r.history)}")
    if r.heimdall:
        cf = r.heimdall.case_file
        print(f"event: {cf.event_status.value} — {cf.event_verification_notes[:300]}")
        print(f"countries {cf.countries}  sectors {cf.sectors}  trade tables {cf.trade_table_ids}")
    if r.stop_reason:
        print(f"STOPPED: {r.stop_reason}")
    for a, s in r.submissions.items():
        print(f"{a}: {len(s.claims)} claim(s), {len(s.rejected)} rejected in code{' — FAILED: ' + s.failed if s.failed else ''}")
    if r.cross_exam:
        cx = r.cross_exam
        print(f"cross-exam: {len(cx.attacks)} attack(s), {len(cx.defenses)} defense(s), {len(cx.concessions)} concession(s), "
              f"{len(cx.invalid_defenses)} invalid defense(s), {len(cx.unanswered)} unanswered")
    if r.odin:
        print("verdicts:", dict(Counter(x.verdict.value for x in r.odin.rulings)), "unruled:", r.odin.unruled)
        for e in r.odin.ranges:
            print(f"  Odin {e.country}/{e.sector}: {e.low}..{e.high} {e.unit} ({e.metric})")
        for i in r.odin.insufficient:
            print(f"  Odin {i['country']}/{i['sector']}: insufficient — {'; '.join(i['missing_data'])[:150]}")
        print(f"sufficiency: {'sufficient' if r.odin.sufficient else 'INSUFFICIENT'} — {r.odin.sufficiency_reason[:200]}")
    for n in r.notes:
        print(f"note: {n}")
    print(f"usage: {r.usage}")
    print(f"files: {r.case_dir}")
    return 0 if r.stage in (Stage.DONE, Stage.STOPPED) or (args.stop_after and r.stage != Stage.FAILED) else 1
