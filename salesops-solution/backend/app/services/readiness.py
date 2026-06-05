"""System readiness gate.

Single source of truth for "is the platform allowed to process inbound mail
right now?". The pipeline ingress (REST, pool, scheduled polls) consults this
before doing any work; the frontend banner consults the same endpoint so the
operator sees the exact same blockers the backend is enforcing.

**Strict by default**: every required external dependency must be connected
and recently verified, with no silent local fallback. Toggle DEMO_MODE in
Settings → System to allow local fallbacks in a sandbox demo (with a red
badge displayed on every screen).

Required dependencies (each is a separate blocker if missing):

  1. Salesforce — active SalesforceConnection, last_tested_at recent, no last_error.
  2. SharePoint — active SharePointConnection, last_tested_at recent, no last_error.
  3. Mailbox    — at least one active EmailAccount, last_synced_at recent, not in error.

Soft warnings (do not halt the pipeline but are surfaced in the banner):
  - Jitterbit / DocuNet placeholder enabled but no endpoint configured.
  - LLM auth missing (only when configured explicitly).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import EmailAccount, IntegrationPlaceholder, SalesforceConnection, SharePointConnection


# How fresh a `last_tested_at` / `last_synced_at` must be for the connection
# to count as live. 30 minutes is generous — operators don't need to click
# "Test connection" every few seconds, but the system should notice when a
# token has expired and refuses for an hour.
RECENT_WINDOW = timedelta(minutes=int(os.environ.get("READINESS_RECENT_MIN", "30")))

# Setting key for the demo-mode override. When set to "1" in environment
# (or via a future Settings UI toggle), the gate switches to warning-only.
DEMO_MODE_ENV = "ENABLE_DEMO_FALLBACKS"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class Blocker:
    provider: str          # 'salesforce' | 'sharepoint' | 'mailbox' | 'llm'
    severity: str          # 'blocker' | 'warning'
    title: str             # short label for the banner
    detail: str            # one-line specific reason
    fix_url: str           # where the operator should go to fix it
    last_event_at: str | None = None  # ISO timestamp of the last test/sync
    last_error: str | None = None     # the last error text if any


@dataclass
class ReadinessReport:
    ok: bool
    blockers: list[Blocker] = field(default_factory=list)
    warnings: list[Blocker] = field(default_factory=list)
    demo_mode: bool = False
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "demo_mode": self.demo_mode,
            "checked_at": self.checked_at,
            "blockers": [b.__dict__ for b in self.blockers],
            "warnings": [b.__dict__ for b in self.warnings],
            "summary": {
                "blocker_count": len(self.blockers),
                "warning_count": len(self.warnings),
                "missing_providers": [b.provider for b in self.blockers],
            },
        }


def _check_salesforce(db: Session) -> Blocker | None:
    conn = (
        db.query(SalesforceConnection)
        .filter_by(is_active=True)
        .order_by(SalesforceConnection.id.desc())
        .first()
    )
    if conn is None:
        return Blocker(
            provider="salesforce",
            severity="blocker",
            title="Salesforce not connected",
            detail="No active Salesforce connection. The pipeline cannot resolve customers, write Cases, or read quotes.",
            fix_url="/settings/integrations",
        )
    last_tested = _coerce_aware(conn.last_tested_at)
    last_error_at = _coerce_aware(conn.last_error_at)
    if last_tested is None:
        return Blocker(
            provider="salesforce",
            severity="blocker",
            title="Salesforce never tested",
            detail="Active connection has not been verified. Test it from Settings → Integrations.",
            fix_url="/settings/integrations",
            last_error=conn.last_error,
        )
    if conn.last_error and last_error_at and last_error_at > (last_tested - timedelta(seconds=1)):
        return Blocker(
            provider="salesforce",
            severity="blocker",
            title="Salesforce connection erroring",
            detail=f"Last test failed: {(conn.last_error or '')[:240]}",
            fix_url="/settings/integrations",
            last_event_at=last_error_at.isoformat(),
            last_error=conn.last_error,
        )
    if last_tested < _now_utc() - RECENT_WINDOW:
        return Blocker(
            provider="salesforce",
            severity="blocker",
            title="Salesforce connection stale",
            detail=f"Last successful test was {int((_now_utc()-last_tested).total_seconds()//60)} min ago. Re-test from Settings → Integrations.",
            fix_url="/settings/integrations",
            last_event_at=last_tested.isoformat(),
        )
    return None


def _check_sharepoint(db: Session) -> Blocker | None:
    conn = (
        db.query(SharePointConnection)
        .filter_by(is_active=True)
        .order_by(SharePointConnection.id.desc())
        .first()
    )
    if conn is None:
        return Blocker(
            provider="sharepoint",
            severity="blocker",
            title="SharePoint not connected",
            detail="No active SharePoint site. SOA filing and customer-document retrieval cannot run.",
            fix_url="/settings/integrations",
        )
    last_tested = _coerce_aware(conn.last_tested_at)
    last_error_at = _coerce_aware(conn.last_error_at)
    if last_tested is None:
        return Blocker(
            provider="sharepoint",
            severity="blocker",
            title="SharePoint never tested",
            detail="Active connection has not been verified. Test it from Settings → Integrations.",
            fix_url="/settings/integrations",
            last_error=conn.last_error,
        )
    if conn.last_error and last_error_at and last_error_at > (last_tested - timedelta(seconds=1)):
        return Blocker(
            provider="sharepoint",
            severity="blocker",
            title="SharePoint connection erroring",
            detail=f"Last test failed: {(conn.last_error or '')[:240]}",
            fix_url="/settings/integrations",
            last_event_at=last_error_at.isoformat(),
            last_error=conn.last_error,
        )
    if last_tested < _now_utc() - RECENT_WINDOW:
        return Blocker(
            provider="sharepoint",
            severity="blocker",
            title="SharePoint connection stale",
            detail=f"Last successful test was {int((_now_utc()-last_tested).total_seconds()//60)} min ago. Re-test from Settings → Integrations.",
            fix_url="/settings/integrations",
            last_event_at=last_tested.isoformat(),
        )
    return None


def _check_mailbox(db: Session) -> Blocker | None:
    active = db.query(EmailAccount).filter_by(is_active=True).all()
    if not active:
        return Blocker(
            provider="mailbox",
            severity="blocker",
            title="No mailbox connected",
            detail="The pipeline has no inbound mail source. Connect a Gmail or Outlook mailbox.",
            fix_url="/settings/integrations",
        )
    # At least one mailbox must have synced recently.
    most_recent_sync = max(
        (_coerce_aware(a.last_synced_at) for a in active if a.last_synced_at),
        default=None,
    )
    if most_recent_sync is None:
        return Blocker(
            provider="mailbox",
            severity="blocker",
            title="No mailbox sync yet",
            detail="Mailbox is connected but has not synced any messages. Trigger a fetch from Settings.",
            fix_url="/settings/integrations",
        )
    # Mailbox sync window is more permissive (poll cadence is typically minutes).
    mailbox_window = timedelta(minutes=int(os.environ.get("READINESS_MAILBOX_MIN", "15")))
    if most_recent_sync < _now_utc() - mailbox_window:
        return Blocker(
            provider="mailbox",
            severity="blocker",
            title="Mailbox sync stale",
            detail=f"No mailbox has synced in {int((_now_utc()-most_recent_sync).total_seconds()//60)} min. The poller may have stopped.",
            fix_url="/settings/integrations",
            last_event_at=most_recent_sync.isoformat(),
        )
    # Any active mailbox in error state is a blocker.
    erroring = [a for a in active if a.last_error]
    if erroring:
        e = erroring[0]
        return Blocker(
            provider="mailbox",
            severity="blocker",
            title=f"Mailbox {e.email_address} erroring",
            detail=(e.last_error or "")[:240],
            fix_url="/settings/integrations",
            last_event_at=(_coerce_aware(e.last_error_at) or _now_utc()).isoformat(),
            last_error=e.last_error,
        )
    return None


def _check_placeholders(db: Session) -> list[Blocker]:
    """Soft warnings for placeholder integrations (Jitterbit / DocuNet)
    that are enabled but missing endpoint configuration."""
    warnings: list[Blocker] = []
    for row in db.query(IntegrationPlaceholder).filter_by(enabled=True).all():
        cfg = row.config or {}
        if not cfg.get("endpoint_url"):
            warnings.append(Blocker(
                provider=row.provider,
                severity="warning",
                title=f"{row.label} enabled but not configured",
                detail="Endpoint URL is empty. The integration will simulate handoff until you provide a URL.",
                fix_url="/settings/integrations",
            ))
    return warnings


def is_demo_mode() -> bool:
    """Demo mode lets the pipeline run with local fallbacks when no enterprise
    creds are available. Off by default. Only flipped via env var so it
    cannot be enabled accidentally from the UI."""
    return os.environ.get(DEMO_MODE_ENV, "0").strip() in {"1", "true", "yes", "on"}


def check_readiness(db: Session) -> ReadinessReport:
    """Compute the full readiness report and publish notifications.

    The notification side effect is the operator-facing surface: any blocker
    becomes a Notification row (de-duplicated by `kind`), and when a blocker
    clears the corresponding notification is auto-resolved. The notifications
    feed is then served via /api/notifications and rendered by the bell.

    Mailbox is currently a *warning* (not a blocker) because the demo is
    seeded with synthetic email rather than fetched from a live IMAP source.
    When mailbox ingestion is wired in for production this becomes a blocker
    again — flip MAILBOX_REQUIRED_FOR_READINESS in env.
    """
    import os as _os
    mailbox_required = _os.environ.get("MAILBOX_REQUIRED_FOR_READINESS", "0") in {"1", "true", "yes"}

    blockers: list[Blocker] = []
    warnings: list[Blocker] = []
    for check in (_check_salesforce, _check_sharepoint):
        b = check(db)
        if b is not None:
            blockers.append(b)

    mb = _check_mailbox(db)
    if mb is not None:
        if mailbox_required:
            blockers.append(mb)
        else:
            # Demote to warning — every blocker becomes the same row but with
            # warning severity. UI shows it in amber, pipelines still run.
            mb.severity = "warning"
            warnings.append(mb)

    warnings.extend(_check_placeholders(db))
    demo = is_demo_mode()
    ok = (len(blockers) == 0) or demo

    # Publish / resolve notifications for each known provider. We track every
    # provider on every call so that when a condition heals the publisher
    # automatically resolves its prior alert (no manual ack from the operator
    # required for the row to clear).
    try:
        _publish_readiness_notifications(db, blockers, warnings)
    except Exception:
        # Never let notification persistence break a readiness check.
        import logging
        logging.getLogger("readiness").exception("publish notifications failed")

    return ReadinessReport(
        ok=ok,
        blockers=blockers,
        warnings=warnings,
        demo_mode=demo,
        checked_at=_now_utc().isoformat(),
    )


# Stable `kind` keys keep the notification feed de-duplicated across polls.
# Connection providers share one kind per provider regardless of severity —
# `salesforce_disconnected` is the same row whether it's a blocker or a
# demoted warning, so when the condition heals (provider drops out of both
# blockers AND warnings) we resolve the single row cleanly.
_CONNECTION_KINDS = {
    "salesforce": "salesforce_disconnected",
    "sharepoint": "sharepoint_disconnected",
    "mailbox": "mailbox_disconnected",
    "llm": "llm_disconnected",
}

# Legacy kinds that earlier builds emitted for demoted-to-warning rows.
# We resolve any active rows under these kinds on every poll so historical
# notifications drain out automatically once the operator reconnects.
_LEGACY_CONNECTION_KINDS = {
    "placeholder_mailbox_unconfigured",
    "placeholder_salesforce_unconfigured",
    "placeholder_sharepoint_unconfigured",
}


def _publish_readiness_notifications(
    db: Session,
    blockers: list[Blocker],
    warnings: list[Blocker],
) -> None:
    """Publish or resolve a single notification per connection provider.

    Semantics: there is exactly ONE notification row per provider at a time
    (deduplicated by `kind`). Each readiness poll either upserts that row
    (when the provider is in blockers OR warnings) or resolves it (when the
    provider has healed). The notification's severity reflects the current
    state — critical for blockers, warning for demoted blockers.
    """
    from . import notifications as notif_svc

    # Build a unified map: provider -> (severity, the_check_result). Connection
    # providers use the same kind regardless of severity so the resolver below
    # can clear the row cleanly when the condition heals — even if it was
    # last published as critical and is now demoted, or vice versa.
    issues_by_provider: dict[str, tuple[str, Blocker]] = {}
    for b in blockers:
        if b.provider in _CONNECTION_KINDS:
            issues_by_provider[b.provider] = ("critical", b)
    for w in warnings:
        # Connection-shaped warnings (mailbox demoted) share the connection
        # kind. Non-connection warnings (placeholder integrations) keep their
        # own kind below.
        if w.provider in _CONNECTION_KINDS and w.provider not in issues_by_provider:
            issues_by_provider[w.provider] = ("warning", w)

    # Connection notifications: publish or resolve per provider.
    for provider, kind in _CONNECTION_KINDS.items():
        if provider in issues_by_provider:
            severity, issue = issues_by_provider[provider]
            notif_svc.publish(
                db,
                kind=kind,
                category="connection",
                severity=severity,
                title=issue.title,
                body=issue.detail,
                action_url=issue.fix_url,
                action_label="Connect now" if severity == "critical" else "Configure",
                meta={
                    "provider": provider,
                    "last_event_at": issue.last_event_at,
                    "last_error": issue.last_error,
                },
            )
        else:
            # Provider has no issue — resolve any active row.
            notif_svc.resolve(db, kind=kind)

    # Drain any legacy rows that earlier builds emitted under the wrong kind
    # (e.g. placeholder_mailbox_unconfigured). The current schema uses the
    # connection kind above; these are leftovers we want to clear so the
    # operator's bell goes back to clean.
    for legacy_kind in _LEGACY_CONNECTION_KINDS:
        notif_svc.resolve(db, kind=legacy_kind)

    # Placeholder integrations (Jitterbit, DocuNet) — these are NOT connection
    # providers, they have their own kinds keyed by provider name.
    placeholder_providers_seen: set[str] = set()
    for w in warnings:
        if w.provider in _CONNECTION_KINDS:
            continue  # already handled above
        wkind = f"placeholder_{w.provider}_unconfigured"
        placeholder_providers_seen.add(w.provider)
        notif_svc.publish(
            db,
            kind=wkind,
            category="connection",
            severity="warning",
            title=w.title,
            body=w.detail,
            action_url=w.fix_url,
            action_label="Configure",
            meta={"provider": w.provider},
        )
    # Resolve placeholder warnings whose provider is no longer in the warning
    # list — operator either configured the integration or disabled it.
    try:
        from ..models import IntegrationPlaceholder
        for row in db.query(IntegrationPlaceholder).all():
            if row.provider in placeholder_providers_seen:
                continue
            notif_svc.resolve(db, kind=f"placeholder_{row.provider}_unconfigured")
    except Exception:
        pass


def require_ready(db: Session) -> ReadinessReport:
    """Raise a structured exception when readiness is not met (and demo mode
    is off). Callers catch ReadinessBlocked at the pipeline ingress to return
    HTTP 412 with the payload."""
    report = check_readiness(db)
    if not report.ok:
        raise ReadinessBlocked(report)
    return report


class ReadinessBlocked(Exception):
    """Raised by `require_ready` when one or more required deps are missing
    and demo mode is off. The HTTP layer translates this to 412 + payload."""

    def __init__(self, report: ReadinessReport):
        self.report = report
        super().__init__(
            f"system not ready: {len(report.blockers)} blocker(s) — "
            + ", ".join(b.provider for b in report.blockers)
        )
