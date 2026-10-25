"""Citation and calculation-link validation.

Checks (existence is not support; Odin judges support separately):
- the document exists; the paragraph or trade row exists and belongs to it;
- the citation's pub_date equals the document's publication date;
- the document is published on or before as_of;
- the quote matches the stored paragraph text, its evidence text, or the row's
  raw text after the documented normalisation only (NFKC, quote characters
  unified, case-folded, whitespace collapsed; see retrieval.text.normalise_quote);
- the quote does not come from a span flagged as an embedded instruction;
- quantitative claims: every referenced calculation exists, reproduces from its
  source rows, and was computed under an as_of no later than the case's.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from ragnarok.calc.trade_calc import TradeCalculator
from ragnarok.models import CalculationRecord, Citation, Claim
from ragnarok.retrieval.text import normalise_quote
from ragnarok.store.db import Store


class CitationCheck(BaseModel):
    ok: bool
    issues: list[str] = Field(default_factory=list)


class ClaimCheck(BaseModel):
    claim_id: str
    ok: bool
    citations: list[CitationCheck]
    calc_issues: list[str] = Field(default_factory=list)


def _quote_hits_flagged(text: str, quote: str, spans: list[tuple[int, int]]) -> bool:
    """True if a (normalised) quote overlaps any flagged span of the paragraph text."""
    norm = normalise_quote(text)
    if len(norm) == len(text):  # paragraph text is whitespace-collapsed at ingest, so offsets line up
        start = 0
        while (i := norm.find(quote, start)) >= 0:
            if any(s < i + len(quote) and i < e for s, e in spans):
                return True
            start = i + 1
        return False
    return any(quote in normalise_quote(text[s:e]) or normalise_quote(text[s:e]) in quote for s, e in spans)


def validate_citation(store: Store, c: Citation, as_of: date) -> CitationCheck:
    issues: list[str] = []
    doc = store.get_document(c.doc_id)
    if doc is None:
        return CitationCheck(ok=False, issues=[f"document {c.doc_id} does not exist"])
    m = doc.meta
    if m.pub_date is None:
        issues.append(f"{c.doc_id} has no readable publication date")
    elif m.pub_date > as_of:
        issues.append(f"{c.doc_id} was published {m.pub_date}, after as_of {as_of} (clock violation)")
    if m.pub_date is not None and c.pub_date != m.pub_date:
        issues.append(f"citation date {c.pub_date} does not match {c.doc_id} publication date {m.pub_date}")
    quote = normalise_quote(c.quote)
    if not quote:
        issues.append("empty quote")
    if c.paragraph_ref:
        p = doc.paragraph(c.paragraph_ref)
        if p is None:
            issues.append(f"{c.doc_id} has no paragraph {c.paragraph_ref}")
        elif quote:
            texts = [p.text] + ([p.evidence_text] if p.evidence_text else [])
            if not any(quote in normalise_quote(t) for t in texts):
                issues.append(f"quote not found in {c.doc_id}#{c.paragraph_ref}")
            else:
                bad = [(f.start, f.end) for f in doc.injection_flags if f.paragraph_ref == p.ref and f.severity == "high"]
                if bad and _quote_hits_flagged(p.text, quote, bad):
                    issues.append(f"quote comes from text flagged as an embedded instruction in {c.doc_id}#{p.ref}")
    if c.row_id:
        r = store.get_trade_row(c.row_id)
        if r is None:
            issues.append(f"trade row {c.row_id} does not exist")
        else:
            if r.source_doc_id != c.doc_id:
                issues.append(f"trade row {c.row_id} belongs to {r.source_doc_id}, not {c.doc_id}")
            if quote and quote not in normalise_quote(r.raw_text):
                issues.append(f"quote not found in trade row {c.row_id}")
            if r.status.value != "valid":
                issues.append(f"trade row {c.row_id} is invalid ({r.status.value}: {r.damage_reason})")
    return CitationCheck(ok=not issues, issues=issues)


def validate_calculations(store: Store, calc: TradeCalculator, calc_ids: list[str], as_of: date) -> list[str]:
    issues: list[str] = []
    for cid in calc_ids:
        raw = store.get_calculation_json(cid)
        if raw is None:
            issues.append(f"calculation {cid} does not exist")
            continue
        rec = CalculationRecord.model_validate_json(raw)
        if rec.as_of is None or rec.as_of > as_of:
            issues.append(f"calculation {cid} was computed under as_of {rec.as_of}, later than {as_of}")
            continue
        ok, why = calc.verify(rec)
        if not ok:
            issues.append(f"calculation {cid} does not reproduce: {why}")
        if rec.result is None:
            issues.append(f"calculation {cid} has no result ({rec.notes})")
        elif not rec.complete:
            issues.append(f"calculation {cid} is partial: {len(rec.excluded_rows)} row(s) excluded")
    return issues


def validate_claim(store: Store, calc: TradeCalculator, claim: Claim, as_of: date) -> ClaimCheck:
    checks = [validate_citation(store, c, as_of) for c in claim.citations]
    calc_issues: list[str] = []
    calc_ids = list(dict.fromkeys(claim.calculation_ids + (claim.exposure.calculation_ids if claim.exposure else [])))
    if claim.exposure is not None and not claim.exposure.insufficient_evidence and not claim.exposure.calculation_ids:
        calc_issues.append("quantitative estimate has no calculation record")
    calc_issues += validate_calculations(store, calc, calc_ids, as_of)
    if claim.exposure is not None:
        for c in claim.exposure.evidence:
            checks.append(validate_citation(store, c, as_of))
        for rid in claim.exposure.trade_row_refs:
            if store.get_trade_row(rid) is None:
                calc_issues.append(f"exposure cites trade row {rid}, which does not exist")
    ok = all(c.ok for c in checks) and not calc_issues
    return ClaimCheck(claim_id=claim.claim_id, ok=ok, citations=checks, calc_issues=calc_issues)
