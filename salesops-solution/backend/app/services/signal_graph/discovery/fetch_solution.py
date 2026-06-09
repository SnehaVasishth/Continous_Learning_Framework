"""Fetch a client's codebase for discovery.

v1 LOCAL MODE: resolve a session_id to a zip already in the repo root and
extract it. The signature (tenant_id, session_id) -> directory is the SAME we
will use for the live API, so swapping to `SOLUTION_FETCH_MODE=live` later
changes only this file.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

# Walk up from this file to the repo root, where the example zips live.
# parents: 0=discovery 1=signal_graph 2=services 3=app 4=backend 5=salesops-solution 6=repo-root
_REPO_ROOT = Path(__file__).resolve().parents[6]

# v1: map a session_id to its zip in the repo root.
_FIXTURES = {
    "f8651fcd-6c46-4ed2-83ec-665f31027267": "tristone---test-case-3.zip",   # todo app
    # add the content-research session id here when known:
    # "<session-id>": "content-research-solution.zip",
}


def fetch_solution(tenant_id: str, session_id: str) -> Path:
    """Return a directory containing the client's extracted codebase.

    v1: read a local zip fixture keyed by session_id. Raises if the mode is
    not 'local' or the session_id has no fixture.
    """
    mode = os.environ.get("SOLUTION_FETCH_MODE", "local")
    if mode != "local":
        raise NotImplementedError("live Solution-Fetch API not wired in v1")

    zip_name = _FIXTURES.get(session_id)
    if not zip_name:
        raise ValueError(f"no local fixture for session_id={session_id}")

    zip_path = _REPO_ROOT / zip_name
    work_dir = Path(tempfile.mkdtemp(prefix=f"sg_{session_id[:8]}_"))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(work_dir)
    return work_dir
