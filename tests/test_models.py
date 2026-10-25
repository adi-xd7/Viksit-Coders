"""Every contract accepts good data and rejects bad data. Values are synthetic."""

from datetime import date

import pytest
from pydantic import ValidationError

from ragnarok.models import (
    AgentName,
    Attack,
    Briefing,
    BriefingFinding,
    CalcInput,
    CalculationRecord,
    CaseFile,
    Citation,
    Claim,
    ClaimType,
    Concession,
    Defense,
    DocMeta,
    Document,
    EventStatus,
    ExposureEstimate,
    ExposureRow,
    InjectionFlag,
    LogEvent,
    LogEventType,
    MemoryEntry,
    MissingEvidence,
    Outlook,
    Paragraph,
    ParserInfo,
    RowStatus,
    Ruling,
    SendBack,
    TradeRow,
    TradeTable,
    Verdict,
)

SHA = "a" * 64
AS_OF = date(2030, 6, 30)


def cite(doc="TST-0001", ref="P1", d=date(2030, 1, 10), row=None):
    return Citation(doc_id=doc, paragraph_ref=ref, row_id=row, pub_date=d, quote="quoted text")


def estimate(agent=AgentName.THOR, **kw):
    data = dict(
        estimate_id="E1", agent=agent, country="Alpha", sector="grain",
        metric="trade_value_change", metric_definition="Change in monthly import value vs prior year",
        unit="USD M", currency="USD", period="2030-01..2030-03", low=10.0, high=20.0,
        evidence=[cite()], trade_row_refs=["TBL-1#R1"],
    )
    data.update(kw)
    return ExposureEstimate(**data)


# ---------------------------------------------------------------- DocMeta ---


def test_docmeta_from_raw_mixed_case_and_types():
    raw = {
        "DOC_ID": "TST-0001", "EVENT_ID": "EV9", "TITLE": "T", "SOURCE_NAME": "Wire",
        "SOURCE_TYPE": "News", "RELIABILITY": "2", "PUB_DATE": "2030-01-10", "PUB_TIME": "09:15",
        "COUNTRY": "Alpha", "SECTOR": "Grain", "doc_id": "TST-0001", "reliability": 2, "file": "TST-0001.txt",
    }
    m = DocMeta.from_raw(raw)
    assert m.reliability_tier == 2 and m.sector == "grain" and m.source_type == "news"
    assert m.event_id == "EV9" and not m.is_background
    assert m.raw["RELIABILITY"] == "2"  # original kept


@pytest.mark.parametrize("ev", ["NONE", "none", "", None])
def test_docmeta_background_event(ev):
    m = DocMeta.from_raw({"DOC_ID": "B-1", "EVENT_ID": ev, "TITLE": "T", "SOURCE_NAME": "S",
                          "SOURCE_TYPE": "atlas", "RELIABILITY": 1, "PUB_DATE": "2029-01-01"})
    assert m.is_background


@pytest.mark.parametrize("bad", [
    {"PUB_DATE": "10/01/2030"}, {"PUB_DATE": "2030-13-01"}, {"RELIABILITY": "7"}, {"DOC_ID": "../etc"},
])
def test_docmeta_rejects_bad(bad):
    raw = {"DOC_ID": "TST-0001", "EVENT_ID": "E", "TITLE": "T", "SOURCE_NAME": "S",
           "SOURCE_TYPE": "news", "RELIABILITY": "2", "PUB_DATE": "2030-01-10"}
    raw.update(bad)
    with pytest.raises(ValidationError):
        DocMeta.from_raw(raw)


# --------------------------------------------------------------- Document ---


def _meta():
    return DocMeta.from_raw({"DOC_ID": "TST-0001", "EVENT_ID": "E", "TITLE": "T", "SOURCE_NAME": "S",
                             "SOURCE_TYPE": "news", "RELIABILITY": 2, "PUB_DATE": "2030-01-10"})


def test_document_good():
    d = Document(meta=_meta(), paragraphs=[Paragraph(ref="P1", ordinal=0, text="x")], file_sha256=SHA,
                 parser=ParserInfo(parser="text"), pack_id="pack",
                 injection_flags=[InjectionFlag(paragraph_ref="P1", start=0, end=1, pattern="role_label", excerpt="x")])
    assert d.paragraph("P1").text == "x" and not d.is_damaged


@pytest.mark.parametrize("kw", [
    {"file_sha256": "nothex"},
    {"paragraphs": [Paragraph(ref="P1", ordinal=0, text="a"), Paragraph(ref="P1", ordinal=1, text="b")]},
])
def test_document_bad(kw):
    data = dict(meta=_meta(), file_sha256=SHA, parser=ParserInfo(parser="text"), pack_id="p")
    data.update(kw)
    with pytest.raises(ValidationError):
        Document(**data)


def test_paragraph_and_flag_bad():
    with pytest.raises(ValidationError):
        Paragraph(ref="para1", ordinal=0, text="x")
    with pytest.raises(ValidationError):
        InjectionFlag(paragraph_ref="P1", start=5, end=2, pattern="p", excerpt="x")


# --------------------------------------------------------------- TradeRow ---


def row(**kw):
    data = dict(row_id="TBL-1#R1", table_id="TBL-1", source_doc_id="TST-0002", row_number=1,
                origin="Alpha", destination="Beta", sector="Grain", period="2030-01",
                value=12.5, currency="USD", volume=1000.0, volume_unit="tonnes",
                raw_text="raw", provenance="prose-v1")
    data.update(kw)
    return TradeRow(**data)


def test_traderow_good_and_missing_stays_none():
    assert row().sector == "grain"
    r = row(value=None, status=RowStatus.MISSING_VALUE, damage_reason="value cell empty")
    assert r.value is None


@pytest.mark.parametrize("kw", [
    {"value": None},  # valid row without value
    {"period": "2030-1"},
    {"row_id": "TBL-1#R2"},
    {"value": -1.0},
    {"currency": None},
    {"status": RowStatus.BAD_NUMBER},  # no damage reason
    {"status": RowStatus.MISSING_VALUE, "damage_reason": "x", "value": 0.0},  # missing became zero
])
def test_traderow_bad(kw):
    with pytest.raises(ValidationError):
        row(**kw)


def test_tradetable_rows_must_belong():
    TradeTable(table_id="TBL-1", source_doc_id="D", origin="A", destination="B", sector="g", layout="prose", rows=[row()])
    with pytest.raises(ValidationError):
        TradeTable(table_id="TBL-9", source_doc_id="D", origin="A", destination="B", sector="g", layout="prose", rows=[row()])


# ------------------------------------------------------ Citation / calc ---


def test_citation_rules():
    assert cite(ref=None, row="TBL-1#R1").row_id
    with pytest.raises(ValidationError):
        Citation(doc_id="D", pub_date=AS_OF, quote="q")  # no locator
    with pytest.raises(ValidationError):
        Citation(doc_id="D", paragraph_ref="P1", pub_date=AS_OF, quote="")


def test_calculation_missing_input_has_no_result():
    ok = CalculationRecord(calc_id="C1", operation="sum", inputs=[CalcInput(row_id="T#R1", label="a", value=1.0)],
                           result=1.0, unit="USD M", formula="a")
    assert ok.result == 1.0
    with pytest.raises(ValidationError):
        CalculationRecord(calc_id="C2", operation="sum", inputs=[CalcInput(row_id="T#R1", label="a", value=None)],
                          result=0.0, unit="USD M", formula="a")
    with pytest.raises(ValidationError):
        CalculationRecord(calc_id="C3", operation="sum", inputs=[], result=None, unit="x", formula="")


# ---------------------------------------------------------------- Exposure ---


def test_exposure_good_and_insufficient():
    assert estimate().high == 20.0
    e = estimate(low=None, high=None, insufficient_evidence=True, missing_data=["no rows for sector"])
    assert e.insufficient_evidence


@pytest.mark.parametrize("kw", [
    {"low": 30.0},
    {"low": None},
    {"unit": "percent"},  # no denominator
    {"evidence": [], "trade_row_refs": []},
    {"insufficient_evidence": True, "low": None, "high": None},  # missing_data not stated
    {"metric_definition": "short"},
])
def test_exposure_bad(kw):
    with pytest.raises(ValidationError):
        estimate(**kw)


# ------------------------------------------------------------- Case/claims ---


def test_casefile():
    c = CaseFile(case_id="case-1", question="How exposed is Alpha?", as_of=AS_OF, event_citations=[cite()])
    assert c.event_status == EventStatus.UNCERTAIN
    with pytest.raises(ValidationError):
        CaseFile(case_id="case-1", question="How exposed is Alpha?", as_of=AS_OF,
                 event_citations=[cite(d=date(2031, 1, 1))])
    with pytest.raises(ValidationError):
        CaseFile(case_id="bad id!", question="How exposed is Alpha?", as_of=AS_OF)


def test_claim():
    c = Claim(claim_id="T1", run_number=1, agent=AgentName.THOR, text="Imports fell sharply after the event",
              claim_type=ClaimType.FACT, citations=[cite()], exposure=estimate())
    assert c.exposure.low == 10.0
    with pytest.raises(ValidationError):
        Claim(claim_id="T2", run_number=1, agent=AgentName.THOR, text="No source for this one",
              claim_type=ClaimType.FACT, citations=[])
    with pytest.raises(ValidationError):
        Claim(claim_id="T3", run_number=1, agent=AgentName.THOR, text="Estimate belongs to Loki here",
              claim_type=ClaimType.INFERENCE, citations=[cite()], exposure=estimate(agent=AgentName.LOKI))
    with pytest.raises(ValidationError):
        Claim(claim_id="T4", run_number=1, agent=AgentName.THOR, text="Bad type value here",
              claim_type="opinion", citations=[cite()])


def _attack(**kw):
    data = dict(attack_id="A1", run_number=1, attacker=AgentName.LOKI, target_agent=AgentName.THOR,
                target_claim_id="T1", objection="The cited figure covers a different route entirely",
                counter_evidence=[cite(doc="TST-0003")], why_it_matters="It removes the basis of the estimate")
    data.update(kw)
    return Attack(**data)


def test_attack():
    assert _attack().attacker == AgentName.LOKI
    assert _attack(counter_evidence=[], evidence_gap="No trade rows exist for this sector").evidence_gap


@pytest.mark.parametrize("kw", [
    {"counter_evidence": []},  # generic disagreement
    {"attacker": AgentName.THOR},  # self attack
    {"attacker": AgentName.ODIN},
    {"objection": "I disagree"},
])
def test_attack_bad(kw):
    with pytest.raises(ValidationError):
        _attack(**kw)


def test_defense_and_concession():
    Defense(defense_id="D1", run_number=1, defender=AgentName.THOR, attack_id="A1", claim_id="T1",
            argument="A second, independent source confirms the drop", new_evidence=[cite(doc="TST-0004")])
    with pytest.raises(ValidationError):
        Defense(defense_id="D2", run_number=1, defender=AgentName.THOR, attack_id="A1", claim_id="T1",
                argument="I still think I am right about this", new_evidence=[])
    Concession(concession_id="K1", run_number=1, agent=AgentName.THOR, claim_id="T1", reason="Counter-evidence is stronger")
    with pytest.raises(ValidationError):
        Concession(concession_id="K2", run_number=1, agent=AgentName.THOR, claim_id="T1",
                   reason="Partly wrong on this", partial=True)


def _ruling(**kw):
    data = dict(ruling_id="R1", run_number=1, claim_id="T1", verdict=Verdict.ESTABLISHED,
                claim_type=ClaimType.FACT, rationale="Directly stated by a tier-1 notice", citations_valid=True)
    data.update(kw)
    return Ruling(**data)


def test_ruling():
    assert _ruling().verdict == "established"
    assert _ruling(verdict=Verdict.CONCEDED, concession_id="K1").concession_id == "K1"
    for kw in ({"verdict": Verdict.CONCEDED}, {"citations_valid": False}, {"verdict": "Approved"}, {"verdict": "Established"}):
        with pytest.raises(ValidationError):
            _ruling(**kw)


def test_sendback():
    SendBack(sendback_id="S1", run_number=1, reason="Key sector has no trade data",
             missing=[MissingEvidence(description="Monthly import rows for sector X",
                                      why_needed="Needed to bound the exposure range")])
    with pytest.raises(ValidationError):
        SendBack(sendback_id="S2", run_number=1, reason="Something is missing", missing=[])


# ---------------------------------------------------------------- Briefing ---


def _finding(verdict=Verdict.ESTABLISHED, d=date(2030, 1, 10)):
    return BriefingFinding(claim_id="T1", ruling_id="R1", verdict=verdict, claim_type=ClaimType.FACT,
                           text="Imports fell", citations=[cite(d=d)])


def _briefing(**kw):
    data = dict(case_id="case-1", as_of=AS_OF, status="partial", runs_completed=2,
                executive_summary="Exposure is moderate with wide uncertainty.", event_status=EventStatus.ESTABLISHED,
                established=[_finding()], exposure_table=[ExposureRow(country="Alpha", sector="grain", thor=estimate())],
                outlook=Outlook(text="Flows likely stay below last year", assumptions=["no new agreement"]))
    data.update(kw)
    return Briefing(**data)


def test_briefing():
    assert _briefing().status == "partial"
    for kw in (
        {"established": [_finding(Verdict.CONTESTED)]},
        {"established": [_finding(d=date(2031, 1, 1))]},  # clock violation
        {"outlook": Outlook(text="Flows likely stay low", assumptions=["x"]), "status": "done"},
        {"status": "complete", "event_status": EventStatus.UNCERTAIN, "missing_data_notes": ["no rows"]},
    ):
        with pytest.raises(ValidationError):
            _briefing(**kw)
    with pytest.raises(ValidationError):
        Outlook(text="Flows likely stay low", assumptions=[])


# ----------------------------------------------------------- Memory / log ---


def test_memory_and_log():
    MemoryEntry(memory_id="M1", agent=AgentName.LOKI, lesson="Tier-4 posts need tier-1/2 corroboration")
    with pytest.raises(ValidationError):
        MemoryEntry(memory_id="M2", agent=AgentName.SYSTEM, lesson="System cannot own memories")
    with pytest.raises(ValidationError):
        MemoryEntry(memory_id="M3", agent=AgentName.LOKI, lesson="Too confident", confidence=1.5)
    e = LogEvent(case_id="case-1", agent=AgentName.HEIMDALL, type=LogEventType.CLOCK_VIOLATION_BLOCKED,
                 summary="blocked doc after as_of", refs=["TST-0009"])
    assert e.type == "CLOCK_VIOLATION_BLOCKED"
    with pytest.raises(ValidationError):
        LogEvent(case_id="case-1", agent=AgentName.HEIMDALL, type="HACKED", summary="x")
    with pytest.raises(ValidationError):
        LogEvent(case_id="case-1", agent=AgentName.HEIMDALL, type=LogEventType.QUERY, summary="x", extra_field=1)
