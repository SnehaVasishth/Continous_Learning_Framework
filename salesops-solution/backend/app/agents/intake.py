"""Stage 1 — Intake & Classification.

Detects language, classifies intent, screens spam/phishing.

Intent definitions, examples, and track-hint mappings are loaded from the
Knowledge Base (`namespace=intent`) at request time so business users can
refine classification rules from the UI without code changes.
"""
from __future__ import annotations

from .. import kb
from ..config import INTENTS, LANGUAGES
from .llm import ask_llm


_INTENT_TRACKS = {
    "po_intake": "trade",
    "quote_to_order": "trade",
    "trade_change_order": "trade",
    "ssd_change_request": "trade",
    "hold_release": "trade",
    "delivery_change": "trade",
    "service_order": "som",
    "wo_update_request": "som",
    "wo_status_inquiry": "som",
    "service_contract_request": "service_contract",
    "general_inquiry": "none",
    "out_of_scope": "none",
    "spam": "none",
    # === v1.1 TASK-1 START === redirect/discard intents short-circuit, no track
    "kso": "none",
    "collections": "none",
    "portal_admin": "none",
    "brazil_tax": "none",
    "undeliverable": "none",
    # === v1.1 TASK-1 END ===
}


def build_system_prompt(*, account_region: str | None = None, rules_override: dict | None = None) -> str:
    """Public alias kept for tools that need to surface the prompt for audit.

    === v1.1 TASK-6 === When `account_region` is provided, the intent menu is
    filtered to that region.

    `rules_override` lets the Continuous Learning back-test inject a candidate
    KB body in place of the live body for one or more intents, without writing
    to the database. Keys are intent names, values are the proposed rule body.
    """
    return _build_system_prompt(account_region=account_region, rules_override=rules_override)


def build_user_prompt(email: dict, *, thread_summary: str | None = None) -> str:
    """Reconstructs the user prompt the intake LLM sees, for audit/UI display.

    When `thread_summary` is provided (the conversation has multiple messages),
    we present the ROOT message as the primary intent source and include the
    chronological reply chain as evidence. The classifier is instructed to
    derive intent from the root, NOT from the latest reply — see Stage 1
    system prompt for the rule.
    """
    if thread_summary:
        return (
            "EMAIL THREAD (chronological; ROOT drives intent, replies are clarifying context):\n"
            f"{thread_summary}\n\n"
            "PRIMARY ENVELOPE OF THE LATEST MESSAGE THAT TRIGGERED THIS PIPELINE:\n"
            f"FROM: {email.get('from', '')}\n"
            f"SUBJECT: {email.get('subject', '')}\n"
            f"LANGUAGE_HINT: {email.get('language_hint') or 'unknown'}\n"
            "\nClassify the THREAD's intent (read from the ROOT message). "
            "The latest message may be a CSR confirmation or buyer follow-up that does not "
            "represent the original ask. Use the full chain to disambiguate. "
            "Output one JSON object only."
        )

    # === v1.1 TASK-3 START === Skip empty / banner / FYI fragments and use the
    # first MEANINGFUL fragment as the primary classification signal. The full
    # body stays available below as fallback context. Mirrors the prior POC's
    # "empty-fragment skip" override rule.
    full_body = email.get("body", "") or ""
    try:
        from ..services.email_thread import pick_first_valid_fragment
        latest_valid, frag_idx = pick_first_valid_fragment(full_body)
    except Exception:
        latest_valid, frag_idx = "", -1
    if latest_valid and frag_idx > 0:
        return (
            f"FROM: {email.get('from', '')}\n"
            f"SUBJECT: {email.get('subject', '')}\n"
            f"LANGUAGE_HINT: {email.get('language_hint') or 'unknown'}\n\n"
            f"PRIMARY FRAGMENT (selected: fragment {frag_idx} of the thread; "
            f"earlier fragments were CAUTION banners / FYI wrappers / empty forwards):\n"
            f"{latest_valid}\n\n"
            f"FULL THREAD BODY (fallback context):\n{full_body}\n"
            "\nClassify per the contract. Use the PRIMARY FRAGMENT as the main "
            "intent signal. Output one JSON object only."
        )
    # === v1.1 TASK-3 END ===

    return (
        f"FROM: {email.get('from', '')}\n"
        f"SUBJECT: {email.get('subject', '')}\n"
        f"LANGUAGE_HINT: {email.get('language_hint') or 'unknown'}\n"
        f"BODY:\n{email.get('body', '')}\n"
        "\nClassify per the contract. Output one JSON object only."
    )


def _build_system_prompt(*, account_region: str | None = None, rules_override: dict | None = None) -> str:
    """Generate the classify-intent system prompt from the live KB at request time.

    Reads each intent's structured body fields (category, description, keywords,
    sender_patterns, exceptions from the prior POC's 25KB override book, exclusions)
    and renders them as a per-intent block. Operators tune any field in /kb without
    a code change — the next pipeline picks up the new prompt automatically.

    === v1.1 TASK-6 === When `account_region` is provided, intents are filtered
    by their `regions` field — only intents matching the region or marked
    "GLOBAL" are included in the menu. Lets us scope APAC/JP-specific intent
    variants without polluting AMS classification.
    """
    rules = dict(kb.intake_intent_rules())
    # Continuous Learning back-test injects a candidate KB body here for one
    # or more intents. Other intents continue to read from the live KB so the
    # candidate is evaluated against an otherwise-unchanged classifier.
    if rules_override:
        for k, v in rules_override.items():
            if isinstance(v, dict):
                rules[k] = v
    intent_blocks: list[str] = []
    # === v1.1 TASK-6 === region filter — include intent if regions==[] / contains "GLOBAL" / matches account_region.
    region = (account_region or "GLOBAL").upper().strip() or "GLOBAL"
    filtered_intents: list[str] = []
    for intent in INTENTS:
        body = rules.get(intent) or {}
        regs = body.get("regions") or []
        if not regs:
            filtered_intents.append(intent)
            continue
        regs_u = [str(r).upper() for r in regs]
        if "GLOBAL" in regs_u or region in regs_u:
            filtered_intents.append(intent)
    for intent in filtered_intents:
        body = rules.get(intent) or {}
        desc = (body.get("description") or "(no definition)").strip()
        track = body.get("track_hint") or _INTENT_TRACKS.get(intent, "none")
        category = body.get("category") or "OTHERS"
        block: list[str] = [f'  "{intent}" (category={category} · track={track}):']
        if desc:
            short = desc if len(desc) <= 220 else desc[:220] + "…"
            block.append(f"      Description: {short}")
        keywords = body.get("keywords") or []
        if keywords:
            kw_str = ", ".join(f'"{k}"' for k in keywords[:8])
            block.append(f"      Keywords: {kw_str}")
        sender_patterns = body.get("sender_patterns") or []
        if sender_patterns:
            sp_str = ", ".join(sender_patterns[:5])
            block.append(f"      Sender patterns: {sp_str}")
        exceptions = body.get("exceptions") or []
        if exceptions:
            block.append("      Exceptions (prior-POC override book):")
            for exc in exceptions[:5]:
                exc_short = exc if len(exc) <= 200 else exc[:200] + "…"
                block.append(f"        · {exc_short}")
        exclusions = body.get("exclusions") or []
        if exclusions:
            block.append("      Exclusions:")
            for exc in exclusions[:3]:
                block.append(f"        · {exc}")
        intent_blocks.append("\n".join(block))

    # Global override-rule excerpts that apply ACROSS intents.
    global_rules: list[str] = []
    try:
        from ..kb_seeds.intent_definitions_v2 import GLOBAL_OVERRIDE_RULES
        global_rules = list(GLOBAL_OVERRIDE_RULES)
    except Exception:
        pass

    # === v1.1 TASK-6 === canonical intent enum follows the region filter.
    canonical = ", ".join(f'"{i}"' for i in (filtered_intents or INTENTS))
    canonical_langs = ", ".join(f'"{l}"' for l in LANGUAGES + ["other"])

    return "\n".join([
        "You are the Stage-1 Intake & Classification agent for Keysight SalesOps. Read one customer email and emit ONE strict JSON object. Output goes directly to json.loads() and enum validators.",
        "",
        "OUTPUT CONTRACT. Emit exactly these 10 keys:",
        "{",
        f'  "language": "<{canonical_langs}>",',
        '  "language_reasoning": "<string>",',
        f'  "intent": "<{canonical}>",',
        '  "intent_confidence": <number 0.0-1.0>,',
        '  "intent_reasoning": "<1-2 sentences citing exact words from the email>",',
        '  "secondary_intents": [],',
        '  "spam": <true|false>,',
        '  "spam_reason": "<string; \"\" if not spam>",',
        '  "summary": "<one English sentence>",',
        '  "track_hint": "<trade|som|service_contract|none>"',
        "}",
        "",
        "FIELD RULES (positive form):",
        '  • "intent" is a single string from the canonical list (never an array, never inside another object).',
        '  • "intent_confidence" is a top-level number (never inside an "intents" object).',
        '  • "track_hint" is the workflow track. One of: trade, som, service_contract, none. NOT an autonomy tier (no "L4_auto", "L3", "auto").',
        '  • "intent_reasoning" is a sentence quoting words from the email (the field name is "intent_reasoning", not "notes" or "rationale").',
        '  • Emit all 10 keys every time. Use "" or [] for empty values.',
        "",
        "INTENT DEFINITIONS (KB-driven · 9-class category mapped per intent):",
        *intent_blocks,
        "",
        "GLOBAL OVERRIDE RULES (apply across all intents; verbatim from the prior Keysight POC's 25KB override book):",
        *[f"  · {r}" for r in global_rules],
        "",
        "  Track meanings: trade = orders/PO/quote conversion/holds/ship-date changes; som = work-orders/calibration/repair/install; service_contract = cal plan/PM plan/support agreement; none = general inquiry, out_of_scope, spam.",
        "",
        "OUT_OF_SCOPE vs SPAM. Pick one carefully:",
        '  • out_of_scope = LEGITIMATE non-customer-business from a KNOWN/established sender. The sender is a real brand or person (Google, Microsoft, AWS, GitHub, LinkedIn, the user\'s own company HR/IT, a Keysight teammate, a known vendor). Content is informational, transactional, or promotional but the sender is RECOGNIZABLE and not lookalike. Examples include: account-security alerts, billing notifications, calendar invites, newsletter forwards, "free trial" offers from real brands, internal HR reminders, out-of-office auto-replies, vendor receipts.',
        '  • spam = UNSOLICITED material from UNKNOWN or LOOKALIKE senders, OR clearly malicious content. Phishing credential traps ("verify your account or it will be suspended"), wire-fraud setups ("our banking details have changed"), 419/advance-fee scams, lookalike-domain attacks (faux-keysight.com), unsolicited promo blasts from senders the recipient never opted into.',
        '  • Decision rule: ',
        '      - Forwarded newsletters / marketing from a real brand the recipient knows (Google, MS, AWS, LinkedIn, etc.) → out_of_scope, NOT spam.',
        '      - "70% OFF" promo blast from no-name unknown-domain sender → spam.',
        '      - Phishing / wire-fraud regardless of sender appearance → spam.',
        '  • Both route to discard, but distinguishing them lets compliance/security flag actual phishing separately from harmless newsletter noise.',
        "",
        "WORKED EXAMPLES (reproduce this exact shape):",
        "",
        "Example 1: fresh PO (po_intake / trade)",
        '  IN  Subject "PO PO-X-1: DSO purchase, please ack" / Body "PO-X-1 attached for one DSO. Net 45."',
        '  OUT {"language":"en","language_reasoning":"All-English.","intent":"po_intake","intent_confidence":0.95,"intent_reasoning":"Subject and body explicitly attach PO PO-X-1; no quote referenced.","secondary_intents":[],"spam":false,"spam_reason":"","summary":"New PO PO-X-1 needing acknowledgment.","track_hint":"trade"}',
        "",
        "Example 2: quote-to-order (quote_to_order / trade)",
        '  IN  Subject "Convert quote QT-A-1 → order, PO attached" / Body "Please convert QT-A-1 into an order using PO-A-1. Send SOA."',
        '  OUT {"language":"en","language_reasoning":"All-English.","intent":"quote_to_order","intent_confidence":0.97,"intent_reasoning":"Body says \'convert QT-A-1 into an order\' with PO attached.","secondary_intents":[],"spam":false,"spam_reason":"","summary":"Convert quote QT-A-1 to a sales order.","track_hint":"trade"}',
        "",
        "Example 3: service order (service_order / som)",
        '  IN  Subject "Multi-asset cal request" / Body "Please open a work order to calibrate 6 instruments on-site, ISO 17025 traceable."',
        '  OUT {"language":"en","language_reasoning":"All-English.","intent":"service_order","intent_confidence":0.96,"intent_reasoning":"Body says \'Please open a work order to calibrate\'; new on-site cal request.","secondary_intents":[],"spam":false,"spam_reason":"","summary":"On-site calibration work order for 6 instruments.","track_hint":"som"}',
        "",
        "Example 4: promotional spam (spam / none)",
        '  IN  Subject "🎉 70% OFF, TODAY ONLY" / Body "Click now to save big!"',
        '  OUT {"language":"en","language_reasoning":"All-English.","intent":"spam","intent_confidence":0.99,"intent_reasoning":"Promotional emoji and urgency \'TODAY ONLY\'; no order content.","secondary_intents":[],"spam":true,"spam_reason":"Promotional discount blast.","summary":"Promotional discount blast.","track_hint":"none"}',
        "",
        "Example 5: Google security alert (out_of_scope / none). LEGITIMATE NOTIFICATION, NOT SPAM.",
        '  IN  From "Google <no-reply@accounts.google.com>" Subject "Security alert" / Body "App password created to sign in to your account. If you didn\'t generate this password, someone might be using your account."',
        '  OUT {"language":"en","language_reasoning":"All-English.","intent":"out_of_scope","intent_confidence":0.97,"intent_reasoning":"Sender is google.com (legitimate); content is an account-security notification about app-password creation; no customer order or service request.","secondary_intents":[],"spam":false,"spam_reason":"","summary":"Google account security notification: app password created.","track_hint":"none"}',
        "",
        "Example 6: internal HR email (out_of_scope / none)",
        '  IN  From "hr@keysight.com" Subject "Open enrollment reminder" / Body "Reminder: benefits open enrollment closes Friday. Log into Workday to make selections."',
        '  OUT {"language":"en","language_reasoning":"All-English.","intent":"out_of_scope","intent_confidence":0.95,"intent_reasoning":"Internal HR reminder about benefits enrollment; not a customer-business request.","secondary_intents":[],"spam":false,"spam_reason":"","summary":"Internal HR reminder about benefits open enrollment.","track_hint":"none"}',
        "",
        "Example 7: forwarded marketing newsletter from a known brand (out_of_scope / none, NOT spam)",
        '  IN  From "rituraj@leewayhertz.com" (forwarded) Subject "Fwd: Work faster with AI built into Google Workspace" / Body "Forwarded message from Google Workspace x YourStory: Try Google Workspace free for 14 days. Start your free trial."',
        '  OUT {"language":"en","language_reasoning":"All-English.","intent":"out_of_scope","intent_confidence":0.96,"intent_reasoning":"Forwarded promotional newsletter from a known brand (Google Workspace) about a free-trial offer; sender is recognizable, not phishing or lookalike.","secondary_intents":[],"spam":false,"spam_reason":"","summary":"Forwarded Google Workspace marketing newsletter with free-trial offer.","track_hint":"none"}',
        "",
        "Now read the email below and emit one JSON object matching the contract exactly. No prose, no code fences, no additional keys.",
    ])


def run_intake(email: dict) -> dict:
    user = (
        f"FROM: {email['from']}\n"
        f"SUBJECT: {email['subject']}\n"
        f"LANGUAGE_HINT: {email.get('language_hint') or 'unknown'}\n"
        f"BODY:\n{email['body']}\n"
        "\nClassify per the contract. Output one JSON object only."
    )
    try:
        out = ask_llm(system=_build_system_prompt(), user=user, json_only=True)
        if not isinstance(out.get("secondary_intents"), list):
            out["secondary_intents"] = []
        return out
    except ValueError as e:
        return {
            "language": email.get("language_hint") or "en",
            "intent": "general_inquiry",
            "intent_confidence": 0.0,
            "secondary_intents": [],
            "spam": False,
            "spam_reason": "",
            "summary": "(intake parse failed — defaulting to manual review)",
            "_intake_error": str(e)[:300],
        }
