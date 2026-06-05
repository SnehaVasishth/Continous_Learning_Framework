"""Operator-managed LLM provider credentials.

Today only OpenAI is wired. Pattern is intentionally identical to
salesforce.py / sharepoint.py: encrypted secret in the DB, a getter that
returns the live secret (DB first, env fall-back), a connect helper that
upserts the row, and a test helper that does a real round-trip to verify
the key works before we save it.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import LLMProviderConfig
from .secrets import decrypt, encrypt


PROVIDER_OPENAI = "openai"
_DEFAULT_OPENAI_MODEL = "gpt-5.2"


# --------------------------------------------------------------------------
# DB row helpers
# --------------------------------------------------------------------------


def get_config(db: Session, provider: str = PROVIDER_OPENAI) -> LLMProviderConfig | None:
    return db.query(LLMProviderConfig).filter(LLMProviderConfig.provider == provider).first()


def resolve_openai_api_key(db: Session | None = None) -> str:
    """Live OpenAI key. Database first (operator-configured), env var second
    (developer fallback). Returns empty string if neither has one."""
    if db is not None:
        try:
            row = get_config(db, PROVIDER_OPENAI)
            if row and row.is_active and row.api_key_enc:
                try:
                    return decrypt(row.api_key_enc) or ""
                except Exception:
                    pass
        except Exception:
            pass
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def resolve_openai_model(db: Session | None = None) -> str:
    if db is not None:
        row = get_config(db, PROVIDER_OPENAI)
        if row and (row.model or "").strip():
            return row.model.strip()
    return (os.environ.get("OPENAI_MODEL") or _DEFAULT_OPENAI_MODEL).strip()


# --------------------------------------------------------------------------
# Serializer for the routes
# --------------------------------------------------------------------------


def _mask_key(api_key: str) -> str:
    """Show enough of the key for the operator to recognise it without
    leaking the secret. "sk-proj-abc12345...xyz9" pattern."""
    if not api_key:
        return ""
    s = api_key.strip()
    if len(s) <= 12:
        return s[:4] + "..." + s[-2:]
    return s[:10] + "..." + s[-4:]


def serialize(row: LLMProviderConfig | None, *, env_fallback_active: bool) -> dict[str, Any]:
    if row is None:
        return {
            "connected": env_fallback_active,
            "source": "env" if env_fallback_active else "none",
            "provider": PROVIDER_OPENAI,
            "model": (os.environ.get("OPENAI_MODEL") or _DEFAULT_OPENAI_MODEL).strip(),
            "api_key_masked": _mask_key(os.environ.get("OPENAI_API_KEY") or "") if env_fallback_active else "",
            "last_tested_at": None,
            "last_error": None,
        }
    api_key = ""
    if row.api_key_enc:
        try:
            api_key = decrypt(row.api_key_enc) or ""
        except Exception:
            api_key = ""
    return {
        "connected": bool(row.is_active and api_key),
        "source": "db",
        "provider": row.provider,
        "model": row.model or _DEFAULT_OPENAI_MODEL,
        "api_key_masked": _mask_key(api_key),
        "is_active": bool(row.is_active),
        "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
        "last_error": row.last_error,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# --------------------------------------------------------------------------
# Connect / disconnect / test
# --------------------------------------------------------------------------


def test_api_key(api_key: str, model: str | None = None) -> dict[str, Any]:
    """Real round-trip against the OpenAI Models endpoint to confirm the key
    works. Returns a small dict the caller can show on the test button."""
    if not (api_key or "").strip():
        return {"ok": False, "message": "API key is empty"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key.strip())
        # Models list is the cheapest call and works on every plan.
        result = client.models.list()
        ids = [m.id for m in result.data[:5]]
        return {"ok": True, "message": f"Authenticated. {len(result.data)} models available.", "model_preview": ids}
    except Exception as ex:
        return {"ok": False, "message": f"{type(ex).__name__}: {str(ex)[:240]}"}


def upsert_openai_config(
    db: Session,
    *,
    api_key: str,
    model: str | None,
    is_active: bool = True,
) -> LLMProviderConfig:
    row = get_config(db, PROVIDER_OPENAI)
    if row is None:
        row = LLMProviderConfig(provider=PROVIDER_OPENAI)
        db.add(row)
    if api_key.strip():
        row.api_key_enc = encrypt(api_key.strip())
    if model is not None:
        row.model = (model or "").strip() or _DEFAULT_OPENAI_MODEL
    row.is_active = is_active
    row.last_tested_at = datetime.utcnow()
    row.last_error = None
    db.commit()
    db.refresh(row)
    return row


def disconnect_openai(db: Session) -> None:
    row = get_config(db, PROVIDER_OPENAI)
    if row is None:
        return
    db.delete(row)
    db.commit()
