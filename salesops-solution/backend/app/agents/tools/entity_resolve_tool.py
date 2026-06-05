"""Resolve a customer email to a Salesforce Account.

Salesforce is the customer system of record. If the sender / extracted
fields don't map to a Salesforce Account, the tool returns a clean
`no_salesforce_match` result and the pipeline routes to HITL with an
"unknown customer — please tag in Salesforce" reason.

Lookup chain:
  1. extracted.customer_code → SF Customer_Code__c
  2. extracted.contact_email / email.from → SF Contact.Email
  3. extracted.customer_name → fuzzy SF Account.Name (LIKE)
"""
from __future__ import annotations

from typing import Any

from ..base import AgentContext, Tool, ToolResult
from ..salesforce_lookup import fetch_account_by_code, fetch_account_by_email, has_active_connection


class EntityResolveTool(Tool):
    """Match an inbound email to a Salesforce Account.

    Lookup priority: Customer_Code__c → Contact.Email → Account.Name (fuzzy).
    Returns `source="salesforce"` on hit, or `source="none"` with a clear
    `basis` and a guardrail note when nothing matched (pipeline goes to HITL).
    """

    name = "entity_resolve_customer"
    description = (
        "Match email to Salesforce Account via Customer_Code__c → Contact.Email → Account.Name (fuzzy)."
    )
    kb_namespaces: list[str] = []

    def invoke(self, ctx: AgentContext, **inputs: Any) -> ToolResult:
        try:
            email = inputs.get("email") or ctx.email or {}
            extracted = inputs.get("extracted") or ctx.extracted or {}
            sender_full = email.get("from") or ""
            sender_addr = _extract_email_address(sender_full)
            customer_code = (
                extracted.get("customer_code")
                or extracted.get("Customer_Code__c")
                or extracted.get("buyer_code")
            )
            buyer_email = (
                extracted.get("buyer_email")
                or extracted.get("contact_email")
                or extracted.get("billing_email")
            )
            name_hint = (
                extracted.get("customer_name")
                or extracted.get("company_name")
                or ""
            )

            if not has_active_connection():
                # Enterprise behaviour: refuse the resolution outright. The
                # readiness gate should already have stopped the pipeline at
                # ingress, but if a pre-readiness pipeline made it this far,
                # fail loudly so the case lands in HITL with the right reason
                # instead of silently mock-resolving against the local DB.
                #
                # The local-DB fallback is only available when the operator
                # has explicitly enabled demo mode (ENABLE_DEMO_FALLBACKS=1),
                # in which case the resolution falls back to the seeded
                # mock CRM and the case is tagged source=local_db_demo.
                from ...services.readiness import is_demo_mode
                if is_demo_mode():
                    fb = _resolve_via_local_db(
                        customer_code=customer_code,
                        candidate_emails=[buyer_email, sender_addr],
                        name_hint=name_hint,
                    )
                    if fb is not None:
                        # Tag the match so the trace shows demo-mode fallback was used.
                        try:
                            fb.data["source"] = "local_db_demo"
                            fb.notes = (fb.notes or []) + ["demo mode — local CRM fallback (ENABLE_DEMO_FALLBACKS=1)"]
                        except Exception:
                            pass
                        return fb
                return ToolResult(
                    name=self.name,
                    ok=False,
                    error="no_active_salesforce_connection",
                    data={
                        "salesforce_account_id": None,
                        "customer_code": None,
                        "customer_name": None,
                        "score": 0.0,
                        "basis": "no_salesforce_connection",
                        "source": "none",
                        "attempted_lookups": [],
                        "extracted_customer_code_seen": customer_code,
                        "extracted_buyer_email_seen": buyer_email,
                        "extracted_customer_name_seen": name_hint,
                        "sender_email_seen": sender_addr,
                    },
                    notes=[
                        "Salesforce is not connected — entity resolution refused. "
                        "Reconnect in Settings → Integrations to enable customer match.",
                    ],
                )

            attempted: list[dict[str, Any]] = []

            if customer_code:
                sf_account = fetch_account_by_code(customer_code)
                attempted.append({
                    "method": "Customer_Code__c",
                    "value": customer_code,
                    "matched": bool(sf_account),
                })
                if sf_account:
                    return _ok(sf_account, basis="salesforce_by_customer_code", attempted=attempted)

            for candidate_email in [buyer_email, sender_addr]:
                if not candidate_email:
                    continue
                sf_account = fetch_account_by_email(candidate_email)
                attempted.append({
                    "method": "Contact.Email",
                    "value": candidate_email,
                    "matched": bool(sf_account),
                })
                if sf_account:
                    basis_label = (
                        "salesforce_by_buyer_email"
                        if candidate_email == buyer_email
                        else "salesforce_by_sender_email"
                    )
                    return _ok(sf_account, basis=basis_label, attempted=attempted)

            if name_hint:
                sf_account = _fuzzy_account_by_name(name_hint)
                attempted.append({
                    "method": "Account.Name LIKE",
                    "value": name_hint,
                    "matched": bool(sf_account),
                })
                if sf_account:
                    return _ok(sf_account, basis="salesforce_by_name_fuzzy", attempted=attempted)

            return ToolResult(
                name=self.name,
                ok=True,
                data={
                    "salesforce_account_id": None,
                    "customer_code": None,
                    "customer_name": None,
                    "score": 0.0,
                    "basis": "no_salesforce_match",
                    "source": "none",
                    "attempted_lookups": attempted,
                    "extracted_customer_code_seen": customer_code,
                    "extracted_buyer_email_seen": buyer_email,
                    "extracted_customer_name_seen": name_hint,
                    "sender_email_seen": sender_addr,
                },
                notes=[
                    f"no Salesforce account matched after {len(attempted)} attempted lookup(s); "
                    f"this email's sender/extracted fields are not in Salesforce yet"
                ],
            )
        except Exception as e:
            return ToolResult(name=self.name, ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")


def _ok(sf_account: dict, *, basis: str, attempted: list[dict]) -> ToolResult:
    return ToolResult(
        name="entity_resolve_customer",
        ok=True,
        data={
            "salesforce_account_id": sf_account.get("Id"),
            "customer_code": sf_account.get("Customer_Code__c"),
            "customer_name": sf_account.get("Name"),
            "score": 1.0,
            "basis": basis,
            "account": sf_account,
            "source": "salesforce",
            "attempted_lookups": attempted,
        },
    )


def _fuzzy_account_by_name(name: str) -> dict | None:
    """Best-effort SOQL fuzzy match on Account.Name. Returns None if no SF or no hit."""
    try:
        from ..salesforce_lookup import _get_sf_client
        sf = _get_sf_client()
        if sf is None:
            return None
        # Lightweight LIKE-style match on a sanitized version of the input.
        token = (name or "").strip().split()[0:3]
        if not token:
            return None
        like_term = " ".join(token).replace("'", "\\'")
        soql = (
            "SELECT Id, Name, Customer_Code__c, Region__c, Vertical__c, SLA_Tier__c, "
            "Compliance_Flags__c, Payment_Terms__c, Credit_Limit__c, Industry, "
            "BillingCity, BillingCountryCode "
            f"FROM Account WHERE Name LIKE '%{like_term}%' LIMIT 1"
        )
        records = sf.query(soql).get("records") or []
        if records:
            rec = dict(records[0])
            rec.pop("attributes", None)
            return rec
    except Exception:
        return None
    return None


def _extract_email_address(s: str) -> str:
    if not s:
        return ""
    if "<" in s and ">" in s:
        try:
            return s.split("<", 1)[1].split(">", 1)[0].strip()
        except Exception:
            return s.strip()
    return s.strip()


def _resolve_via_local_db(
    *,
    customer_code: str | None,
    candidate_emails: list[str | None],
    name_hint: str,
) -> ToolResult | None:
    """Local mock CRM fallback when no real Salesforce connection is configured.

    Match priority mirrors the Salesforce flow: customer_code -> contact email
    -> account email -> fuzzy name. Returns a ToolResult shaped like the
    Salesforce success path so downstream stages don't need to special-case
    the fallback. Returns None if no local match found, letting the caller
    emit the standard no_match response.
    """
    try:
        from ...db import SessionLocal
        from ...models import Contact, Customer
        from sqlalchemy import func
    except Exception:
        return None
    db = SessionLocal()
    try:
        attempted: list[dict[str, Any]] = []
        cust: Customer | None = None
        basis = ""

        # 1. Customer code match
        if customer_code:
            cust = (
                db.query(Customer)
                .filter(func.lower(Customer.code) == customer_code.lower())
                .first()
            )
            attempted.append({"method": "local_db_customer_code", "value": customer_code, "matched": bool(cust)})
            if cust:
                basis = "local_db_by_customer_code"

        # 2. Contact email match
        if cust is None:
            for candidate in candidate_emails:
                if not candidate:
                    continue
                contact = (
                    db.query(Contact)
                    .filter(func.lower(Contact.email) == candidate.lower())
                    .first()
                )
                attempted.append({"method": "local_db_contact_email", "value": candidate, "matched": bool(contact)})
                if contact:
                    cust = db.get(Customer, contact.customer_id)
                    if cust:
                        basis = "local_db_by_contact_email"
                        break

        # 3. Account inbox email match (customers.email column)
        if cust is None:
            for candidate in candidate_emails:
                if not candidate:
                    continue
                row = (
                    db.query(Customer)
                    .filter(func.lower(Customer.email) == candidate.lower())
                    .first()
                )
                attempted.append({"method": "local_db_account_email", "value": candidate, "matched": bool(row)})
                if row:
                    cust = row
                    basis = "local_db_by_account_email"
                    break

        # 4. Fuzzy name match (sender domain or customer name LIKE)
        if cust is None and name_hint:
            token = (name_hint or "").strip().split()[0:3]
            like_term = " ".join(token)
            if like_term:
                row = (
                    db.query(Customer)
                    .filter(Customer.name.ilike(f"%{like_term}%"))
                    .first()
                )
                attempted.append({"method": "local_db_name_fuzzy", "value": like_term, "matched": bool(row)})
                if row:
                    cust = row
                    basis = "local_db_by_name_fuzzy"

        if cust is None:
            return None

        # Compose a Salesforce-shaped account dict so downstream code that
        # reads sf_account.get("...") keeps working unchanged.
        mock_sf_account = {
            "Id": f"LOCAL-MOCK-{cust.id:08d}",
            "Name": cust.name,
            "Customer_Code__c": cust.code,
            "Region__c": cust.region,
            "Vertical__c": cust.vertical,
            "SLA_Tier__c": cust.sla_tier,
            "Compliance_Flags__c": ", ".join(cust.compliance or []),
            "Payment_Terms__c": cust.payment_terms,
            "Credit_Limit__c": cust.credit_limit,
            "Industry": cust.industry,
            "BillingCity": (cust.addresses[0].get("city") if cust.addresses else None),
            "BillingCountryCode": (cust.addresses[0].get("country") if cust.addresses else None),
        }
        return ToolResult(
            name="entity_resolve_customer",
            ok=True,
            data={
                "salesforce_account_id": mock_sf_account["Id"],
                "customer_code": cust.code,
                "customer_name": cust.name,
                "score": 1.0,
                "basis": basis,
                "account": mock_sf_account,
                "source": "local_mock_crm",
                "attempted_lookups": attempted,
            },
            notes=[
                "matched via local mock CRM (Customer table) because no Salesforce connection is configured; "
                "production deployments will resolve against the real Salesforce org"
            ],
        )
    finally:
        db.close()
