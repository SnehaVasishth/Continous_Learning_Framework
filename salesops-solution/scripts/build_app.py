"""Build every artefact required to deploy the Keysight SalesOps demo.

What this script does:
  1. Compiles the React + Vite frontend production bundle into frontend/dist.
  2. Verifies backend Python deps install cleanly in the existing venv.
  3. Regenerates every RFP-reply DOCX into keysight-rfp-build.
  4. Reports byte sizes for every produced artefact.

Usage:
    cd backend
    ./.venv/bin/python ../scripts/build_app.py [--skip-frontend] [--skip-rfp]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
RFP_OUT = ROOT / "keysight-rfp-build"
FRONTEND_DIST = FRONTEND / "dist"


def run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(cmd)}   (cwd={cwd})")
    subprocess.run(cmd, cwd=cwd, check=True)


def folder_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-frontend", action="store_true",
                        help="Do not rebuild the frontend bundle")
    parser.add_argument("--skip-rfp", action="store_true",
                        help="Do not regenerate the RFP DOCX deliverables")
    parser.add_argument("--refresh-deps", action="store_true",
                        help="Refresh backend Python dependencies (default: skip; venv already provisioned)")
    args = parser.parse_args()

    artefacts: list[tuple[str, int]] = []

    section("1. Frontend production bundle (Vite + tsc)")
    if args.skip_frontend:
        print("Skipped per --skip-frontend.")
    else:
        npm = shutil.which("npm")
        if not npm:
            print("ERROR: npm not found on PATH; cannot build frontend.", file=sys.stderr)
            return 2
        run([npm, "run", "build"], cwd=FRONTEND)
    if FRONTEND_DIST.exists():
        size = folder_bytes(FRONTEND_DIST)
        artefacts.append((str(FRONTEND_DIST.relative_to(ROOT)), size))
        for f in sorted(FRONTEND_DIST.rglob("*")):
            if f.is_file():
                print(f"  {f.relative_to(FRONTEND_DIST)!s:<50s}  {f.stat().st_size:>10,d} bytes")
    else:
        print(f"WARN: {FRONTEND_DIST} does not exist after build.")

    section("2. Backend Python venv check")
    py = BACKEND / ".venv" / "bin" / "python"
    if not py.exists():
        print("ERROR: backend/.venv/bin/python not found. Run:")
        print("  cd backend && python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.txt")
        return 2
    if args.refresh_deps:
        run([str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=BACKEND)
        print("Backend deps refreshed.")
    else:
        # Sanity-check that the section builders import cleanly
        run([str(py), "-c", "from app.services.rfp_reply_docx import SECTIONS; print('imports OK,', len(SECTIONS), 'sections registered')"], cwd=BACKEND)
    artefacts.append((str((BACKEND / ".venv").relative_to(ROOT)), folder_bytes(BACKEND / ".venv")))

    section("3. RFP-reply DOCX deliverables")
    if args.skip_rfp:
        print("Skipped per --skip-rfp.")
    else:
        if not py.exists():
            print("ERROR: backend venv missing; cannot build RFP docs.", file=sys.stderr)
            return 3
        run([str(py), str(ROOT / "scripts" / "build_rfp.py")], cwd=BACKEND)
    if RFP_OUT.exists():
        size = folder_bytes(RFP_OUT)
        artefacts.append((str(RFP_OUT.relative_to(ROOT)), size))

    section("Artefact summary")
    total = 0
    for name, size in artefacts:
        print(f"  {name:<35s}  {size:>12,d} bytes")
        total += size
    print(f"  {'TOTAL':<35s}  {total:>12,d} bytes")

    print()
    print("Next steps:")
    print(f"  Run locally   : cd backend && ./.venv/bin/python -m uvicorn app.main:app --port 8000")
    print(f"  Docker build  : docker compose -f docker-compose.yml build")
    print(f"  Docker up     : docker compose -f docker-compose.yml up -d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
