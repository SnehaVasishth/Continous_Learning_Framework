"""Stale-inbox sweeper.

Reclassifies emails that landed in the inbox, never started a pipeline, and
have aged past a configurable threshold. The intent is to keep the Dashboard
"New" tile honest: only emails that a human could still reasonably action
remain countable as new. Older untouched messages move to
``expired_unworkable`` so they stop inflating the operator's backlog but stay
queryable for audit.

Design notes:
- We never delete rows. The sweep is a status reclassification only.
- The sweep is idempotent: re-running it on the same window changes nothing.
- The decision is two-part: (1) status must still be ``new``, (2) no
  Pipeline row references the email. If a pipeline exists, the email is in
  someone's funnel and the sweeper leaves it alone regardless of age.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import Email, Pipeline

log = logging.getLogger("email_sweeper")

# New terminal status applied by the sweeper. Kept in lockstep with
# ``app.routes.emails.KNOWN_STATUSES`` so the Inbox dropdown surfaces the
# bucket and the Dashboard reconciliation tile can attribute the volume.
EXPIRED_STATUS = "expired_unworkable"

# Default age threshold. Picked so that "this week's" mail still counts as
# actionable while older untouched mail clears out of the New tile.
DEFAULT_MAX_AGE_DAYS = 7


def sweep_stale_new(db: Session, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> int:
    """Reclassify stale, never-touched ``new`` emails as ``expired_unworkable``.

    An email is swept when all of the following hold:
      1. ``Email.status == 'new'``
      2. No ``Pipeline`` row references the email (``Pipeline.email_id``).
      3. ``Email.received_at`` is older than ``now - max_age_days``.

    Returns the number of rows updated. Safe to call repeatedly; subsequent
    runs return 0 once the backlog is drained.
    """
    if max_age_days < 0:
        raise ValueError("max_age_days must be non-negative")

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    started_email_ids = (
        db.query(Pipeline.email_id)
        .filter(Pipeline.email_id.isnot(None))
        .distinct()
        .subquery()
    )

    stmt = (
        update(Email)
        .where(Email.status == "new")
        .where(Email.received_at < cutoff)
        .where(~Email.id.in_(started_email_ids))
        .values(status=EXPIRED_STATUS)
    )
    try:
        result = db.execute(stmt)
        count = int(result.rowcount or 0)
        if count > 0:
            db.commit()
            log.info(
                "email_sweeper: reclassified %s stale new emails to %s (max_age_days=%s)",
                count,
                EXPIRED_STATUS,
                max_age_days,
            )
        else:
            db.commit()
        return count
    except Exception:
        db.rollback()
        log.exception("email_sweeper: sweep failed")
        return 0
