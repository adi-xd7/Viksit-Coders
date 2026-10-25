"""Lessons derived by code from what actually happened in a run.

Lessons are general: they describe kinds of evidence, source types, tiers,
tool usage and outcomes. Case specifics (place and entity names, document /
row / calc / claim IDs, dates and numbers) are masked, so a lesson can never
carry an event answer into another case. The unmasked specifics go into the
`context` field, which is stored for audit but never shown to an agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ragnarok.models import AgentName, CaseFile, Claim, Ruling, Verdict
from ragnarok.store.db import Store

_ID_PATTERNS = [
    (re.compile(r"\bCALC-[0-9a-fA-F]+\b"), "<calc>"),
    (re.compile(r"\b[A-Z]{2,6}-\d{2,6}(?:#R\d+)?(?:[/#]P\d+)?\b"), "<doc>"),
    (re.compile(r"\b[TL]\d+-\d+\b"), "<claim>"),
    (re.compile(r"\bA\d+-[TL]\d+\b"), "<attack>"),
    (re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b"), "<date>"),
    (re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                r"(?:\s+\d{4})?\b"), "<month>"),
    (re.compile(r"\d[\d,]*(?:\.\d+)?%?"), "<n>"),
]
_CAP = re.compile(r"\b[A-Z][a-zA-Z'’-]+\b")
_REPEAT = re.compile(r"(<(?:name|place)>)(?:\s+<(?:name|place)>)+")


class Masker:
    """Masks case-specific names and identifiers in free text taken from model output."""

    def __init__(self, names: set[str]) -> None:
        self.names = sorted({n.strip() for n in names if n and len(n.strip()) >= 3}, key=len, reverse=True)

    @classmethod
    def for_case(cls, store: Store, cf: CaseFile) -> "Masker":
        names = set(cf.countries) | set(cf.related_countries)
        for r in store.conn.execute("SELECT DISTINCT country FROM documents WHERE country IS NOT NULL"):
            names.add(r["country"])
        for r in store.conn.execute("SELECT DISTINCT origin, destination FROM trade_tables"):
            names.update(x for x in (r["origin"], r["destination"]) if x)
        return cls(names)

    def __call__(self, text: str, limit: int = 160) -> str:
        t = " ".join(str(text).split())
        for n in self.names:
            t = re.sub(rf"\b{re.escape(n)}\b", "<place>", t, flags=re.IGNORECASE)
        for rx, rep in _ID_PATTERNS:
            t = rx.sub(rep, t)

        def cap(m: re.Match) -> str:
            start = m.start()
            before = t[:start].rstrip()
            sentence_start = not before or before[-1] in ".!?:;("
            nxt = t[m.end():].lstrip()
            if sentence_start and not (nxt[:1].isupper()):
                return m.group(0)  # an ordinary capitalised first word
            return "<name>"

        t = _CAP.sub(cap, t)
        t = _REPEAT.sub(r"\1", t)
        return t[:limit].rstrip() + ("..." if len(t) > limit else "")


@dataclass
class LessonDraft:
    agent: AgentName
    kind: str
    lesson: str
    stages: list[str]
    context: str = ""
    confidence: float = 0.5
    refs: list[str] = field(default_factory=list)


def _source_types(store: Store, doc_ids) -> tuple[list[str], list[int]]:
    types, tiers = set(), set()
    for d in doc_ids:
        doc = store.get_document(d)
        if doc:
            types.add(doc.meta.source_type or "unknown")
            if doc.meta.reliability_tier:
                tiers.add(doc.meta.reliability_tier)
    return sorted(types), sorted(tiers)


def _fmt(xs) -> str:
    return ", ".join(str(x) for x in xs) or "unknown"


def _filters_text(filters: dict, mask: Masker) -> str:
    keep = {k: v for k, v in (filters or {}).items() if v not in (None, False, [], "") and k != "include_duplicates"}
    parts = []
    for k, v in sorted(keep.items()):
        if k in ("country", "doc_ids"):
            v = "<given>"
        elif isinstance(v, list):
            v = ",".join(mask(str(x), 40) for x in v)
        parts.append(f"{k}={v}")
    return "; ".join(parts) or "none"


# --------------------------------------------------------------------------- #
# Advocates
# --------------------------------------------------------------------------- #

_HARD_FAIL_LESSONS = [
    ("tier-4", "rejected_tier4", "A claim supported only by tier-4 sources ({src}) was rejected. Corroborate with a tier 1-2 "
     "source before making such a claim; search with max_reliability 2 first.", ["research", "brief"]),
    ("corrected", "rejected_corrected", "A claim that cited only reports later corrected or retracted was rejected. When a hit "
     "is marked corrected-by, read the correction and argue from it.", ["research", "brief"]),
    ("do not reproduce", "rejected_calc", "An estimate whose calculations did not reproduce was rejected. Compute every bound "
     "with trade_calc on valid rows and cite exactly those calc IDs.", ["brief"]),
    ("after as_of", "rejected_late", "A claim citing evidence published after the as-of date was rejected. Cite only "
     "evidence shown in the case.", ["brief"]),
    ("no valid citation", "rejected_citation", "A claim without a valid citation was rejected. Copy quotes exactly from the "
     "paragraph or from a trade row's source text.", ["brief"]),
]


def useful_queries(store: Store, case_id: str, agent: AgentName, refs: set[str]) -> list[dict]:
    """The agent's own searches in this case whose hits include any of `refs`."""
    evs = store.events(case_id)
    queries = {e.seq: e for e in evs if e.type.value == "QUERY" and e.agent == agent and "query" in e.payload}
    out, seen = [], set()
    for e in evs:
        if e.type.value != "RETRIEVED" or e.agent != agent:
            continue
        qseq = e.payload.get("query_seq")
        if qseq in queries and refs & set(e.refs):
            q = queries[qseq]
            key = q.payload.get("query_norm")
            if key not in seen:
                seen.add(key)
                out.append({"query": q.payload["query"], "filters": q.payload.get("filters", {}), "seq": qseq})
    return out


def advocate_lessons(store: Store, mask: Masker, agent: AgentName, case_id: str, run: int, claims: list[Claim],
                     rulings: list[Ruling], prechecks: dict, cx) -> list[LessonDraft]:
    mine = {c.claim_id: c for c in claims if c.agent == agent}
    out: list[LessonDraft] = []
    attacks = {a.attack_id: a for a in cx.attacks}
    concessions = {k.claim_id: k for k in cx.concessions if k.agent == agent}
    established_refs: set[str] = set()
    for r in rulings:
        c = mine.get(r.claim_id)
        if c is None:
            continue
        src, tiers = _source_types(store, {x.doc_id for x in c.citations})
        ctx = f"case {case_id} run {run}: {c.claim_id} {r.verdict.value} - {r.rationale[:300]}"
        if r.verdict == Verdict.REJECTED:
            hard = getattr(prechecks.get(c.claim_id), "hard_fail", []) or []
            matched = False
            for needle, kind, text, stages in _HARD_FAIL_LESSONS:
                if any(needle in h for h in hard):
                    out.append(LessonDraft(agent, kind, text.format(src=_fmt(src)), stages, ctx, 0.7))
                    matched = True
            if not matched:
                out.append(LessonDraft(agent, "rejected_support", (
                    f"Odin rejected a {c.claim_type.value} claim citing {_fmt(src)} (tier {_fmt(tiers)}) because the passages "
                    f"did not support it as stated (\"{mask(r.rationale, 140)}\"). Keep claims no broader than the quoted "
                    "passage."), ["brief"], ctx, 0.6))
        elif r.verdict == Verdict.CONCEDED and c.claim_id in concessions:
            k = concessions[c.claim_id]
            a = attacks.get(k.attack_id) if k.attack_id else None
            if a is not None:
                ctypes, _ = _source_types(store, {x.doc_id for x in a.counter_evidence})
                shown = f"counter-evidence from {_fmt(ctypes)}" if ctypes else "an evidence gap"
                gap = mask(a.evidence_gap or a.objection, 140)
                out.append(LessonDraft(agent, "conceded_after_attack", (
                    f"I conceded a claim (citing {_fmt(src)}) after the opponent showed {shown}: \"{gap}\". Before making "
                    "this kind of claim, look for that evidence myself and state the limitation."),
                    ["research", "brief", "cross_exam"], ctx, 0.6))
            else:
                out.append(LessonDraft(agent, "withdrawn_after_new_evidence", (
                    f"I withdrew a claim (citing {_fmt(src)}) after a later run brought new evidence: \"{mask(k.reason, 140)}\". "
                    "Check whether newer evidence covers the same gap before claiming."), ["brief"], ctx, 0.55))
        elif r.verdict == Verdict.ESTABLISHED:
            established_refs |= {x.row_id or f"{x.doc_id}#{x.paragraph_ref}" for x in c.citations}
            if c.exposure is not None:
                e = c.exposure
                out.append(LessonDraft(agent, "established_estimate", (
                    f"An estimate of the metric \"{mask(e.metric, 60)}\" ({e.unit}) computed with trade_calc from "
                    f"{_fmt(src)} evidence (tier {_fmt(tiers)}) was established; this metric definition held up."),
                    ["brief"], ctx, 0.55))
    for d in cx.invalid_defenses:
        if d.agent == agent:
            out.append(LessonDraft(agent, "invalid_defense", (
                "A defense that re-cited the attacked claim's own sources was rejected as bringing no new evidence. "
                "Find a new paragraph or trade row before defending, or concede."), ["cross_exam"],
                f"case {case_id} run {run}: {d.claim_id} vs {d.attack_id}", 0.7))
    for q in useful_queries(store, case_id, agent, established_refs)[:3]:
        out.append(LessonDraft(agent, "useful_query", (
            f"A search like \"{mask(q['query'], 80)}\" (filters: {_filters_text(q['filters'], mask)}) found evidence for a "
            "claim Odin established."), ["research"], f"case {case_id} run {run}: query #{q['seq']} {q['query']}", 0.5))
    return out


# --------------------------------------------------------------------------- #
# Heimdall
# --------------------------------------------------------------------------- #


def heimdall_sendback_lessons(mask: Masker, case_id: str, run: int, missing) -> list[LessonDraft]:
    return [LessonDraft(AgentName.HEIMDALL, "sendback_gap", (
        f"Odin sent a case back because this was missing after the first investigation: \"{mask(m.description, 140)}\" "
        f"(source types: {_fmt([mask(s, 40) for s in m.source_types])}). Search for this kind of evidence in the first "
        "investigation and list it in the Case File."), ["research"],
        f"case {case_id} run {run}: {m.description} | why: {m.why_needed}", 0.6) for m in missing]


def heimdall_research_lessons(mask: Masker, store: Store, case_id: str, run: int, items: list[dict]) -> list[LessonDraft]:
    """items: [{description, queries: [{query, filters}], new_refs: [...], new_doc_ids: [...]}]"""
    out = []
    for it in items:
        desc = mask(it["description"], 120)
        if it["new_refs"]:
            types, _ = _source_types(store, it["new_doc_ids"])
            for q in it["queries"][:1]:
                out.append(LessonDraft(AgentName.HEIMDALL, "useful_query", (
                    f"For a gap like \"{desc}\", the targeted search \"{mask(q['query'], 80)}\" (filters: "
                    f"{_filters_text(q['filters'], mask)}) found new evidence in {_fmt(types)}."),
                    ["research", "sendback"], f"case {case_id} run {run}: {it['description']} -> {it['new_refs'][:6]}", 0.6))
        else:
            out.append(LessonDraft(AgentName.HEIMDALL, "dead_end", (
                f"Targeted searches for a gap like \"{desc}\" found nothing new before the as-of date. Report such a gap "
                "plainly instead of repeating similar searches."), ["sendback"],
                f"case {case_id} run {run}: {it['description']} queries {[q['query'] for q in it['queries']]}", 0.5))
    return out


def heimdall_case_lessons(case_id: str, cf: CaseFile) -> list[LessonDraft]:
    out = []
    if cf.corrections:
        out.append(LessonDraft(AgentName.HEIMDALL, "corrections_matter", (
            "Corrections, retractions or contradicting reports changed the record of the event. Search for correction "
            "and retraction notices and official notices before setting the event status."), ["research"],
            f"case {case_id}: {len(cf.corrections)} correction note(s)", 0.55))
    return out


# --------------------------------------------------------------------------- #
# Odin
# --------------------------------------------------------------------------- #

_GUARD_LESSONS = [
    ("'established' blocked", "guard_established", "Code blocked my 'established' verdict on a claim with hard pre-check "
     "failures. Read each claim's PRE-CHECK line before ruling."),
    ("without a concession", "guard_conceded", "Code changed my 'conceded' verdict because the proponent had not conceded. "
     "Use 'conceded' only where a concession is recorded; otherwise 'contested' or 'rejected'."),
    ("fully conceded", "guard_full_concession", "Code changed my verdict on a fully conceded claim to 'conceded'. A full "
     "concession by the proponent always means 'conceded'."),
    ("marked insufficient", "guard_range", "A range I gave was not reproducible from calc records and was marked insufficient. "
     "Request trade_calc for each bound before giving a range."),
]


def odin_lessons(case_id: str, run: int, guards: list[str], sendback_effect: dict | None) -> list[LessonDraft]:
    out, seen = [], set()
    for g in guards:
        for needle, kind, text in _GUARD_LESSONS:
            if needle in g and kind not in seen:
                seen.add(kind)
                out.append(LessonDraft(AgentName.ODIN, kind, text, ["ruling"], f"case {case_id} run {run}: {g[:300]}", 0.7))
    if sendback_effect is not None:
        if not sendback_effect.get("new_evidence"):
            out.append(LessonDraft(AgentName.ODIN, "sendback_no_new_evidence", (
                "A send-back found no new evidence before the as-of date. When the missing data probably does not exist "
                "in the evidence, report it as a gap in the briefing instead of relying on another run."), ["ruling"],
                f"case {case_id} run {run}: {sendback_effect}", 0.55))
        else:
            changed = sendback_effect.get("changed", 0)
            out.append(LessonDraft(AgentName.ODIN, "sendback_useful" if changed else "sendback_no_change", (
                "Naming missing evidence by kind and source type in a send-back led to new evidence that "
                + ("changed rulings or ranges in the next run." if changed else "did not change any ruling or range.")),
                ["ruling"], f"case {case_id} run {run}: {sendback_effect}", 0.5))
    return out
