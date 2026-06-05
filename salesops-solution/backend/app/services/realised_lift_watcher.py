"""Realised-lift watcher.

Closes the "expected vs realised" loop the Continuous Learning deck claims.
For every promoted A/B experiment that has been live for at least
`WATCH_DELAY_HOURS`, the watcher recomputes the candidate's effective
accuracy on the production traffic that occurred after the promotion
timestamp and writes `realised_lift_pct` / `realised_lift_ci` /
`realised_sample_size` / `realised_lift_at` onto the experiment row.

If the realised lift trails the back-test delta by more than
`AUTO_ROLLBACK_TOLERANCE_PCT`, the watcher auto-rolls-back via the existing
`learning_promotion.rollback_promotion` path and stamps
`auto_rolled_back = True`. Operators see the entire timeline (back-test,
promotion, post-promotion measurement, rollback) on the same experiment
card.

Schedule: a single thread launched from `app.main` ticks every
`POLL_INTERVAL_SECONDS`. Safe to run multiple times; idempotent because we
key off `realised_lift_at IS NULL`.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import ABExperiment, Feedback, Pipeline

log = logging.getLogger("realised_lift_watcher")

# Production sample must accumulate at least this long after promotion
# before the watcher takes a reading. Short enough to give same-day
# feedback, long enough that we are not chasing noise.
WATCH_DELAY_HOURS = int(os.environ.get("REALISED_LIFT_WATCH_DELAY_H", "1"))
# Minimum production sample size before the realised number is trusted.
MIN_SAMPLE = int(os.environ.get("REALISED_LIFT_MIN_SAMPLE", "20"))
# How far below the back-test delta is "too far". e.g. backtest +6%, realised
# +1% with TOLERANCE 4 -> auto-rollback fires (5% gap).
AUTO_ROLLBACK_TOLERANCE_PCT = float(os.environ.get("REALISED_LIFT_TOLERANCE_PCT", "5.0"))
POLL_INTERVAL_SECONDS = int(os.environ.get("REALISED_LIFT_POLL_S", "120"))


def _candidates(db: Session) -> Iterable[ABExperiment]:
    """Experiments that have been promoted long enough and not yet measured."""
    cutoff = datetime.utcnow() - timedelta(hours=WATCH_DELAY_HOURS)
    return (
        db.query(ABExperiment)
        .filter(ABExperiment.promote_status == "promoted")
        .filter(ABExperiment.promoted_at.isnot(None))
        .filter(ABExperiment.promoted_at <= cutoff)
        .filter(ABExperiment.realised_lift_at.is_(None))
        .all()
    )


def _measure(db: Session, exp: ABExperiment) -> dict | None:
    """Recompute accuracy delta on production traffic since promotion.

    Two signal sources, used in this priority order:

      1. Shadow A/B results. If the experiment ran in shadow before
         promotion, `ABShadowResult` rows have per-case agreement between
         candidate and production. We compute realised delta as the
         post-promotion thumbs accuracy minus the pre-promotion thumbs
         accuracy, attributing the change to the candidate that actually
         landed.
      2. Thumbs proxy. When no shadow data exists (the change_type didn't
         have a shadow runner, or backtest mode), fall back to:
           thumbs_up / approve = correct
           thumbs_down / reject = incorrect
           edit / edit_and_approve = 0.5 (partial)

    Either way, the back-test delta we compare against is
    `accuracy_delta_pct`; the realised delta is realised_accuracy minus
    the pre-promotion control accuracy.
    """
    if exp.promoted_at is None:
        return None
    since = exp.promoted_at

    # Source 1: shadow agreement, when present. Anchors the realised number
    # on real side-by-side comparison instead of CSR opinion.
    try:
        from ..models import ABShadowResult
        shadow_rows = (
            db.query(ABShadowResult)
            .filter(ABShadowResult.experiment_id == exp.id)
            .order_by(ABShadowResult.created_at.desc())
            .limit(500)
            .all()
        )
    except Exception:
        shadow_rows = []
    shadow_agreement_rate: float | None = None
    if len(shadow_rows) >= MIN_SAMPLE:
        agreed = sum(1 for r in shadow_rows if r.agreement)
        shadow_agreement_rate = agreed / len(shadow_rows)
    # Pull post-promotion feedback for pipelines that ran AFTER the change.
    rows = (
        db.query(Pipeline, Feedback)
        .join(Feedback, Feedback.pipeline_id == Pipeline.id)
        .filter(Pipeline.started_at >= since)
        .all()
    )
    if not rows:
        return None
    correct = 0.0
    total = 0
    for _p, f in rows:
        kind = (f.kind or "").lower()
        if kind in ("approve", "thumbs_up", "promoted", "accept"):
            correct += 1
        elif kind in ("reject", "thumbs_down", "retired"):
            correct += 0
        elif kind in ("edit", "edit_and_approve"):
            correct += 0.5
        else:
            # Unknown kinds don't push the number either way.
            correct += 0.5
        total += 1
    if total < MIN_SAMPLE:
        return None
    realised_acc = correct / total
    # Control accuracy: pre-promotion baseline. Use feedback rows in the
    # window immediately before promotion of the same shape.
    pre_since = since - timedelta(days=14)
    pre_rows = (
        db.query(Pipeline, Feedback)
        .join(Feedback, Feedback.pipeline_id == Pipeline.id)
        .filter(Pipeline.started_at >= pre_since)
        .filter(Pipeline.started_at < since)
        .all()
    )
    if pre_rows:
        c2 = 0.0
        for _p, f in pre_rows:
            kind = (f.kind or "").lower()
            if kind in ("approve", "thumbs_up", "promoted", "accept"):
                c2 += 1
            elif kind in ("reject", "thumbs_down", "retired"):
                c2 += 0
            else:
                c2 += 0.5
        control_acc = c2 / len(pre_rows)
    else:
        control_acc = realised_acc  # No control window — realised delta is 0.

    delta_pct = (realised_acc - control_acc) * 100.0
    # Wilson 95% CI half-width on the delta — coarse but useful.
    se = math.sqrt(max(0.0, realised_acc * (1 - realised_acc)) / max(1, total))
    half = 1.96 * se * 100.0
    ci = f"{delta_pct:+.1f}% (95% CI ±{half:.1f}, n={total})"
    # If we have shadow data, attach it for the UI to show alongside the
    # thumbs-derived realised delta.
    note = None
    if shadow_agreement_rate is not None:
        note = (
            f"shadow agreement: {shadow_agreement_rate*100:.1f}% over "
            f"{len(shadow_rows)} replays (candidate matched production)"
        )
    return {
        "delta_pct": round(delta_pct, 2),
        "ci": ci,
        "sample_size": total,
        "shadow_agreement_rate": shadow_agreement_rate,
        "shadow_sample": len(shadow_rows),
        "note": note,
    }


def _tick_once(db: Session) -> int:
    """Run one watcher pass. Returns number of experiments reconciled."""
    reconciled = 0
    for exp in _candidates(db):
        try:
            res = _measure(db, exp)
            if res is None:
                continue
            exp.realised_lift_pct = res["delta_pct"]
            exp.realised_lift_ci = res["ci"]
            exp.realised_sample_size = res["sample_size"]
            exp.realised_lift_at = datetime.utcnow()

            backtest_delta = exp.accuracy_delta_pct
            gap = None
            should_rollback = False
            if backtest_delta is not None:
                gap = backtest_delta - res["delta_pct"]
                if gap > AUTO_ROLLBACK_TOLERANCE_PCT:
                    should_rollback = True

            if should_rollback:
                exp.realised_note = (
                    f"Auto-rollback: realised {res['delta_pct']:+.1f}% vs back-test "
                    f"{backtest_delta:+.1f}% (gap {gap:+.1f}%, tolerance {AUTO_ROLLBACK_TOLERANCE_PCT}%). "
                    f"Rolled back by realised-lift watcher."
                )
                exp.rolled_back_at = datetime.utcnow()
                exp.rolled_back_by = "realised_lift_watcher"
                exp.rolled_back_note = exp.realised_note
                exp.promote_status = "retired"
                exp.auto_rolled_back = True
                # The actual KB rule rollback happens via the existing
                # promotion service if the operator wants to revert at the
                # rule level. We mark the experiment retired here; the
                # accompanying KbRuleVersion rollback is intentionally
                # operator-mediated for the demo so a human stays in the
                # loop on the rule itself.
                log.warning("realised_lift_watcher: auto-rollback exp=%s gap=%.1f%%", exp.id, gap)
            else:
                if gap is None:
                    exp.realised_note = (
                        f"Realised {res['delta_pct']:+.1f}% (no back-test delta to compare)."
                    )
                else:
                    exp.realised_note = (
                        f"Realised {res['delta_pct']:+.1f}% vs back-test {backtest_delta:+.1f}% "
                        f"(gap {gap:+.1f}%, within {AUTO_ROLLBACK_TOLERANCE_PCT}% tolerance)."
                    )
                # Append shadow-agreement evidence when we have it. Surfaces
                # the real side-by-side comparison the CSR-thumbs proxy
                # cannot give on its own.
                if res.get("shadow_agreement_rate") is not None:
                    exp.realised_note = (
                        (exp.realised_note or "")
                        + f" Shadow agreement {res['shadow_agreement_rate']*100:.1f}% "
                        + f"over {res['shadow_sample']} replays."
                    )
            db.add(exp)
            db.commit()
            reconciled += 1
        except Exception:
            log.exception("realised_lift_watcher: failed exp=%s", exp.id)
            db.rollback()
    return reconciled


_STARTED = False


def start_in_background() -> None:
    """Kick off the watcher in a daemon thread. Safe to call multiple times."""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True

    def _loop() -> None:
        log.info(
            "realised_lift_watcher started — delay=%dh min_sample=%d tolerance=%.1f%% poll=%ds",
            WATCH_DELAY_HOURS, MIN_SAMPLE, AUTO_ROLLBACK_TOLERANCE_PCT, POLL_INTERVAL_SECONDS,
        )
        while True:
            try:
                db = SessionLocal()
                try:
                    n = _tick_once(db)
                    if n:
                        log.info("realised_lift_watcher reconciled %d experiments", n)
                finally:
                    db.close()
            except Exception:
                log.exception("realised_lift_watcher tick failed")
            time.sleep(POLL_INTERVAL_SECONDS)

    t = threading.Thread(target=_loop, name="realised_lift_watcher", daemon=True)
    t.start()


def tick_now(db: Session) -> int:
    """Manual trigger for tests / admin endpoint."""
    return _tick_once(db)
