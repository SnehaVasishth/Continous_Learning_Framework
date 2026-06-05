"""Auto-start a cloudflared quick tunnel so AWS Lambda can reach our local files.

Background: the Azure DocIntelligence Lambda only accepts a publicly-reachable
`pdf_url`. AWS Lambda cannot reach localhost. To make the Lambda fire by
default in local dev, we spawn `cloudflared tunnel --url http://localhost:<port>`,
parse the *.trycloudflare.com hostname out of its log output, and export it as
APP_BASE_URL so the extraction tool can build public URLs for our /files/uploads
mounts.

When the Lambda is later given an S3-presigned URL or moved to private
networking, this entire path becomes a no-op.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

LOG = logging.getLogger(__name__)

_BIN = Path(__file__).resolve().parent.parent.parent / "bin" / "cloudflared.exe"
_TUNNEL_RE = re.compile(r"https://[A-Za-z0-9-]+\.trycloudflare\.com")
_proc: subprocess.Popen | None = None
_url: str | None = None
_lock = threading.Lock()


def _read_output(proc: subprocess.Popen) -> None:
    """Background reader: parse the tunnel URL out of cloudflared's stderr."""
    global _url
    assert proc.stderr is not None
    for line in iter(proc.stderr.readline, ""):
        if not line:
            break
        if _url is None:
            m = _TUNNEL_RE.search(line)
            if m:
                # Order matters: export env BEFORE setting _url, so any caller
                # that polls _url and then reads os.environ sees a consistent state.
                os.environ["APP_BASE_URL"] = m.group(0)
                _url = m.group(0)
                LOG.info("cloudflared tunnel ready: %s", _url)


def start(*, port: int = 8000, wait_seconds: float = 12.0) -> str | None:
    """Start the tunnel if not already running. Returns the public URL or None."""
    global _proc, _url
    with _lock:
        if _url:
            return _url
        if _proc and _proc.poll() is None:
            return _url
        if not _BIN.exists():
            LOG.warning("cloudflared binary missing at %s — Lambda OCR will fall back to local extractor", _BIN)
            return None
        try:
            _proc = subprocess.Popen(
                [str(_BIN), "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except Exception as e:
            LOG.warning("failed to start cloudflared: %s", e)
            return None

        threading.Thread(target=_read_output, args=(_proc,), daemon=True).start()

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if _url:
            return _url
        if _proc and _proc.poll() is not None:
            LOG.warning("cloudflared exited prematurely (rc=%s)", _proc.returncode)
            return None
        time.sleep(0.25)
    LOG.warning("cloudflared did not surface a tunnel URL within %ss", wait_seconds)
    return None


def stop() -> None:
    global _proc, _url
    with _lock:
        if _proc and _proc.poll() is None:
            try:
                _proc.terminate()
                try:
                    _proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    _proc.kill()
            except Exception:
                pass
        _proc = None
        _url = None


def current_url() -> str | None:
    """Return the public base URL Lambda can fetch /files/uploads/ through.

    Resolution order:
      1. `APP_BASE_URL` env var, when set to a non-localhost URL. This is the
         path operators use when they already run a tunnel (e.g. cloudflared,
         ngrok, or a tunnel-fronted Caddy) and just want the backend to
         consume the URL.
      2. The URL the in-process tunnel reader thread captured from a spawned
         `cloudflared --url http://localhost:<port>` process.
    """
    env_url = os.environ.get("APP_BASE_URL", "").strip()
    if env_url and "localhost" not in env_url and "127.0.0.1" not in env_url:
        return env_url.rstrip("/")
    return _url
