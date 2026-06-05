"""Agent + Tool primitives for the ZBrain agent fabric.

Each pipeline stage is a `BaseAgent` subclass with a declared tool belt.
Tools are concrete units of work (LLM call, OCR pass, Salesforce query,
SOQL write, KB rule evaluation) that emit their own trace events.

Execution model: deterministic per-stage flow defined inside the agent's
`run()` method — tools are called explicitly (not via LLM tool-use), so the
control flow is auditable and testable. The agent shape lets the UI surface
*which tools fired with what timing and what KB rules they referenced* —
which is the per-stage drill-down the RFP architecture diagram demands.

Guardrails live here as middleware on `_invoke_tool()` so every stage gets
them by inheritance (intent normalization, write idempotency, customer-match
checks, etc.).
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..trace_log import log_event


@dataclass
class ToolResult:
    """The output of a single tool invocation. Always emit one trace event per result."""

    name: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)


class Tool(ABC):
    """Abstract tool — every tool the agents can call implements this."""

    name: str = "unnamed_tool"
    description: str = ""
    kb_namespaces: list[str] = []  # KB namespaces this tool reads at runtime

    @abstractmethod
    def invoke(self, ctx: "AgentContext", **inputs: Any) -> ToolResult:
        ...


@dataclass
class AgentContext:
    """Shared mutable state passed through every tool call within a stage."""

    db: Session
    pipeline_id: int
    email: dict[str, Any]
    intake: dict[str, Any] = field(default_factory=dict)
    extracted: dict[str, Any] = field(default_factory=dict)
    customer_match: dict[str, Any] = field(default_factory=dict)
    reconcile: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    reply: dict[str, Any] = field(default_factory=dict)
    customer_id: int | None = None
    kb_rules_consulted: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    """The aggregate output of a single stage's run."""

    stage: str
    output: dict[str, Any] = field(default_factory=dict)
    tool_results: list[ToolResult] = field(default_factory=list)
    guardrails_fired: list[str] = field(default_factory=list)
    duration_ms: int = 0


class BaseAgent(ABC):
    """Each pipeline stage subclasses this and implements `run()`.

    Subclasses declare their tool belt as a class attribute; the base class
    handles per-tool trace event emission, timing, and the guardrail
    middleware that wraps every tool invocation.
    """

    stage_key: str = "unnamed"          # short stage id used in trace events
    stage_label: str = "Unnamed Stage"
    tools: list[Tool] = []

    def __init__(self) -> None:
        self._tool_index: dict[str, Tool] = {t.name: t for t in self.tools}

    # ------------------------------------------------------------------
    # Subclass entrypoint
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, ctx: AgentContext) -> AgentResult:
        """Subclass orchestrates which tools to invoke in what order."""

    # ------------------------------------------------------------------
    # Tool invocation (with built-in observability + guardrails)
    # ------------------------------------------------------------------

    def invoke_tool(
        self,
        ctx: AgentContext,
        tool_name: str,
        guardrails: list[Callable[[ToolResult, AgentContext], list[str]]] | None = None,
        **inputs: Any,
    ) -> ToolResult:
        """Run a tool by name. Emits two trace events (tool_start / tool_end)
        and applies the per-tool guardrails. Tools never raise — they return
        ToolResult(ok=False, error=...)."""

        tool = self._tool_index.get(tool_name)
        if tool is None:
            return ToolResult(name=tool_name, ok=False, error=f"unknown tool: {tool_name}")

        log_event(
            ctx.db,
            ctx.pipeline_id,
            self.stage_key,
            "tool_start",
            f"{tool.name} — {tool.description[:80]}",
            data={"tool": tool.name, "kb_namespaces": tool.kb_namespaces, "inputs_summary": _summarize(inputs)},
        )
        ctx.db.flush()

        start = time.perf_counter()
        try:
            result = tool.invoke(ctx, **inputs)
        except Exception as e:
            result = ToolResult(name=tool.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
        result.duration_ms = result.duration_ms or int((time.perf_counter() - start) * 1000)

        # Apply guardrails (each may modify the result and append note strings)
        guardrail_notes: list[str] = []
        for g in guardrails or []:
            try:
                guardrail_notes.extend(g(result, ctx) or [])
            except Exception as e:
                guardrail_notes.append(f"guardrail_error: {type(e).__name__}: {e}")
        if guardrail_notes:
            result.notes.extend(guardrail_notes)

        log_event(
            ctx.db,
            ctx.pipeline_id,
            self.stage_key,
            "tool_end",
            f"{tool.name} {'ok' if result.ok else 'failed'} ({result.duration_ms}ms)",
            data={
                "tool": tool.name,
                "ok": result.ok,
                "duration_ms": result.duration_ms,
                "data": _truncate(result.data),
                "error": result.error,
                "notes": result.notes,
            },
            duration_ms=result.duration_ms,
        )
        ctx.db.commit()
        return result


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _summarize(inputs: dict[str, Any]) -> dict[str, Any]:
    """Compact representation of tool inputs for trace events (no giant payloads)."""
    out: dict[str, Any] = {}
    for k, v in inputs.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        elif isinstance(v, list):
            out[k] = f"<list:{len(v)}>"
        elif isinstance(v, dict):
            out[k] = f"<dict:{len(v)} keys>"
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = repr(v)[:120]
    return out


def _truncate(data: dict[str, Any], max_chars: int = 64000) -> dict[str, Any]:
    """Cap trace event data so the activity log doesn't blow up SQLite JSON columns.
    Limit raised from 4 KB to 64 KB so behind-the-scenes prompts (classify_intent's
    ~5 KB system prompt, full LLM responses, etc.) survive intact for the UI."""
    import json as _json

    try:
        s = _json.dumps(data, default=str)
        if len(s) <= max_chars:
            return data
        return {"_truncated": True, "_original_chars": len(s), "_preview": s[:max_chars]}
    except Exception:
        return {"_unserializable": True}
