"""Citation, evidence-reference, clock-cutoff, and trap validation service."""

import re
from typing import Any, Optional, Tuple
from backend.app.schemas.evidence import EvidenceReference


# Outlet reliability mapping defined in Runemark Atlas ATL-0012
OUTLET_TIERS: dict[str, int] = {
    # Tier 1: Official notices (canal and government)
    "Ymir Canal Authority": 1,
    "Realm Trade Ministry": 1,
    # Tier 2: Wire service, business daily, trade press
    "Raven Wire": 2,
    "Midgard Times": 2,
    "Harbour Review": 2,
    "Cargo Weekly": 2,
    "Vantro Trading": 2,  # Company statement with trade desk backing
    "Anchor Marine": 2,   # Tolan port operator
    "Corvan Grain": 2,    # Port operator company statement
    # Tier 3: Regional paper and analyst firms
    "Asgard Herald": 3,
    "Tide Research": 3,
    "Ledger Analytics": 3,
    # Tier 4: Social posts, blog, tabloid
    "Saga Chat": 4,
    "Trade Whisper": 4,
    "Daily Roar": 4,
}

# Known retractions and corrections in Runemark corpus
# format: retracted_doc_id -> (correction_doc_id, explanation)
RETRACTIONS_AND_CORRECTIONS: dict[str, Tuple[str, str]] = {
    "ORV-0043": (
        "ORV-0013",
        "ORV-0043 falsely claimed corridor renewal. Retracted by ORV-0013 correction and ORV-0016 gov notice."
    ),
    "ORV-0026": (
        "ORV-0016",
        "ORV-0026 is an unverified Tier 4 blog rumor claiming every grain ship sunk. Contradicted by official port bulletins."
    ),
    "ORV-0028": (
        "ORV-0006",
        "ORV-0028 is a Tier 4 tabloid headline ('FAMINE FEAR') unsupported by trade flows."
    ),
}

# Patterns indicating prompt injections embedded in raw documents (e.g. ORV-0020 [P7])
INJECTION_PATTERNS = [
    re.compile(r"ASSISTANT\s*:\s*.*", re.IGNORECASE),
    re.compile(r"SYSTEM\s*:\s*.*", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?(previous\s+)?rules", re.IGNORECASE),
    re.compile(r"skip\s+cross[- ]examination", re.IGNORECASE),
    re.compile(r"approve\s+all\s+claims", re.IGNORECASE),
    re.compile(r"do\s+not\s+challenge", re.IGNORECASE),
]


class CitationValidator:
    """Validates citations against Runemark manifest metadata, simulated clock, and traps."""

    @staticmethod
    def validate_doc_id_format(doc_id: str) -> bool:
        """Verify doc ID follows Runemark nomenclature (e.g. ATL-0001, ORV-0027, WLD-0025)."""
        if not doc_id or not isinstance(doc_id, str):
            return False
        pattern = r"^(ATL|ORV|WLD)-\d{4}$"
        return bool(re.match(pattern, doc_id.strip()))

    @staticmethod
    def is_clock_violation(pub_date: str, as_of_date: str) -> bool:
        """
        Check if document was published strictly AFTER the as-of cutoff date.
        Simulated clock rule: Any document dated > as_of_date is a clock violation.
        Handles date-only (YYYY-MM-DD) and ISO/space timestamps safely.
        """
        if not pub_date or not as_of_date:
            return False
        p_date = pub_date.strip().split("T")[0].split(" ")[0]
        a_date = as_of_date.strip().split("T")[0].split(" ")[0]
        return p_date > a_date

    @staticmethod
    def check_retraction(doc_id: str) -> Optional[Tuple[str, str]]:
        """Return (correction_doc_id, reason) if the document was retracted or contradicted."""
        return RETRACTIONS_AND_CORRECTIONS.get(doc_id.strip())

    @staticmethod
    def get_outlet_tier(source_name: str) -> int:
        """Resolve outlet to reliability tier 1-4 per ATL-0012, default to 3 if unknown."""
        return OUTLET_TIERS.get(source_name.strip(), 3)

    @classmethod
    def sanitize_content(cls, text: str) -> Tuple[str, bool]:
        """
        Scrub prompt injection directives from retrieved document text.
        Returns: (sanitized_text, injection_detected_flag)
        """
        if not text:
            return "", False

        injection_detected = False
        sanitized_lines = []
        for line in text.splitlines():
            is_injected = any(pattern.search(line) for pattern in INJECTION_PATTERNS)
            if is_injected:
                injection_detected = True
                sanitized_lines.append("[REDACTED INJECTION ATTEMPT]")
            else:
                sanitized_lines.append(line)

        return "\n".join(sanitized_lines), injection_detected

    @classmethod
    def validate_evidence(cls, evidence: EvidenceReference, as_of_date: str) -> dict[str, Any]:
        """Comprehensive verification of an evidence citation."""
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Format check
        if not cls.validate_doc_id_format(evidence.doc_id):
            errors.append(f"Invalid Runemark document ID format: {evidence.doc_id}")

        # 2. Clock cutoff check
        if evidence.publication_date and cls.is_clock_violation(evidence.publication_date, as_of_date):
            errors.append(
                f"Clock violation: {evidence.doc_id} published on {evidence.publication_date}, "
                f"after as-of date {as_of_date}"
            )

        # 3. Retraction check
        retraction = cls.check_retraction(evidence.doc_id)
        if retraction:
            corr_id, reason = retraction
            warnings.append(f"Retracted or contradicted source ({evidence.doc_id}): {reason} (See {corr_id})")

        # 4. Reliability tier evaluation
        if evidence.reliability_tier == 4:
            warnings.append(f"Low credibility source ({evidence.doc_id}): Tier 4 source. High risk of exaggeration.")

        # 5. Injection check in snippet
        _, injected = cls.sanitize_content(evidence.quote_or_datapoint)
        if injected:
            warnings.append(f"Snippet in {evidence.doc_id} contains suspected prompt injection.")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "is_retracted": retraction is not None,
            "is_tier_4": evidence.reliability_tier == 4,
        }
