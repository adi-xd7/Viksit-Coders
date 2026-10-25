"""
Event verifier — confirms whether a disruption event is real.

Checks:
  1. Multiple reliable sources confirm the event
  2. Retractions / corrections are detected and handled
  3. Contradictory documents are flagged
  4. Fake / rumoured events are caught
  5. Unreliable sources (tier 4) are not treated as evidence
  6. The as-of date is respected
"""

from __future__ import annotations

from typing import Any

import config
from heimdall.logger import HeimdallLogger
from interfaces.case_file_schema import VerificationResult, VerificationStatus


class EventVerifier:
    """
    Verify whether a disruption event actually exists in Runemark.

    Heimdall does NOT debate exposure — only confirms the event is real.
    """

    def __init__(self, manifest: dict[str, Any],
                 doc_texts: dict[str, str],
                 logger: HeimdallLogger | None = None):
        self.manifest = manifest
        self.doc_texts = doc_texts
        self.logger = logger or HeimdallLogger()

    def verify(self, event_id: str, as_of_date: str) -> VerificationResult:
        """
        Run the full verification pipeline for an event.

        Returns a VerificationResult with status, confidence, and evidence.
        """
        result = VerificationResult()

        # 1. Find all documents referencing this event
        event_docs = self._get_event_docs(event_id, as_of_date)

        if not event_docs:
            result.status = VerificationStatus.FAKE
            result.confidence = 0.0
            result.reason = (
                f"No documents found referencing event '{event_id}' "
                f"on or before {as_of_date}."
            )
            self.logger.event_verification(event_id, result.status,
                                           result.confidence, result.reason)
            return result

        # 2. Separate by reliability and type
        reliable_docs = []       # tier 1-2
        moderate_docs = []       # tier 3
        unreliable_docs = []     # tier 4
        retractions = []
        corrections = []

        for doc in event_docs:
            reliability = int(doc.get("RELIABILITY", 4))
            source_type = str(doc.get("SOURCE_TYPE", "")).lower()

            if source_type in config.RETRACTION_SOURCE_TYPES:
                corrections.append(doc)
            elif reliability <= 2:
                reliable_docs.append(doc)
            elif reliability == 3:
                moderate_docs.append(doc)
            else:
                unreliable_docs.append(doc)

        # 3. Check for retractions
        retracted_doc_ids = self._find_retracted_docs(corrections, event_docs)
        result.retracted_doc_ids = retracted_doc_ids

        # Remove retracted docs from reliable/moderate lists
        retracted_set = set(retracted_doc_ids)
        reliable_docs = [d for d in reliable_docs
                         if d["DOC_ID"] not in retracted_set]
        moderate_docs = [d for d in moderate_docs
                         if d["DOC_ID"] not in retracted_set]

        # 4. Check for contradictions
        contradictions = self._find_contradictions(event_docs, as_of_date)
        result.contradicting_doc_ids = [d["DOC_ID"] for d in contradictions]

        # 5. Build supporting evidence
        supporting = reliable_docs + moderate_docs
        result.supporting_doc_ids = [d["DOC_ID"] for d in supporting]

        # 6. Flag unreliable sources
        if unreliable_docs:
            for ud in unreliable_docs:
                result.warnings.append(
                    f"Unreliable source (tier {ud.get('RELIABILITY')}): "
                    f"{ud['DOC_ID']} — {ud.get('TITLE', 'untitled')}"
                )

        # 7. Flag fake indicators
        fake_indicators = self._detect_fake_indicators(
            event_id, event_docs, reliable_docs, unreliable_docs)
        result.fake_indicators = fake_indicators

        # 8. Determine final status
        if fake_indicators and not reliable_docs:
            result.status = VerificationStatus.FAKE
            result.confidence = 0.1
            result.reason = ("Event appears to be fake/rumoured. "
                             "Only unreliable sources mention it. "
                             + "; ".join(fake_indicators))
        elif not supporting:
            result.status = VerificationStatus.INSUFFICIENT_EVIDENCE
            result.confidence = 0.2
            result.reason = ("No reliable or moderate sources confirm "
                             "the event after removing retractions.")
        elif retracted_doc_ids and not reliable_docs:
            result.status = VerificationStatus.RETRACTED
            result.confidence = 0.3
            result.reason = ("Key documents about this event have been "
                             "retracted/corrected.")
        else:
            # Verified — compute confidence based on source quality
            tier1_count = sum(1 for d in supporting
                              if int(d.get("RELIABILITY", 4)) == 1)
            tier2_count = sum(1 for d in supporting
                              if int(d.get("RELIABILITY", 4)) == 2)
            tier3_count = sum(1 for d in supporting
                              if int(d.get("RELIABILITY", 4)) == 3)

            confidence = min(1.0, (
                tier1_count * 0.25 +
                tier2_count * 0.15 +
                tier3_count * 0.08
            ))
            # Reduce confidence if there are contradictions
            if contradictions:
                confidence *= 0.85

            result.status = VerificationStatus.VERIFIED
            result.confidence = round(confidence, 2)
            result.reason = (
                f"Event confirmed by {len(supporting)} sources "
                f"(tier-1: {tier1_count}, tier-2: {tier2_count}, "
                f"tier-3: {tier3_count}). "
                + (f"{len(contradictions)} contradictions noted. "
                   if contradictions else "")
                + (f"{len(retracted_doc_ids)} documents retracted/corrected."
                   if retracted_doc_ids else "")
            )

            if contradictions:
                result.warnings.append(
                    "Some documents contradict each other — "
                    "review contradicting_doc_ids."
                )

        self.logger.event_verification(
            event_id, result.status, result.confidence, result.reason)

        return result

    # ── Internal helpers ─────────────────────────────────────────────────

    def _get_event_docs(self, event_id: str,
                        as_of_date: str) -> list[dict]:
        """Get all manifest docs for this event, respecting as-of date."""
        docs = []
        for doc in self.manifest["documents"]:
            doc_event = str(doc.get("EVENT_ID", "")).upper()
            pub_date = doc.get("PUB_DATE", "9999-99-99")
            if doc_event == event_id.upper() and pub_date <= as_of_date:
                docs.append(doc)
        return docs

    def _find_retracted_docs(self, corrections: list[dict],
                             all_event_docs: list[dict]) -> list[str]:
        """
        Identify which documents have been retracted or corrected.

        Corrections reference earlier documents — we check the correction
        text for mentions of other doc IDs or titles.
        """
        retracted_ids: list[str] = []

        for corr in corrections:
            corr_id = corr["DOC_ID"]
            corr_text = self.doc_texts.get(corr_id, "").lower()
            corr_title = str(corr.get("TITLE", "")).lower()

            # The correction itself supersedes what it corrects
            # Look for docs that the correction contradicts
            for doc in all_event_docs:
                if doc["DOC_ID"] == corr_id:
                    continue
                doc_title = str(doc.get("TITLE", "")).lower()

                # Check if the correction text mentions the corrected claim
                # e.g., ORV-0013 "Correction: Orvan corridor agreement was not renewed"
                # contradicts ORV-0043 "Orvan grain corridor renewed for a second year"
                if ("not renewed" in corr_title and
                        "renewed" in doc_title and
                        "not" not in doc_title and
                        "correction" not in doc_title.lower()):
                    retracted_ids.append(doc["DOC_ID"])
                elif ("correction" in corr_title.lower() or
                      "retract" in corr_title.lower()):
                    # Check if correction text references the doc
                    if doc["DOC_ID"].lower() in corr_text:
                        retracted_ids.append(doc["DOC_ID"])

        return list(set(retracted_ids))

    def _find_contradictions(self, event_docs: list[dict],
                             as_of_date: str) -> list[dict]:
        """
        Find documents that contradict each other.

        For example: one says "renewed" while another says "not renewed".
        """
        contradictions = []
        titles = [(d["DOC_ID"], str(d.get("TITLE", "")).lower())
                  for d in event_docs]

        # Look for renewal vs non-renewal contradictions
        renewal_positive = [d for did, t in titles
                            for d in event_docs
                            if d["DOC_ID"] == did and
                            "renewed" in t and "not" not in t and
                            "correction" not in t]
        renewal_negative = [d for did, t in titles
                            for d in event_docs
                            if d["DOC_ID"] == did and
                            ("not renewed" in t or "expires" in t or
                             "no renewal" in t)]

        if renewal_positive and renewal_negative:
            # The later-dated documents are more authoritative
            for doc in renewal_positive:
                for neg in renewal_negative:
                    if doc.get("PUB_DATE", "") < neg.get("PUB_DATE", ""):
                        # Earlier positive contradicted by later negative
                        contradictions.append(doc)
                    elif doc.get("PUB_DATE", "") > neg.get("PUB_DATE", ""):
                        # Check reliability — lower tier doc might be wrong
                        doc_rel = int(doc.get("RELIABILITY", 4))
                        neg_rel = int(neg.get("RELIABILITY", 4))
                        if doc_rel > neg_rel:
                            contradictions.append(doc)

        return contradictions

    def _detect_fake_indicators(
        self, event_id: str,
        all_docs: list[dict],
        reliable_docs: list[dict],
        unreliable_docs: list[dict],
    ) -> list[str]:
        """Detect indicators that the event might be fake/rumoured."""
        indicators = []

        if not reliable_docs and unreliable_docs:
            indicators.append(
                "Only unreliable (tier 4) sources mention this event.")

        if len(all_docs) == 1:
            doc = all_docs[0]
            source_type = str(doc.get("SOURCE_TYPE", "")).lower()
            if source_type in ("blog", "social_post", "tabloid"):
                indicators.append(
                    f"Single source of type '{source_type}' — "
                    f"likely rumour.")

        # Check for exaggerated claims in unreliable sources
        for doc in unreliable_docs:
            title = str(doc.get("TITLE", "")).upper()
            text = self.doc_texts.get(doc["DOC_ID"], "").upper()
            if any(word in title for word in ["FAMINE", "SUNK", "SHUT FOR GOOD",
                                               "VANISHES", "CATASTROPHE"]):
                indicators.append(
                    f"Exaggerated claim in {doc['DOC_ID']}: {doc.get('TITLE', '')}")

        return indicators
