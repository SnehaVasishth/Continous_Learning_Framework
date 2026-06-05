# Build queue — remaining work after audit

**Audience:** the agent building the keysight-salesops-demo (any session). Read this end-to-end before starting; each task is self-contained with file paths, schemas, verbatim KB content, acceptance criteria, and test plan. Pair with [RESEARCH_BRIEF.md](RESEARCH_BRIEF.md) (the why and the source-of-truth gap analysis) and [SESSION_HANDOFF.md](SESSION_HANDOFF.md) (active lane coordination).

**Generated from:** end-to-end audit on 2026-05-10 of the gap list shipped in `RESEARCH_BRIEF.md`. The audit found 8 items done, 4 partial, 5 missing — this document tells you exactly what's left.

**Demo deadline:** 2026-05-10 (today). Triage accordingly.

---

## TL;DR — priority-ordered queue

| Priority | Task | What it is | Effort | Lane |
|----------|------|------------|--------|------|
| **P0** | [TASK-1](#task-1--add-5-missing-first-class-intents) | Add 5 RFP-required first-class intents (KSO, COLLECTIONS, PORTAL_ADMIN, BRAZIL_TAX, UNDELIVERABLE) | 1.5–2 hrs | Session A (KB + classify) |
| **P0** | [TASK-2](#task-2--pre-ai-deterministic-outlook-rules-stage) | Pre-AI Outlook rules stage (6 deterministic rules running before Stage 1) | 3–4 hrs | Session A (new agent stage) |
| **P0** | [TASK-3](#task-3--empty-fragment-thread-pre-processing) | Empty-fragment thread pre-processing (skip empty forwards / banners / disclaimers, walk back to first valid fragment) | 1.5–2 hrs | Shared (`email_thread.py` + classify entry point) |
| **P1** | [TASK-4](#task-4--existing-ccc-status-branch) | Existing-CCC status branch (lookup by PO#/WO#, branch on 9 case statuses) | 3–4 hrs | Mine (Salesforce service) + Session A (Decide stage) |
| **P1** | [TASK-5](#task-5--distributor-list--magic-sku-routing-rules) | Distributor partner list + magic-SKU routing rules (CUSTOM PRODUCT / SOWDUMMY / EXPORTDUMMY) | 2 hrs | Session A (new KB seed) |
| **P1** | [TASK-6](#task-6--region-aware-rule-pack-wiring) | Make `regions` field functional (filter intent definitions by account/customer region) | 2 hrs | Session A (classify_intent) |
| **P2** | [TASK-7](#task-7--test-corpus-regression-page) | Test-corpus regression page (Initial Pass / Failed / Post-Fix Pass / Still Failed) | 4–5 hrs | Mine (models + route + page) |
| **P2** | [TASK-8](#task-8--msg-attachment-unrolling) | `.msg` attachment unrolling (extract embedded Outlook items as sub-emails) | 2–3 hrs | Mine (IMAP) + Session A (extract tool) |
| **P3** | [TASK-9](#task-9--third-shadow-test-classifier-slot) | Third "shadow test classifier" slot (run alongside Context+Override, log side-by-side) | 2 hrs | Session A |

**Recommended cut-line:** if compressed, do **TASK-1, 2, 3** at minimum. They are the items Keysight will visibly notice are missing because their prior POC already does these.

---

## Dependency graph

```
TASK-1 (5 missing intents) ─┬─→ TASK-2 (rules layer can target these intents)
                            └─→ TASK-3 (override-pass over the right intent set)

TASK-3 (empty-fragment skip) ──→ TASK-2 (pre-AI rules see clean fragments too)

TASK-4 (existing-CCC) ──→ depends on the 5 new intents being able to *be* SALES_PO/ISC_WO_RTK
                            (TASK-1) for accurate PO-vs-WO lookup branching

TASK-5 (disty + magic SKUs) — independent
TASK-6 (region wiring)      — depends on TASK-1 (need the intents in place to filter)
TASK-7 (test corpus)        — independent
TASK-8 (.msg unrolling)     — independent
TASK-9 (shadow A/B)         — independent
```

**Critical path:** TASK-3 → TASK-1 → TASK-2 → (TASK-4 ‖ TASK-5 ‖ TASK-6).

---

## TASK-1 — Add 5 missing first-class intents

**Problem.** Audit showed `INTENT_TO_CATEGORY` dict maps the 13 internal intents to a 9-category RFP taxonomy. But **the classifier cannot return KSO / COLLECTIONS / PORTAL_ADMIN / BRAZIL_TAX / UNDELIVERABLE** as primary intents — they only exist as downstream category labels. The Override-pass tool can't revise *to* these categories either, because they're not in `INTENTS`. This blocks the entire 9-class taxonomy ambition.

**Why it matters.** RFP and call explicitly call out these as separate handling buckets:
- KSO redirects to `keysightorders@keysight.com` (govt/defense compliance).
- COLLECTIONS redirects to `collections.pdl-americas@keysight.com`.
- PORTAL_ADMIN redirects to `portal-admin.pdl-ccc-americas@keysight.com`.
- BRAZIL_TAX redirects to `lar_orders@keysight.com`.
- UNDELIVERABLE → discard.

Without first-class intents, the agent can't *route* to these correctly — it'll classify a Remittance Advice email as `general_inquiry` and try to respond to it. Wrong.

### Files to touch

| File | Change |
|------|--------|
| `backend/app/config.py` | Add 5 keys to `INTENTS`, `INTENT_DESCRIPTIONS`, `INTENT_TO_FLOW`. Add `TERMINAL_INTENTS` entries for `undeliverable`. |
| `backend/app/kb_seeds/intent_definitions_v2.py` | Add 5 fully-structured intent records with verbatim keywords/sender_patterns from the prior POC's 25KB override prompt. Update `INTENT_TO_CATEGORY` (likely no-op since names match). |
| `backend/app/agents/tools/classify_intent_tool.py` | Verify the intent JSON-schema enum is built from `INTENTS` dynamically (it should be). |
| `backend/app/agents/tools/override_pass_tool.py` | Same — verify `revised_intent` allowed values include the 5 new intents. |
| `backend/app/agents/orchestrator.py` | When the chosen intent is `kso`, `collections`, `portal_admin`, `brazil_tax`, or `undeliverable`, **skip Stages 2-6** (similar to existing `TERMINAL_INTENTS = {"spam", "out_of_scope"}` short-circuit), back-stamp to the matching folder, log a CommunicationLog entry indicating the redirect destination. |
| `backend/app/services/imap_back_stamp.py` | Verify `_INTENT_TO_CATEGORY` dict already routes these correctly (it does — see `DEFAULT_FOLDER_MAP`). Add the 5 new intents to that dict so back-stamping picks the right folder. |

### Verbatim KB content to seed

Each new intent's record in `intent_definitions_v2.py`:

```python
"kso": {
    "category": "KSO",
    "track_hint": "discarded",  # short-circuit; no Stage 2-6
    "priority": 0,  # check FIRST in stop-at-first-match
    "regions": ["GLOBAL"],
    "description": (
        "Government / defense / federal-prime customer email. Handled by a "
        "different team for compliance reasons (ITAR/EAR/DFARS). Agent "
        "does NOT auto-respond — redirects to keysightorders@keysight.com."
    ),
    "keywords": [
        "N5194A", "N5193A", "N5192A", "N5191A",
        "Boeing", "Sandia", "Tevet", "Peraton",
        "Vallen", "Leidos", "Raytheon", "Pratt Whitney",
        "Cobham", "General Dynamics",
    ],
    "sender_patterns": [
        "@lmco.com", "@fastx.com", "@l3harris.com", "@us.af.mil",
        "@caci.com", "@boeing.com", "@ngc.com", "@gov.in",
        "@testmart.com", "@nasa.gov", "@baesystems.com", "@tevet.com",
    ],
    "examples_positive": [
        "From: orders@boeing.com — please quote N5194A for our defense lab.",
        "Email body mentions 'Raytheon' and 'Peraton' as end customers.",
    ],
    "examples_negative": [
        "Email mentions 'Raytheon' only inside the email signature footer — NOT KSO.",
    ],
    "exceptions": [
        "Override-prompt KSO Rule — strict string/keyword match only. Do NOT infer "
        "intent based on tone or industry. If a KSO domain or keyword is matched, "
        "classify as KSO regardless of any other rule that might match.",
    ],
    "exclusions": [],
    "redirect_to": "keysightorders@keysight.com",
},
"collections": {
    "category": "COLLECTIONS",
    "track_hint": "discarded",
    "priority": 4,  # after KSO/AUTO_REPLY/BRAZIL_TAX
    "regions": ["GLOBAL"],
    "description": (
        "Payment / remittance / banking notification email. Handled by the "
        "Collections team. Agent does not process — redirects to "
        "collections.pdl-americas@keysight.com + usar_keysight@keysight.com."
    ),
    "keywords": [
        "Remittance Advice",
        "Payment Advice",
        "Payment Remittance Advice",
        "Notice of new scheduled payment",
        "Notice of new Remittance Advice",
        "ACH Payment Remittance Advice",
        "You got paid by Energy Medical Systems",
        "early payment opportunity",
        "GOOGLE PAYMENT NOTIFICATION",
        "Your invoice(s) have been received and may require additional attention",
        "ACH setup",
        "test deposit",
        "bank verification",
        "account summary",
        "statement request",
        "authorization letter",
        "zero balance",
        "accounts receivable",
    ],
    "sender_patterns": [],
    "examples_positive": [
        "Subject: Remittance Advice — payment of $24,000.00 made via ACH on 2026-05-08.",
        "Subject: ACH Payment Remittance Advice — payment confirmation for invoices listed.",
    ],
    "examples_negative": [
        "Email mentions 'Net 30 payment terms' only in the disclaimer footer — NOT collections.",
    ],
    "exceptions": [
        "Override Rule 4 — payment terms appearing only in disclaimers/footers/signatures "
        "do NOT trigger COLLECTIONS.",
        "Override Rule 21A — payment-method or bank-account verification (ACH test deposit, "
        "payment onboarding) takes precedence over PORTAL_ADMIN.",
    ],
    "exclusions": [],
    "redirect_to": "collections.pdl-americas@keysight.com,usar_keysight@keysight.com",
},
"portal_admin": {
    "category": "PORTAL_ADMIN",
    "track_hint": "discarded",
    "priority": 5,
    "regions": ["GLOBAL"],
    "description": (
        "Portal / SSO / login-verification system message — password reset, "
        "OTP, verification code. Agent doesn't act — redirects to "
        "portal-admin.pdl-ccc-americas@keysight.com."
    ),
    "keywords": [
        "Password",
        "validation code",
        "verification code",
        "one-time password",
        "OTP",
        "authentication code",
        "login code",
        "password reset link",
        "reset your password",
        "account activation",
        "verify your email",
        "email confirmation",
        "Use this code to log in",
        "access the portal with",
    ],
    "sender_patterns": [],
    "examples_positive": [
        "Subject: Your verification code is 123456 — valid for 10 minutes.",
        "Body: Click here to reset your password — link expires in 1 hour.",
    ],
    "examples_negative": [
        "Subject: ACH test deposit verification (this is COLLECTIONS via Rule 21A, not PORTAL_ADMIN).",
    ],
    "exceptions": [
        "Override Rule 21A — if the verification context is about payment / bank account / "
        "ACH setup, classify as COLLECTIONS instead.",
    ],
    "exclusions": [],
    "redirect_to": "portal-admin.pdl-ccc-americas@keysight.com",
},
"brazil_tax": {
    "category": "BRAZIL_TAX",
    "track_hint": "discarded",
    "priority": 3,
    "regions": ["AMS"],  # Latin-America Region
    "description": (
        "Brazilian tax document email (Nota Fiscal, NF-e, ICMS, CFOP). "
        "Handled by LAR Orders team. Agent doesn't process — redirects to "
        "lar_orders@keysight.com."
    ),
    "keywords": [
        "Brazil Tax",
        "TMF Group",
        "Nota Fiscal",
        "NF-e",
        "NFe",
        "CNPJ",
        "ICMS",
        "CFOP",
    ],
    "sender_patterns": [
        "keysight.bra-tax@tmf-group.com",
        "@gmail.com",  # Override prompt explicit: gmail.com sender → BRAZIL_TAX
    ],
    "examples_positive": [
        "From: keysight.bra-tax@tmf-group.com — Subject: NF-e 12345 emitida.",
        "Body contains: CNPJ 12.345.678/0001-90 — ICMS calculation attached.",
    ],
    "examples_negative": [
        "From: collections@third-party.com mentions 'Remittance Advice' — that's COLLECTIONS not BRAZIL_TAX.",
    ],
    "exceptions": [
        "Override Rule 3 (BRAZIL_TAX) — if email is clearly about general remittance/payment "
        "advice, classify as COLLECTIONS instead.",
    ],
    "exclusions": [],
    "redirect_to": "lar_orders@keysight.com",
},
"undeliverable": {
    "category": "UNDELIVERABLE",
    "track_hint": "discarded",
    "priority": 1,  # check before everything except KSO
    "regions": ["GLOBAL"],
    "description": (
        "Bounce / DSN / mail-delivery-failure notification. Discarded — no "
        "customer-facing reply needed. Stored for audit, moved to "
        "Undeliverable folder."
    ),
    "keywords": [
        "Undeliverable",
        "Mail Delivery Failure",
        "Delivery Failure",
        "Returned Mail",
        "Delivery Status Notification",
        "Non-Delivery Report",
        "Failed Delivery",
        "Undelivered Mail Returned to Sender",
        "[Postmaster] Email Delivery Failure",
        "Mail Delivery Failed",
        "Delivery Delayed",
        "DELIVERY FAILURE",
        "Delivery delayed: Keysight Support Web Email Update",
        "You have some new Bonfire matches!",
        "5.1.1 User unknown",
        "550 5.",
        "Diagnostic-Code: smtp;",
        "Action: failed",
    ],
    "sender_patterns": [
        "mailer-daemon",
        "noreply@keysight.com",
        "postmaster@",
        "MAILER-DAEMON@",
    ],
    "examples_positive": [
        "From: mailer-daemon@gmail.com — Subject: Delivery Status Notification (Failure).",
        "From: noreply@keysight.com — Subject: Mail Delivery Failed.",
    ],
    "examples_negative": [
        "Email forwarded by a customer that quotes a bounce notification but contains a "
        "user-written business request — classify on the business request, NOT UNDELIVERABLE.",
    ],
    "exceptions": [
        "Override Rule 6 — UNDELIVERABLE only when the latest senderEmail is exactly "
        "noreply@keysight.com or mailer-daemon. Do not match on quoted/forwarded sender info.",
        "Override 'Actionable Content Exception' — if the same fragment includes a clear "
        "business instruction or user request, do NOT classify as UNDELIVERABLE.",
    ],
    "exclusions": [],
    "redirect_to": null,  # discard-only, no forward
},
```

Add to `INTENT_TO_CATEGORY` (already in file but verify):

```python
INTENT_TO_CATEGORY: dict[str, str] = {
    # existing 13...
    "kso": "KSO",
    "collections": "COLLECTIONS",
    "portal_admin": "PORTAL_ADMIN",
    "brazil_tax": "BRAZIL_TAX",
    "undeliverable": "UNDELIVERABLE",
}
```

Add to `config.py`:

```python
INTENTS = [
    # existing 13 keys...
    "kso",
    "collections",
    "portal_admin",
    "brazil_tax",
    "undeliverable",
]

# Intents that short-circuit Stages 2-6 (mailbox redirect / discard).
TERMINAL_INTENTS = {"spam", "out_of_scope", "kso", "collections", "portal_admin", "brazil_tax", "undeliverable"}

INTENT_DESCRIPTIONS = {
    # existing...
    "kso": "Government / defense / federal-prime customer — redirect to keysightorders@",
    "collections": "Payment / remittance / banking notification — redirect to collections.pdl-americas@",
    "portal_admin": "Portal / SSO / verification-code system message — redirect to portal-admin.pdl",
    "brazil_tax": "Brazilian tax document (NF-e / Nota Fiscal) — redirect to lar_orders@",
    "undeliverable": "Bounce / DSN / mail-delivery-failure — discard",
}

INTENT_TO_FLOW = {
    # existing...
    "kso": "redirected",
    "collections": "redirected",
    "portal_admin": "redirected",
    "brazil_tax": "redirected",
    "undeliverable": "discarded",
}
```

### Orchestrator short-circuit

In `orchestrator.py`, where `TERMINAL_INTENTS` is checked, extend the handling so each redirect intent:
1. Logs trace event `pre_intake.redirect` with `redirect_to` from KB.
2. Writes a `CommunicationLog` entry with `delivery_status="redirected"`, `direction="redirected"`, `note=f"would forward to {redirect_to}"`.
3. Calls `imap_back_stamp.back_stamp_pipeline_email(...)` — the back-stamp service's `_INTENT_TO_CATEGORY` already maps these correctly via `DEFAULT_FOLDER_MAP`.
4. Sets `pipeline.status = "completed"` (not "discarded") — these are *handled*, just not by the agent pipeline.
5. Marks `email.status = "redirected"` (new value) so the Inbox dropdown can filter on it. Add `redirected` to `KNOWN_STATUSES` in `routes/emails.py`.

> **Demo-safety note:** the redirect should *flag* "would forward to X" not actually SMTP-send to a real Keysight DL. Production would actually forward; demo just records the intent.

### Acceptance criteria

1. `GET /api/kb/intent` returns 18 intent records (13 existing + 5 new).
2. Run pipeline on these test emails (synthesize via `synthetic/generate.py`):
   - **KSO:** sender `procurement@boeing.com`, subject "Quote needed for N5194A" → intent=`kso`, category=`KSO`, status=`redirected`, IMAP-moved to "ZBrain/Government" folder.
   - **COLLECTIONS:** subject "ACH Payment Remittance Advice — invoice 12345" → intent=`collections`.
   - **PORTAL_ADMIN:** subject "Your verification code is 123456" → intent=`portal_admin`.
   - **BRAZIL_TAX:** sender `keysight.bra-tax@tmf-group.com`, subject "NF-e 9876 emitida" → intent=`brazil_tax`.
   - **UNDELIVERABLE:** sender `mailer-daemon@gmail.com`, subject "Mail Delivery Failed" → intent=`undeliverable`, status=`discarded`.
3. Override-pass can revise *to* one of these — e.g., a `general_inquiry` initial classification with sender `boeing.com` → override-pass returns `revised_intent="kso"`.
4. Inbox status dropdown shows "Redirected (n)" option that filters correctly.
5. Trace event `pre_intake.redirect` appears in the trace timeline for each redirect.

---

## TASK-2 — Pre-AI deterministic Outlook rules stage

**Problem.** Keysight wrote 6 deterministic Outlook rules that fire *before* any AI in their current production setup. Our pipeline currently runs the LLM classifier on every email, including bounces, OOO replies, and govt-domain mail that should never reach the AI. **Wastes tokens, ignores Keysight's existing operational behavior, and the demo CSR will spot the missing layer immediately.**

**Why it matters.** This is the single most-visible omission. Their Outlook PDF lays out the 6 rules with verbatim keyword lists. A demo that doesn't show "we adopted your existing Outlook rules as-is, just made them KB-tunable" is a tell.

### Architecture

Add a new pipeline stage **before** Stage 1 Intake:

```
[Inbound email]
   ↓
Stage 0 — Pre-Intake (deterministic, no LLM)
   ├─ Match each rule (Undeliverable / KSO / Collections / Portal Admin / Brazil Tax / Auto Reply)
   ├─ First match wins; emit `pre_intake.matched_rule`
   └─ Two outcomes:
       a. Match → short-circuit: route to redirect mailbox, back-stamp folder, end pipeline
       b. No match → continue to Stage 1
   ↓
Stage 1 — Intake (LLM classifier, only when Stage 0 didn't match)
   ↓
... rest of pipeline
```

This is **deterministic** — string matching, regex, sender-domain checks. No LLM call. Saves tokens AND mirrors Keysight's existing behavior exactly.

### Files

| File | Change |
|------|--------|
| `backend/app/kb_seeds/outlook_rules.py` (new) | Seed the 6 rules with verbatim predicates from the Outlook PDF |
| `backend/app/kb.py` | Register new namespace `outlook_rules` |
| `backend/app/agents/pre_intake.py` (new) | Pure-Python rule engine that evaluates KB `outlook_rules` against an email |
| `backend/app/agents/orchestrator.py` | Call `pre_intake.evaluate()` before `stage1_intake_agent.run()`. On match, short-circuit. |
| `backend/app/routes/kb.py` | Confirm new namespace surfaces via `GET /api/kb/outlook_rules` |
| `frontend/src/pages/KnowledgeBase.tsx` | New tab "Outlook Rules" (mirrors existing `spam_heuristic` tab pattern) |

### KB seed — `backend/app/kb_seeds/outlook_rules.py`

```python
"""Pre-AI deterministic Outlook rules (Stage 0).

Mirrors the prior Keysight POC's six Outlook rules verbatim, just stored
in KB so operators can tune without a code change. Each rule has:

  - `key`           — short id (e.g., "outlook.undeliverable")
  - `display_name`  — human label
  - `description`   — what this rule does
  - `priority`      — lower = checked first; first match wins
  - `enabled`       — operator can disable per-rule
  - `predicates`    — list of OR'd conditions, each with:
        - kind: "subject_contains" | "subject_equals" | "body_contains"
                | "sender_equals" | "sender_contains" | "sender_domain"
                | "to_contains" | "regex_subject" | "regex_body"
        - value: string or list of strings (any-match)
        - case_sensitive: bool (default false)
  - `intent`        — which TASK-1 intent to assign on match
                      (kso / collections / portal_admin / brazil_tax /
                       undeliverable / out_of_scope)
  - `redirect_to`   — destination mailbox (already on the intent record;
                      duplicated here for the rule's own reference)
  - `actionable_exception` — if true, do not match this rule when the
                      same fragment contains a clear business instruction
                      (mirrors the prior POC's "actionable content" exceptions)
"""
from __future__ import annotations


OUTLOOK_RULES: list[dict] = [
    {
        "key": "outlook.undeliverable",
        "display_name": "Undeliverable / DSN / Bounce",
        "priority": 10,
        "enabled": True,
        "intent": "undeliverable",
        "actionable_exception": True,
        "predicates": [
            {"kind": "subject_contains", "value": [
                "Undeliverable",
                "Undelivered Mail Returned to Sender",
                "[Postmaster] Email Delivery Failure",
                "Returned Mail: see transcript for details",
                "You have some new Bonfire matches!",
                "Your message couldn’t be delivered",
                "Your message couldn't be delivered",
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
        "display_name": "Auto-Reply / OOO",
        "priority": 20,
        "enabled": True,
        "intent": "out_of_scope",  # quarantine, like spam
        "actionable_exception": True,
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
        "display_name": "Brazil Tax (TMF Group)",
        "priority": 30,
        "enabled": True,
        "intent": "brazil_tax",
        "actionable_exception": False,
        "predicates": [
            {"kind": "sender_equals", "value": ["keysight.bra-tax@tmf-group.com"]},
        ],
    },
    {
        "key": "outlook.kso",
        "display_name": "KSO — Government / Defense / Federal-Prime",
        "priority": 40,
        "enabled": True,
        "intent": "kso",
        "actionable_exception": False,
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
        "display_name": "Collections / Remittance",
        "priority": 50,
        "enabled": True,
        "intent": "collections",
        "actionable_exception": True,
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
        "display_name": "Portal / SSO / Verification Codes",
        "priority": 60,
        "enabled": True,
        "intent": "portal_admin",
        "actionable_exception": True,
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


def seed_default_outlook_rules(db) -> int:
    from ..models import KnowledgeRule
    inserted = 0
    for rule in OUTLOOK_RULES:
        existing = db.query(KnowledgeRule).filter_by(
            namespace="outlook_rules", key=rule["key"]
        ).first()
        if existing:
            continue
        db.add(KnowledgeRule(
            namespace="outlook_rules",
            key=rule["key"],
            display_name=rule["display_name"],
            severity="hard_block" if rule["intent"] == "undeliverable" else "warn",
            data=rule,
            enabled=rule["enabled"],
        ))
        inserted += 1
    db.commit()
    return inserted
```

### Engine — `backend/app/agents/pre_intake.py`

```python
"""Pre-Intake (Stage 0) — deterministic Outlook-rule short-circuit.

Runs BEFORE Stage 1 Intake. If any KB outlook_rules rule matches, short-circuit
the pipeline and route to the rule's redirect destination. No LLM. No tokens.

The rule predicates are pure string/regex matching. The actionable-exception
guard is the one piece of LLM-style heuristic — it's a quick string scan for
'directive' verbs (please, kindly, find attached, requesting, ship, cancel,
update, process, release, schedule, expedite). When found in the same body
the rule matched on, the rule is suppressed and the pipeline continues to
Stage 1 (which will figure out the actual intent).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from .. import kb
from ..models import Email
from ..tracing import bus

log = logging.getLogger(__name__)

_DIRECTIVE_PATTERNS = re.compile(
    r"\b(please|kindly|find\s+attached|requesting|request\s+to|ship|cancel|"
    r"update|process|release|schedule|expedite|approve|book|confirm|"
    r"acknowledge|issue\s+(soa|order)|return|exchange|repair|calibrate)\b",
    re.IGNORECASE,
)


def _check_directive(text: str) -> bool:
    return bool(_DIRECTIVE_PATTERNS.search(text or ""))


def _domain(addr: str) -> str:
    addr = (addr or "").lower()
    m = re.search(r"@([\w.-]+)", addr)
    return m.group(1) if m else ""


def _match_predicate(pred: dict, email: Email) -> bool:
    kind = pred.get("kind", "")
    values = pred.get("value", [])
    if isinstance(values, str):
        values = [values]
    cs = pred.get("case_sensitive", False)
    subj = email.subject or ""
    body = email.body or ""
    sender = email.from_address or ""
    if not cs:
        subj_l, body_l, sender_l = subj.lower(), body.lower(), sender.lower()
        values = [v.lower() for v in values]
    else:
        subj_l, body_l, sender_l = subj, body, sender

    if kind == "subject_contains":
        return any(v in subj_l for v in values)
    if kind == "subject_equals":
        return subj_l.strip() in [v.strip() for v in values]
    if kind == "body_contains":
        return any(v in body_l for v in values)
    if kind == "sender_equals":
        return sender_l.strip() in [v.strip() for v in values]
    if kind == "sender_contains":
        return any(v in sender_l for v in values)
    if kind == "sender_domain":
        d = _domain(sender)
        return any(d == v.strip() or d.endswith("." + v.strip()) for v in values)
    if kind == "regex_subject":
        return any(re.search(v, subj, 0 if cs else re.IGNORECASE) for v in values)
    if kind == "regex_body":
        return any(re.search(v, body, 0 if cs else re.IGNORECASE) for v in values)
    return False


def evaluate(db: Session, email: Email, *, pipeline_id: int | None = None) -> dict[str, Any] | None:
    """Returns {matched, rule_key, intent, redirect_to, reason} on first match, else None."""
    rules = sorted(
        kb.list_rules(db, namespace="outlook_rules", enabled_only=True),
        key=lambda r: r.data.get("priority", 999),
    )
    body = email.body or ""
    has_directive = _check_directive(body)

    for rule in rules:
        data = rule.data or {}
        preds = data.get("predicates", [])
        if not preds:
            continue
        # OR within rule — first matching predicate fires
        matched_pred = None
        for p in preds:
            if _match_predicate(p, email):
                matched_pred = p
                break
        if matched_pred is None:
            continue

        # Actionable exception — if rule allows it AND body has a directive,
        # suppress this rule (let the LLM classifier handle it).
        if data.get("actionable_exception", False) and has_directive:
            log.info(
                "pre_intake suppressed rule %s due to actionable directive in body",
                rule.key,
            )
            continue

        result = {
            "matched": True,
            "rule_key": rule.key,
            "rule_display_name": rule.display_name,
            "intent": data.get("intent"),
            "redirect_to": data.get("redirect_to"),
            "predicate_kind": matched_pred.get("kind"),
            "reason": (
                f"Pre-intake rule {rule.key} matched on {matched_pred.get('kind')} "
                f"({rule.display_name})"
            ),
        }
        bus.publish(pipeline_id, {
            "stage": "pre_intake",
            "kind": "rule_matched",
            "message": f"Pre-intake rule matched: {rule.display_name}",
            "data": result,
        })
        return result

    return None
```

### Orchestrator wiring

In `orchestrator.py`, **before** calling `stage1_intake_agent.run`:

```python
from . import pre_intake

# ... inside run_pipeline ...
pre_match = pre_intake.evaluate(db, email_row, pipeline_id=pipe.id)
if pre_match:
    # Short-circuit: assign intent, redirect, back-stamp, end.
    pipe.intent = pre_match["intent"]
    pipe.autonomy_tier = "L4_AUTO"  # deterministic = high-confidence
    pipe.confidence = 1.0
    pipe.status = "completed"
    pipe.execution = {
        **(pipe.execution or {}),
        "pre_intake_match": pre_match,
        "redirect_to": pre_match.get("redirect_to"),
    }
    email_row.status = "redirected" if pre_match.get("redirect_to") else "discarded"
    db.commit()
    _back_stamp_safe(db, pipe.id)
    return pipe.id
```

### KnowledgeBase UI tab

Mirror the existing `spam_heuristic` tab in `KnowledgeBase.tsx`:
- New tab "Outlook Rules"
- Each row shows: `display_name`, `priority`, `intent`, `enabled` toggle, `actionable_exception` toggle, predicate count.
- Click row → expand to show predicate list (kind + value array, editable).
- Drag-handle to reorder priority.

### Acceptance criteria

1. Restart backend → KB reseed creates 6 records under namespace `outlook_rules`.
2. Run pipeline on an inbound email with `subject="Mail Delivery Failed"` and sender `mailer-daemon@gmail.com`:
   - Trace shows new stage `pre_intake` event before `intake`.
   - Pipeline `intent="undeliverable"`, `confidence=1.0`, `autonomy_tier="L4_AUTO"`, `status="completed"`.
   - Stages 1-6 are NOT in the trace.
   - Email moved to "ZBrain/Undeliverable" folder.
   - Trace `data.pre_intake_match.rule_key == "outlook.undeliverable"`.
3. Run pipeline on `subject="ACH Payment Remittance Advice"` BUT body contains "Please process this remittance and confirm":
   - Pre-intake rule matches the subject AND `has_directive=True` → rule is **suppressed**.
   - Falls through to Stage 1 LLM classifier.
   - Classifier still likely returns `collections` (because of TASK-1's keyword KB), but routing decision came from LLM not deterministic rule.
4. Frontend `Settings → Knowledge Base → Outlook Rules` tab renders 6 rows; toggling `enabled=false` on `outlook.brazil_tax` causes a Brazilian-tax email to fall through to the LLM instead.
5. New trace event `pre_intake.rule_matched` (and an absence event `pre_intake.no_match` when nothing matches) is observable in `frontend/src/pages/Trace.tsx`.

---

## TASK-3 — Empty-fragment thread pre-processing

**Problem.** The override-pass prompt (TASK-1's `exceptions` referenced rules) explicitly assumes the input has been **pre-processed to skip empty forwards / banner-only fragments / disclaimer-only quotes** and pass only the *first valid fragment* to the LLM. Currently we send the entire body string. Override-pass is operating on input it wasn't designed for, producing different (worse) outputs.

**Why it matters.** This is the foundation under TASK-1 and TASK-2's actionable-exception logic. Without it:
- "FYI — see below" (with a buried real PO request beneath) → LLM classifies as OTHERS instead of looking deeper.
- A bare forwarded acknowledgment with no new content → LLM might classify on the quoted-old-content instead of recognizing it's empty.
- Banner / disclaimer noise pollutes the prompt.

### Files

| File | Change |
|------|--------|
| `backend/app/services/email_thread.py` | Add `pick_first_valid_fragment(body, thread)` and `is_meaningful_fragment(text)` helpers |
| `backend/app/agents/intake.py` | When building the prompt for `classify_intent`, call `pick_first_valid_fragment` and use that as the primary signal — keep the full body available as `email.full_body` for the override-pass |
| `backend/app/agents/tools/classify_intent_tool.py` | Update prompt template to refer to `latest_valid_fragment` and `full_thread_for_context` |
| `backend/app/agents/tools/override_pass_tool.py` | Same — input gets both fields |

### Helper signatures

```python
# email_thread.py

import re

_BANNER_PATTERNS = [
    re.compile(r"\bCAUTION\s*:.*?external\s+sender", re.IGNORECASE | re.DOTALL),
    re.compile(r"This e-?mail (and any attachments)? is.*confidential", re.IGNORECASE | re.DOTALL),
    re.compile(r"DISCLAIMER\s*:", re.IGNORECASE),
    re.compile(r"This message is intended only for", re.IGNORECASE),
]

_GENERIC_PHRASES = [
    "fyi", "for your information", "just a reminder", "please check below",
    "see previous message", "check earlier email", "sharing for visibility",
    "per our earlier discussion", "looping you in", "forwarding for reference",
    "see below", "see attached",
]

_FROM_HEADER = re.compile(r"^\s*From:\s+", re.IGNORECASE | re.MULTILINE)


def is_meaningful_fragment(text: str) -> bool:
    """Returns True if the fragment has user-written or system-generated business content.

    A fragment is NOT meaningful if it contains only:
      - From/To/Subject headers (and nothing else)
      - Banner/disclaimer/CAUTION text
      - Empty forwards (only quoted older content with no new text)
      - Generic context-free phrases (FYI, Thanks, Noted)
    """
    if not text:
        return False
    s = text.strip()
    if len(s) < 30:
        # Too short to carry business intent
        if s.lower() in {"thanks", "thank you", "noted", "ok", "fyi", "test", "hello", "hi"}:
            return False
        return False

    # Strip banners/disclaimers
    cleaned = s
    for pat in _BANNER_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = cleaned.strip()

    # If only the From/To/Subject headers remain, not meaningful
    no_headers = _FROM_HEADER.sub("", cleaned).strip()
    if len(no_headers) < 30:
        return False

    # If the fragment is only generic phrases, not meaningful
    lower = cleaned.lower()
    generic_only = all(
        ph in lower for ph in _GENERIC_PHRASES if ph in lower
    ) and len(cleaned) < 200
    if generic_only:
        return False

    return True


def split_thread_fragments(body: str) -> list[str]:
    """Split a thread body into per-message fragments using From: as delimiter.

    Returns fragments in CHRONOLOGICAL order with newest first (matching the
    typical Outlook reply-quoting style: latest message at top, oldest at bottom).
    """
    if not body:
        return []
    # Split on From: but keep the From: line in the next fragment
    parts = _FROM_HEADER.split(body)
    # First part is the latest reply (no From: header above it)
    fragments = [parts[0]]
    for p in parts[1:]:
        fragments.append(("From: " + p).strip())
    return [f.strip() for f in fragments if f.strip()]


def pick_first_valid_fragment(body: str) -> tuple[str, int]:
    """Walk fragments newest-first, return (fragment, index_from_top).

    Returns ('', -1) if no valid fragment found in entire thread.
    """
    fragments = split_thread_fragments(body)
    for i, frag in enumerate(fragments):
        if is_meaningful_fragment(frag):
            return frag, i
    return ("", -1)
```

### Wiring into intake

```python
# In agents/intake.py or stage1_intake_agent.py — wherever the classify_intent
# prompt is built:

from ..services.email_thread import pick_first_valid_fragment

latest_valid, frag_index = pick_first_valid_fragment(email.body or "")
ctx.intake["latest_valid_fragment"] = latest_valid
ctx.intake["latest_valid_fragment_index"] = frag_index
ctx.intake["full_thread_body"] = email.body or ""
```

Then the classify_intent prompt template should distinguish:
- `latest_valid_fragment` — the primary classification signal
- `full_thread_body` — fallback context if `latest_valid_fragment` is empty

### Acceptance criteria

1. Unit test:
   ```python
   body = "FYI — see below.\n\nFrom: customer@aurora.com\nSubject: PO-99887\n\nPlease process the attached PO."
   frag, idx = pick_first_valid_fragment(body)
   assert "Please process the attached PO" in frag
   assert idx == 1  # walked past the empty "FYI" first fragment
   ```
2. Trace UI shows new fields under Stage 1 sub-step input: `latest_valid_fragment`, `latest_valid_fragment_index`.
3. Run pipeline on a synthesized "FYI — see below" forward of a real PO email → classifier returns `po_intake` (not `general_inquiry`), because the prompt operated on the buried PO directive, not the FYI wrapper.
4. Banner-only forward (CAUTION external sender) → `pick_first_valid_fragment` returns the next valid fragment, not the banner.

---

## TASK-4 — Existing-CCC status branch

**Problem.** Agent #2 narrative from `ISC WO RTK.txt` and `Sales PO Std Process` PDFs is mostly about **what to do when a CCC already exists** for the customer's PO# / WO#. We currently treat every email as a fresh pipeline. **The single biggest functional gap between our demo and Keysight's actual workflow.**

**Why it matters.** When a customer sends "PO-12345 — please change qty on line 2" and a CCC for PO-12345 already exists in Salesforce as `Continue Processing`, the agent should attach the email + notify the owner via Chatter — NOT create a new CCC. Today we'd create a duplicate.

### Branching matrix (verbatim from `ISC WO RTK.txt` step 6 + Sales PO PDF step 3.c)

| Existing CCC status | Action |
|---------------------|--------|
| `New` | Attach email; verify $ amount; if amount changed, update; notify owner via Chatter; proceed to step 21 (commit). |
| `Assigned` | Attach email; proceed to step 21. |
| `In Progress` (legacy alias for `Working`) | Attach email; flip status to `Continue Processing`; update PO#; change request type to Work Order (if ISC) or keep Order Request (if Sales). |
| `Continue Processing` | Attach email; notify owner via Chatter; commit. |
| `Awaiting Customer-CIA` | Attach email; flip status to `Continue Processing`; commit. |
| `Awaiting Customer-info` | Attach email; flip status to `Continue Processing`; commit. |
| `Awaiting Internal-FE` | Attach email; flip status to `Continue Processing`; commit. |
| `Awaiting Internal-System` | Attach email; flip status to `Continue Processing`; commit. |
| `Cancelled` | Create a NEW CCC (treat as if no existing record). |
| `Closed` | **Clone** as Change Order Request: type=`Change Order`, order amount=NewPO−OldPO, currency check, final-destination-country re-eval. Commit clone. |

### Files

| File | Change |
|------|--------|
| `backend/app/services/salesforce_cases.py` | Add `find_by_po_or_wo(db, sf, *, po_number, wo_number) -> CaseRecord \| None`, `clone_as_change_order(sf, src_case_id, *, order_amount_delta, new_currency, new_dest_country, new_po_number) -> CaseRecord`, `attach_email_to_case(sf, case_id, *, email_id) -> bool`, `chatter_notify_owner(sf, case_id, *, message) -> bool` |
| `backend/app/models.py` | Add `Pipeline.existing_case_id`, `Pipeline.existing_case_status`, `Pipeline.ccc_action` (enum: `new` / `update` / `clone_change_order`), `Pipeline.duplicate_detected` |
| `backend/app/db_migrate.py` | Add four new columns |
| `backend/app/agents/decide.py` | New step before computing tier: call `existing_case_lookup`, branch on status, set `ccc_action`, attach to extraction context, update Action Feasibility gate (if duplicate detected with status that requires special handling, downgrade Action Feasibility) |
| `backend/app/agents/execute.py` | Branch on `pipeline.ccc_action`: if `update`, call `attach_email_to_case` + `chatter_notify_owner`; if `clone_change_order`, call `clone_as_change_order`; if `new`, existing path |
| `frontend/src/pages/Hitl.tsx` | If `pipeline.existing_case_id` is set, show a "Existing CCC" header card with status, owner, last-action timestamp |
| `frontend/src/pages/Trace.tsx` | Show new sub-step "Existing-CCC lookup" under Decide stage |

### Service signatures

```python
# salesforce_cases.py

@dataclass
class ExistingCaseMatch:
    case_id: str
    case_number: str  # "00001234"
    request_number: str | None  # our local Request_Number__c
    status: str  # SF picklist value
    stage: str | None
    owner_name: str | None
    owner_id: str | None
    type: str | None
    track: str | None
    po_number: str | None
    wo_number: str | None
    bill_to_match: bool
    ship_to_match: bool


def find_by_po_or_wo(
    sf,
    *,
    po_number: str | None = None,
    wo_number: str | None = None,
    customer_account_id: str | None = None,
) -> ExistingCaseMatch | None:
    """Search Salesforce Cases by PO# OR WO#. Returns the most recent match.

    SOQL:
        SELECT Id, CaseNumber, Request_Number__c, Status, Stage__c,
               Type, Track__c, OwnerId, Owner.Name,
               PO_Number__c, WO_Number__c,
               Bill_To_Account__c, Ship_To_Account__c, AccountId
        FROM Case
        WHERE (PO_Number__c = :po OR WO_Number__c = :wo)
          AND IsDeleted = false
        ORDER BY CreatedDate DESC
        LIMIT 1
    """
    ...


def clone_as_change_order(
    sf,
    *,
    src_case_id: str,
    order_amount_delta: float,
    new_currency: str,
    new_dest_country: str | None,
    new_po_number: str | None,
) -> ExistingCaseMatch:
    """Clone a Closed case as a Change Order Request.

    Steps (verbatim from Sales PO PDF step 3(c)(ii)):
      1. SF Apex/REST clone (or insert with copied fields)
      2. Set Type = 'Change Order'
      3. Set Order_Amount__c = new_po_total - old_po_total (may be negative)
      4. Verify currency, update if changed
      5. Verify Final Destination Country, update if changed
      6. If non-US destination → set Track__c='Export' and follow exception routing
      7. Return the clone's case ID
    """
    ...


def attach_email_to_case(sf, case_id: str, *, email_id: int, db: Session) -> bool:
    """Upload our local Email row's body+attachments as ContentVersion(s) on the Case.

    Mirrors 'Files quick link → Add Files → Doc type FCNV' from the narrative.
    Sets ContentDocumentLink to the Case so it shows in the Files related list.
    """
    ...


def chatter_notify_owner(sf, case_id: str, *, message: str) -> bool:
    """Post a Chatter @-mention to the Case owner so they see the new activity.

    POST /services/data/v60.0/chatter/feed-elements/
    body: { feedElementType: "FeedItem", subjectId: case_id, body: { messageSegments: [...] } }
    """
    ...
```

### Decide-stage branch

```python
# In decide.py — after extraction is complete, before confidence-scoring

extracted = pipe.extracted or {}
po_num = extracted.get("po_number")
wo_num = extracted.get("wo_number") or extracted.get("work_order_number")

if po_num or wo_num:
    sf_conn = sf_svc.get_active_connection(db)
    if sf_conn:
        sf = sf_svc.client_for(sf_conn)
        existing = sf_cases.find_by_po_or_wo(
            sf, po_number=po_num, wo_number=wo_num,
            customer_account_id=customer_match.get("account_id"),
        )
        if existing:
            pipe.existing_case_id = existing.case_id
            pipe.existing_case_status = existing.status
            pipe.duplicate_detected = True
            sf_status = (existing.status or "").lower()

            if sf_status == "cancelled":
                pipe.ccc_action = "new"
                # Cancelled → treat as fresh; new CCC will be created
            elif sf_status == "closed":
                pipe.ccc_action = "clone_change_order"
            else:
                # All other statuses (new, assigned, working, awaiting_*) → update
                pipe.ccc_action = "update"
        else:
            pipe.ccc_action = "new"
    else:
        pipe.ccc_action = "new"  # SF not configured; default
else:
    pipe.ccc_action = "new"

# Surface in the 4-gate Action Feasibility gate
if pipe.ccc_action == "clone_change_order" and not extracted.get("order_amount"):
    action_feas_score *= 0.7  # missing delta drag
```

### Execute-stage branch

```python
# In execute.py _apply()

if pipe.ccc_action == "update" and pipe.existing_case_id:
    sf_cases.attach_email_to_case(sf, pipe.existing_case_id, email_id=email.id, db=db)
    sf_cases.chatter_notify_owner(
        sf, pipe.existing_case_id,
        message=f"New customer email attached. Original status: {pipe.existing_case_status}. "
                f"Status flipped to Continue Processing.",
    )
    if pipe.existing_case_status.lower() in {"awaiting customer-cia", "awaiting customer-info",
                                              "awaiting internal-fe", "awaiting internal-system",
                                              "in progress", "working"}:
        sf_cases.update_status(sf, pipe.existing_case_id, "Continue Processing")
    return {"applied": True, "case_id": pipe.existing_case_id, "ccc_action": "update"}

elif pipe.ccc_action == "clone_change_order" and pipe.existing_case_id:
    new_case = sf_cases.clone_as_change_order(
        sf,
        src_case_id=pipe.existing_case_id,
        order_amount_delta=extracted.get("order_amount", 0) - (existing.order_amount or 0),
        new_currency=extracted.get("currency"),
        new_dest_country=extracted.get("ship_to_country"),
        new_po_number=extracted.get("po_number"),
    )
    return {"applied": True, "case_id": new_case.case_id, "ccc_action": "clone_change_order"}

else:
    # ccc_action == "new" — existing path
    ...
```

### Acceptance criteria

1. Synthesize a customer email referencing `PO-12345`, where Salesforce already has Case `00001234` for `PO-12345` with `Status="Awaiting Customer-info"`.
2. Run pipeline → trace shows new sub-step "Existing-CCC lookup" with `data.existing_case = {Id, CaseNumber, Status, Owner}`.
3. Pipeline `ccc_action="update"`, `existing_case_id=<sf_id>`, `duplicate_detected=true`.
4. Execute stage → email attached as ContentVersion on the Case (verify in SF UI), Chatter post visible on the Case feed, Case status flipped to "Continue Processing".
5. HITL UI shows "Existing CCC" header card.
6. Repeat with a `Status="Closed"` case → `ccc_action="clone_change_order"`, new Case created with `Type="Change Order"` and the order amount delta.
7. Repeat with a `Status="Cancelled"` case → `ccc_action="new"`, fresh Case created (no clone).

---

## TASK-5 — Distributor list + magic-SKU routing rules

**Problem.** Sales PO PDF (page 6, 8, 9) has explicit routing logic for distributor partners (auto-assign to AMFO_Disty/Rental queue) and three magic SKUs (CUSTOM PRODUCT, SOWDUMMY, EXPORTDUMMY) that override default routing. Our Decide stage doesn't know about any of this.

**Why it matters.** A customer like Mouser placing a standard PO should auto-route to the AMFO_Disty/Rental queue without HITL. Without this, the agent treats Mouser like any other customer.

### Files

| File | Change |
|------|--------|
| `backend/app/kb_seeds/routing_rules.py` (new) | Seed the disty list + magic-SKU table |
| `backend/app/kb.py` | Register namespace `routing_rules` |
| `backend/app/agents/decide.py` | New step: `_resolve_routing(pipeline, extracted, customer)` returns target queue / CSR. Updates `pipeline.routing_target`. |
| `backend/app/models.py` | `Pipeline.routing_target` (str — queue name or CSR id), `Pipeline.routing_basis` (str — which rule fired) |
| `backend/app/db_migrate.py` | Add the two new columns |
| `frontend/src/pages/KnowledgeBase.tsx` | New tab "Routing Rules" — disty table + dummy-SKU mapping |
| `frontend/src/pages/Hitl.tsx` | Surface `routing_target` + `routing_basis` in the header |

### KB seed — `backend/app/kb_seeds/routing_rules.py`

```python
"""Routing-rules KB — disty partner list + magic-SKU overrides.

Drives the auto-assignment step of Sales PO Agent #3 (page 8-9 of
Sales PO Std Process & Change Order PDF).

Rule precedence (highest priority first):
  1. CSR_OVERRIDE       — body contains explicit "route to <name>" instruction
  2. EXPORT_DESTINATION — final destination country != US/CA
  3. SOW_PRODUCT        — order contains an SOW SKU (Z-prefix) or "Statement of Work"
  4. EBIZ_SENDER        — email from Keysight-Used-Equipment-Store (ebiz@keysight.com)
  5. DISTY_PARTNER      — sender's customer matches a disty in the partner list
  6. STANDARD           — default routing by intent + region

Each rule sets:
  - routing_target — queue name or CSR identifier
  - magic_sku      — CUSTOM PRODUCT / SOWDUMMY / EXPORTDUMMY (or None)
  - basis          — which rule fired
"""
from __future__ import annotations


# US/Canada disty partners — auto-route to AMFO_Disty/Rental queue
DISTY_PARTNERS_US_CA: list[str] = [
    "RS",  # formerly Allied
    "Avnet",
    "Continental Resources",  # ConRes
    "ConRes",
    "Electrorent",
    "Gap Wireless",
    "Mouser Electronics Inc",
    "Mouser",
    "Newark",
    "RFMW LTD",
    "RFMW",
    "Tessco",
    "TestEquity",
    "Transcat",
    "TRS",
]

# LAR (Latin America Region) disty partners
DISTY_PARTNERS_LAR: list[str] = [
    "AQTK Peru S.A.",
    "AQTK S.A.",
    "Complementos Electrónicos S.A.",
    "Element14 S. de R.L. de C.V.",
    "Grupo Prod&Khym, S.A.",
    "Hi-Tech Automatización S.A.S",
    "INCAL Comércio, Importação e Exportação de Instrumentos Ltda.",
    "Inceleris S. de R.L. de C.V.",
    "Interlatin S. de R.L. de C.V.",
    "JMD Produtos Eletrônicos Ltda.",
    "Karimex Componentes Eletrônicos Ltda",
    "Negenex SAS",
    "Nextest Instrumentos e Sistemas Ltda",
    "OHMINI Comercio, Importação e Exportação de Produtos Ltda – EPP",
    "Precision Solutions",
    "Q Wire Inc.",
    "Q-Wire Technologies Inc.",
    "RCBI Instrumentos Ltda.",
    "Servicios Técnicos de Ingeniería S.A. de C.V.",
    "Tecnología y Electrónica S.A.",
    "TestEquity de México S. de R.L. de C.V.",
]


# Magic SKUs — used to override default routing
MAGIC_SKUS: dict[str, dict] = {
    "CUSTOM PRODUCT": {
        "description": "Fallback when SKU not in catalog. Also used to escape AMFO_Disty/Rental routing for standard customers.",
        "routing_target": "CSR_QUEUE",
    },
    "SOWDUMMY": {
        "description": "Statement of Work — routes to SOW Team.",
        "routing_target": "SOW_TEAM_QUEUE",
    },
    "EXPORTDUMMY": {
        "description": "Non-US destination — routes to Export Team.",
        "routing_target": "EXPORT_TEAM_QUEUE",
    },
}


# Sender hints
EBIZ_SENDERS = ["ebiz@keysight.com", "Keysight-Used-Equipment-Store"]


# Routing rules in precedence order
ROUTING_RULES: list[dict] = [
    {
        "key": "routing.csr_override",
        "display_name": "CSR Manual Override (body instruction)",
        "priority": 1,
        "predicates": [{"kind": "ctx_field", "field": "csr_override.has_override", "value": True}],
        "routing_target": "{{csr_override.target}}",  # template
        "magic_sku": None,
    },
    {
        "key": "routing.export",
        "display_name": "Export — non-US/CA destination",
        "priority": 2,
        "predicates": [
            {"kind": "extracted_country_not_in", "value": ["US", "USA", "CA", "CAN", "Canada", "United States"]},
        ],
        "routing_target": "EXPORT_TEAM_QUEUE",
        "magic_sku": "EXPORTDUMMY",
    },
    {
        "key": "routing.sow",
        "display_name": "SOW — Statement of Work",
        "priority": 3,
        "predicates": [
            {"kind": "subject_or_body_contains", "value": ["Statement of Work", "Cover Letter", "EID #", "Custom Solutions"]},
            {"kind": "any_sku_starts_with", "value": ["Z"]},
        ],
        "routing_target": "SOW_TEAM_QUEUE",
        "magic_sku": "SOWDUMMY",
    },
    {
        "key": "routing.ebiz",
        "display_name": "eBiz — Keysight Used Equipment Store",
        "priority": 4,
        "predicates": [
            {"kind": "sender_contains", "value": EBIZ_SENDERS},
            {"kind": "po_number_starts_with", "value": ["eBiz_"]},
        ],
        "routing_target": "AMFO_Disty/Rental",
        "magic_sku": None,
    },
    {
        "key": "routing.disty_us_ca",
        "display_name": "Distributor — US/Canada",
        "priority": 5,
        "predicates": [
            {"kind": "customer_name_in", "value": DISTY_PARTNERS_US_CA},
        ],
        "routing_target": "AMFO_Disty/Rental",
        "magic_sku": None,
    },
    {
        "key": "routing.disty_lar",
        "display_name": "Distributor — Latin America Region",
        "priority": 6,
        "predicates": [
            {"kind": "customer_name_in", "value": DISTY_PARTNERS_LAR},
        ],
        "routing_target": "AMFO_Disty/Rental_LAR",
        "magic_sku": None,
    },
]


def seed_default_routing_rules(db) -> int:
    from ..models import KnowledgeRule
    inserted = 0
    for rule in ROUTING_RULES:
        existing = db.query(KnowledgeRule).filter_by(
            namespace="routing_rules", key=rule["key"]
        ).first()
        if existing:
            continue
        db.add(KnowledgeRule(
            namespace="routing_rules",
            key=rule["key"],
            display_name=rule["display_name"],
            severity="warn",
            data=rule,
            enabled=True,
        ))
        inserted += 1
    # Also seed disty list + magic SKUs as data records under separate keys
    db.add(KnowledgeRule(
        namespace="routing_rules", key="disty_partners.us_ca",
        display_name="US/Canada disty partners (auto-AMFO)",
        severity="warn", enabled=True,
        data={"partners": DISTY_PARTNERS_US_CA},
    ))
    db.add(KnowledgeRule(
        namespace="routing_rules", key="disty_partners.lar",
        display_name="LAR disty partners (auto-AMFO)",
        severity="warn", enabled=True,
        data={"partners": DISTY_PARTNERS_LAR},
    ))
    db.add(KnowledgeRule(
        namespace="routing_rules", key="magic_skus",
        display_name="Magic SKUs (override routing)",
        severity="warn", enabled=True,
        data={"skus": MAGIC_SKUS},
    ))
    db.commit()
    return inserted
```

### Decide-stage usage

Add to `decide.py`:

```python
def _resolve_routing(db, pipeline, extracted, customer_match, intake_ctx) -> tuple[str | None, str]:
    """Returns (routing_target, basis_rule_key) or (None, '') if no rule fires."""
    rules = sorted(
        kb.list_rules(db, namespace="routing_rules", enabled_only=True,
                      key_filter=lambda k: k.startswith("routing.")),
        key=lambda r: r.data.get("priority", 999),
    )
    for rule in rules:
        if _eval_routing_predicates(rule.data["predicates"], extracted, customer_match, intake_ctx):
            return rule.data["routing_target"], rule.key
    return None, ""
```

### Acceptance criteria

1. KB has 6 records under `routing_rules` namespace + 3 data records (`disty_partners.us_ca`, `disty_partners.lar`, `magic_skus`).
2. Email from `Mouser Electronics Inc` with `po_intake` intent → pipeline `routing_target="AMFO_Disty/Rental"`, `routing_basis="routing.disty_us_ca"`.
3. Email with extracted `ship_to_country="DE"` → `routing_target="EXPORT_TEAM_QUEUE"`.
4. Email containing "Statement of Work" → `routing_target="SOW_TEAM_QUEUE"`.
5. Frontend KB tab "Routing Rules" lets operators add/remove disty names without code change.
6. HITL queue shows the routing target and basis rule on each task card.

---

## TASK-6 — Region-aware rule pack wiring

**Problem.** TASK-1's `intent_definitions_v2.py` has a `regions` field per intent record, but every entry is `["GLOBAL"]` and **no code reads the field**. RFP call explicitly mentioned Japan-specific field requirements and region-specific rule packs (Americas / EMEA / APAC / Japan).

### Files

| File | Change |
|------|--------|
| `backend/app/agents/tools/classify_intent_tool.py` | When building the intent menu for the prompt, filter by `account_region` (from EmailAccount) or `customer_region` (from matched customer). Include intent if `account_region in regions` OR `"GLOBAL" in regions`. |
| `backend/app/kb_seeds/intent_definitions_v2.py` | Update at least one intent (e.g., `service_contract_request`) to be region-scoped to demonstrate behavior — e.g., `regions=["APAC", "JP", "GLOBAL"]` for one variant, `regions=["AMS"]` for another. |
| `backend/app/models.py` | Add `EmailAccount.region` (str: AMS / EMEA / APAC / JP / GLOBAL, default "GLOBAL") if not already present |
| `frontend/src/pages/settings/Connections.tsx` | Add region dropdown to the Add-mailbox modal |

### Acceptance criteria

1. Add a Japan-specific intent variant (e.g., `service_contract_request_jp` with `regions=["JP"]`).
2. Connect a mailbox with `region="JP"` → classifier menu includes `service_contract_request_jp` as a candidate.
3. Connect a mailbox with `region="AMS"` → classifier menu does NOT include `service_contract_request_jp` (filtered out).
4. Trace event `intake.region_filter_applied` shows `available_intents` count differing per region.

---

## TASK-7 — Test-corpus regression page

**Problem.** Keysight's prior POC has a 109-email labelled test corpus with expected-vs-actual + accuracy report (Initial Pass / Failed / Post-Fix Pass / Still Failed buckets). We have no equivalent. **Big credibility miss for the productionization story.**

### Files

| File | Change |
|------|--------|
| `backend/app/models.py` | Add 3 tables: `TestCase` (labelled email), `TestRun` (a complete corpus run), `TestRunResult` (one row per case in a run, holding actual vs expected) |
| `backend/app/routes/test_corpus.py` (new) | `POST /api/test-corpus/import` (CSV/JSON), `GET /api/test-corpus/cases`, `POST /api/test-corpus/run`, `GET /api/test-corpus/runs/{id}`, `GET /api/test-corpus/runs/{id}/results` |
| `frontend/src/pages/TestCorpus.tsx` (new) | Upload modal + cases table + run trigger + results dashboard with "Initial Pass / Failed / Post-Fix Pass / Still Failed" breakdown |
| `frontend/src/api.ts` | Types + endpoints |
| `backend/app/main.py` | Register `test_corpus` router |

### Schema

```python
class TestCase(Base):
    __tablename__ = "test_cases"
    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)  # filename or label
    subject = Column(String)
    from_address = Column(String)
    body = Column(Text)
    attachments = Column(JSON, default=list)
    expected_intent = Column(String, index=True)
    expected_action = Column(String, nullable=True)
    expected_routing = Column(String, nullable=True)
    expected_keywords = Column(JSON, default=list)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now)


class TestRun(Base):
    __tablename__ = "test_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=now)
    finished_at = Column(DateTime, nullable=True)
    label = Column(String)  # "2026-05-10 v3 prompt"
    case_count = Column(Integer, default=0)
    initial_pass = Column(Integer, default=0)
    initial_fail = Column(Integer, default=0)
    post_fix_pass = Column(Integer, default=0)
    still_failed = Column(Integer, default=0)
    pipeline_version_hash = Column(String, nullable=True)


class TestRunResult(Base):
    __tablename__ = "test_run_results"
    id = Column(Integer, primary_key=True)
    test_run_id = Column(Integer, ForeignKey("test_runs.id"), index=True)
    test_case_id = Column(Integer, ForeignKey("test_cases.id"), index=True)
    actual_intent = Column(String, nullable=True)
    actual_keywords = Column(JSON, default=list)
    actual_reason = Column(Text, nullable=True)
    pass_initial = Column(Boolean, default=False)
    pass_post_fix = Column(Boolean, nullable=True)  # null until re-run
    pipeline_id = Column(Integer, nullable=True)
    diff = Column(JSON, default=dict)  # what differed: {"intent": "expected vs actual"}
```

### Acceptance criteria

1. Operator imports a CSV with columns: `name, subject, from, body, expected_intent, expected_keywords, notes` → seeds `test_cases`.
2. Click "Run corpus" → backend iterates cases, creates a synthetic Email + Pipeline per case, runs through the same pipeline, stores `actual_intent` + `pass_initial=(actual==expected)` per case.
3. UI shows: total cases, initial pass % (matches Keysight's report), failed list with diffs (expected vs actual side-by-side).
4. After tuning a KB rule, click "Re-run failed only" → recomputes `pass_post_fix` for those cases.
5. Dashboard tile: 109 / 62 initial-pass / 47 initial-fail / 41 post-fix-pass / 5 still-failed (matches their 96% post-fix accuracy).
6. Export `/api/test-corpus/runs/{id}.csv` for spreadsheet hand-off.

---

## TASK-8 — `.msg` attachment unrolling

**Problem.** Keysight's POC accuracy report listed `.msg` (embedded Outlook items in forwarded emails) as the #1 unsupported-attachment failure mode. Our IMAP fetcher and extract pipeline don't handle them.

### Files

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `extract-msg==0.50.0` (or current) |
| `backend/app/services/imap_client.py` | When loading attachments, detect `.msg` MIME (`application/vnd.ms-outlook` or filename ending). Use `extract_msg.Message` to unroll subject/body/from/attachments. Two output options: |
|  | • Append the unrolled `.msg`'s text content to the parent Email's body as `--- forwarded ---\nFrom: ...\nSubject: ...\n<body>` |
|  | • Or create a separate sub-Email row linked via parent_email_id (fancier; not needed for MVP) |
| `backend/app/agents/tools/azure_doc_intelligence_tool.py` (Session A) | When iterating attachments, `.msg` is now pre-flattened to text — skip OCR, treat as plain text |

### Implementation sketch

```python
# imap_client.py — inside _save_attachments

import extract_msg

def _maybe_unroll_msg(parts: list[Message], saved: list[dict], body_appendix: list[str]) -> None:
    """If any .msg attachments exist, unroll their text content + their nested
    attachments. Append to body, save nested attachments separately."""
    for part in list(parts):
        ctype = part.get_content_type() or ""
        fn = (part.get_filename() or "").lower()
        if ctype != "application/vnd.ms-outlook" and not fn.endswith(".msg"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            tmp = Path(UPLOADS) / f"_tmp_{uuid.uuid4().hex}.msg"
            tmp.write_bytes(payload)
            msg = extract_msg.Message(str(tmp))
            try:
                appendix = (
                    f"\n\n--- forwarded message (.msg) ---\n"
                    f"From: {msg.sender}\n"
                    f"Subject: {msg.subject}\n"
                    f"Date: {msg.date}\n\n"
                    f"{msg.body or ''}\n"
                )
                body_appendix.append(appendix)
                # Also save the .msg's nested attachments
                for att in (msg.attachments or []):
                    safe = _safe_filename(att.longFilename or att.shortFilename or "msg_inner.bin")
                    stamped = f"msg_{uuid.uuid4().hex[:8]}_{safe}"
                    target = Path(UPLOADS) / stamped
                    target.write_bytes(att.data or b"")
                    saved.append({
                        "name": stamped,
                        "original_name": att.longFilename or att.shortFilename,
                        "size": len(att.data or b""),
                        "content_type": "application/octet-stream",
                        "source": "msg_inner",
                    })
            finally:
                msg.close()
                try:
                    tmp.unlink()
                except OSError:
                    pass
        except Exception as e:
            log.warning("msg unroll failed for %s: %s", fn, e)
```

### Acceptance criteria

1. Email with a forwarded `.msg` attachment gets imported → body now contains `--- forwarded message (.msg) ---` block with the inner subject/from/body.
2. Inner `.msg` attachments are saved as separate files in `uploads/` with `msg_` prefix.
3. Pipeline classifies based on the unrolled forwarded content, not the empty wrapper.
4. Trace event shows `imap.msg_unrolled` with the count of inner attachments saved.

---

## TASK-9 — Third "shadow test classifier" slot

**Problem.** Keysight's POC has THREE classifiers running side-by-side (Context-pass / Override-pass / "New Rules Test"-pass) so they can roll out a new prompt in shadow without breaking production. We have only two.

**Why it matters.** P3 — only build if everything else is done. Kept here for completeness. Useful as a positioning slide ("we support shadow A/B prompt rollouts").

### Files

| File | Change |
|------|--------|
| `backend/app/agents/tools/shadow_classifier_tool.py` (new) | A third classifier that runs alongside Context+Override but its output is **not consumed** — only logged. The prompt is operator-tunable in KB (`kb.shadow_classifier_prompt`). |
| `backend/app/agents/stage1_intake_agent.py` | If `kb.shadow_classifier.enabled=True`, invoke `shadow_classifier` after Override-pass; store output in `pipeline.shadow_classification`. |
| `backend/app/models.py` | `Pipeline.shadow_classification` JSON column |
| `frontend/src/pages/Trace.tsx` | Show shadow result side-by-side with primary in Decide stage. |

### Acceptance criteria

1. Toggle `kb.shadow_classifier.enabled=true` → pipeline runs 3 classifiers; `pipeline.shadow_classification` JSON populated; trace shows both primary and shadow side-by-side.
2. Toggle off → pipeline runs only 2 classifiers (no extra latency / cost).
3. Ops dashboard: agreement rate column "Primary vs Shadow agreement" shown when shadow is enabled.

---

## Cross-cutting acceptance — full-pipeline smoke test

After all P0-P1 tasks land, run a single email end-to-end and verify each stage:

**Test email (synthesize):**
```
From: procurement@mouser.com
To: orderinbox@leewayhertz.com
Subject: PO-MOUSER-77001 — Convert quote QT-MOU-2026-001 to order
Body:
  CAUTION: External sender.

  --- Original Message ---
  From: helpdesk@mouser.com
  Subject: PO-MOUSER-77001

  Hi Keysight team,

  Please find attached PO-MOUSER-77001. This converts quote
  QT-MOU-2026-001 (sent 2026-04-15) into a standing order.

  Ship to Mouser warehouse, Texas, USA.
  Net 30, USD.

  Thanks,
  Sarah Chen
  Senior Buyer, Mouser Electronics

Attachments:
  - PO-MOUSER-77001.pdf
  - quote-QT-MOU-2026-001.pdf
  - forwarded_internal_thread.msg  ← TASK-8 unrolls this
```

**Expected behavior:**

| Stage | Expected output |
|-------|-----------------|
| **Pre-Intake (TASK-2)** | No rule matches (not bounce, not OOO, not collections, etc.) → fall through |
| **TASK-3** | `pick_first_valid_fragment` skips the CAUTION banner + the `--- Original Message ---` line, returns the actual PO body |
| **TASK-8** | `forwarded_internal_thread.msg` unrolled into appendix; inner attachments saved |
| **Stage 1 Intake** | classify_intent returns `quote_to_order`; override-pass confirms (no override needed) |
| **TASK-1** | Even though intent isn't one of the 5 new ones here, INTENTS list now includes them as available revisable values |
| **TASK-6** | Region filter on classify_intent menu uses `account.region` (likely "GLOBAL") |
| **Stage 2 Extract** | Extracts `po_number=PO-MOUSER-77001`, `quote_number=QT-MOU-2026-001`, `customer_name=Mouser Electronics` |
| **Stage 3 Decide — TASK-4** | `find_by_po_or_wo("PO-MOUSER-77001")` → returns None → `ccc_action="new"` |
| **Stage 3 Decide — TASK-5** | `customer_name in DISTY_PARTNERS_US_CA` → `routing_target="AMFO_Disty/Rental"`, `routing_basis="routing.disty_us_ca"` |
| **Stage 3 Decide — 4-gate (already done)** | All 4 gates green → `tier="L4_AUTO"` |
| **Stage 4 Execute** | Creates new SF Case with `OwnerId` set to AMFO_Disty/Rental queue; Type=`Order Request` |
| **Stage 5 Communicate** | Drafts SOA reply in English |
| **Stage 6 Back-stamp (already done)** | IMAP-moves email to `ZBrain/Sales POs` folder |

**Verification points:**
- Trace timeline shows `pre_intake → intake → extract → reconcile → decide(existing_case_lookup, routing_resolve, 4_gate) → execute → communicate → back_stamp`
- Ops dashboard new row shows: `category=SALES_PO`, `intent=quote_to_order`, `routing_target=AMFO_Disty/Rental`, `case_id=<new sf id>`, `status=Success`
- HITL queue is empty (L4 auto-resolved)

---

## Lane assignments summary

| Task | Session A (agents/KB/Trace/KnowledgeBase) | Session B / mine (services/email/UI) |
|------|-------------------------------------------|---------------------------------------|
| TASK-1 | KB seed, INTENTS, classify prompt, override-pass values, orchestrator short-circuit | Inbox `redirected` status filter |
| TASK-2 | New stage `pre_intake.py`, KB seed, KnowledgeBase tab | (none) |
| TASK-3 | Wire into classify prompt | `email_thread.py` helpers |
| TASK-4 | Decide branch, Execute branch, Trace sub-step, HITL header card | `salesforce_cases.py` find/clone/attach/chatter, models, db_migrate |
| TASK-5 | Decide `_resolve_routing`, KB seed, KnowledgeBase tab | (none) |
| TASK-6 | classify_intent region filter, intent_definitions_v2 region scoping | EmailAccount.region column + Connect modal |
| TASK-7 | (light — pipeline must accept synthesized Email cleanly) | models, route, page, api.ts |
| TASK-8 | azure_doc_intelligence handles unrolled `.msg` text | imap_client `_maybe_unroll_msg`, requirements.txt |
| TASK-9 | shadow_classifier_tool, stage1 wiring, Trace UI | (none) |

**Cross-cutting (need a SESSION_HANDOFF.md crossover note):**
- TASK-1: `models.py` (`email.status` accepts `redirected`), `db_migrate.py`, `routes/emails.py` `KNOWN_STATUSES`
- TASK-4: `models.py` (4 new Pipeline columns), `db_migrate.py`, `frontend/src/api.ts` (Pipeline type)
- TASK-5: `models.py` (`routing_target`, `routing_basis`), `db_migrate.py`
- TASK-6: `models.py` (`EmailAccount.region`), `db_migrate.py`
- TASK-7: `models.py` (3 new tables), `routes/__init__.py` if needed, `main.py` router include
- TASK-9: `models.py` (`Pipeline.shadow_classification`), `db_migrate.py`

---

## Read-this-first reference

- [RESEARCH_BRIEF.md](RESEARCH_BRIEF.md) — full background: prior POC artifacts, ZBrain workflow JSON, RFP Q&A call. Read sections 4 ("override rule book") and 7 ("comprehensive gap analysis") before TASK-1, TASK-2.
- [SESSION_HANDOFF.md](SESSION_HANDOFF.md) — active lane coordination + crossover events log. Add an entry per cross-cutting touch.
- [CLAUDE.md](CLAUDE.md) — branding rules. **Never surface "Claude" anywhere user-visible.** Use ZBrain.

## Source artifacts referenced

- `C:\Users\Rituraj\Downloads\keysight poc\ISC WO RTK.txt` — Agent #1.3, #2, #3 narratives (ISC WO RTK scope)
- `C:\Users\Rituraj\Downloads\keysight poc\Sales PO Std Process & Change order (1).pdf` — 16-page narrative including disty list (page 6, 8-9), magic SKUs, Stock Rotation / Rebates / eBiz / SOW subtypes
- `C:\Users\Rituraj\Downloads\keysight poc\Current Outlook Rules_Narratives (1).pdf` — 6 pre-AI rules (verbatim source for TASK-2 KB seed)
- `C:\Users\Rituraj\Downloads\keysight poc\FRONT OFFICE AGENT 1 COMPARISION REPORT.xlsx` — 109-email test corpus (source for TASK-7 sample data)
- `C:\Users\Rituraj\Downloads\Agents\KS FO Agent.json` — running ZBrain workflow with 25KB override prompt (verbatim source for TASK-1 keyword/sender_pattern lists)

---

## Verification checklist for the agent picking this up

Before declaring done on each task:

```
[ ] All files listed under "Files to touch" actually changed (use `git diff --stat`)
[ ] Backend restarts cleanly (no import errors)
[ ] DB migrations apply without errors (check `app.log` on startup)
[ ] OpenAPI shows new routes (`curl /openapi.json | grep <new-route>`)
[ ] Frontend hot-reloads without TypeScript errors
[ ] Acceptance criteria run as a manual smoke test
[ ] Add crossover note in SESSION_HANDOFF.md if any cross-cutting file changed
[ ] Update SOLUTION.md if a new ADR was made (e.g., Why Pre-Intake stage)
```

When all P0 tasks pass their acceptance criteria, the demo is faithful to Keysight's prior POC behavior plus the new RFP-required gates. Reach out before starting P3 (TASK-9).
