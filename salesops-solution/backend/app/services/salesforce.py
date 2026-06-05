"""Salesforce connector — OAuth 2.0 username-password flow + REST/SOQL.

Authenticates via OAuth Username-Password flow (REST), bypassing the
deprecated SOAP `login()` endpoint that newer orgs disable by default.
Credentials are stored encrypted in `salesforce_connections`.

Usage:
    conn = get_active_connection(db)            # returns SalesforceConnection or None
    sf = client_for(conn)                        # returns simple-salesforce client
    sf.query("SELECT Id, Name FROM Account")
    sf.Account.create({"Name": "Acme Corp"})
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from simple_salesforce import Salesforce, SalesforceLogin
from simple_salesforce.exceptions import SalesforceError
from sqlalchemy.orm import Session

from ..models import SalesforceConnection
from .secrets import decrypt, encrypt

log = logging.getLogger("salesforce")

OAUTH_TOKEN_PATH = "/services/oauth2/token"


@dataclass
class AuthCredentials:
    instance_url: str
    consumer_key: str
    consumer_secret: str
    flow: str = "client_credentials"
    username: str | None = None
    password: str | None = None
    security_token: str | None = None
    domain: str = "login"
    api_version: str = "60.0"


@dataclass
class WhoAmI:
    org_id: str
    org_name: str
    org_edition: str
    user_id: str
    user_display_name: str
    instance_url: str
    daily_api_remaining: int | None
    daily_api_max: int | None


def _normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _login_url(creds: AuthCredentials) -> str:
    """Prefer the org's My Domain URL for OAuth; fall back to login.salesforce.com."""
    if creds.instance_url:
        return f"{_normalize_url(creds.instance_url)}{OAUTH_TOKEN_PATH}"
    base = "test" if creds.domain == "test" else "login"
    return f"https://{base}.salesforce.com{OAUTH_TOKEN_PATH}"


def oauth_token(creds: AuthCredentials) -> dict[str, Any]:
    """OAuth 2.0 token grant — supports client_credentials and password flows."""
    if creds.flow == "client_credentials":
        payload = {
            "grant_type": "client_credentials",
            "client_id": creds.consumer_key,
            "client_secret": creds.consumer_secret,
        }
    elif creds.flow == "password":
        if not creds.username or not creds.password:
            raise RuntimeError("password flow requires username + password")
        payload = {
            "grant_type": "password",
            "client_id": creds.consumer_key,
            "client_secret": creds.consumer_secret,
            "username": creds.username,
            "password": creds.password + (creds.security_token or ""),
        }
    else:
        raise RuntimeError(f"unsupported flow: {creds.flow}")

    url = _login_url(creds)
    resp = requests.post(url, data=payload, timeout=30)
    if resp.status_code != 200:
        try:
            err = resp.json()
            raise RuntimeError(
                f"oauth_failed @ {url} ({creds.flow}): {err.get('error')} — {err.get('error_description')}"
            )
        except ValueError:
            raise RuntimeError(f"oauth_failed @ {url} ({creds.flow}): HTTP {resp.status_code} — {resp.text[:200]}")
    return resp.json()


# Keep the old name as an alias so existing call sites don't break.
oauth_password_login = oauth_token


def client_from_credentials(creds: AuthCredentials) -> Salesforce:
    """Authenticate via OAuth and return a simple-salesforce client."""
    token = oauth_token(creds)
    return Salesforce(
        instance_url=token["instance_url"],
        session_id=token["access_token"],
        version=creds.api_version,
    )


def whoami(sf: Salesforce) -> WhoAmI:
    org = sf.query("SELECT Id, Name, OrganizationType FROM Organization LIMIT 1")["records"][0]
    user_resp = sf.restful("chatter/users/me", method="GET") or {}
    limits = sf.limits()
    daily = limits.get("DailyApiRequests", {})
    return WhoAmI(
        org_id=org["Id"],
        org_name=org["Name"],
        org_edition=org["OrganizationType"],
        user_id=str(user_resp.get("id", "")),
        user_display_name=str(user_resp.get("displayName", "")),
        instance_url=sf.sf_instance,
        daily_api_remaining=daily.get("Remaining"),
        daily_api_max=daily.get("Max"),
    )


def serialize(conn: SalesforceConnection, *, include_secrets: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": conn.id,
        "label": conn.label,
        "instance_url": conn.instance_url,
        "username": conn.username,
        "domain": conn.domain,
        "api_version": conn.api_version,
        "is_active": conn.is_active,
        "last_tested_at": conn.last_tested_at.isoformat() if conn.last_tested_at else None,
        "last_error": conn.last_error,
        "last_error_at": conn.last_error_at.isoformat() if conn.last_error_at else None,
        "org_id": conn.org_id,
        "org_name": conn.org_name,
        "org_edition": conn.org_edition,
        "user_display_name": conn.user_display_name,
        "daily_api_remaining": conn.daily_api_remaining,
        "daily_api_max": conn.daily_api_max,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
    }
    if include_secrets:
        out["password"] = decrypt(conn.password_enc)
        out["security_token"] = decrypt(conn.security_token_enc) if conn.security_token_enc else None
        out["consumer_key"] = decrypt(conn.consumer_key_enc)
        out["consumer_secret"] = decrypt(conn.consumer_secret_enc)
    return out


def credentials_from_db(conn: SalesforceConnection) -> AuthCredentials:
    flow = "password" if conn.password_enc else "client_credentials"
    return AuthCredentials(
        instance_url=conn.instance_url,
        consumer_key=decrypt(conn.consumer_key_enc),
        consumer_secret=decrypt(conn.consumer_secret_enc),
        flow=flow,
        username=conn.username if flow == "password" else None,
        password=decrypt(conn.password_enc) if conn.password_enc else None,
        security_token=decrypt(conn.security_token_enc) if conn.security_token_enc else None,
        domain=conn.domain or "login",
        api_version=conn.api_version or "60.0",
    )


def get_active_connection(db: Session) -> SalesforceConnection | None:
    return db.query(SalesforceConnection).filter_by(is_active=True).order_by(SalesforceConnection.id.desc()).first()


def record_url(db: Session, record_id: str | None) -> str | None:
    """Build a Salesforce Lightning deep-link for a record Id (Case / Order /
    Account / etc.). Uses the active org's `instance_url`. Returns None when
    no record_id, no active connection, or no instance_url.

    Lightning URL format: `{instance_url}/lightning/r/{Object}/{Id}/view`
    The object name is derived from the 3-character Id prefix when known; we
    pass the Id only (`/lightning/r/{Id}/view`) which Lightning still
    resolves correctly because it does its own prefix lookup."""
    if not record_id:
        return None
    conn = get_active_connection(db)
    if not conn or not conn.instance_url:
        return None
    base = conn.instance_url.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return f"{base}/lightning/r/{record_id}/view"


def client_for(conn: SalesforceConnection) -> Salesforce:
    return client_from_credentials(credentials_from_db(conn))


def upsert_connection(
    db: Session,
    *,
    instance_url: str,
    consumer_key: str,
    consumer_secret: str,
    flow: str = "client_credentials",
    username: str | None = None,
    password: str | None = None,
    security_token: str | None = None,
    domain: str = "login",
    api_version: str = "60.0",
    label: str = "Production org",
) -> SalesforceConnection:
    """Create or replace the active connection. Tests credentials before saving."""
    creds = AuthCredentials(
        instance_url=instance_url,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        flow=flow,
        username=username,
        password=password,
        security_token=security_token,
        domain=domain,
        api_version=api_version,
    )
    sf = client_from_credentials(creds)
    info = whoami(sf)

    db.query(SalesforceConnection).update({"is_active": False})
    row = SalesforceConnection(
        label=label,
        instance_url=info.instance_url,
        username=username or info.user_display_name,
        password_enc=encrypt(password) if password else None,
        security_token_enc=encrypt(security_token) if security_token else None,
        consumer_key_enc=encrypt(consumer_key),
        consumer_secret_enc=encrypt(consumer_secret),
        domain=domain,
        api_version=api_version,
        is_active=True,
        last_tested_at=datetime.now(timezone.utc),
        org_id=info.org_id,
        org_name=info.org_name,
        org_edition=info.org_edition,
        user_display_name=info.user_display_name,
        daily_api_remaining=info.daily_api_remaining,
        daily_api_max=info.daily_api_max,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_connection(
    *,
    instance_url: str,
    consumer_key: str,
    consumer_secret: str,
    flow: str = "client_credentials",
    username: str | None = None,
    password: str | None = None,
    security_token: str | None = None,
    domain: str = "login",
    api_version: str = "60.0",
) -> tuple[bool, str, dict | None]:
    """Test credentials without saving. Returns (ok, message, whoami_dict)."""
    try:
        sf = client_from_credentials(AuthCredentials(
            instance_url=instance_url,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            flow=flow,
            username=username,
            password=password,
            security_token=security_token,
            domain=domain,
            api_version=api_version,
        ))
        info = whoami(sf)
        return True, "ok", {
            "org_id": info.org_id,
            "org_name": info.org_name,
            "org_edition": info.org_edition,
            "user_display_name": info.user_display_name,
            "instance_url": info.instance_url,
            "daily_api_remaining": info.daily_api_remaining,
            "daily_api_max": info.daily_api_max,
        }
    except RuntimeError as e:
        return False, str(e), None
    except SalesforceError as e:
        return False, f"salesforce_error: {e}", None
    except requests.RequestException as e:
        return False, f"network_error: {e}", None
    except Exception as e:
        log.exception("test_connection failed")
        return False, f"unexpected: {type(e).__name__}: {e}", None


def refresh_status(db: Session, conn: SalesforceConnection) -> SalesforceConnection:
    """Re-authenticate, update last_tested_at + org info + API quota."""
    try:
        sf = client_for(conn)
        info = whoami(sf)
        conn.last_tested_at = datetime.now(timezone.utc)
        conn.last_error = None
        conn.last_error_at = None
        conn.org_id = info.org_id
        conn.org_name = info.org_name
        conn.org_edition = info.org_edition
        conn.user_display_name = info.user_display_name
        conn.daily_api_remaining = info.daily_api_remaining
        conn.daily_api_max = info.daily_api_max
    except Exception as e:
        conn.last_error = str(e)[:500]
        conn.last_error_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conn)
    return conn
