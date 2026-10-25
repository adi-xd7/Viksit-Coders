"""Run a trial from the command line.

    python -m backend.trial "<question>" --as-of YYYY-MM-DD [--db PATH] [--stop-after HEIMDALL|THOR_LOKI] [--save-demo]
    python -m backend.trial --resume <case_id>   (finished steps replay from the case's own response cache)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from ragnarok.config import get_settings
from ragnarok.store.db import Store
from ragnarok.trial.machine import Stage, new_case_id
from ragnarok.trial.runner import run_case


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.trial", description="Run one Trial of the Nine Realms case.")
    ap.add_argument("question", nargs="?")
    ap.add_argument("--as-of", type=date.fromisoformat)
    ap.add_argument("--resume", metavar="CASE_ID", help="resume an unfinished case (question and as-of from its state.json)")
    ap.add_argument("--db", type=Path)
    ap.add_argument("--case-id")
    ap.add_argument("--stop-after", choices=[Stage.HEIMDALL.value, Stage.ADVOCATES.value, Stage.CROSS_EXAM.value])
    ap.add_argument("--save-demo", action="store_true", help="also copy the case folder to logs/demo/<case_id>")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()
    if not settings.has_api_key:
        print(f"error: {settings.api_key_name} is not set in .env (LLM_PROVIDER={settings.llm_provider})", file=sys.stderr)
        return 2
    if args.db:
        settings = settings.model_copy(update={"db_path": args.db.resolve()})
    if args.resume:
        try:
            state = json.loads((settings.cases_dir / args.resume / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"error: no saved case {args.resume} in {settings.cases_dir}", file=sys.stderr)
            return 2
        args.question, args.as_of, args.case_id = state["question"], date.fromisoformat(state["as_of"]), args.resume
    if not args.question or not args.as_of:
        ap.error("a question and --as-of are required (or --resume CASE_ID)")
    case_id = args.case_id or new_case_id(args.question, args.as_of)
    print(f"case {case_id}: running (logs in {settings.cases_dir / case_id})", flush=True)
    r = run_case(args.question, args.as_of, settings, case_id=case_id,  # same core function as POST /cases
                 stop_after=Stage(args.stop_after) if args.stop_after else None)
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
    for run in r.runs:
        new = [e["ref"] for e in run.research.new_evidence] if run.research else []
        print(f"run {run.run_number}: {len(run.ruled_claims)} claim(s) ruled"
              + (f"; new evidence {new}" if run.research else "")
              + (f"; sent back for {len(run.sendback.missing)} missing item(s)" if run.sendback else ""))
    if r.superseded:
        print(f"superseded: {r.superseded}")
    with Store(settings.db_path) as store:
        evs = store.events(r.case_id)
    kinds = Counter(e.type.value for e in evs)
    print(f"memory: {kinds.get('MEMORY_READ', 0)} read(s), {kinds.get('MEMORY_WRITE', 0)} write(s), "
          f"{kinds.get('MEMORY_APPLIED', 0)} logged behaviour change(s)")
    for e in evs:
        if e.type.value == "MEMORY_APPLIED":
            print(f"  {e.summary[:240]}")
    print(f"briefing: {r.briefing_status or 'none'}")
    for n in r.notes:
        print(f"note: {n}")
    print(f"usage: {r.usage}")
    llm = r.usage.get("llm_calls", {})
    print(f"model requests: {llm.get('used')} (limit {llm.get('limit')}; {llm.get('cached', 0)} replayed from the case "
          f"cache); details in llm_calls.json")
    print(f"files: {r.case_dir}")
    if args.save_demo:
        dest = settings.log_dir / "demo" / r.case_id
        shutil.copytree(r.case_dir, dest, dirs_exist_ok=True)
        print(f"saved demo copy: {dest}")
    return 0 if r.stage in (Stage.DONE, Stage.STOPPED) or (args.stop_after and r.stage != Stage.FAILED) else 1
