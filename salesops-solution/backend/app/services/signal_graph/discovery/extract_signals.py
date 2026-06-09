"""Pass 1 of discovery: extract observable SIGNALS (facts) from a codebase.

We build a digest of the files most likely to reveal signals (docs + routes +
schema + server), hand it to the LLM, and validate each returned item through
the `Signal` model so malformed entries are dropped rather than crashing.
"""
from __future__ import annotations

from pathlib import Path

from ....agents.llm import ask_llm        # 4 dots: discovery -> signal_graph -> services -> app, then agents.llm
from .schema import Signal

# Files most likely to contain observable signals.
_DOC_GLOBS = ("*.md",)
_SRC_GLOBS = ("**/routes/*.*", "**/*.sql", "**/server.*", "**/agents-plan.md")
_MAX_CHARS = 60_000   # keep the digest within model context for v1 small codebases


def _build_digest(code_dir: Path) -> str:
    """Concatenate the relevant files into one labelled text blob, capped."""
    parts: list[str] = []
    seen: set[Path] = set()
    for pat in _DOC_GLOBS + _SRC_GLOBS:
        for f in sorted(code_dir.rglob(pat)):
            if f in seen or not f.is_file():
                continue
            seen.add(f)
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            parts.append(f"\n\n===== FILE: {f.relative_to(code_dir).as_posix()} =====\n{text}")
    return "".join(parts)[:_MAX_CHARS]


_SYSTEM = (
    "You are analyzing a software system to find its observable QUALITY SIGNALS. "
    "A signal is a FACT about something the running system emits or records: HTTP status "
    "codes, errors, latencies, log/telemetry events, DB writes (these are 'telemetry'); or "
    "human corrections/edits/reviews of the system's output (these are 'feedback'). Do NOT "
    "invent metrics or thresholds. Only report signals you can point to in the provided files. "
    "Return JSON: {\"signals\": [{\"key\",\"description\",\"stream\",\"observable\",\"evidence\",\"segment_hint\"}]}. "
    "stream is exactly 'telemetry' or 'feedback'. evidence is a file:line or filename reference."
)


def extract_signals(code_dir: Path) -> list[Signal]:
    """Run Pass 1 and return the validated signals (bad items skipped)."""
    digest = _build_digest(code_dir)
    data = ask_llm(system=_SYSTEM, user=digest, json_only=True)
    raw = (data or {}).get("signals", []) if isinstance(data, dict) else []
    out: list[Signal] = []
    for item in raw:
        try:
            out.append(Signal(**item))          # pydantic validates each; bad ones skipped
        except Exception:
            continue
    return out
