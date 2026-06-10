"""Fetch a client's codebase for discovery.

Two modes (SOLUTION_FETCH_MODE):
  - "live"  : POST the ZBrain download-app API, which returns the client's
              codebase as a zip, and extract it. Falls back to a local fixture
              when the API is unreachable and one exists for the session.
  - "local" : extract a repo-root zip fixture keyed by session_id.

The signature (tenant_id, session_id) -> directory is identical in both modes,
so nothing downstream cares which path produced the codebase.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
import zipfile
from pathlib import Path

import requests

log = logging.getLogger("signal_graph.fetch_solution")

# Walk up from this file to the repo root, where the example zips live.
# parents: 0=discovery 1=signal_graph 2=services 3=app 4=backend 5=salesops-solution 6=repo-root
_REPO_ROOT = Path(__file__).resolve().parents[6]

# Map a session_id to its local zip fixture (used by 'local' mode and as the
# 'live' fallback when the API is down).
_FIXTURES = {
    "f8651fcd-6c46-4ed2-83ec-665f31027267": "tristone---test-case-3.zip",      # todo app
    "de11b0cf-59dc-48e4-8b56-7ecb18dd6946": "content-research-solution.zip",   # content research
}

_DEFAULT_URL = "https://content.staging.zbrain.ai/solution-apps/download-app"


def _extract_zip_bytes(data: bytes, session_id: str) -> Path:
    """Extract a zip held in memory into a fresh temp dir and return it."""
    work_dir = Path(tempfile.mkdtemp(prefix=f"sg_{session_id[:8]}_"))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(work_dir)
    return work_dir


def _fetch_local(session_id: str) -> Path:
    """Extract the repo-root zip fixture for this session."""
    zip_name = _FIXTURES.get(session_id)
    if not zip_name:
        raise ValueError(f"no local fixture for session_id={session_id}")
    zip_path = _REPO_ROOT / zip_name
    return _extract_zip_bytes(zip_path.read_bytes(), session_id)


def _fetch_live(tenant_id: str, session_id: str) -> Path:
    """Download the client's codebase zip from the ZBrain download-app API.

    The Bearer token is a short-lived JWT read from the environment — it is
    NEVER hardcoded here. Raises on any non-zip / error response so the caller
    can decide whether to fall back to a fixture.
    """
    url = os.environ.get("SOLUTION_FETCH_URL", _DEFAULT_URL)
    token = os.environ.get("SOLUTION_FETCH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SOLUTION_FETCH_TOKEN is not set (cannot call the live API)")

    resp = requests.post(
        url,
        json={"sessionId": session_id, "tenantId": tenant_id},
        headers={
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "accept": "application/json, application/zip, */*",
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"download-app returned HTTP {resp.status_code}: {resp.text[:200]}")

    body = resp.content
    if body[:2] != b"PK":  # zip files start with the magic bytes "PK"
        ctype = resp.headers.get("content-type", "?")
        raise RuntimeError(f"download-app did not return a zip (content-type={ctype}): {body[:200]!r}")

    return _extract_zip_bytes(body, session_id)


def fetch_solution(tenant_id: str, session_id: str) -> Path:
    """Return a directory containing the client's extracted codebase.

    'live' mode hits the API and, if it fails while a local fixture exists,
    falls back to the fixture so the demo never breaks. 'local' mode uses the
    fixture directly.
    """
    mode = os.environ.get("SOLUTION_FETCH_MODE", "local").strip().lower()

    if mode == "live":
        try:
            return _fetch_live(tenant_id, session_id)
        except Exception as e:
            if session_id in _FIXTURES:
                log.warning("live fetch failed (%s); falling back to local fixture for %s", e, session_id)
                return _fetch_local(session_id)
            raise  # no fixture to fall back to — surface the real error

    return _fetch_local(session_id)
