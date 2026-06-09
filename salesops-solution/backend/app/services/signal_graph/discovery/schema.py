"""Contracts for the two-pass discovery layer.

A `Signal` is a FACT the LLM extracts from a client's codebase (something the
running system observably emits). A `CandidateGate` is a JUDGMENT the LLM makes
on top of those facts (a quality metric worth monitoring). They are separate
types because they are produced by two separate passes and reviewed differently.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class Signal(BaseModel):
    """One observable signal the system emits — a verifiable fact."""
    key: str                                   # stable id, e.g. "post_title_400"
    description: str                           # human-readable fact
    stream: Literal["telemetry", "feedback"]   # the ONE fixed categorization
    observable: str                            # free-text hint, e.g. "status_code"
    evidence: str                              # file:line / doc ref, for verification
    segment_hint: Optional[str] = None         # optional, e.g. "endpoint:POST /todos"


class CandidateGate(BaseModel):
    """One proposed quality gate over signals — a judgment. Carries NO target
    value (the user sets it on accept) and NO priority (candidates are unranked;
    priority is a property of accepted baseline targets, computed from data)."""
    key: str
    description: str
    direction: Literal["min", "max"]
    compute: Literal["rate", "ratio", "p95", "psi", "count", "mean"]
    inputs: list[str]                          # Signal.key list = the graph edges (gate <- signals)
    segment_dimension: str = "global"          # discovered; may be "global"
    rationale: str
