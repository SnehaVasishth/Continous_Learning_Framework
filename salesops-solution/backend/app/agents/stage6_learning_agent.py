"""Stage 6 — Continuous Learning: aggregate feedback and emit drift signals (placeholder)."""
from __future__ import annotations

import time

from ..models import Feedback, Pipeline
from .base import AgentContext, AgentResult, BaseAgent


class Stage6LearningAgent(BaseAgent):
    """Aggregates per-pipeline feedback events and emits a drift signal placeholder."""

    stage_key = "learning"
    stage_label = "Continuous Learning"
    tools = []

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.perf_counter()
        guardrails: list[str] = []
        try:
            try:
                feedback_count = (
                    ctx.db.query(Feedback).filter(Feedback.pipeline_id == ctx.pipeline_id).count()
                )
            except Exception as e:
                feedback_count = 0
                guardrails.append(f"feedback_query_failed: {type(e).__name__}: {str(e)[:200]}")

            learning = {
                "feedback_count": int(feedback_count or 0),
                "drift_signal": "none",
            }
            ctx.learning = learning  # type: ignore[attr-defined]

            self._persist(ctx, learning)
            return AgentResult(
                stage=self.stage_key,
                output=learning,
                tool_results=[],
                guardrails_fired=guardrails,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as e:
            return AgentResult(
                stage=self.stage_key,
                output={},
                tool_results=[],
                guardrails_fired=[*guardrails, f"stage_error: {type(e).__name__}: {str(e)[:300]}"],
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def _persist(self, ctx: AgentContext, learning: dict) -> None:
        pipe = ctx.db.get(Pipeline, ctx.pipeline_id)
        if not pipe:
            return
        existing = (pipe.suggested_fix or {}) if isinstance(pipe.suggested_fix, dict) else {}
        existing["learning"] = learning
        pipe.suggested_fix = existing
        ctx.db.commit()
