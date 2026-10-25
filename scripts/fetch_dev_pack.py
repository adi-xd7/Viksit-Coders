"""Download the PS3 dev pack without a git clone and verify it.

Downloads the organizer repo as a zip over HTTPS (avoids Windows long-path issues
and the unauthenticated GitHub API rate limit), extracts only the
"03_Ragnarok Trial of the Nine Realms" folder into data/runemark/, then checks the
file count against manifest.json and every checksum in hashes.sha256.

Usage: .venv/Scripts/python scripts/fetch_dev_pack.py [--verify-only]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "runemark"
ZIP_URL = "https://codeload.github.com/Nodal-leaf/Problem-Statements-RAGNAROK/zip/refs/heads/main"
PREFIX = "Problem-Statements-RAGNAROK-main/03_Ragnarok Trial of the Nine Realms/"


def download_and_extract() -> int:
    with urllib.request.urlopen(ZIP_URL, timeout=120) as resp:
        blob = resp.read()
    count = 0
    dest_root = DEST.resolve()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith(PREFIX):
                continue
            rel = PurePosixPath(info.filename[len(PREFIX):])
            if len(rel.parts) == 1 and rel.suffix.lower() == ".pdf":
                out = dest_root / "problem_statement" / rel.name
            else:
                out = dest_root / Path(*rel.parts)
            out = out.resolve()
            if not out.is_relative_to(dest_root):
                raise RuntimeError(f"refusing path outside destination: {rel}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(info))
            count += 1
    return count


def verify(pack_dir: Path) -> bool:
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    on_disk = {p.name for p in (pack_dir / "docs").iterdir() if p.is_file()}
    listed = {d.get("file") for d in docs}
    ok = True
    print(f"manifest count={manifest.get('count')} listed={len(docs)} on_disk={len(on_disk)}")
    if manifest.get("count") != len(docs) or listed != on_disk:
        ok = False
        print("  MISMATCH listed-not-on-disk:", sorted(listed - on_disk), "on-disk-not-listed:", sorted(on_disk - listed))
    bad, checked = [], 0
    for line in (pack_dir / "hashes.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split(None, 1)
        path = pack_dir / rel.strip().lstrip("*")
        checked += 1
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest.lower():
            bad.append(rel.strip())
    print(f"checksums checked={checked} mismatched/missing={bad}")
    return ok and not bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()
    if not args.verify_only:
        print("extracted", download_and_extract(), "files into", DEST)
    good = verify(DEST / "dev_pack_E5")
    print("VERIFIED" if good else "VERIFICATION PROBLEMS (see above)")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
