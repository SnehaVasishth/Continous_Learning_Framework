"""Role-based access control backed by Salesforce permission sets.

Operating model: the governance app is for ZBrain admins. They drive the
platform — promote A/B experiments, edit baselines, tune detectors, edit
governance policies. The Keysight functional team are stakeholders who
see outcomes (and run their CSR work inside Salesforce, not here), but
they are NOT a role in this app. Two roles total:

  - viewer        → read-only. Sees every page; touches nothing.
  - zbrain_admin  → full platform control. Promotes, rolls back, edits
                    baselines, edits detector tuning, edits governance
                    policies, deletes baselines.

Role resolution (per request, in priority order):
  1. `X-SF-User-Id` header → look up the Salesforce User's permission set
     assignments and derive the role. THIS IS THE PRODUCTION PATH.
  2. `X-Demo-Role` header → explicit override. Useful for QA / curl /
     screenshots; not for production.
  3. `RBAC_DEFAULT_ROLE` env → useful for dev loop with no headers.
  4. `viewer` → fail-closed default.

The Salesforce-backed path queries Permission Set assignments. One
permission set, configurable via env:

  RBAC_SF_PERM_SET_ZBRAIN_ADMIN  (default: `ZBrain_Platform_Admin`)

If the permission set isn't provisioned on the SF org yet (common in
fresh demo orgs), the resolver falls back to `config.LEARNING_RULE_OWNERS`
for the zbrain_admin role. The UI surfaces which source produced each
user's role so the IT admin can see whether they're on the production or
fallback path.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable

from fastapi import Depends, HTTPException, Request

log = logging.getLogger("rbac")


# Closed role set. The gate functions reference these constants rather than
# free-form strings so a typo surfaces at import time.
ROLE_VIEWER = "viewer"
ROLE_ZBRAIN_ADMIN = "zbrain_admin"

ALL_ROLES = {ROLE_VIEWER, ROLE_ZBRAIN_ADMIN}

# Back-compat aliases — older endpoints written before the SF-backed model
# may still import these names. Both fold onto zbrain_admin in the
# simplified 2-role model.
ROLE_CL_ADMIN = ROLE_ZBRAIN_ADMIN
ROLE_PLATFORM_ADMIN = ROLE_ZBRAIN_ADMIN
ROLE_FUNCTIONAL_REVIEWER = ROLE_VIEWER  # if any caller still references it


def current_role(request: Request) -> str:
    """Resolve the role for this request. Priority documented in module docstring."""
    # 1. Salesforce-backed identity. Production path.
    sf_user_id = (request.headers.get("x-sf-user-id") or "").strip()
    if sf_user_id:
        try:
            from . import sf_identity
            role, _source = sf_identity.resolve_role_for_sf_user(sf_user_id)
            if role in ALL_ROLES:
                return role
        except Exception:
            log.exception("rbac: SF role resolution failed for user %s; falling through", sf_user_id)

    # 2. Explicit demo override.
    hdr = (request.headers.get("x-demo-role") or "").strip().lower()
    if hdr in ALL_ROLES:
        return hdr

    # 3. Env default for dev.
    env = (os.environ.get("RBAC_DEFAULT_ROLE") or "").strip().lower()
    if env in ALL_ROLES:
        return env

    # 4. Fail-closed.
    return ROLE_VIEWER


def require_role(*allowed: str):
    """FastAPI dependency: 403 if the caller's role is not in `allowed`.

    Usage:
        @router.post(
            "/promote",
            dependencies=[Depends(require_role(ROLE_ZBRAIN_ADMIN))],
        )

    Pure dependency — does not return a value; caller does not need it in
    the handler signature. Resolves via the SF-backed `current_role()`.
    """
    allowed_set = set(allowed)
    if not allowed_set.issubset(ALL_ROLES):
        raise ValueError(f"unknown roles in require_role: {allowed_set - ALL_ROLES}")

    def _dep(request: Request) -> None:
        role = current_role(request)
        if role not in allowed_set:
            sf_user_id = (request.headers.get("x-sf-user-id") or "").strip() or None
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "rbac_denied",
                    "your_role": role,
                    "required": sorted(allowed_set),
                    "sf_user_id": sf_user_id,
                    "hint": (
                        "Assign the ZBrain_Platform_Admin Salesforce Permission Set "
                        "to your user to take admin actions. For test runs, the "
                        "X-Demo-Role header overrides."
                    ),
                },
            )

    return _dep


def get_role(request: Request) -> str:
    """Dependency variant that returns the role string. Use when the handler
    needs to branch on the role (e.g. soft-hide vs hard-deny)."""
    return current_role(request)
