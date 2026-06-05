"""IMAP fetcher.

Uses stdlib `imaplib` in a thread executor (called via `asyncio.to_thread` from
the poller). Pulls only UIDs greater than `last_uid_seen` so re-runs are cheap
and don't re-import old mail.

Provider presets keep the demo "add account" UX one-click for Gmail / Outlook;
the underlying transport is plain IMAP-over-TLS, identical for both.
"""
from __future__ import annotations

import email
import imaplib
import re
import uuid
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import UPLOADS
from ..models import Email, EmailAccount
from .secrets import decrypt

PROVIDER_PRESETS: dict[str, dict] = {
    "gmail": {"imap_host": "imap.gmail.com", "imap_port": 993, "folder": "INBOX"},
    "outlook": {"imap_host": "outlook.office365.com", "imap_port": 993, "folder": "INBOX"},
    "imap": {"imap_host": "", "imap_port": 993, "folder": "INBOX"},
}


def _connect(host: str, port: int, username: str, password: str) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(host, port, timeout=20)
    conn.login(username, password)
    return conn


def test_connection(host: str, port: int, username: str, password: str, folder: str = "INBOX") -> tuple[bool, str]:
    try:
        conn = _connect(host, port, username, password)
    except imaplib.IMAP4.error as e:
        return False, f"login failed: {e}"
    except Exception as e:
        return False, f"connect failed: {type(e).__name__}: {e}"
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return False, f"folder select failed: {folder}"
        return True, "ok"
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _decode(raw) -> str:
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _pick_body(msg: Message) -> tuple[str, list[Message]]:
    """Returns (text_body, attachment_parts). Prefers text/plain over text/html."""
    text_plain: str | None = None
    text_html: str | None = None
    attachments: list[Message] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp or part.get_filename():
                attachments.append(part)
                continue
            if ctype == "text/plain" and text_plain is None:
                try:
                    text_plain = part.get_content()
                except Exception:
                    text_plain = part.get_payload(decode=True).decode(errors="replace") if part.get_payload(decode=True) else ""
            elif ctype == "text/html" and text_html is None:
                try:
                    text_html = part.get_content()
                except Exception:
                    text_html = part.get_payload(decode=True).decode(errors="replace") if part.get_payload(decode=True) else ""
    else:
        try:
            text_plain = msg.get_content()
        except Exception:
            payload = msg.get_payload(decode=True)
            text_plain = payload.decode(errors="replace") if payload else ""
    body = text_plain or _strip_html(text_html or "")
    return (body or "").strip(), attachments


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return _HTML_TAG_RE.sub("", s).strip() if s else ""


def _safe_filename(name: str) -> str:
    name = (name or "attachment.bin").strip().replace("\\", "_").replace("/", "_")
    return re.sub(r"[^A-Za-z0-9._\-]", "_", name)[:120] or "attachment.bin"


def _detect_language(text: str) -> str:
    sample = (text or "")[:400]
    if re.search(r"[぀-ヿ一-鿿]", sample):
        return "ja"
    if re.search(r"[áéíóúñ¿¡]|\b(hola|gracias|por favor|saludos)\b", sample, re.IGNORECASE):
        return "es"
    return "en"


def _save_attachments(parts: list[Message]) -> tuple[list[dict], str]:
    """Save each attachment to UPLOADS. Returns (saved_records, body_appendix).

    === v1.1 TASK-8 === When a `.msg` (Outlook embedded message) attachment
    is found, unroll its inner subject/body/from + nested attachments and
    append a "--- forwarded message (.msg) ---" block to the parent email's
    body. Inner attachments are saved separately with `msg_inner` source tag.
    """
    saved: list[dict] = []
    msg_appendix_parts: list[str] = []
    for part in parts:
        try:
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            original = _decode(part.get_filename()) or "attachment.bin"
            ctype = (part.get_content_type() or "").lower()
            is_msg = ctype == "application/vnd.ms-outlook" or original.lower().endswith(".msg")

            if is_msg:
                appendix, inner_attachments = _unroll_msg_attachment(payload, original)
                if appendix:
                    msg_appendix_parts.append(appendix)
                saved.extend(inner_attachments)
                # Still save the .msg blob itself for audit
                stamped = f"imap_{uuid.uuid4().hex[:8]}_{_safe_filename(original)}"
                target = Path(UPLOADS) / stamped
                target.write_bytes(payload)
                saved.append({
                    "name": stamped,
                    "original_name": original,
                    "size": len(payload),
                    "content_type": ctype or "application/vnd.ms-outlook",
                    "source": "msg_outer",
                })
                continue

            stamped = f"imap_{uuid.uuid4().hex[:8]}_{_safe_filename(original)}"
            target = Path(UPLOADS) / stamped
            target.write_bytes(payload)
            saved.append({"name": stamped, "original_name": original, "size": len(payload), "content_type": part.get_content_type()})
        except Exception:
            continue
    body_appendix = "\n\n".join(msg_appendix_parts)
    return saved, body_appendix


def _unroll_msg_attachment(payload: bytes, original_name: str) -> tuple[str, list[dict]]:
    """Parse a .msg attachment with extract-msg. Returns (body_appendix, inner_attachments).

    Returns ('', []) on any error (extract-msg missing, malformed .msg, etc.) —
    never raises. Caller can fall back to treating .msg as opaque blob.
    """
    try:
        import extract_msg as _extract_msg
    except ImportError:
        return "", []
    tmp_path = Path(UPLOADS) / f"_tmp_msg_{uuid.uuid4().hex}.msg"
    inner_records: list[dict] = []
    try:
        tmp_path.write_bytes(payload)
        msg = _extract_msg.openMsg(str(tmp_path))
        try:
            inner_subject = (getattr(msg, "subject", "") or "")[:300]
            inner_from = (getattr(msg, "sender", "") or "")[:300]
            inner_date = str(getattr(msg, "date", "") or "")[:50]
            inner_body = (getattr(msg, "body", "") or "")[:6000]
            appendix = (
                f"\n\n--- forwarded message (.msg: {original_name}) ---\n"
                f"From: {inner_from}\n"
                f"Subject: {inner_subject}\n"
                f"Date: {inner_date}\n\n"
                f"{inner_body}\n"
            )
            for att in (getattr(msg, "attachments", []) or []):
                try:
                    inner_data = getattr(att, "data", None)
                    if not inner_data:
                        continue
                    inner_name = (
                        getattr(att, "longFilename", None)
                        or getattr(att, "shortFilename", None)
                        or "msg_inner.bin"
                    )
                    stamped = f"msg_{uuid.uuid4().hex[:8]}_{_safe_filename(inner_name)}"
                    target = Path(UPLOADS) / stamped
                    target.write_bytes(inner_data)
                    inner_records.append({
                        "name": stamped,
                        "original_name": inner_name,
                        "size": len(inner_data),
                        "content_type": "application/octet-stream",
                        "source": "msg_inner",
                    })
                except Exception:
                    continue
            return appendix, inner_records
        finally:
            try:
                msg.close()
            except Exception:
                pass
    except Exception:
        return "", inner_records
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def fetch_new(account: EmailAccount, db: Session, *, max_messages: int = 50) -> list[int]:
    """Fetches messages with UID > account.last_uid_seen. Returns list of new Email IDs."""
    password = decrypt(account.password_enc)
    conn = _connect(account.imap_host, account.imap_port, account.username, password)
    new_email_ids: list[int] = []
    try:
        typ, _ = conn.select(account.folder, readonly=False)
        if typ != "OK":
            raise RuntimeError(f"folder select failed: {account.folder}")

        last_uid = int(account.last_uid_seen or 0)
        search_range = f"{last_uid + 1}:*"
        typ, data = conn.uid("SEARCH", None, "UID", search_range)
        if typ != "OK":
            raise RuntimeError("UID SEARCH failed")
        uids = [int(x) for x in (data[0] or b"").split() if int(x) > last_uid]
        uids.sort()
        if max_messages:
            uids = uids[:max_messages]

        for uid in uids:
            typ, msg_data = conn.uid("FETCH", str(uid), "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_bytes = msg_data[0][1]
            msg = email.message_from_bytes(raw_bytes)

            subject = _decode(msg.get("Subject")) or "(no subject)"
            from_addr = _decode(msg.get("From")) or account.email_address
            message_id = (msg.get("Message-Id") or msg.get("Message-ID") or "").strip() or None
            in_reply_to = (msg.get("In-Reply-To") or "").strip() or None
            references = (msg.get("References") or "").strip() or None
            try:
                received = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else datetime.now(timezone.utc)
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
            except Exception:
                received = datetime.now(timezone.utc)

            body, attach_parts = _pick_body(msg)
            # === v1.1 TASK-8 === unroll .msg attachments into the body so
            # downstream classification sees the forwarded content.
            attachments, msg_appendix = _save_attachments(attach_parts)
            if msg_appendix:
                body = (body or "") + msg_appendix
            language = _detect_language(f"{subject}\n{body}")

            row = Email(
                received_at=received,
                from_address=from_addr,
                subject=subject,
                body=body,
                language_hint=language,
                attachments=attachments,
                status="new",
                account_id=account.id,
                message_id=message_id,
                in_reply_to=in_reply_to,
                email_references=references,
            )
            db.add(row)
            db.flush()
            new_email_ids.append(row.id)

            account.last_uid_seen = max(int(account.last_uid_seen or 0), uid)

        account.last_synced_at = datetime.now(timezone.utc)
        account.last_error = None
        account.last_error_at = None
        account.messages_imported = int(account.messages_imported or 0) + len(new_email_ids)
        db.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass
    return new_email_ids
