"""Relations between documents: exact duplicates, near-duplicates and corrections.

- Exact duplicate: same normalised body hash (content_sha256). The earliest
  published copy (then lowest doc ID) is canonical; the others get
  duplicate_of -> canonical and a DUPLICATE flag. Nothing is deleted.
- Near-duplicate: same normalised title, a body that is a prefix of another
  (a cut-off copy), or high word-shingle overlap. Flagged possible_duplicate with
  near_duplicate_of; never merged.
- Corrections/retractions: a document whose source type or title marks it as a
  correction is linked to the earlier document(s) it most plausibly corrects
  (same outlet, date mentioned in its text, title overlap). Both stay as records.

Relations are recomputed over the whole store after every ingest so the result
does not depend on ingestion order.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date

from ragnarok.ingest.metadata import MONTHS
from ragnarok.models import DamageFlag, DamageKind, DocRelation, Document, RelationType

AUTO_RELATIONS = {RelationType.DUPLICATE_OF, RelationType.NEAR_DUPLICATE_OF, RelationType.CORRECTS, RelationType.RETRACTS}
AUTO_FLAGS = {DamageKind.DUPLICATE, DamageKind.POSSIBLE_DUPLICATE}

_CORRECTION_TYPES = {"correction", "retraction", "erratum", "clarification", "corrigendum"}
_CORRECTION_TITLE = re.compile(r"^\s*(correction|retraction|clarification|erratum|corrigendum|editor'?s note)\b", re.I)
_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "as", "at", "by", "is", "was", "be", "not",
    "with", "from", "after", "its", "it", "this", "that", "correction", "retraction", "clarification",
}

SHINGLE_THRESHOLD = 0.6
PREFIX_MIN_CHARS = 80


def normalised_body(doc: Document) -> str:
    return " ".join(" ".join(p.text for p in doc.paragraphs).split()).casefold()


def body_hash(doc: Document) -> str | None:
    body = normalised_body(doc)
    return hashlib.sha256(body.encode("utf-8")).hexdigest() if body else None


def _shingles(text: str, k: int = 5) -> set[str]:
    words = re.findall(r"\w+", text)
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _order_key(doc: Document) -> tuple:
    m = doc.meta
    return (m.pub_date or date.max, m.pub_time.isoformat() if m.pub_time else "99:99", m.doc_id)


def _title_key(doc: Document) -> str:
    return " ".join(re.findall(r"\w+", doc.meta.title.casefold()))


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.casefold()) if w not in _STOP and len(w) > 2}


def is_correction(doc: Document) -> bool:
    return (doc.meta.source_type or "") in _CORRECTION_TYPES or bool(_CORRECTION_TITLE.match(doc.meta.title))


def _dates_mentioned(text: str) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    names = "|".join(sorted(MONTHS, key=len, reverse=True))
    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({names})\b", text, re.I):
        out.add((MONTHS[m.group(2).lower()], int(m.group(1))))
    for m in re.finditer(rf"\b({names})\.?\s+(\d{{1,2}})\b", text, re.I):
        out.add((MONTHS[m.group(1).lower()], int(m.group(2))))
    for m in re.finditer(r"\b\d{4}-(\d{2})-(\d{2})\b", text):
        out.add((int(m.group(1)), int(m.group(2))))
    return out


def compute_relations(docs: list[Document]) -> dict[str, tuple[list[DocRelation], list[DamageFlag]]]:
    """Return, per doc ID, the automatic relations and flags it should carry."""
    rels: dict[str, list[DocRelation]] = defaultdict(list)
    flags: dict[str, list[DamageFlag]] = defaultdict(list)
    by_id = {d.meta.doc_id: d for d in docs}

    # Exact duplicates.
    groups: dict[str, list[Document]] = defaultdict(list)
    for d in docs:
        if d.content_sha256:
            groups[d.content_sha256].append(d)
    exact_pairs: set[frozenset[str]] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=_order_key)
        canon = group[0]
        for dup in group[1:]:
            rels[dup.meta.doc_id].append(DocRelation(
                type=RelationType.DUPLICATE_OF, target_doc_id=canon.meta.doc_id,
                evidence="identical normalised body text (same content hash)",
            ))
            flags[dup.meta.doc_id].append(DamageFlag(kind=DamageKind.DUPLICATE, detail=f"exact duplicate of {canon.meta.doc_id}"))
        ids = [g.meta.doc_id for g in group]
        exact_pairs.update(frozenset((a, b)) for i, a in enumerate(ids) for b in ids[i + 1:])

    # Near-duplicates (pairwise; packs are small).
    bodies = {d.meta.doc_id: normalised_body(d) for d in docs}
    shingles = {k: _shingles(v) for k, v in bodies.items()}
    titles = {d.meta.doc_id: _title_key(d) for d in docs}
    ordered = sorted(docs, key=_order_key)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            ida, idb = a.meta.doc_id, b.meta.doc_id
            if frozenset((ida, idb)) in exact_pairs:
                continue
            ba, bb = bodies[ida], bodies[idb]
            reason = None
            target, source = ida, idb  # the later doc points to the earlier one by default
            if ba and bb and min(len(ba), len(bb)) >= PREFIX_MIN_CHARS and (ba.startswith(bb) or bb.startswith(ba)):
                shorter, longer = (idb, ida) if len(bb) < len(ba) else (ida, idb)
                source, target = shorter, longer
                pct = 100 * min(len(ba), len(bb)) / max(len(ba), len(bb))
                reason = f"body is a cut-off copy of {longer} ({pct:.0f}% of its length)"
            else:
                sim = _jaccard(shingles[ida], shingles[idb])
                if sim >= SHINGLE_THRESHOLD:
                    reason = f"word 5-shingle overlap {sim:.2f}"
                elif titles[ida] and titles[ida] == titles[idb]:
                    if not ba or not bb:
                        empty = ida if not ba else idb
                        other = idb if empty == ida else ida
                        source, target = empty, other
                        reason = f"same title; {empty} has no readable body"
                    else:
                        reason = f"same title, different content (shingle overlap {sim:.2f})"
            if reason:
                rels[source].append(DocRelation(type=RelationType.NEAR_DUPLICATE_OF, target_doc_id=target, evidence=reason))
                flags[source].append(DamageFlag(kind=DamageKind.POSSIBLE_DUPLICATE, detail=f"possible duplicate of {target}: {reason}"))

    # Corrections and retractions.
    for c in docs:
        if not is_correction(c) or c.meta.published_at is None:
            continue
        rtype = RelationType.RETRACTS if "retract" in f"{c.meta.source_type} {c.meta.title}".lower() else RelationType.CORRECTS
        c_text = " ".join(p.text for p in c.paragraphs)
        mentioned = _dates_mentioned(c_text)
        c_words = _content_words(c.meta.title + " " + c_text)
        scored: list[tuple[float, str, list[str]]] = []
        for d in docs:
            if d is c or is_correction(d) or d.meta.published_at is None or d.meta.published_at > c.meta.published_at:
                continue
            if c.meta.event_id and d.meta.event_id and c.meta.event_id != d.meta.event_id:
                continue
            reasons: list[str] = []
            score = 0.0
            if c.meta.source_name and d.meta.source_name.casefold() == c.meta.source_name.casefold():
                score += 3
                reasons.append("same outlet")
            if d.meta.pub_date and (d.meta.pub_date.month, d.meta.pub_date.day) in mentioned:
                score += 3
                reasons.append(f"correction mentions its publication date {d.meta.pub_date.isoformat()}")
            overlap = _jaccard(c_words, _content_words(d.meta.title))
            if overlap:
                score += 4 * overlap
                reasons.append(f"title word overlap {overlap:.2f}")
            if score >= 4:
                scored.append((score, d.meta.doc_id, reasons))
        if not scored:
            continue
        scored.sort(key=lambda x: (-x[0], x[1]))
        best = scored[0][0]
        for score, target, reasons in scored:
            if best - score > 0.5 or len([r for r in rels[c.meta.doc_id] if r.type == rtype]) >= 3:
                break
            if by_id.get(target) is None:
                continue
            rels[c.meta.doc_id].append(DocRelation(
                type=rtype, target_doc_id=target, evidence=f"score {score:.1f}: " + "; ".join(reasons),
            ))

    return {d.meta.doc_id: (rels.get(d.meta.doc_id, []), flags.get(d.meta.doc_id, [])) for d in docs}


def apply_relations(docs: list[Document]) -> list[Document]:
    """Replace automatic relations/flags on each doc; return the docs that changed."""
    computed = compute_relations(docs)
    changed: list[Document] = []
    for d in docs:
        new_rels, new_flags = computed[d.meta.doc_id]
        kept_rels = [r for r in d.relations if r.type not in AUTO_RELATIONS]
        kept_flags = [f for f in d.damage_flags if f.kind not in AUTO_FLAGS]
        rels = kept_rels + new_rels
        dmg = kept_flags + new_flags
        if rels != d.relations or dmg != d.damage_flags:
            d.relations = rels
            d.damage_flags = dmg
            changed.append(d)
    return changed
