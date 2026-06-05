"""Salesforce Case writes — replaces the local SQLite CCCRequest table.

Cases drive the same RFP "Customer Contact Center request" lifecycle. Our
local request_number lives on `Case.Request_Number__c` (external id) so the
pipeline can upsert idempotently.

Status mapping — SF Case ships with "New", "Working", "Escalated", "Closed".
We map our local lifecycle (`new` / `assigned` / `in_progress` / `closed`)
to the closest standard value, then probe the org once to confirm. If a
target value is missing in the org's picklist, we fall back to "New".

Stage / fallout / track / category / owner-label all live on custom fields
so we don't fight the native picklists.
"""
from __future__ import annotations

import logging
from typing import Any

from simple_salesforce.exceptions import SalesforceError
from sqlalchemy.orm import Session

from . import salesforce as sf_svc

log = logging.getLogger("salesforce_cases")


# Local lifecycle -> SF standard Status picklist
_DEFAULT_STATUS_MAP = {
    "new": "New",
    "assigned": "Working",
    "in_progress": "Working",
    "closed": "Closed",
}

_STATUS_FALLBACK = "New"

# Cache of valid Status values per org (keyed by SF instance host).
_STATUS_CACHE: dict[str, set[str]] = {}


def _valid_statuses(sf) -> set[str]:
    host = getattr(sf, "sf_instance", "default")
    cached = _STATUS_CACHE.get(host)
    if cached is not None:
        return cached
    valid: set[str] = set()
    for candidate in ("New", "Working", "Escalated", "Closed", "On Hold"):
        try:
            sf.query(f"SELECT Id FROM Case WHERE Status='{candidate}' LIMIT 1")
            valid.add(candidate)
        except SalesforceError:
            continue
    if not valid:
        valid = {_STATUS_FALLBACK}
    _STATUS_CACHE[host] = valid
    return valid


def _map_status(sf, local_status: str | None) -> str:
    valid = _valid_statuses(sf)
    target = _DEFAULT_STATUS_MAP.get((local_status or "new").lower(), _STATUS_FALLBACK)
    if target in valid:
        return target
    if "New" in valid:
        return "New"
    return next(iter(valid))


def _strip_attrs(rec: dict | None) -> dict | None:
    if not rec:
        return None
    return {k: v for k, v in rec.items() if k != "attributes"}


def _instance_url(conn) -> str:
    return (getattr(conn, "instance_url", "") or "").rstrip("/")


def _connect(db: Session):
    conn = sf_svc.get_active_connection(db)
    if not conn:
        raise RuntimeError("no_active_salesforce_connection")
    sf = sf_svc.client_for(conn)
    return conn, sf


def _build_payload(
    sf,
    *,
    account_id: str | None,
    email_id: int | None,
    pipeline_id: int | None,
    request_number: str,
    category: str | None,
    request_type: str | None,
    sub_type: str | None,
    track: str | None,
    status: str | None,
    stage: str | None,
    owner_label: str | None,
    fallout_reason: str | None,
    notes: str | None,
    customer_code: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "Request_Number__c": request_number,
        "Status": _map_status(sf, status),
        "Origin": "Email",
    }
    if account_id:
        payload["AccountId"] = account_id
    subject_bits = [request_type or category or "Inbound request", request_number]
    payload["Subject"] = " · ".join([s for s in subject_bits if s])[:255]
    if notes:
        payload["Description"] = notes[:32000]
    if customer_code:
        payload["Customer_Code__c"] = customer_code
    if category:
        payload["Category__c"] = category
    if request_type:
        payload["Request_Type__c"] = request_type
    if sub_type:
        payload["Sub_Type__c"] = sub_type
    if track:
        payload["Track__c"] = track
    if stage:
        payload["Stage__c"] = stage
    if owner_label:
        payload["Owner_Label__c"] = owner_label
    if fallout_reason:
        payload["Fallout_Reason__c"] = fallout_reason
    if pipeline_id is not None:
        payload["Pipeline_Id__c"] = str(pipeline_id)
    if email_id is not None:
        payload["Email_Id__c"] = str(email_id)
    return payload


def _case_url(conn, case_id: str) -> str:
    base = _instance_url(conn)
    return f"{base}/lightning/r/Case/{case_id}/view" if base else ""


def find_case_by_request_number(db: Session, request_number: str) -> dict | None:
    if not request_number:
        return None
    conn, sf = _connect(db)
    safe = request_number.replace("'", "''")
    try:
        res = sf.query(
            f"SELECT Id, CaseNumber, Status, AccountId, Pipeline_Id__c, Request_Number__c, Stage__c "
            f"FROM Case WHERE Request_Number__c = '{safe}' LIMIT 1"
        )
    except SalesforceError as e:
        log.warning("find_case_by_request_number failed: %s", e)
        return None
    recs = res.get("records") or []
    return _strip_attrs(recs[0]) if recs else None


def find_case_by_pipeline_id(db: Session, pipeline_id: int | str) -> dict | None:
    if pipeline_id is None:
        return None
    conn, sf = _connect(db)
    safe = str(pipeline_id).replace("'", "''")
    try:
        res = sf.query(
            f"SELECT Id, CaseNumber, Status, AccountId, Pipeline_Id__c, Request_Number__c, Stage__c "
            f"FROM Case WHERE Pipeline_Id__c = '{safe}' LIMIT 1"
        )
    except SalesforceError as e:
        log.warning("find_case_by_pipeline_id failed: %s", e)
        return None
    recs = res.get("records") or []
    return _strip_attrs(recs[0]) if recs else None


def create_case(
    db: Session,
    *,
    account_id: str | None,
    email_id: int | None,
    pipeline_id: int | None,
    request_number: str,
    category: str | None = None,
    request_type: str | None = None,
    sub_type: str | None = None,
    track: str | None = None,
    status: str | None = "new",
    stage: str | None = "automation_in_progress",
    owner_label: str | None = None,
    fallout_reason: str | None = None,
    notes: str | None = None,
    customer_code: str | None = None,
) -> dict[str, Any]:
    """Create or upsert a Salesforce Case keyed on Request_Number__c.

    If a Case with this request_number already exists, we update it instead
    of creating a duplicate (idempotent re-runs).
    """
    conn, sf = _connect(db)

    payload = _build_payload(
        sf,
        account_id=account_id,
        email_id=email_id,
        pipeline_id=pipeline_id,
        request_number=request_number,
        category=category,
        request_type=request_type,
        sub_type=sub_type,
        track=track,
        status=status,
        stage=stage,
        owner_label=owner_label,
        fallout_reason=fallout_reason,
        notes=notes,
        customer_code=customer_code,
    )

    safe = request_number.replace("'", "''")
    existing = sf.query(
        f"SELECT Id, CaseNumber FROM Case WHERE Request_Number__c = '{safe}' LIMIT 1"
    )
    recs = existing.get("records") or []
    if recs:
        case_id = recs[0]["Id"]
        case_number = recs[0].get("CaseNumber")
        update_payload = {k: v for k, v in payload.items() if k != "Request_Number__c"}
        try:
            sf.Case.update(case_id, update_payload)
        except SalesforceError as e:
            log.warning("Case.update on existing %s failed: %s", case_id, e)
            return {"ok": False, "case_id": case_id, "case_number": case_number, "reason": str(e)[:300]}
        return {
            "ok": True,
            "case_id": case_id,
            "case_number": case_number,
            "sf_url": _case_url(conn, case_id),
            "upserted": True,
        }

    try:
        res = sf.Case.create(payload)
    except SalesforceError as e:
        return {"ok": False, "reason": str(e)[:300]}
    if not res.get("success"):
        return {"ok": False, "reason": "Case.create returned non-success", "raw": res}
    case_id = res["id"]
    case_number = None
    try:
        result = sf.Case.get(case_id)
        case_number = result.get("CaseNumber")
    except Exception:
        pass
    return {
        "ok": True,
        "case_id": case_id,
        "case_number": case_number,
        "sf_url": _case_url(conn, case_id),
        "upserted": False,
    }


def update_case(db: Session, *, case_id: str, **fields: Any) -> dict[str, Any]:
    """Patch an existing Case. Accepts our local field names (status, stage,
    fallout_reason, owner_label, category, request_type, sub_type, track,
    notes) and translates to SF API names. Unknown keys are dropped."""
    if not case_id:
        return {"ok": False, "reason": "missing case_id"}
    conn, sf = _connect(db)

    payload: dict[str, Any] = {}
    if "status" in fields and fields["status"] is not None:
        payload["Status"] = _map_status(sf, fields["status"])
    if "stage" in fields and fields["stage"] is not None:
        payload["Stage__c"] = fields["stage"]
    if "fallout_reason" in fields:
        payload["Fallout_Reason__c"] = fields["fallout_reason"]
    if "owner_label" in fields:
        payload["Owner_Label__c"] = fields["owner_label"]
    if "owner_id" in fields and fields["owner_id"]:
        # OwnerId on a Salesforce Case can be a User Id or a Queue Id (the
        # 15/18-char `Group` Id with Type='Queue'). We populate this from the
        # owner_mapping KB row that the track classifier resolved.
        payload["OwnerId"] = fields["owner_id"]
    if "category" in fields:
        payload["Category__c"] = fields["category"]
    if "request_type" in fields:
        payload["Request_Type__c"] = fields["request_type"]
    if "sub_type" in fields:
        payload["Sub_Type__c"] = fields["sub_type"]
    if "track" in fields:
        payload["Track__c"] = fields["track"]
    if "notes" in fields and fields["notes"] is not None:
        payload["Description"] = str(fields["notes"])[:32000]

    if not payload:
        return {"ok": True, "case_id": case_id, "noop": True}

    try:
        sf.Case.update(case_id, payload)
    except SalesforceError as e:
        log.warning("Case.update %s failed: %s", case_id, e)
        return {"ok": False, "case_id": case_id, "reason": str(e)[:300]}
    return {"ok": True, "case_id": case_id, "sf_url": _case_url(conn, case_id)}


def fetch_case(db: Session, case_id: str) -> dict | None:
    """Read a single Case (used by the pipeline detail route)."""
    if not case_id:
        return None
    _, sf = _connect(db)
    try:
        rec = sf.Case.get(case_id)
    except SalesforceError as e:
        log.warning("Case.get %s failed: %s", case_id, e)
        return None
    return _strip_attrs(rec)


# === v1.1 TASK-4 START === Existing-CCC status branch helpers
def find_by_po_or_wo(
    db: Session,
    *,
    po_number: str | None = None,
    wo_number: str | None = None,
    customer_account_id: str | None = None,
) -> dict | None:
    """Search Salesforce Cases by PO# or WO# (custom fields PO_Number__c /
    WO_Number__c). Returns the most recent match as a dict or None.

    Best-effort: if SF isn't connected, the custom fields don't exist in the
    org, or the SOQL fails, returns None and the orchestrator falls back to
    `ccc_action="new"`.
    """
    if not po_number and not wo_number:
        return None
    conn, sf = _connect(db)
    if not sf:
        return None
    try:
        clauses: list[str] = []
        if po_number:
            esc = po_number.replace("'", "\'")
            clauses.append(f"PO_Number__c = '{esc}'")
        if wo_number:
            esc = wo_number.replace("'", "\'")
            clauses.append(f"WO_Number__c = '{esc}'")
        if customer_account_id:
            esc = customer_account_id.replace("'", "\'")
            clauses.append(f"AccountId = '{esc}'")
        where = " AND ".join([f"({clauses[0]} OR {clauses[1]})"] if len(clauses) == 2 and not customer_account_id else clauses) if clauses else ""
        if customer_account_id and (po_number or wo_number):
            ids_clause = " OR ".join([c for c in clauses if c.startswith("PO_Number") or c.startswith("WO_Number")])
            acct = next((c for c in clauses if c.startswith("AccountId")), None)
            where = f"({ids_clause})"
            if acct:
                where = f"{where} AND {acct}"
        soql = (
            "SELECT Id, CaseNumber, Request_Number__c, Status, Stage__c, Type, "
            "Track__c, OwnerId, Owner.Name, PO_Number__c, WO_Number__c, AccountId, "
            "CreatedDate "
            f"FROM Case WHERE {where} ORDER BY CreatedDate DESC LIMIT 1"
        )
        result = sf.query(soql)
    except SalesforceError as e:
        # Custom fields likely missing — fail soft.
        log.info("find_by_po_or_wo SOQL failed (custom fields may not exist): %s", str(e)[:200])
        return None
    except Exception as e:
        log.info("find_by_po_or_wo unexpected error: %s", str(e)[:200])
        return None
    records = (result or {}).get("records") or []
    if not records:
        return None
    rec = _strip_attrs(records[0])
    owner = rec.get("Owner") or {}
    return {
        "case_id": rec.get("Id"),
        "case_number": rec.get("CaseNumber"),
        "request_number": rec.get("Request_Number__c"),
        "status": rec.get("Status"),
        "stage": rec.get("Stage__c"),
        "type": rec.get("Type"),
        "track": rec.get("Track__c"),
        "owner_id": rec.get("OwnerId"),
        "owner_name": owner.get("Name") if isinstance(owner, dict) else None,
        "po_number": rec.get("PO_Number__c"),
        "wo_number": rec.get("WO_Number__c"),
        "account_id": rec.get("AccountId"),
        "created_at": rec.get("CreatedDate"),
    }


def find_candidate_ccc_requests(
    db: Session,
    *,
    po_number: str | None = None,
    wo_number: str | None = None,
    quote_number: str | None = None,
    customer_account_id: str | None = None,
    days_open_window: int = 30,
    limit_per_query: int = 5,
) -> list[dict]:
    """Collect candidate Salesforce Cases this email might belong to.

    Runs up to four narrow SOQL queries in sequence, deduplicates by Case Id,
    and returns the raw candidates. Scoring + selection happens in the
    caller (Stage 3 decide agent) so the resolution decision is auditable.

    Sources:
      1. Cases with `PO_Number__c = po_number` (any status)
      2. Cases with `WO_Number__c = wo_number` (any status)
      3. Cases with `Quote_Number__c = quote_number` (any status)
      4. Cases for the same customer that are still open and recent
         (`AccountId = X AND Status NOT IN ('Closed','Cancelled') AND CreatedDate > N days ago`)

    Each candidate dict carries a `match_signals` list (the queries it
    matched) so the scoring step can weigh them.
    """
    if not (po_number or wo_number or quote_number or customer_account_id):
        return []
    conn, sf = _connect(db)
    if not sf:
        return []

    seen: dict[str, dict] = {}

    def _add(rec: dict, signal: str) -> None:
        rec = _strip_attrs(rec)
        cid = rec.get("Id")
        if not cid:
            return
        if cid not in seen:
            seen[cid] = {
                "case_id": cid,
                "case_number": rec.get("CaseNumber"),
                "request_number": rec.get("Request_Number__c"),
                "status": rec.get("Status"),
                "stage": rec.get("Stage__c"),
                "type": rec.get("Type"),
                "request_type": rec.get("Request_Type__c"),
                "sub_type": rec.get("Sub_Type__c"),
                "category": rec.get("Category__c"),
                "track": rec.get("Track__c"),
                "owner_id": rec.get("OwnerId"),
                "po_number": rec.get("PO_Number__c"),
                "wo_number": rec.get("WO_Number__c"),
                "quote_number": rec.get("Quote_Number__c"),
                "account_id": rec.get("AccountId"),
                "subject": rec.get("Subject"),
                "description": rec.get("Description"),
                "pipeline_id_str": rec.get("Pipeline_Id__c"),
                "created_at": rec.get("CreatedDate"),
                "match_signals": [],
            }
        seen[cid]["match_signals"].append(signal)

    # Discover which Case custom fields exist in this org so we can build a
    # SOQL that doesn't 400 with INVALID_FIELD. Some orgs (e.g. the ZBrain
    # sandbox) don't carry PO_Number__c / WO_Number__c / Quote_Number__c on
    # Case — without this probe the entire candidate query short-circuits
    # silently and downstream duplicate-detection never sees any candidates.
    optional_fields = {
        "Request_Number__c", "Stage__c", "Request_Type__c", "Sub_Type__c",
        "Category__c", "Track__c", "PO_Number__c", "WO_Number__c",
        "Quote_Number__c", "Description", "Pipeline_Id__c", "OwnerId",
    }
    try:
        desc = sf.Case.describe()
        existing_field_names = {f["name"] for f in desc.get("fields") or []}
    except Exception as e:
        log.info("CCC candidate Case.describe failed: %s", str(e)[:160])
        existing_field_names = set()

    base_field_list = [
        "Id", "CaseNumber", "Status", "Type", "AccountId", "Subject",
        "CreatedDate",
    ]
    for f in optional_fields:
        if not existing_field_names or f in existing_field_names:
            base_field_list.append(f)
    base_select = "SELECT " + ", ".join(base_field_list)

    has_po_field = (not existing_field_names) or ("PO_Number__c" in existing_field_names)
    has_wo_field = (not existing_field_names) or ("WO_Number__c" in existing_field_names)
    has_quote_field = (not existing_field_names) or ("Quote_Number__c" in existing_field_names)

    def _safe_query(soql: str, signal: str) -> None:
        try:
            res = sf.query(soql)
        except Exception as e:
            log.info("CCC candidate query failed (%s): %s", signal, str(e)[:160])
            return
        for r in (res or {}).get("records", []) or []:
            _add(r, signal)

    if po_number and has_po_field:
        esc = po_number.replace("'", "\\'")
        _safe_query(f"{base_select} FROM Case WHERE PO_Number__c = '{esc}' ORDER BY CreatedDate DESC LIMIT {limit_per_query}", "po_match")
    if wo_number and has_wo_field:
        esc = wo_number.replace("'", "\\'")
        _safe_query(f"{base_select} FROM Case WHERE WO_Number__c = '{esc}' ORDER BY CreatedDate DESC LIMIT {limit_per_query}", "wo_match")
    if quote_number and has_quote_field:
        esc = quote_number.replace("'", "\\'")
        _safe_query(
            f"{base_select} FROM Case WHERE Quote_Number__c = '{esc}' ORDER BY CreatedDate DESC LIMIT {limit_per_query}",
            "quote_match",
        )
    if customer_account_id:
        esc = customer_account_id.replace("'", "\\'")
        cutoff = f"LAST_N_DAYS:{int(max(1, days_open_window))}"
        # Open + recent (existing behavior — captures live duplicates).
        _safe_query(
            f"{base_select} FROM Case WHERE AccountId = '{esc}' "
            f"AND Status NOT IN ('Closed', 'Cancelled') "
            f"AND CreatedDate = {cutoff} "
            f"ORDER BY CreatedDate DESC LIMIT {limit_per_query}",
            "customer_open_recent",
        )
        # Closed-recent — captures the just-completed Case from a prior
        # pipeline run, so a re-sent customer email doesn't mint a fresh
        # Case. Window is intentionally narrow to keep the LLM matcher's
        # candidate set small.
        closed_cutoff = f"LAST_N_DAYS:{int(max(1, min(days_open_window, 7)))}"
        _safe_query(
            f"{base_select} FROM Case WHERE AccountId = '{esc}' "
            f"AND Status IN ('Closed', 'Resolved') "
            f"AND CreatedDate = {closed_cutoff} "
            f"ORDER BY CreatedDate DESC LIMIT {limit_per_query}",
            "customer_closed_recent",
        )

    return list(seen.values())


def score_ccc_candidates(
    candidates: list[dict],
    *,
    extracted_po: str | None,
    extracted_wo: str | None,
    extracted_quote: str | None,
    customer_account_id: str | None,
) -> list[dict]:
    """Score the raw candidate list. Returns the SAME list with `score` and
    `score_breakdown` populated on each row, sorted by score desc.

    Scoring matrix:
      + 0.50 — `email_thread` parent (set by caller, not by this fn)
      + 0.35 — PO# exact match
      + 0.30 — WO# exact match
      + 0.25 — Quote# exact match
      + 0.20 — Customer is open + recent
      - 0.30 — Status is Closed (less likely to be the live matter)
      - 0.40 — Account Id mismatches the resolved customer

    The caller (Stage 3 decide agent) layers email-thread evidence on top
    before final ranking.
    """
    for c in candidates:
        breakdown: list[tuple[str, float]] = []
        sigs = set(c.get("match_signals") or [])
        if "po_match" in sigs and extracted_po and (c.get("po_number") or "").strip() == extracted_po.strip():
            breakdown.append(("po_exact", 0.35))
        if "wo_match" in sigs and extracted_wo and (c.get("wo_number") or "").strip() == extracted_wo.strip():
            breakdown.append(("wo_exact", 0.30))
        if "quote_match" in sigs and extracted_quote and (c.get("quote_number") or "").strip() == extracted_quote.strip():
            breakdown.append(("quote_exact", 0.25))
        if "customer_open_recent" in sigs:
            breakdown.append(("customer_open_recent", 0.20))
        status = (c.get("status") or "").lower()
        if status in {"closed"}:
            breakdown.append(("status_closed_penalty", -0.30))
        if customer_account_id and c.get("account_id") and c.get("account_id") != customer_account_id:
            breakdown.append(("account_mismatch_penalty", -0.40))
        score = round(sum(v for _, v in breakdown), 3)
        c["score"] = score
        c["score_breakdown"] = breakdown
    candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return candidates


def attach_email_to_case(db: Session, case_id: str, *, email_id: int) -> dict:
    """Attach the local Email's body+subject as a ContentVersion on the Case.

    For the demo we record the action as a simulated success when the SF
    Files API isn't available — the trace UI still shows "attached".
    """
    if not case_id or not email_id:
        return {"ok": False, "reason": "missing case_id or email_id"}
    from ..models import Email as _Email
    e = db.get(_Email, email_id)
    if not e:
        return {"ok": False, "reason": "email not found"}
    conn, sf = _connect(db)
    if not sf:
        return {"ok": True, "simulated": True, "reason": "SF not connected — would attach email body"}
    try:
        import base64 as _b64
        title = (e.subject or f"Email-{e.id}")[:240]
        body_bytes = ((e.body or "") + "\n").encode("utf-8", "replace")
        cv = sf.ContentVersion.create({
            "Title": title,
            "PathOnClient": f"{title}.txt",
            "VersionData": _b64.b64encode(body_bytes).decode("ascii"),
        })
        cv_id = cv.get("id") if isinstance(cv, dict) else None
        if cv_id:
            cdoc = sf.query(f"SELECT ContentDocumentId FROM ContentVersion WHERE Id='{cv_id}' LIMIT 1")
            doc_recs = (cdoc or {}).get("records") or []
            if doc_recs:
                content_doc_id = doc_recs[0].get("ContentDocumentId")
                if content_doc_id:
                    sf.ContentDocumentLink.create({
                        "ContentDocumentId": content_doc_id,
                        "LinkedEntityId": case_id,
                        "ShareType": "V",
                    })
        return {"ok": True, "case_id": case_id, "content_version_id": cv_id}
    except Exception as ex:
        log.info("attach_email_to_case failed: %s", str(ex)[:200])
        return {"ok": False, "case_id": case_id, "reason": str(ex)[:200]}


def chatter_notify_owner(db: Session, case_id: str, *, message: str) -> dict:
    """Post a Chatter feed item on the Case so the owner sees the new activity.

    HARD RULE: Chatter @-mentions trigger SF notification emails to the assignee.
    Per config.DEMO_TRANSMIT_LOCKED, we record what WOULD have been posted as
    a simulated result — no actual API call to Salesforce.
    """
    from ..config import DEMO_TRANSMIT_LOCKED
    if DEMO_TRANSMIT_LOCKED:
        return {
            "ok": False,
            "simulated": True,
            "case_id": case_id,
            "would_post": (message or "")[:500],
            "reason": "blocked by config.DEMO_TRANSMIT_LOCKED — Chatter post simulated, SF feed unchanged",
        }
    if not case_id or not message:
        return {"ok": False, "reason": "missing case_id or message"}
    conn, sf = _connect(db)
    if not sf:
        return {"ok": False, "reason": "SF not connected"}
    try:
        sf.FeedItem.create({"ParentId": case_id, "Body": message[:5000]})
        return {"ok": True, "case_id": case_id}
    except Exception as ex:
        log.info("chatter_notify_owner failed: %s", str(ex)[:200])
        return {"ok": False, "case_id": case_id, "reason": str(ex)[:200]}


def add_case_comment(db: Session, case_id: str, *, body: str, is_public: bool = False) -> dict:
    """Write a CaseComment on the Case. Used to record evidence-file
    references (SharePoint URLs of uploaded attachments) so the operator can
    open them straight from the Case feed."""
    if not case_id or not body:
        return {"ok": False, "reason": "missing case_id or body"}
    conn, sf = _connect(db)
    if not sf:
        return {"ok": False, "reason": "SF not connected"}
    try:
        res = sf.CaseComment.create({"ParentId": case_id, "CommentBody": body[:4000], "IsPublished": bool(is_public)})
        return {"ok": True, "case_id": case_id, "comment_id": res.get("id")}
    except Exception as ex:
        log.info("add_case_comment failed: %s", str(ex)[:200])
        return {"ok": False, "case_id": case_id, "reason": str(ex)[:200]}


def update_case_status(db: Session, case_id: str, status: str) -> dict:
    """Patch a Case's Status field — used to flip an existing Case to
    'Working'/'Continue Processing' when a follow-up email arrives."""
    if not case_id:
        return {"ok": False, "reason": "missing case_id"}
    conn, sf = _connect(db)
    if not sf:
        return {"ok": False, "reason": "SF not connected"}
    try:
        valid = _valid_statuses(sf)
        target = status if status in valid else _STATUS_FALLBACK
        sf.Case.update(case_id, {"Status": target})
        return {"ok": True, "case_id": case_id, "status": target}
    except Exception as ex:
        log.info("update_case_status failed: %s", str(ex)[:200])
        return {"ok": False, "case_id": case_id, "reason": str(ex)[:200]}
# === v1.1 TASK-4 END ===
