"""CLI runner for demonstrating and executing the Loki agent locally."""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.claim import Claim, ExposureEstimate
from backend.app.schemas.evidence import EvidenceReference
from backend.app.schemas.debate import CrossExamination
from backend.app.services.retrieval import RunemarkCorpusRetrievalService, MockRetrievalService
from backend.app.services.memory import LokiMemoryService
from backend.app.services.logging_service import StructuredLogger
from backend.app.agents.loki import LokiAgent


def run_loki_cli():
    parser = argparse.ArgumentParser(description="Run the Loki courtroom agent locally.")
    parser.add_argument("--case-id", default="CASE-E5-RUNEMARK", help="Unique Case ID")
    parser.add_argument("--as-of-date", default="2027-01-25", help="As-of cutoff date (YYYY-MM-DD)")
    parser.add_argument("--round", type=int, default=1, choices=[1, 2], help="Trial round (1: Claims, 2: Cross-examination & Concessions)")
    parser.add_argument("--run", type=int, default=1, help="Trial run number (1 or 2)")
    parser.add_argument("--pack-dir", default="03_Ragnarok Trial of the Nine Realms/dev_pack_E5", help="Path to dev_pack_E5")
    parser.add_argument("--use-mock", action="store_true", help="Force using mock retrieval instead of real Runemark corpus")
    parser.add_argument("--json", action="store_true", help="Output full JSON result")

    args = parser.parse_args()

    # Initialize retrieval
    pack_path = Path(args.pack_dir)
    if not pack_path.exists():
        fallback_path = Path(__file__).resolve().parent.parent / args.pack_dir
        if fallback_path.exists():
            pack_path = fallback_path

    if pack_path.exists() and not args.use_mock:
        retrieval = RunemarkCorpusRetrievalService(pack_dir=str(pack_path))
        print(f"[*] Ingested {len(retrieval.index)} documents from real Runemark corpus: {pack_path}")
    else:
        print("[!] Using mock retrieval service (synthetic test fixtures)")
        retrieval = MockRetrievalService()

    memory = LokiMemoryService()
    logger = StructuredLogger(agent_name="loki")
    agent = LokiAgent(retrieval_service=retrieval, memory_service=memory, logger_service=logger)

    question = (
        "As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement? "
        "Give a low and high range for wheat and maize imports."
    )

    case_file = CaseFile(
        case_id=args.case_id,
        question=question,
        as_of_date=args.as_of_date,
        is_verified=True,
        event_id="E5",
        round_number=args.round,
        run_number=args.run,
    )

    # In Round 2, supply Loki's claim, Thor's counter-claim, and Thor's attack to demonstrate full debate
    if args.round == 2:
        case_file.claims.append(Claim(
            claim_id="LOKI-C01",
            agent="loki",
            stance="limited_exposure",
            claim_type="inference",
            statement="Midgard wheat exposure is limited to 35%-45% by Ravik rail and Vanir supply.",
            reasoning="Rail movements and Vanir parcels cushion net commercial drop.",
            confidence=0.85,
            estimates=[ExposureEstimate(country="Midgard", sector="Wheat", metric="net_value_loss_pct", min_estimate=35.0, max_estimate=45.0, unit="%")],
            citations=[EvidenceReference(doc_id="ORV-0027", paragraph="P6", quote_or_datapoint="Vanir wheat Nov value USD 38.5M")]
        ))
        case_file.claims.append(Claim(
            claim_id="THOR-C01",
            agent="thor",
            stance="high_exposure",
            claim_type="inference",
            statement="Midgard and Tolan face catastrophic 80% to 90% trade loss due to port paralysis.",
            reasoning="Orvan sea loadings fell 62% and millers are unable to fully substitute.",
            confidence=0.9,
            estimates=[ExposureEstimate(country="Midgard", sector="Wheat", metric="net_value_loss_pct", min_estimate=80.0, max_estimate=90.0, unit="%")],
            citations=[EvidenceReference(doc_id="ORV-0028", paragraph="P1", reliability_tier=4, quote_or_datapoint="FAMINE FEAR AS ORVAN GRAIN VANISHES")]
        ))
        case_file.attacks.append(CrossExamination(
            challenge_id="THOR-X01",
            challenger="thor",
            target_claim_id="LOKI-C01",
            challenge_type="unsupported_inference",
            objection="Ravik Rail Link is a single track with siding constraints and cannot absorb maritime volumes.",
            reasoning="ORV-0001 confirmed rail is only a partial bridge.",
            counter_citations=[]
        ))

    print(f"\n[*] Executing Loki Agent Turn: Case={args.case_id}, Round={args.round}, Run={args.run}, As-Of={args.as_of_date}...")
    result = agent.investigate_and_argue(case_file)

    if args.json:
        print(json.dumps(result.model_dump(), indent=2))
        return

    # Formatted terminal presentation
    print("\n" + "=" * 80)
    print(f"LOKI AGENT BRIEFING — STATUS: {result.status.upper()}")
    print("=" * 80)

    print(f"\n[CLAIMS SUBMITTED: {len(result.claims)}]")
    for c in result.claims:
        print(f"\n  [{c.claim_id}] ({c.stance.upper()} | {c.claim_type}) Confidence: {c.confidence:.2f}")
        print(f"  Statement: {c.statement}")
        print(f"  Reasoning: {c.reasoning}")
        for est in c.estimates:
            print(f"  -> Exposure: {est.format_range()}")
            for a in est.assumptions:
                print(f"     * Assumption: {a}")
        print(f"  Citations ({len(c.citations)}):")
        for cit in c.citations:
            print(f"     - {cit.to_citation_str()}")

    if result.attacks:
        print(f"\n[CROSS-EXAMINATION ATTACKS ON THOR: {len(result.attacks)}]")
        for x in result.attacks:
            print(f"\n  [{x.challenge_id}] Target: {x.target_claim_id} | Type: {x.challenge_type}")
            print(f"  Objection: {x.objection}")
            print(f"  Reasoning: {x.reasoning}")
            for cc in x.counter_citations:
                print(f"     - Counter-Evidence: {cc.to_citation_str()}")

    if result.concessions:
        print(f"\n[CONCESSIONS MADE: {len(result.concessions)}]")
        for con in result.concessions:
            print(f"\n  [{con.concession_id}] Action: {con.action.upper()} on {con.target_claim_id}")
            print(f"  Reason: {con.reason}")
            for adj in con.adjusted_estimates:
                print(f"  -> Adjusted Exposure: {adj.format_range()}")

    if result.uncertainties:
        print(f"\n[DOCUMENTED UNCERTAINTIES & GAPS: {len(result.uncertainties)}]")
        for u in result.uncertainties:
            print(f"  ! {u}")

    print("\n" + "=" * 80)
    print(f"Searches logged: {len(result.search_log)} | Memory references: {len(result.memory_used)}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_loki_cli()
