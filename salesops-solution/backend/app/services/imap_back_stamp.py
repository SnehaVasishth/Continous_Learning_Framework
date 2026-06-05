"""IMAP back-stamping — mirrors the Outlook Graph `POST /messages/{id}/move`
flow used in Keysight's POC, but over IMAP COPY+EXPUNGE so it works against
any IMAP-connected mailbox (Gmail, Outlook IMAP, generic).

The classifier deposits each processed email in the per-category folder the
user configured for the connected mailbox (see `EmailAccount.category_folder_map`).
On Gmail, "folder" maps onto a label — IMAP COPY against Gmail's IMAP gateway
materialises the COPY as a label add, which is the right shape anyway.
"""
from __future__ import annotations

import imaplib
import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import Email, EmailAccount, Pipeline
from .imap_client import _connect
from .secrets import decrypt

log = logging.getLogger(__name__)

# Mirror of Keysight's 9-class taxonomy (see RESEARCH_BRIEF.md). Maps the
# 13 internal intents the orchestrator emits to the smaller folder categories.
_INTENT_TO_CATEGORY: dict[str, str] = {
    "po_intake": "SALES_PO",
    "quote_to_order": "SALES_PO",
    "trade_change_order": "SALES_PO",
    "hold_release": "SALES_PO",
    "ssd_change_request": "OTHERS",
    "delivery_change": "OTHERS",
    "service_order": "ISC_WO_RTK",
    "wo_update_request": "ISC_WO_RTK",
    "wo_status_inquiry": "ISC_WO_RTK",
    "service_contract_request": "ISC_WO_RTK",
    "general_inquiry": "OTHERS",
    "out_of_scope": "AUTO_REPLY",
    "spam": "OTHERS",
    # === v1.1 TASK-1 START === 5 first-class intents per prior-POC 9-class taxonomy
    "kso": "KSO",
    "collections": "COLLECTIONS",
    "portal_admin": "PORTAL_ADMIN",
    "brazil_tax": "BRAZIL_TAX",
    "undeliverable": "UNDELIVERABLE",
    # === v1.1 TASK-1 END ===
}

DEFAULT_FOLDER_MAP: dict[str, str] = {
    "SALES_PO": "ZBrain/Sales POs",
    "ISC_WO_RTK": "ZBrain/Service WOs",
    "KSO": "ZBrain/Government",
    "OTHERS": "ZBrain/Others",
    "AUTO_REPLY": "ZBrain/Auto-Replies",
    "UNDELIVERABLE": "ZBrain/Undeliverable",
    "COLLECTIONS": "ZBrain/Collections",
    "PORTAL_ADMIN": "ZBrain/Portal Admin",
    "BRAZIL_TAX": "ZBrain/Brazil Tax",
}


def _is_gmail(account: EmailAccount) -> bool:
    host = (account.imap_host or "").lower()
    return "gmail" in host or account.provider == "gmail"


def _ensure_folder(conn: imaplib.IMAP4_SSL, folder: str) -> None:
    """Best-effort CREATE — most servers return NO if it already exists; ignore."""
    try:
        typ, _ = conn.create(f'"{folder}"')
        if typ == "OK":
            try:
                conn.subscribe(f'"{folder}"')
            except Exception:
                pass
    except Exception:
        pass


def _find_uid_by_message_id(conn: imaplib.IMAP4_SSL, message_id: str) -> str | None:
    mid = message_id.strip()
    if not mid:
        return None
    typ, data = conn.uid("SEARCH", None, "HEADER", "Message-ID", mid)
    if typ != "OK" or not data or not data[0]:
        return None
    parts = data[0].split()
    if not parts:
        return None
    return parts[-1].decode() if isinstance(parts[-1], bytes) else str(parts[-1])


def move_message_to_folder(
    account: EmailAccount,
    message_id: str,
    target_folder: str,
) -> dict[str, Any]:
    """Locate the message by RFC822 Message-ID, COPY into target_folder
    (creating it first if needed), then mark the original deleted and EXPUNGE.
    """
    if not message_id:
        return {"ok": False, "target_folder": target_folder, "error": "missing message_id"}
    if not target_folder:
        return {"ok": False, "target_folder": target_folder, "error": "missing target_folder"}

    # Hard rule (config.DEMO_TRANSMIT_LOCKED) — defense in depth.
    from ..config import DEMO_TRANSMIT_LOCKED
    if DEMO_TRANSMIT_LOCKED:
        return {
            "ok": False,
            "simulated": True,
            "target_folder": target_folder,
            "error": "blocked by config.DEMO_TRANSMIT_LOCKED — mailbox unchanged",
        }

    try:
        password = decrypt(account.password_enc)
    except Exception as e:
        return {"ok": False, "target_folder": target_folder, "error": f"decrypt failed: {e}"}

    conn: imaplib.IMAP4_SSL | None = None
    try:
        conn = _connect(account.imap_host, account.imap_port, account.username, password)
        typ, _ = conn.select(account.folder, readonly=False)
        if typ != "OK":
            return {"ok": False, "target_folder": target_folder, "error": f"select {account.folder} failed"}

        uid = _find_uid_by_message_id(conn, message_id)
        if not uid:
            return {
                "ok": False,
                "target_folder": target_folder,
                "error": f"message-id not found: {message_id}",
            }

        _ensure_folder(conn, target_folder)

        typ, copy_data = conn.uid("COPY", uid, f'"{target_folder}"')
        if typ != "OK":
            return {
                "ok": False,
                "target_folder": target_folder,
                "error": f"COPY failed: {copy_data!r}",
            }

        typ, _ = conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        if typ != "OK":
            return {
                "ok": False,
                "target_folder": target_folder,
                "error": "STORE \\Deleted failed",
            }
        try:
            conn.expunge()
        except Exception as e:
            log.warning("expunge failed (non-fatal): %s", e)

        return {"ok": True, "target_folder": target_folder, "error": None}
    except imaplib.IMAP4.error as e:
        return {"ok": False, "target_folder": target_folder, "error": f"imap error: {e}"}
    except Exception as e:
        return {"ok": False, "target_folder": target_folder, "error": f"{type(e).__name__}: {e}"}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn.logout()
            except Exception:
                pass


def prepend_subject_tag(
    account: EmailAccount,
    message_id: str,
    tag: str,
) -> dict[str, Any]:
    """Stamp a tag onto the original message.

    IMAP can't edit subject lines. On Gmail we exploit X-GM-LABELS to apply
    the tag as a label (the closest analogue to Outlook's CCC# subject prefix).
    On non-Gmail providers we log+skip — this is a best-effort enhancement,
    never a hard requirement.
    """
    if not message_id or not tag:
        return {"ok": False, "tag": tag, "error": "missing message_id or tag"}

    # Hard rule (config.DEMO_TRANSMIT_LOCKED) — defense in depth.
    from ..config import DEMO_TRANSMIT_LOCKED
    if DEMO_TRANSMIT_LOCKED:
        return {
            "ok": False,
            "simulated": True,
            "tag": tag,
            "error": "blocked by config.DEMO_TRANSMIT_LOCKED — mailbox unchanged",
        }

    if not _is_gmail(account):
        log.info(
            "subject prepend skipped — IMAP doesn't support edit; tag would have been: %s",
            tag,
        )
        return {"ok": False, "tag": tag, "error": "non-gmail: subject prepend skipped"}

    try:
        password = decrypt(account.password_enc)
    except Exception as e:
        return {"ok": False, "tag": tag, "error": f"decrypt failed: {e}"}

    conn: imaplib.IMAP4_SSL | None = None
    try:
        conn = _connect(account.imap_host, account.imap_port, account.username, password)
        typ, _ = conn.select(account.folder, readonly=False)
        if typ != "OK":
            return {"ok": False, "tag": tag, "error": f"select {account.folder} failed"}

        uid = _find_uid_by_message_id(conn, message_id)
        if not uid:
            return {"ok": False, "tag": tag, "error": f"message-id not found: {message_id}"}

        label = tag.replace('"', '')
        typ, data = conn.uid("STORE", uid, "+X-GM-LABELS", f'"{label}"')
        if typ != "OK":
            return {"ok": False, "tag": tag, "error": f"X-GM-LABELS failed: {data!r}"}
        return {"ok": True, "tag": tag, "error": None}
    except imaplib.IMAP4.error as e:
        return {"ok": False, "tag": tag, "error": f"imap error: {e}"}
    except Exception as e:
        return {"ok": False, "tag": tag, "error": f"{type(e).__name__}: {e}"}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn.logout()
            except Exception:
                pass


def back_stamp_pipeline_email(db: Session, pipeline_id: int) -> dict[str, Any]:
    """Top-level helper: resolve pipeline → email → account, look up the
    category folder for the pipeline's intent, and move the original message
    into that folder. Designed to be safe to call after a pipeline has reached
    any terminal state — it never raises, only returns a structured result.
    """
    pipe = db.get(Pipeline, pipeline_id)
    if not pipe:
        return {"ok": False, "moved_to": None, "category": None, "error": "pipeline not found"}

    email_row = db.get(Email, pipe.email_id) if pipe.email_id else None
    if not email_row:
        return {"ok": False, "moved_to": None, "category": None, "error": "email not found"}

    if not email_row.account_id:
        return {
            "ok": False,
            "moved_to": None,
            "category": None,
            "error": "email has no account_id (likely seeded synthetic)",
        }

    account = db.get(EmailAccount, email_row.account_id)
    if not account:
        return {"ok": False, "moved_to": None, "category": None, "error": "account not found"}

    if not email_row.message_id:
        return {
            "ok": False,
            "moved_to": None,
            "category": None,
            "error": "email has no Message-Id header",
        }

    intent = (pipe.intent or "").strip()
    category = _INTENT_TO_CATEGORY.get(intent, "OTHERS")

    folder_map: dict[str, str] = dict(account.category_folder_map or {})
    target_folder = folder_map.get(category) or DEFAULT_FOLDER_MAP.get(category)
    if not target_folder:
        return {
            "ok": False,
            "moved_to": None,
            "category": category,
            "error": f"no folder mapping for category {category}",
        }

    # Hard rule (config.DEMO_TRANSMIT_LOCKED) — no mailbox mutation.
    # Return a simulated result so the orchestrator's trace event still shows
    # "would have moved to <folder>". Nothing touches the IMAP server.
    from ..config import DEMO_TRANSMIT_LOCKED
    if DEMO_TRANSMIT_LOCKED:
        return {
            "ok": True,
            "simulated": True,
            "moved_to": None,
            "would_move_to": target_folder,
            "category": category,
            "error": None,
            "note": "blocked by config.DEMO_TRANSMIT_LOCKED — folder move simulated, mailbox unchanged",
        }

    res = move_message_to_folder(account, email_row.message_id, target_folder)
    return {
        "ok": res.get("ok", False),
        "moved_to": target_folder if res.get("ok") else None,
        "category": category,
        "error": res.get("error"),
    }
