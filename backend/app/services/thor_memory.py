"""Thor-only private persistent memory with case isolation and provenance."""

from typing import Optional
from backend.app.services.memory import LokiMemoryService, CaseMemory, MemoryItem


class ThorMemoryService(LokiMemoryService):
    """
    Manages private, persistent memory for the Thor agent.
    Strictly isolated per case_id and isolated from Loki and other agents (NFR 1, NFR 6).
    Reuses the robust CaseMemory and MemoryItem data structures.
    """

    agent_name: str = "thor"

    def __init__(self, storage_path: Optional[str] = None):
        super().__init__(storage_path=storage_path)
