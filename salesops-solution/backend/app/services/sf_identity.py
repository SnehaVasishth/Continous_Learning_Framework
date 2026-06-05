"""Salesforce-backed identity + role resolution.

Maps a Salesforce User Id to one of two RBAC roles by inspecting that
user's Permission Set assignments on the live org:

  ZBrain_Platform_Admin  → zbrain_admin
  anything else          → viewer (read-only)

The mapping is intentionally enterprise-grade rather than file-based:
adding or removing a user's admin authority is a Salesforce Setup task,
not a deploy. A 5-minute in-process cache keeps load on the SF API low.

When the SF connection is offline OR the permission set is not
provisioned on the org yet, the resolver falls back to the legacy
`config.LEARNING_RULE_OWNERS` allowlist for zbrain_admin. The UI
surfaces which source produced each user's role.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from .. import config as _cfg

log = logging.getLogger("sf_identity")


_PERM_SET_ZBRAIN_ADMIN = os.environ.get(
    "RBAC_SF_PERM_SET_ZBRAIN_ADMIN", "ZBrain_Platform_Admin"
).strip()

_TTL_SEC = 300.0  # 5 minutes; SF Permission Set changes propagate on next tick.

# Two caches: the full per-org permission-set name set (rare), and the per-
# user assignment list (common).
_PERMSET_NAMES_CACHE: dict[str, Any] = {"ts": 0.0, "names": set()}
_USER_ROLE_CACHE: dict[str, dict] = {}  # sf_user_id → {"ts": float, "role": str, "source": dict}


def _from_username_local(username: str | None) -> str:
    """Mirror the helper in routes/sf_users.py — strip @domain and any +tag
    suffix, lowercase. Used for matching against LEARNING_RULE_OWNERS."""
    if not username:
        return ""
    s = str(username).strip().lower()
    s = s.split("@", 1)[0]
    s = s.split("+", 1)[0]
    return s


def _allowlist_role(username: str | None) -> tuple[str | None, str | None]:
    local = _from_username_local(username)
    label = _cfg.LEARNING_RULE_OWNERS.get(local)
    if label:
        return ("zbrain_admin", label)
    return (None, None)


def _query_org_permset_names(sf) -> set[str]:
    """All Permission Set names that exist on the org (not just assigned
    ones). Used to detect whether the ZBrain_* permission sets have been
    provisioned at all."""
    now = time.time()
    cached = _PERMSET_NAMES_CACHE
    if cached["names"] and (now - cached["ts"]) < _TTL_SEC:
        return cached["names"]
    try:
        res = sf.query_all(
            "SELECT Name FROM PermissionSet WHERE IsCustom = true ORDER BY Name LIMIT 500"
        )
        names = {row["Name"] for row in res.get("records", []) if row.get("Name")}
    except Exception:
        names = set()
    _PERMSET_NAMES_CACHE["names"] = names
    _PERMSET_NAMES_CACHE["ts"] = now
    return names


def _query_user_permsets(sf, sf_user_id: str) -> list[str]:
    """Return the permission set names assigned to this SF user."""
    try:
        res = sf.query_all(
            "SELECT PermissionSet.Name "
            "FROM PermissionSetAssignment "
            f"WHERE AssigneeId = '{sf_user_id}' "
            "LIMIT 200"
        )
    except Exception:
        return []
    out: list[str] = []
    for row in res.get("records", []):
        ps = row.get("PermissionSet") or {}
        name = ps.get("Name") if isinstance(ps, dict) else None
        if name:
            out.append(name)
    return out


def resolve_role_for_sf_user(sf_user_id: str) -> tuple[str, dict[str, Any]]:
    """Return `(role, source)` for a Salesforce User Id.

    `role` is one of `viewer`, `functional_reviewer`, `zbrain_admin`.
    `source` is a small dict for the UI / audit log:
      { "source": "sf_permission_set"|"fallback_allowlist"|"sf_query_failed"|"unknown_user",
        "permission_sets": [str, ...],
        "username": str|None,
        "matched": str|None,           # the rule that fired
      }

    Cached for 5 minutes per sf_user_id.
    """
    sf_user_id = (sf_user_id or "").strip()
    if not sf_user_id:
        return ("viewer", {"source": "unknown_user", "permission_sets": [], "username": None, "matched": None})

    now = time.time()
    cached = _USER_ROLE_CACHE.get(sf_user_id)
    if cached and (now - cached["ts"]) < _TTL_SEC:
        return (cached["role"], cached["source"])

    # Resolve the active SF connection. If the org is offline we still want
    # the resolver to produce SOMETHING usable; fall back to viewer with a
    # documented reason.
    role: str = "viewer"
    source: dict[str, Any] = {
        "source": "viewer_default",
        "permission_sets": [],
        "username": None,
        "matched": None,
    }
    sf = None
    username: str | None = None
    try:
        from ..db import SessionLocal
        from . import salesforce as sf_svc

        db = SessionLocal()
        try:
            conn = sf_svc.get_active_connection(db)
            if conn:
                sf = sf_svc.client_for(conn)
        finally:
            db.close()
    except Exception:
        sf = None

    if sf is None:
        # No SF — fall back to allowlist via username. We don't have the
        # username so look up the LEARNING_RULE_OWNERS by id is not
        # possible; mark unknown.
        source["source"] = "sf_offline"
        _USER_ROLE_CACHE[sf_user_id] = {"ts": now, "role": role, "source": source}
        return (role, source)

    # Pull the user's username for the fallback path.
    try:
        ures = sf.query(f"SELECT Username FROM User WHERE Id = '{sf_user_id}' LIMIT 1")
        if ures.get("records"):
            username = ures["records"][0].get("Username")
            source["username"] = username
    except Exception:
        username = None

    org_permsets = _query_org_permset_names(sf)
    assigned = _query_user_permsets(sf, sf_user_id)
    source["permission_sets"] = assigned

    if _PERM_SET_ZBRAIN_ADMIN in assigned:
        role = "zbrain_admin"
        source["source"] = "sf_permission_set"
        source["matched"] = _PERM_SET_ZBRAIN_ADMIN
    else:
        # No ZBrain permission set assigned. Decide whether to fall back to
        # the allowlist (because the permission set isn't provisioned at
        # all) or to leave them as viewer.
        ps_provisioned = _PERM_SET_ZBRAIN_ADMIN in org_permsets
        if not ps_provisioned:
            # Fallback: legacy username-based allowlist.
            allow_role, allow_label = _allowlist_role(username)
            if allow_role:
                role = allow_role
                source["source"] = "fallback_allowlist"
                source["matched"] = allow_label
            else:
                source["source"] = "fallback_allowlist_no_match"
        else:
            # Permission sets exist but this user doesn't hold either —
            # genuine viewer.
            source["source"] = "sf_permission_set_no_assignment"

    _USER_ROLE_CACHE[sf_user_id] = {"ts": now, "role": role, "source": source}
    return (role, source)


def list_user_roles(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate a list of SF user dicts with `role`, `permission_sets`,
    and `role_source` fields. Used by the /api/sf-users endpoint."""
    out: list[dict[str, Any]] = []
    for u in users:
        role, source = resolve_role_for_sf_user(u.get("id") or "")
        out.append({
            **u,
            "role": role,
            "permission_sets": source.get("permission_sets") or [],
            "role_source": source,
        })
    return out


def invalidate_cache(sf_user_id: str | None = None) -> None:
    """Drop the cache. `None` clears all; an id clears one user."""
    if sf_user_id is None:
        _USER_ROLE_CACHE.clear()
        _PERMSET_NAMES_CACHE["names"] = set()
        _PERMSET_NAMES_CACHE["ts"] = 0.0
    else:
        _USER_ROLE_CACHE.pop(sf_user_id, None)
