"""Evidence and Document schemas compatible across all RAGNAROK PS3 courtroom agents."""

from typing import Optional
from pydantic import BaseModel, Field


class EvidenceReference(BaseModel):
    """Reference to an exact paragraph, page, or trade row in a Runemark document."""
    doc_id: str = Field(description="Runemark document ID, e.g. 'ORV-0027'")
    paragraph: Optional[str] = Field(default=None, description="Paragraph or table row, e.g. 'P6', 'row 3'")
    reliability_tier: Optional[int] = Field(default=None, ge=1, le=4, description="Tier 1 (Official) to 4 (Weak)")
    source_name: Optional[str] = Field(default=None, description="Publishing outlet or authority name")
    publication_date: Optional[str] = Field(default=None, description="Publication date in YYYY-MM-DD")
    quote_or_datapoint: str = Field(description="Directly quoted text or exact numerical observation")
    is_off_runemark: bool = Field(default=False, description="True if evidence is from outside Runemark")

    def to_citation_str(self) -> str:
        p_str = f" [{self.paragraph}]" if self.paragraph else ""
        tier_str = f" (Tier {self.reliability_tier})" if self.reliability_tier else ""
        return f"{self.doc_id}{p_str}{tier_str}: {self.quote_or_datapoint}"


class Document(BaseModel):
    """Raw or parsed Runemark document."""
    doc_id: str
    event_id: str
    title: str
    source_name: str
    source_type: str
    reliability_tier: int = Field(ge=1, le=4)
    pub_date: str
    pub_time: Optional[str] = None
    country: str
    sector: str
    language: str = "en"
    format: str
    file_path: Optional[str] = None
    content: str
    paragraphs: dict[str, str] = Field(default_factory=dict)
