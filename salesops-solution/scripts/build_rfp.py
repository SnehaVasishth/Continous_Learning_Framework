"""Build every Keysight RFP response DOCX and write it to a release directory.

Usage from the backend venv:
    cd backend
    ./.venv/bin/python ../scripts/build_rfp.py

Default output directory is keysight-salesops-demo/keysight-rfp-build at the repo root.
Pass --out PATH to override.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.rfp_reply_docx import SECTIONS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(ROOT / "keysight-rfp-build"),
        help="Output directory (default: keysight-salesops-demo/keysight-rfp-build)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    print(f"Building {len(SECTIONS)} deliverables into {out_dir}")
    print("-" * 78)
    for s in SECTIONS:
        payload = s["builder"]()
        path = out_dir / s["filename"]
        path.write_bytes(payload)
        total_bytes += len(payload)
        print(f"  {s['filename']:<55s}  {len(payload):>8,d} bytes")
    print("-" * 78)
    print(f"  TOTAL  {total_bytes:>8,d} bytes across {len(SECTIONS)} files")
    print()
    print(f"Done. Files written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
