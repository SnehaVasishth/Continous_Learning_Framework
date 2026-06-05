"""Audit: every tool name and substep ID emitted by the orchestrator in the
last `--days` days must be claimed by some entry in `subprocess_taxonomy`.

This script is the contract enforcer between the orchestrator's tool / substep
emission and the Analytics per-stage detail UI. Run it after any agent change
to make sure the taxonomy still covers the real signals.

Exit code:
    0  every event signature is claimed
    1  one or more signatures are unclassified

Usage from the backend venv:
    cd backend
    ./.venv/bin/python ../scripts/check_subprocess_taxonomy.py [--days 30]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.analytics.subprocess_taxonomy import SUBPROCESS_TAXONOMY  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import TraceEvent  # noqa: E402


def collect_taxonomy_keys() -> tuple[set[tuple[str, str, str]], set[tuple[str, str]]]:
    """Return (tool_keys, substep_keys).

    tool_keys is a set of (stage, "tool", tool_name).
    Substeps don't carry a stage in the predicate but are emitted under a
    specific stage; we use (stage, substep_id) and check membership at audit
    time against the substeps a sub-process declares.
    """
    tool_keys: set[tuple[str, str]] = set()    # (stage_in_predicate, tool)
    substep_keys: set[str] = set()
    bare_kinds: set[tuple[str, str]] = set()   # (stage_in_predicate, kind)
    for entry in SUBPROCESS_TAXONOMY:
        for sp in entry["subprocesses"]:
            pred = sp.get("match", {})
            stages_in_pred = pred.get("stages") or [entry["stage"]]
            for tool in (pred.get("tools") or []):
                for s in stages_in_pred:
                    tool_keys.add((s, tool))
            for sub in (pred.get("substeps") or []):
                substep_keys.add(sub)
            for k in (pred.get("kinds") or []):
                for s in stages_in_pred:
                    bare_kinds.add((s, k))
    return tool_keys, substep_keys, bare_kinds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    cutoff = datetime.utcnow() - timedelta(days=args.days)
    db = SessionLocal()
    tool_keys, substep_keys, bare_kind_keys = collect_taxonomy_keys()

    # ---- Tool audit -----------------------------------------------------------
    emitted_tools: Counter[tuple[str, str]] = Counter()
    for ev in db.query(TraceEvent).filter(TraceEvent.kind == "tool_end").filter(TraceEvent.ts >= cutoff).all():
        data = ev.data if isinstance(ev.data, dict) else {}
        tool = data.get("tool")
        if not tool:
            continue
        emitted_tools[(ev.stage, tool)] += 1

    unclassified_tools = [(s, t, n) for (s, t), n in emitted_tools.items() if (s, t) not in tool_keys]

    # ---- Substep audit --------------------------------------------------------
    emitted_substeps: Counter[tuple[str, str]] = Counter()
    for ev in db.query(TraceEvent).filter(TraceEvent.kind == "substep_done").filter(TraceEvent.ts >= cutoff).all():
        data = ev.data if isinstance(ev.data, dict) else {}
        sub = data.get("substep")
        if not sub:
            continue
        emitted_substeps[(ev.stage, sub)] += 1

    unclassified_substeps = [(s, sub, n) for (s, sub), n in emitted_substeps.items() if sub not in substep_keys]

    # ---- Bare-kind audit (kinds-style predicates only) -----------------------
    declared_bare_kinds = bare_kind_keys
    emitted_bare = Counter()
    for (stage, kind) in declared_bare_kinds:
        n = (
            db.query(TraceEvent)
            .filter(TraceEvent.stage == stage)
            .filter(TraceEvent.kind == kind)
            .filter(TraceEvent.ts >= cutoff)
            .count()
        )
        emitted_bare[(stage, kind)] = n
    missing_bare = [(s, k) for (s, k), n in emitted_bare.items() if n == 0]

    # ---- Report --------------------------------------------------------------
    print(f"Taxonomy audit ({args.days}-day window)")
    print("-" * 68)
    print(f"  taxonomy entries: {sum(len(e['subprocesses']) for e in SUBPROCESS_TAXONOMY)} sub-processes across {len(SUBPROCESS_TAXONOMY)} stages")
    print(f"  emitted tool signatures (distinct): {len(emitted_tools)}")
    print(f"  emitted substep signatures (distinct): {len(emitted_substeps)}")
    print(f"  declared bare-kind predicates: {len(declared_bare_kinds)}")
    print()

    failed = False
    if unclassified_tools:
        failed = True
        print(f"UNCLASSIFIED tool signatures ({len(unclassified_tools)}):")
        for s, t, n in sorted(unclassified_tools, key=lambda x: -x[2]):
            print(f"  - stage={s!r:14s}  tool={t!r:35s}  n={n}")
        print()
    if unclassified_substeps:
        failed = True
        print(f"UNCLASSIFIED substep signatures ({len(unclassified_substeps)}):")
        for s, sub, n in sorted(unclassified_substeps, key=lambda x: -x[2]):
            print(f"  - stage={s!r:14s}  substep={sub!r:10s}  n={n}")
        print()
    if missing_bare:
        # missing bare kinds are a warning, not an error: a kind declared in
        # the taxonomy that produced zero events in the window is plausible.
        print(f"Declared bare-kind predicates with no emissions in window (informational, {len(missing_bare)}):")
        for s, k in missing_bare:
            print(f"  - stage={s!r:14s}  kind={k!r}")
        print()

    if failed:
        print("FAIL: taxonomy is out of sync with emitted events.")
        return 1

    print("OK: every tool and substep signature is claimed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
