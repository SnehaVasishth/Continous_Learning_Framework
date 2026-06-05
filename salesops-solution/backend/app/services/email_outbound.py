"""SMTP send for HITL-approved replies.

Reuses the IMAP app password stored on each EmailAccount (Gmail / Outlook
app passwords work for SMTP too). Builds a proper RFC822 message with
In-Reply-To + References so replies thread in the customer's mailbox when
the originating Email row carries a Message-Id.

Account resolution order (when caller doesn't pin one):
1. The EmailAccount that imported the originating Email (`Email.account_id`).
2. The single active EmailAccount, if exactly one is configured.
3. None — caller surfaces "no outbound mailbox configured" to the UI.

Cloud notes: outbound TCP 587 (STARTTLS) is the only network requirement.
EMAIL_SECRET_KEY must be the same key that encrypted the stored password,
otherwise decrypt() raises and the send fails before connecting.
"""
from __future__ import annotations

import logging
import mimetypes
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from ..config import OUTPUTS, UPLOADS
from ..models import Email, EmailAccount
from .secrets import decrypt

log = logging.getLogger("email_outbound")

PROVIDER_SMTP: dict[str, dict] = {
    "gmail": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "use_starttls": True},
    "outlook": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "use_starttls": True},
    "imap": {"smtp_host": "", "smtp_port": 587, "use_starttls": True},
}


class OutboundError(RuntimeError):
    pass


def resolve_send_account(
    db: Session, *, originating_email: Email | None = None, prefer_account_id: int | None = None
) -> EmailAccount:
    if prefer_account_id:
        acc = db.get(EmailAccount, prefer_account_id)
        if acc and acc.is_active:
            return acc
    if originating_email and originating_email.account_id:
        acc = db.get(EmailAccount, originating_email.account_id)
        if acc and acc.is_active:
            return acc
    actives = db.query(EmailAccount).filter_by(is_active=True).all()
    if len(actives) == 1:
        return actives[0]
    if not actives:
        raise OutboundError("no active email account configured — connect a mailbox in Settings → Connections")
    raise OutboundError(
        "multiple mailboxes configured but originating email has no account_id; pin one with prefer_account_id"
    )


def _smtp_settings(account: EmailAccount) -> tuple[str, int, bool]:
    preset = PROVIDER_SMTP.get(account.provider) or PROVIDER_SMTP["imap"]
    host = (preset["smtp_host"] or "").strip()
    if not host:
        host = (account.imap_host or "").strip().replace("imap.", "smtp.", 1)
    if not host:
        raise OutboundError(f"no SMTP host for provider={account.provider!r}")
    return host, int(preset["smtp_port"]), bool(preset["use_starttls"])


def _to_address_only(addr_or_pair: str) -> str:
    _, email_addr = parseaddr(addr_or_pair or "")
    return (email_addr or addr_or_pair or "").strip()


def _split_recipients(value: str | None) -> list[str]:
    if not value:
        return []
    parts = getaddresses([value])
    return [a for _, a in parts if a]


def _resolve_attachment(name: str) -> Path | None:
    for base in (OUTPUTS, UPLOADS):
        candidate = Path(base) / name
        if candidate.is_file():
            return candidate
    return None


def _ensure_re_subject(subject: str | None) -> str:
    s = (subject or "").strip()
    if not s:
        return "Re: (no subject)"
    if s.lower().startswith("re:"):
        return s
    return f"Re: {s}"


def build_reply_message(
    *,
    sender_account: EmailAccount,
    to_address: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references: str | None = None,
    cc: list[str] | None = None,
    attachments: Iterable[str] = (),
    sender_label: str | None = None,
) -> tuple[EmailMessage, str]:
    msg = EmailMessage()
    domain = sender_account.email_address.split("@", 1)[-1] or "localhost"
    msg_id = make_msgid(domain=domain)
    msg["Message-Id"] = msg_id
    msg["Date"] = formatdate(localtime=True)
    msg["From"] = formataddr((sender_label or sender_account.label or "ZBrain Sales Operations", sender_account.email_address))
    msg["To"] = to_address
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = _ensure_re_subject(subject)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        ref_chain = (references or "").strip()
        if ref_chain and in_reply_to not in ref_chain:
            ref_chain = f"{ref_chain} {in_reply_to}".strip()
        elif not ref_chain:
            ref_chain = in_reply_to
        if ref_chain:
            msg["References"] = ref_chain
    msg["X-ZBrain-Trace"] = uuid.uuid4().hex
    msg.set_content(body or "")
    for name in attachments or ():
        if not name:
            continue
        path = _resolve_attachment(name)
        if not path:
            log.warning("attachment not found, skipping: %s", name)
            continue
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return msg, msg_id


def _send_smtp(account: EmailAccount, msg: EmailMessage, recipients: list[str]) -> None:
    host, port, use_starttls = _smtp_settings(account)
    password = decrypt(account.password_enc)
    username = account.username or account.email_address
    context = ssl.create_default_context()
    if use_starttls:
        with smtplib.SMTP(host, port, timeout=25) as s:
            s.ehlo()
            s.starttls(context=context)
            s.ehlo()
            s.login(username, password)
            s.send_message(msg, from_addr=account.email_address, to_addrs=recipients)
    else:
        with smtplib.SMTP_SSL(host, port, timeout=25, context=context) as s:
            s.login(username, password)
            s.send_message(msg, from_addr=account.email_address, to_addrs=recipients)


def send_reply(
    db: Session,
    *,
    originating_email: Email | None,
    to_address: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references: str | None = None,
    cc: list[str] | None = None,
    attachments: Iterable[str] = (),
    prefer_account_id: int | None = None,
    sender_label: str | None = None,
) -> dict:
    """Send a reply. Returns a dict with delivery result; never raises."""
    out: dict = {
        "delivery_status": "failed",
        "provider_message_id": None,
        "error": None,
        "sent_via_account_id": None,
        "smtp_host": None,
    }
    # Hard rule (config.DEMO_TRANSMIT_LOCKED) — no outbound mail of any kind.
    # The env-var kill switch is a secondary gate kept for legacy deploys; the
    # constant is the source of truth. CommunicationLog still records the draft
    # so the UI can render "this is what would have gone out".
    from ..config import DEMO_TRANSMIT_LOCKED
    import os as _os
    if DEMO_TRANSMIT_LOCKED:
        out["delivery_status"] = "blocked_by_demo_lock"
        out["error"] = "outbound transmission disabled (config.DEMO_TRANSMIT_LOCKED=True)"
        log.warning(
            "outbound send blocked by DEMO_TRANSMIT_LOCKED → to=%s subj=%s",
            to_address, subject[:60],
        )
        return out
    if (_os.environ.get("OUTBOUND_EMAIL_ENABLED", "1").strip() or "1") == "0":
        out["delivery_status"] = "blocked_by_kill_switch"
        out["error"] = "outbound disabled (OUTBOUND_EMAIL_ENABLED=0)"
        log.warning("outbound send blocked by OUTBOUND_EMAIL_ENABLED=0 → to=%s subj=%s", to_address, subject[:60])
        return out
    try:
        account = resolve_send_account(
            db, originating_email=originating_email, prefer_account_id=prefer_account_id
        )
    except OutboundError as e:
        out["error"] = str(e)
        return out

    out["sent_via_account_id"] = account.id
    try:
        out["smtp_host"], _, _ = _smtp_settings(account)
    except OutboundError as e:
        out["error"] = str(e)
        return out

    primary_to = _to_address_only(to_address)
    if not primary_to:
        out["error"] = "no recipient address"
        return out

    if originating_email is not None:
        in_reply_to = in_reply_to or originating_email.message_id
        if not references:
            ref_chain = (originating_email.email_references or "").strip()
            if originating_email.message_id and originating_email.message_id not in ref_chain:
                ref_chain = (f"{ref_chain} {originating_email.message_id}").strip()
            references = ref_chain or None

    cc_addrs = [_to_address_only(c) for c in (cc or []) if _to_address_only(c)]
    recipients = [primary_to] + cc_addrs

    try:
        msg, provider_msg_id = build_reply_message(
            sender_account=account,
            to_address=primary_to,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            references=references,
            cc=cc_addrs or None,
            attachments=attachments,
            sender_label=sender_label,
        )
    except Exception as e:
        out["error"] = f"build failed: {type(e).__name__}: {e}"
        return out

    try:
        _send_smtp(account, msg, recipients)
    except smtplib.SMTPAuthenticationError as e:
        out["error"] = f"SMTP auth failed: {e.smtp_code} {e.smtp_error.decode(errors='replace') if isinstance(e.smtp_error, bytes) else e.smtp_error}"
        log.warning("smtp auth failed for %s: %s", account.email_address, out["error"])
        return out
    except smtplib.SMTPException as e:
        out["error"] = f"SMTP error: {type(e).__name__}: {e}"[:400]
        log.warning("smtp send failed for %s: %s", account.email_address, out["error"])
        return out
    except (OSError, ssl.SSLError) as e:
        out["error"] = f"SMTP transport error: {type(e).__name__}: {e}"[:400]
        return out
    except ValueError as e:
        out["error"] = f"decrypt failed: {e}"
        return out

    out["delivery_status"] = "sent"
    out["provider_message_id"] = provider_msg_id
    return out


def test_smtp(account: EmailAccount) -> tuple[bool, str]:
    """Login + EHLO without sending anything. For the connection-test UI."""
    try:
        host, port, use_starttls = _smtp_settings(account)
        password = decrypt(account.password_enc)
        username = account.username or account.email_address
        context = ssl.create_default_context()
        if use_starttls:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                s.starttls(context=context)
                s.ehlo()
                s.login(username, password)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as s:
                s.login(username, password)
        return True, f"ok ({host}:{port})"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
