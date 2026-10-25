"""Tests for the Executive Briefing Generator (Part 7)."""

from pathlib import Path
import pytest

from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.evidence import EvidenceReference
from backend.app.schemas.claim import Claim, ExposureEstimate
from backend.app.schemas.debate import Concession
from backend.app.schemas.heimdall_result import HeimdallVerificationResult, PremiseVerification
from backend.app.schemas.odin_result import OdinResult, ClaimRuling
from backend.app.schemas.debate_result import DebateResult
from backend.app.schemas.feedback_loop import TrialRecord
from backend.app.schemas.executive_briefing import ExecutiveBriefing
from backend.app.services.executive_briefing import ExecutiveBriefingGenerator
from backend.app.services.debate_orchestrator import DebateOrchestrator
from backend.app.services.retrieval import RunemarkCorpusRetrievalService
from backend.app.services.memory import LokiMemoryService
from backend.app.services.thor_memory import ThorMemoryService


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_case_file() -> CaseFile:
    return CaseFile(
        case_id="CASE-E5-BRIEFING",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
    )


@pytest.fixture
def mock_evidence_refs() -> dict[str, EvidenceReference]:
    return {
        "ORV-0016": EvidenceReference(
            doc_id="ORV-0016",
            paragraph="P1",
            reliability_tier=1,
            source_name="Realm Trade Ministry",
            publication_date="2026-09-10",
            quote_or_datapoint="The Corridor Agreement expired on 10 September 2026 without renewal.",
        ),
        "ORV-0007": EvidenceReference(
            doc_id="ORV-0007",
            paragraph="P1",
            reliability_tier=2,
            source_name="Harbour Review",
            publication_date="2026-09-14",
            quote_or_datapoint="Indefinite port strike commenced at Orvan Grain Port on 14 September 2026.",
        ),
        "ORV-0001": EvidenceReference(
            doc_id="ORV-0001",
            paragraph="P2",
            reliability_tier=2,
            source_name="Vantro Trading",
            publication_date="2026-10-20",
            quote_or_datapoint="The rail link can take only a fraction of normal port sea volume.",
        ),
        "ORV-0018": EvidenceReference(
            doc_id="ORV-0018",
            paragraph="P4",
            reliability_tier=3,
            source_name="Grain Logistics Quarterly",
            publication_date="2026-11-05",
            quote_or_datapoint="Ravik Rail link operates at practical ceiling (+54% over USD 25M base).",
        ),
        "ORV-0027": EvidenceReference(
            doc_id="ORV-0027",
            paragraph="P6",
            reliability_tier=1,
            source_name="Midgard Trade Authority",
            publication_date="2026-11-15",
            quote_or_datapoint="Vanir to Midgard direct wheat shipments surged to 96,000 tonnes in Nov 2026.",
        ),
        "ORV-0046": EvidenceReference(
            doc_id="ORV-0046",
            paragraph="P7",
            reliability_tier=1,
            source_name="Realm Trade Ministry",
            publication_date="2027-01-20",
            quote_or_datapoint="Tolan 2026-Q4 wheat imports dropped from USD 115.8M base to USD 46.2M.",
        ),
        "ORV-0043": EvidenceReference(
            doc_id="ORV-0043",
            paragraph="P1",
            reliability_tier=4,
            source_name="Port City Rumor Sheet",
            publication_date="2026-10-15",
            quote_or_datapoint="RETRACTED: Fake notice claiming corridor agreement was secretly renewed.",
        ),
        "ORV-POST": EvidenceReference(
            doc_id="ORV-POST",
            paragraph="P1",
            reliability_tier=1,
            source_name="Future Dispatch",
            publication_date="2027-02-10",
            quote_or_datapoint="Post-cutoff notice published in February 2027.",
        ),
    }


@pytest.fixture
def completed_debate_result(
    sample_case_file: CaseFile,
    mock_evidence_refs: dict[str, EvidenceReference]
) -> DebateResult:
    """A realistic completed multi-trial DebateResult."""
    # Heimdall verification
    heimdall = HeimdallVerificationResult(
        agent="heimdall",
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        event_id=sample_case_file.event_id,
        is_event_real=True,
        verification_status="verified",
        premises=[
            PremiseVerification(
                premise_id="P1",
                premise="Corridor Agreement expired on 2026-09-10 without renewal.",
                status="verified",
                confidence=0.95,
                reasoning="Confirmed by official notice ORV-0016.",
                citations=[mock_evidence_refs["ORV-0016"]],
            ),
            PremiseVerification(
                premise_id="P2",
                premise="Port strike commenced at Orvan Grain Port on 2026-09-14.",
                status="verified",
                confidence=0.90,
                reasoning="Confirmed by maritime wire ORV-0007.",
                citations=[mock_evidence_refs["ORV-0007"]],
            ),
        ],
        unverified_premises=[],
        contradicted_premises=[],
        evidence_examined=["ORV-0016", "ORV-0007"],
        summary="Heimdall verified the disruption event is genuine and active.",
    )

    # Thor high-exposure claims
    thor_claim = Claim(
        claim_id="THOR-C01",
        agent="thor",
        stance="high_exposure",
        claim_type="sourced_fact",
        statement="Orvan sea grain export loadings dropped over 50% year-over-year in 2026-Q4.",
        reasoning="Port strike and agreement termination halted sea departures.",
        confidence=0.85,
        estimates=[
            ExposureEstimate(
                country="Orvan",
                sector="Wheat",
                metric="sea_export_value_loss_pct",
                min_estimate=50.0,
                max_estimate=60.0,
                unit="%",
                period="2026-Q4",
                assumptions=["Corridor ended 10 Sept", "Port strike began 14 Sept"],
            )
        ],
        citations=[mock_evidence_refs["ORV-0016"], mock_evidence_refs["ORV-0007"]],
    )

    # Loki limited-exposure claims
    loki_claim = Claim(
        claim_id="LOKI-C01",
        agent="loki",
        stance="limited_exposure",
        claim_type="sourced_fact",
        statement="Midgard and Tolan wheat exposure is mitigated by Ravik rail link and Vanir deliveries.",
        reasoning="Rail increased +54% and Vanir direct trade cushioned supply.",
        confidence=0.88,
        estimates=[
            ExposureEstimate(
                country="Midgard",
                sector="Wheat",
                metric="net_value_loss_pct",
                min_estimate=35.0,
                max_estimate=45.0,
                unit="%",
                period="2026-Q4",
                assumptions=["Ravik rail operating near ceiling", "Vanir wheat replaces volume"],
            )
        ],
        citations=[
            mock_evidence_refs["ORV-0001"],
            mock_evidence_refs["ORV-0018"],
            mock_evidence_refs["ORV-0027"],
            mock_evidence_refs["ORV-0046"],
        ],
    )

    sample_case_file.claims = [thor_claim, loki_claim]
    sample_case_file.concessions = [
        Concession(
            concession_id="THOR-CON01",
            agent="thor",
            target_claim_id="THOR-C01",
            action="adjust_range",
            reason="Acknowledging Ravik rail link (+54%) mitigates total economic loss to 35%-45%.",
            adjusted_estimates=[
                ExposureEstimate(
                    country="Midgard",
                    sector="Wheat",
                    metric="net_value_loss_pct",
                    min_estimate=35.0,
                    max_estimate=45.0,
                    unit="%",
                    period="2026-Q4",
                    assumptions=["Adjusted following Loki cross-examination on rail link"],
                )
            ],
            defence_citations=[mock_evidence_refs["ORV-0018"]],
        )
    ]

    # Odin final rulings
    odin_res = OdinResult(
        agent="odin",
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        run_number=2,
        adjudication_status="completed",
        claim_rulings=[
            ClaimRuling(
                claim_id="THOR-C01",
                claim_statement="Orvan sea grain export loadings dropped over 50% year-over-year in 2026-Q4.",
                proponent="thor",
                claim_type="sourced_fact",
                ruling="conceded",
                confidence=0.85,
                reasoning="Conceded and refined: Rail and Vanir substitutions limit net value loss to 35-45%.",
                supporting_citations=[mock_evidence_refs["ORV-0016"], mock_evidence_refs["ORV-0007"]],
                adjudicated_range=ExposureEstimate(
                    country="Midgard",
                    sector="Wheat",
                    metric="net_value_loss_pct",
                    min_estimate=35.0,
                    max_estimate=45.0,
                    unit="%",
                    period="2026-Q4",
                    assumptions=["Refined through formal concession"],
                ),
            ),
            ClaimRuling(
                claim_id="LOKI-C01",
                claim_statement="Midgard and Tolan wheat exposure is mitigated by Ravik rail link and Vanir deliveries.",
                proponent="loki",
                claim_type="sourced_fact",
                ruling="established",
                confidence=0.88,
                reasoning="Established: Substantial trade receipts and ministry notes corroborate substitution.",
                supporting_citations=[
                    mock_evidence_refs["ORV-0018"],
                    mock_evidence_refs["ORV-0027"],
                    mock_evidence_refs["ORV-0046"],
                ],
                adjudicated_range=ExposureEstimate(
                    country="Midgard",
                    sector="Wheat",
                    metric="net_value_loss_pct",
                    min_estimate=35.0,
                    max_estimate=45.0,
                    unit="%",
                    period="2026-Q4",
                    assumptions=["Corroborated by trade note ORV-0046"],
                ),
            ),
            ClaimRuling(
                claim_id="THOR-C02",
                claim_statement="Tolan grain processing sector faces immediate complete total collapse.",
                proponent="thor",
                claim_type="inference",
                ruling="contested",
                confidence=0.40,
                reasoning="Contested: Overstated claim unsupported by evidence; Vanir imports continue.",
                supporting_citations=[],
                contradicting_citations=[mock_evidence_refs["ORV-0046"]],
                evidence_gaps=["No evidence of complete mill shutdowns in Tolan."],
            ),
        ],
        established_claims=["LOKI-C01"],
        contested_claims=["THOR-C02"],
        conceded_claims=["THOR-C01"],
        unresolved_disputes=["Whether long-term Tolan mill capacity can endure ongoing spot freight premiums."],
        evidence_limitations=["Tolan inland storage reserve statistics unobserved in Q4."],
        evidence_examined=["ORV-0016", "ORV-0007", "ORV-0001", "ORV-0018", "ORV-0027", "ORV-0046"],
        is_evidence_sufficient=True,
        summary="Trial 2 adjudication completed. Core mitigation claims established; extreme collapse claim contested.",
    )

    t1_rec = TrialRecord(
        trial_number=1,
        status="success",
        is_evidence_sufficient=False,
        evidence_gaps_identified=["Lacked Vanir trade receipts in Trial 1."],
        gap_resolution_summary="Progress: Discovered new admissible trade notes ORV-0027 and ORV-0046.",
    )
    t2_rec = TrialRecord(
        trial_number=2,
        status="success",
        is_evidence_sufficient=True,
        gap_resolution_summary="Evidence sufficient: All material claims adjudicated with complete trade documentation.",
    )

    return DebateResult(
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        run_number=2,
        status="success",
        heimdall_verification=heimdall,
        odin_adjudication=odin_res,
        case_file=sample_case_file,
        stages_executed=[
            "validation", "heimdall_verification", "loki_round1", "thor_round1",
            "loki_round2", "thor_round2", "odin_adjudication"
        ],
        total_trials=2,
        retries_attempted=1,
        max_retries=2,
        loop_stop_reason="evidence_sufficient",
        trial_history=[t1_rec, t2_rec],
    )


# -----------------------------------------------------------------------------
# Test 1: Valid Final Adjudication Produces Correctly Structured Briefing
# -----------------------------------------------------------------------------

def test_valid_final_adjudication_produces_correctly_structured_briefing(
    completed_debate_result: DebateResult,
):
    """Requirement 1: A valid final adjudication produces a correctly structured briefing."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    assert isinstance(briefing, ExecutiveBriefing)
    assert briefing.case_id == "CASE-E5-BRIEFING"
    assert briefing.as_of_date == "2027-01-25"
    assert briefing.status == "completed"
    assert briefing.event_verified is True
    assert len(briefing.confirmed_disruption_facts) >= 2
    assert len(briefing.timeline) >= 2
    assert len(briefing.exposure_table) >= 1
    assert len(briefing.cited_sources) >= 4
    assert briefing.total_trials == 2
    assert briefing.loop_stop_reason == "evidence_sufficient"


# -----------------------------------------------------------------------------
# Test 2: Established Claims Appear as Established
# -----------------------------------------------------------------------------

def test_established_claims_appear_as_established(
    completed_debate_result: DebateResult,
):
    """Requirement 2: Established claims appear in established_claims and not in contested."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    est_ids = [c.claim_id for c in briefing.established_claims]
    assert "LOKI-C01" in est_ids
    assert "THOR-C02" not in est_ids
    for cl in briefing.established_claims:
        assert cl.ruling == "established"


# -----------------------------------------------------------------------------
# Test 3: Contested Claims Remain Explicitly Contested
# -----------------------------------------------------------------------------

def test_contested_claims_remain_explicitly_contested(
    completed_debate_result: DebateResult,
):
    """Requirement 3: Contested claims remain explicitly contested with unresolved reasoning."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    cont_ids = [c.claim_id for c in briefing.contested_claims]
    assert "THOR-C02" in cont_ids
    assert "LOKI-C01" not in cont_ids
    for cl in briefing.contested_claims:
        assert cl.ruling == "contested"
        assert len(cl.evidence_gaps) >= 1 or len(cl.contradicting_citations) >= 1


# -----------------------------------------------------------------------------
# Test 4: Concessions Attributed to Correct Advocate
# -----------------------------------------------------------------------------

def test_concessions_attributed_to_correct_advocate(
    completed_debate_result: DebateResult,
):
    """Requirement 4: Concessions are attributed to the correct advocate with reasoning and adjusted ranges."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    assert len(briefing.concessions) >= 1
    conc = briefing.concessions[0]
    assert conc.concession_id == "THOR-CON01"
    assert conc.advocate == "thor"
    assert conc.target_claim_id == "THOR-C01"
    assert conc.action == "adjust_range"
    assert conc.adjusted_range_str is not None
    assert "35.0 - 45.0 %" in conc.adjusted_range_str


# -----------------------------------------------------------------------------
# Test 5: Unsupported Claims Do Not Become Factual Assertions
# -----------------------------------------------------------------------------

def test_unsupported_claims_do_not_become_factual_assertions(
    completed_debate_result: DebateResult,
):
    """Requirement 5: Unsupported claims are excluded from confirmed facts."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    fact_text = " ".join(briefing.confirmed_disruption_facts)
    assert "complete total collapse" not in fact_text
    assert "THOR-C02" not in [r.claim_id for r in briefing.established_claims]


# -----------------------------------------------------------------------------
# Test 6: Quantitative Ranges Preserve Units, Time Periods, and Assumptions
# -----------------------------------------------------------------------------

def test_quantitative_ranges_preserve_units_time_periods_assumptions(
    completed_debate_result: DebateResult,
):
    """Requirement 6: Exposure table rows preserve country, sector, metric, units, and periods."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    assert len(briefing.exposure_table) >= 1
    row = briefing.exposure_table[0]
    assert row.unit in ("%", "USD M", "tonnes")
    assert row.period == "2026-Q4"
    assert len(row.key_assumptions) >= 1
    assert row.odin_adjudicated_range is not None
    assert "35.0 - 45.0" in row.odin_adjudicated_range


# -----------------------------------------------------------------------------
# Test 7: Conflicting Quantitative Estimates Are Not Silently Combined
# -----------------------------------------------------------------------------

def test_conflicting_quantitative_estimates_not_silently_combined(
    sample_case_file: CaseFile,
    mock_evidence_refs: dict[str, EvidenceReference],
):
    """Requirement 7: Thor and Loki conflicting estimates are presented side-by-side, not averaged."""
    thor_cl = Claim(
        claim_id="THOR-CONFLICT",
        agent="thor",
        stance="high_exposure",
        claim_type="inference",
        statement="Tolan grain loss is 70-80%.",
        reasoning="Severe shortfall.",
        estimates=[
            ExposureEstimate(country="Tolan", sector="Grain", metric="loss_pct", min_estimate=70.0, max_estimate=80.0)
        ],
        citations=[mock_evidence_refs["ORV-0016"]],
    )
    loki_cl = Claim(
        claim_id="LOKI-CONFLICT",
        agent="loki",
        stance="limited_exposure",
        claim_type="inference",
        statement="Tolan grain loss is 10-20%.",
        reasoning="Mild shortfall.",
        estimates=[
            ExposureEstimate(country="Tolan", sector="Grain", metric="loss_pct", min_estimate=10.0, max_estimate=20.0)
        ],
        citations=[mock_evidence_refs["ORV-0016"]],
    )
    sample_case_file.claims = [thor_cl, loki_cl]

    odin_res = OdinResult(
        agent="odin",
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        claim_rulings=[
            ClaimRuling(
                claim_id="THOR-CONFLICT",
                claim_statement="Tolan grain loss is 70-80%.",
                proponent="thor",
                ruling="contested",
                reasoning="Irreconcilable dispute.",
            ),
            ClaimRuling(
                claim_id="LOKI-CONFLICT",
                claim_statement="Tolan grain loss is 10-20%.",
                proponent="loki",
                ruling="contested",
                reasoning="Irreconcilable dispute.",
            ),
        ],
        established_claims=[],
        contested_claims=["THOR-CONFLICT", "LOKI-CONFLICT"],
        unresolved_disputes=["Tolan grain loss magnitude"],
        is_evidence_sufficient=False,
        summary="Contested estimates.",
    )

    debate_res = DebateResult(
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        case_file=sample_case_file,
        odin_adjudication=odin_res,
        status="success",
    )

    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(debate_res)

    row = next(r for r in briefing.exposure_table if r.country == "Tolan")
    assert "70.0 - 80.0 %" in str(row.thor_range)
    assert "10.0 - 20.0 %" in str(row.loki_range)
    # Must NOT be averaged to 45%
    assert row.odin_status == "contested"
    assert "Contested" in str(row.odin_adjudicated_range)


# -----------------------------------------------------------------------------
# Test 8: Citations Preserve Source Provenance
# -----------------------------------------------------------------------------

def test_citations_preserve_source_provenance(
    completed_debate_result: DebateResult,
):
    """Requirement 8: Citations preserve doc_id, paragraph, tier, source, pub_date, and quotes."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    assert len(briefing.cited_sources) >= 4
    for src in briefing.cited_sources:
        assert src.doc_id.startswith("ORV-")
        assert src.reliability_tier is not None
        assert 1 <= src.reliability_tier <= 4
        assert src.publication_date is not None
        assert src.quote_or_datapoint != ""


# -----------------------------------------------------------------------------
# Test 9: Post-Cutoff Evidence Cannot Appear as Admissible Supporting Evidence
# -----------------------------------------------------------------------------

def test_post_cutoff_evidence_filtered_from_briefing(
    completed_debate_result: DebateResult,
    mock_evidence_refs: dict[str, EvidenceReference],
):
    """Requirement 9: Citations with pub_date > as_of_date are rejected from cited_sources."""
    # Inject post-cutoff reference into Odin ruling
    ruling = completed_debate_result.odin_adjudication.claim_rulings[0]  # type: ignore
    ruling.supporting_citations.append(mock_evidence_refs["ORV-POST"])

    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    cited_ids = [s.doc_id for s in briefing.cited_sources]
    assert "ORV-POST" not in cited_ids


# -----------------------------------------------------------------------------
# Test 10: Retracted Evidence Is Not Presented as Authoritative
# -----------------------------------------------------------------------------

def test_retracted_evidence_not_presented_as_authoritative(
    completed_debate_result: DebateResult,
    mock_evidence_refs: dict[str, EvidenceReference],
):
    """Requirement 10: Retracted source ORV-0043 is strictly excluded from bibliography."""
    ruling = completed_debate_result.odin_adjudication.claim_rulings[0]  # type: ignore
    ruling.supporting_citations.append(mock_evidence_refs["ORV-0043"])

    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    cited_ids = [s.doc_id for s in briefing.cited_sources]
    assert "ORV-0043" not in cited_ids


# -----------------------------------------------------------------------------
# Test 11: Trial History Explains Relevant Revisions Without Overriding Final Rulings
# -----------------------------------------------------------------------------

def test_trial_history_explains_revisions_without_overriding_final_rulings(
    completed_debate_result: DebateResult,
):
    """Requirement 11: Multi-trial history is presented as an audit trace."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    assert len(briefing.trial_progression_summary) >= 2
    trace_text = "\n".join(briefing.trial_progression_summary)
    assert "Trial 1" in trace_text
    assert "Trial 2" in trace_text
    assert "Final Loop Termination Reason: 'evidence_sufficient'." in trace_text


# -----------------------------------------------------------------------------
# Test 12: Retry Exhaustion and Insufficient Evidence Reported Accurately
# -----------------------------------------------------------------------------

def test_retry_exhaustion_and_insufficient_evidence_reported_accurately(
    completed_debate_result: DebateResult,
):
    """Requirement 12: When loop stops due to retry exhaustion, briefing reflects insufficiency."""
    completed_debate_result.loop_stop_reason = "max_retries_exhausted"
    completed_debate_result.odin_adjudication.is_evidence_sufficient = False  # type: ignore

    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    assert briefing.status == "insufficient_evidence"
    assert briefing.is_evidence_sufficient is False
    assert briefing.loop_stop_reason == "max_retries_exhausted"
    assert "INSUFFICIENT" in briefing.executive_summary


# -----------------------------------------------------------------------------
# Test 13: Missing Final Adjudication Handled Explicitly
# -----------------------------------------------------------------------------

def test_missing_final_adjudication_handled_explicitly(
    sample_case_file: CaseFile,
):
    """Requirement 13: If OdinResult is completely missing, return clear insufficient_input result."""
    debate_res = DebateResult(
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        case_file=sample_case_file,
        odin_adjudication=None,
        status="partial",
    )

    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(debate_res)

    assert briefing.status == "insufficient_input"
    assert briefing.overall_confidence == 0.0
    assert briefing.established_claims == []
    assert briefing.exposure_table == []
    assert "incomplete" in briefing.executive_summary.lower()


# -----------------------------------------------------------------------------
# Test 14: Failed Debate Orchestration Produces Error Briefing
# -----------------------------------------------------------------------------

def test_failed_debate_orchestration_produces_error_briefing(
    sample_case_file: CaseFile,
):
    """Requirement 14: If debate halted in error, briefing status is error with diagnostic message."""
    debate_res = DebateResult(
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        case_file=sample_case_file,
        status="error",
        failed_stage="heimdall_verification",
        error_message="Foundational event premises contradicted.",
        loop_stop_reason="heimdall_gate_rejected",
    )

    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(debate_res)

    assert briefing.status == "error"
    assert briefing.event_verified is False
    assert briefing.error_message == "Foundational event premises contradicted."
    assert briefing.loop_stop_reason == "heimdall_gate_rejected"


# -----------------------------------------------------------------------------
# Test 15: Recommendations Are Grounded in Evidence and Clearly Qualified
# -----------------------------------------------------------------------------

def test_recommendations_grounded_and_qualified(
    completed_debate_result: DebateResult,
):
    """Requirement 15: Recommendations are qualified and grounded in substantiated findings."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    assert briefing.recommendations_qualified is True
    assert len(briefing.recommended_actions) >= 2
    rec_text = " ".join(briefing.recommended_actions)
    assert "Recommendations are subject to data availability" in rec_text


# -----------------------------------------------------------------------------
# Test 16: Output Validates Against Briefing Schema
# -----------------------------------------------------------------------------

def test_output_validates_against_briefing_schema(
    completed_debate_result: DebateResult,
):
    """Requirement 16: Serializing and deserializing to JSON confirms schema adherence."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(completed_debate_result)

    json_str = briefing.model_dump_json()
    reloaded = ExecutiveBriefing.model_validate_json(json_str)

    assert reloaded.case_id == briefing.case_id
    assert len(reloaded.exposure_table) == len(briefing.exposure_table)


# -----------------------------------------------------------------------------
# Test 17: None Input Handled Safely
# -----------------------------------------------------------------------------

def test_none_input_handled_safely():
    """Requirement 17: Passing None returns an insufficient_input briefing without crashing."""
    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(None)  # type: ignore

    assert briefing.status == "insufficient_input"
    assert briefing.error_message == "DebateResult is None."


# -----------------------------------------------------------------------------
# Test 18: Official Runemark dev_pack_E5 End-to-End Integration
# -----------------------------------------------------------------------------

def test_official_corpus_e5_executive_briefing_integration(tmp_path: Path):
    """Requirement 18: Run full debate orchestrator against dev_pack_E5 and verify briefing."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[2] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    if not pack_dir.exists():
        pytest.skip("Official dev_pack_E5 corpus directory not available.")

    retrieval = RunemarkCorpusRetrievalService(str(pack_dir))
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=1,
    )

    case_file = CaseFile(
        case_id="CASE-CORPUS-E5-BRIEFING",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
    )

    debate_result = orchestrator.run_debate(case_file)
    assert debate_result.status == "success"

    generator = ExecutiveBriefingGenerator()
    briefing = generator.generate_briefing(debate_result)

    assert briefing.status == "completed"
    assert briefing.case_id == "CASE-CORPUS-E5-BRIEFING"
    assert briefing.event_id == "E5"
    assert briefing.event_verified is True
    assert len(briefing.timeline) >= 1
    assert len(briefing.exposure_table) >= 1
    assert len(briefing.established_claims) >= 1
    assert len(briefing.cited_sources) >= 1
    assert briefing.next_quarter_outlook != ""
    assert len(briefing.recommended_actions) >= 1
