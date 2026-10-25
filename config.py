"""
Central configuration for the RAGNAROK Trial of the Nine Realms system.
All paths, defaults, and shared settings live here.
"""

import os
from pathlib import Path

# ── Project root ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent

# ── Data paths ────────────────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
DEV_PACK_DIR = DATA_DIR / "dev_pack_E5"
DOCS_DIR = DEV_PACK_DIR / "docs"
MANIFEST_PATH = DEV_PACK_DIR / "manifest.json"
SAMPLE_QUESTION_PATH = DEV_PACK_DIR / "sample_question.txt"

# ── Index / cache paths ──────────────────────────────────────────────────────
INDEX_DIR = PROJECT_ROOT / "indices"
FAISS_INDEX_PATH = INDEX_DIR / "faiss.index"
BM25_INDEX_PATH = INDEX_DIR / "bm25.pkl"
CHUNKS_PATH = INDEX_DIR / "chunks.json"

# ── Heimdall private memory ──────────────────────────────────────────────────
HEIMDALL_MEMORY_DIR = PROJECT_ROOT / "heimdall_memory"
HEIMDALL_MEMORY_PATH = HEIMDALL_MEMORY_DIR / "memory.json"

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = PROJECT_ROOT / "logs"
HEIMDALL_LOG_PATH = LOG_DIR / "heimdall.jsonl"

# ── Model settings ───────────────────────────────────────────────────────────
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384          # dimension for all-MiniLM-L6-v2
CHUNK_SIZE = 512                   # characters per chunk
CHUNK_OVERLAP = 64                 # overlap between chunks

# ── Retrieval defaults ───────────────────────────────────────────────────────
DEFAULT_TOP_K = 20                 # results returned per search mode
RRF_K = 60                        # Reciprocal Rank Fusion constant
HYBRID_TOP_K = 15                  # final results after fusion

# ── Reliability tiers (from ATL-0012) ────────────────────────────────────────
# Tier 1: Government / official ministry  → highest trust
# Tier 2: Established trade press, reputable company statements
# Tier 3: Analyst notes, regional papers with editorial standards
# Tier 4: Tabloids, blogs, social media, unverified sources → lowest trust
UNRELIABLE_TIER = 4

# ── Source types that indicate retractions / corrections ─────────────────────
RETRACTION_SOURCE_TYPES = {"correction", "retraction"}

# ── Ensure directories exist ────────────────────────────────────────────────
for d in [DATA_DIR, DEV_PACK_DIR, DOCS_DIR, INDEX_DIR,
          HEIMDALL_MEMORY_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)
