"""
Download the dev_pack_E5 corpus from GitHub.

Run this once to populate data/dev_pack_E5/docs/ with the 76 documents.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

BASE_URL = (
    "https://raw.githubusercontent.com/Nodal-leaf/Problem-Statements-RAGNAROK/"
    "main/03_Ragnarok%20Trial%20of%20the%20Nine%20Realms/dev_pack_E5"
)

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data" / "dev_pack_E5"
DOCS_DIR = DATA_DIR / "docs"


def download_file(url: str, dest: Path) -> bool:
    """Download a single file."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, str(dest))
        return True
    except Exception as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        return False


def main():
    print("=== Downloading dev_pack_E5 corpus ===")

    # 1. Download metadata files
    meta_files = ["manifest.json", "sample_question.txt", "hashes.sha256",
                  "README.md"]
    for fname in meta_files:
        dest = DATA_DIR / fname
        if dest.exists():
            print(f"  [skip] {fname} (already exists)")
            continue
        url = f"{BASE_URL}/{fname}"
        print(f"  [download] {fname}")
        download_file(url, dest)

    # 2. Load manifest to get document list
    manifest_path = DATA_DIR / "manifest.json"
    if not manifest_path.exists():
        print("ERROR: manifest.json not downloaded!", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 3. Download all documents
    docs = manifest.get("documents", [])
    print(f"\nDownloading {len(docs)} documents...")

    success = 0
    failed = 0
    skipped = 0

    for doc in docs:
        filename = doc.get("file", "")
        if not filename:
            continue
        dest = DOCS_DIR / filename
        if dest.exists():
            skipped += 1
            continue
        url = f"{BASE_URL}/docs/{urllib.request.quote(filename)}"
        sys.stdout.write(f"  [{success + failed + skipped + 1}/{len(docs)}] "
                         f"{filename}... ")
        sys.stdout.flush()
        if download_file(url, dest):
            success += 1
            print("OK")
        else:
            failed += 1
            print("FAILED")

    print(f"\nDone: {success} downloaded, {skipped} skipped, {failed} failed")
    print(f"Corpus location: {DOCS_DIR}")


if __name__ == "__main__":
    main()
