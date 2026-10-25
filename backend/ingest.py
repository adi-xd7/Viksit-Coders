"""Entry point so `python -m backend.ingest <pack_dir>` works from the project root."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragnarok.ingest.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
