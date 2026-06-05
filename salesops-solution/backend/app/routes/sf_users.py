"""Salesforce user identity endpoint.

Exposes the live Salesforce demo users so the frontend can render a "current
operator" picker. Each user is annotated with whether they hold the
rule-owner role (Continuous Learning promotion authority) per the allow-list
in config.LEARNING_RULE_OWNERS.

This is the single source of operator identity for learning actions. The
frontend stores the chosen user's SF Id in localStorage and passes it on
every learning POST/PATCH so the audit log records a real person, not a
free-text string.

Cached in-process for 60s so the Learning page does not hammer Salesforce on
every render.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import LEARNING_RULE_OWNERS
from ..db import get_db
from ..services import salesforce as sf_svc

router = APIRouter()

_CACHE: dict[str, Any] = {"ts": 0.0, "users": []}
_CACHE_TTL_SEC = 60.0


def _username_local(username: str | None) -> str:
    """Return the canonical local part of a Salesforce username for allow-list
    matching. Strips the @ domain and any `+tag` suffix (used heavily on the
    demo org's usernames), case-insensitive."""
    if not username:
        return ""
    s = str(username).strip().lower()
    s = s.split("@", 1)[0]
    s = s.split("+", 1)[0]
    return s


def _is_rule_owner(username: str | None) -> tuple[bool, str | None]:
    local = _username_local(username)
    label = LEARNING_RULE_OWNERS.get(local)
    return (label is not None, label)


@router.get("")
def list_sf_users(force_refresh: bool = False, db: Session = Depends(get_db)) -> list[dict]:
    """Return the active Salesforce users in the org, annotated with their
    rule-owner status. Cached for 60s in-process.

    The list is filtered to users present in any ZBrain_* queue, so the picker
    surfaces only the operators relevant to this solution rather than the
    entire SF org user table.
    """
    now = time.time()
    if not force_refresh and _CACHE["users"] and (now - _CACHE["ts"]) < _CACHE_TTL_SEC:
        return _CACHE["users"]

    conn = sf_svc.get_active_connection(db)
    if not conn:
        raise HTTPException(412, "no active Salesforce connection")
    try:
        sf = sf_svc.client_for(conn)
        # Pull users via the ZBrain_* queue membership so we surface the demo
        # operators rather than the entire SF user directory.
        groups = sf.query_all(
            "SELECT Id FROM Group WHERE Type='Queue' AND DeveloperName LIKE 'ZBrain_%'"
        )
        gids = [g["Id"] for g in groups["records"]]
        users: list[dict] = []
        if gids:
            quoted = ",".join(f"'{g}'" for g in gids)
            members = sf.query_all(
                f"SELECT UserOrGroupId FROM GroupMember WHERE GroupId IN ({quoted})"
            )
            user_ids = sorted({m["UserOrGroupId"] for m in members["records"]})
            if user_ids:
                uquoted = ",".join(f"'{u}'" for u in user_ids)
                ures = sf.query_all(
                    "SELECT Id, Name, FirstName, LastName, Username, Email, IsActive "
                    f"FROM User WHERE Id IN ({uquoted}) AND IsActive = true"
                )
                for u in ures["records"]:
                    is_owner, owner_label = _is_rule_owner(u.get("Username"))
                    users.append({
                        "id": u["Id"],
                        "name": u.get("Name"),
                        "first_name": u.get("FirstName"),
                        "last_name": u.get("LastName"),
                        "username": u.get("Username"),
                        "email": u.get("Email"),
                        "is_rule_owner": is_owner,
                        "rule_owner_label": owner_label,
                    })
        # Annotate every user with their RBAC role resolved via Salesforce
        # Permission Sets (with the legacy allowlist as a fallback). This is
        # the single place the UI reads to decide who can promote / view,
        # and the same resolver the per-request role gate uses, so the
        # displayed authority and the enforced authority can never drift.
        from ..services import sf_identity
        users = sf_identity.list_user_roles(users)
        # Sort: zbrain_admin first, then viewer, alphabetical within each band.
        _ROLE_RANK = {"zbrain_admin": 0, "viewer": 1}
        users.sort(key=lambda r: (_ROLE_RANK.get(r.get("role") or "viewer", 9), r.get("name") or ""))
        _CACHE["users"] = users
        _CACHE["ts"] = now
        return users
    except Exception as e:
        raise HTTPException(500, f"sf_users fetch failed: {e}")


@router.get("/me/{user_id}")
def get_sf_user(user_id: str, db: Session = Depends(get_db)) -> dict:
    """Lookup a single SF user by Id. Used by the audit-display path to
    resolve a recorded actor_id back to a name."""
    users = list_sf_users(db=db)
    for u in users:
        if u["id"] == user_id:
            return u
    raise HTTPException(404, "user not found in active SF queues")
