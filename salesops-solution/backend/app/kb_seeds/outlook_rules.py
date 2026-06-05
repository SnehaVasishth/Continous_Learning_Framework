# === v1.1 TASK-2 START ===
"""Pre-AI deterministic Outlook rules (Stage 0).

Mirrors the prior Keysight POC's six Outlook rules verbatim, just stored
in the KB so operators can tune without a code change. Each rule is a
KnowledgeRule row in namespace=`outlook_rules`.

Body shape (flat — matches `_seed_namespace_from_list` helper convention):

  - priority             — lower = checked first; first match wins
  - enabled              — operator can disable per-rule
  - intent               — which TASK-1 intent to assign on match
  - actionable_exception — if True, suppress this rule when the same
        body fragment contains a clear business directive (please / kindly /
        ship / cancel / etc.) — let Stage 1 LLM classifier handle.
  - severity             — "hard_block" | "warn"
  - redirect_to          — destination mailbox (mirror of intent record)
  - predicates           — list of OR'd conditions, each with kind + value:
        kind: subject_contains | subject_equals | body_contains
              | sender_equals | sender_contains | sender_domain
              | regex_subject | regex_body
"""
from __future__ import annotations


OUTLOOK_RULES: list[dict] = [
    {
        "key": "outlook.undeliverable",
        "label": "Undeliverable / DSN / Bounce",
        "description": "Bounce / mail-delivery-failure notifications. Discard.",
        "priority": 10,
        "enabled": True,
        "intent": "undeliverable",
        "actionable_exception": True,
        "severity": "hard_block",
        "redirect_to": None,
        "predicates": [
            {"kind": "subject_contains", "value": [
                "Undeliverable",
                "Undelivered Mail Returned to Sender",
                "[Postmaster] Email Delivery Failure",
                "Returned Mail: see transcript for details",
                "You have some new Bonfire matches!",
                "Your message couldn't be delivered",
                "Your message couldn’t be delivered",
                "Delivery delayed: Keysight Support Web Email Update",
                "Delivery Status Notification",
                "Returned Mail",
                "Mail Delivery Failure",
                "Mail Delivery Failed",
                "Delivery Delayed",
                "DELIVERY FAILURE",
            ]},
            {"kind": "sender_contains", "value": ["mailer-daemon", "MAILER-DAEMON"]},
            {"kind": "sender_equals", "value": ["noreply@keysight.com"]},
        ],
    },
    {
        "key": "outlook.auto_reply",
        "label": "Auto-Reply / OOO",
        "description": "Out-of-office and auto-responder messages.",
        "priority": 20,
        "enabled": True,
        "intent": "out_of_scope",
        "actionable_exception": True,
        "severity": "warn",
        "redirect_to": None,
        "predicates": [
            {"kind": "subject_contains", "value": [
                "Automatic Reply",
                "Out of the office",
                "OUT OF OFFICE",
                "Out of Office",
                "Auto reply",
                "Auto-responder",
                "Automatic Reply: Keysight Support Web Email Update",
            ]},
        ],
    },
    {
        "key": "outlook.brazil_tax",
        "label": "Brazil Tax (TMF Group)",
        "description": "Brazil tax document forwarder. Redirect to LAR Orders team.",
        "priority": 30,
        "enabled": True,
        "intent": "brazil_tax",
        "actionable_exception": False,
        "severity": "warn",
        "redirect_to": "lar_orders@keysight.com",
        "predicates": [
            {"kind": "sender_equals", "value": ["keysight.bra-tax@tmf-group.com"]},
        ],
    },
    {
        "key": "outlook.kso",
        "label": "KSO — Government / Defense / Federal-Prime",
        "description": (
            "Government / defense customer email — ITAR/EAR compliance. "
            "Redirect to keysightorders@keysight.com. Strict string match only — "
            "no LLM call on these emails."
        ),
        "priority": 40,
        "enabled": True,
        "intent": "kso",
        "actionable_exception": False,
        "severity": "hard_block",
        "redirect_to": "keysightorders@keysight.com",
        "predicates": [
            {"kind": "sender_domain", "value": [
                "lmco.com", "fastx.com", "l3harris.com", "us.af.mil",
                "caci.com", "boeing.com", "ngc.com", "gov.in",
                "testmart.com", "nasa.gov", "baesystems.com", "tevet.com",
            ]},
            {"kind": "body_contains", "value": [
                "N5194A", "N5193A", "N5192A", "N5191A",
                "Boeing", "Sandia", "Tevet", "Peraton",
                "Vallen", "Leidos", "Raytheon", "Pratt Whitney",
                "Cobham", "General Dynamics",
            ]},
        ],
    },
    {
        "key": "outlook.collections",
        "label": "Collections / Remittance",
        "description": "Payment / remittance / banking notifications. Redirect to Collections team.",
        "priority": 50,
        "enabled": True,
        "intent": "collections",
        "actionable_exception": True,
        "severity": "warn",
        "redirect_to": "collections.pdl-americas@keysight.com",
        "predicates": [
            {"kind": "subject_contains", "value": [
                "Remittance Advice",
                "Payment Advice",
                "Payment Remittance Advice",
                "Notice of new scheduled payment",
                "Notice of new Remittance Advice",
                "ACH Payment Remittance Advice",
                "You got paid by Energy Medical Systems",
                "early payment opportunity",
                "GOOGLE PAYMENT NOTIFICATION",
            ]},
            {"kind": "subject_equals", "value": [
                "Your invoice(s) have been received and may require additional attention",
            ]},
            {"kind": "body_contains", "value": [
                "Remittance Advice",
                "Payment Advice",
                "ACH Payment",
            ]},
        ],
    },
    {
        "key": "outlook.portal_admin",
        "label": "Portal / SSO / Verification Codes",
        "description": "Portal verification, OTP, password reset emails. Redirect to portal-admin.",
        "priority": 60,
        "enabled": True,
        "intent": "portal_admin",
        "actionable_exception": True,
        "severity": "warn",
        "redirect_to": "portal-admin.pdl-ccc-americas@keysight.com",
        "predicates": [
            {"kind": "subject_contains", "value": [
                "Password",
                "validation code",
                "verification code",
                "one-time password",
                "OTP",
            ]},
            {"kind": "body_contains", "value": [
                "verification code",
                "authentication code",
                "one-time password",
                "OTP",
                "valid for",
                "expires in",
                "password reset link",
                "reset your password",
            ]},
        ],
    },
]


def all_rules() -> list[dict]:
    """Returns the canonical rule list. Used by kb.seed_defaults via _seed_namespace_from_list."""
    return OUTLOOK_RULES
# === v1.1 TASK-2 END ===
