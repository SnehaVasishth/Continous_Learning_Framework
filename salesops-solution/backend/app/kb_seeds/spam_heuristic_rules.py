"""Spam / phishing heuristic regex rules — knowledge-base seed.

This module defines a curated list of high-precision regex rules used by the
enterprise B2B email classifier in the SalesOps pipeline. Each rule is
testable as a standalone ``re.search(pattern, text, flags)`` call against one
of the fields we actually capture (``subject``, ``body``, ``sender``,
``from_domain``).

Rules in this file are derived from / inspired by the following open-source
projects. Heavy modifications (Perl-to-Python regex translation, scope
tightening for B2B false-positive avoidance, custom emoji and unicode rules)
have been applied — these are NOT byte-for-byte copies of upstream content.

Source attributions
-------------------
* **Apache SpamAssassin** — Apache License 2.0
  https://github.com/apache/spamassassin
  Specifically: ``rules/20_phrases.cf``, ``rules/20_head_tests.cf``,
  ``rules/20_advance_fee.cf``, ``rules/20_freemail.cf``.

* **SwiftFilter** by SwiftOnSecurity — MIT License
  https://github.com/SwiftOnSecurity/SwiftFilter
  Credential-phishing phrase patterns (mailbox-full, password-expiry,
  voicemail-attached, document-shared lures).

* **Custom rules** authored for this project for emoji / unicode abuse and
  payment-redirect / banking-change wire-fraud patterns that upstream
  projects do not cover.

Rule schema
-----------
Each entry in ``SPAM_HEURISTIC_RULES`` is a ``dict`` with these fields:

* ``id``           — uppercase identifier, unique
* ``category``     — one of: emoji_unicode, urgency, money_free,
                              credential_phishing, payment_redirect,
                              caps_punct, lookalike_freemail, advance_fee
* ``description``  — human-readable rationale (auditable in the trace UI)
* ``regex``        — raw Python regex string (always written as ``r"..."``)
* ``field``        — one of: subject, body, sender, from_domain
* ``flags``        — ``"i"`` for case-insensitive, ``""`` otherwise
* ``severity``     — low | medium | high
* ``source``       — spamassassin | swiftfilter | custom
* ``score_weight`` — float, contribution to overall spam score
"""

from __future__ import annotations

import re
from typing import Iterable

SPAM_HEURISTIC_RULES: list[dict] = [
    # ------------------------------------------------------------------
    # 1. Emoji / unicode spam in subject  (custom — SpamAssassin lacks these)
    # ------------------------------------------------------------------
    {
        "id": "EMOJI_SUBJECT_MULTI",
        "category": "emoji_unicode",
        "description": "Two or more emoji in subject line — common in promo blasts.",
        "regex": r"[\U0001F300-\U0001FAFF]{2,}",
        "field": "subject",
        "flags": "",
        "severity": "medium",
        "source": "custom",
        "score_weight": 2.0,
    },
    {
        "id": "EMOJI_SUBJECT_FIRE_ROCKET",
        "category": "emoji_unicode",
        "description": "Marketing 'hot deal' emoji (fire / rocket / 100) in subject.",
        "regex": r"[\U0001F525\U0001F680\U0001F4AF]",
        "field": "subject",
        "flags": "",
        "severity": "low",
        "source": "custom",
        "score_weight": 1.0,
    },
    {
        "id": "EMOJI_SUBJECT_MONEY",
        "category": "emoji_unicode",
        "description": "Money-bag / dollar / euro emoji in subject — promo or scam.",
        "regex": r"[\U0001F4B0\U0001F4B5\U0001F4B6\U0001F4B7\U0001F4B8\U0001F911]",
        "field": "subject",
        "flags": "",
        "severity": "medium",
        "source": "custom",
        "score_weight": 1.5,
    },
    {
        "id": "UNICODE_HOMOGLYPH_CYRILLIC_LATIN",
        "category": "emoji_unicode",
        "description": "Cyrillic letter inside an otherwise-ASCII word — common in lookalike phishing.",
        "regex": r"[A-Za-z][Ѐ-ӿ][A-Za-z]",
        "field": "subject",
        "flags": "",
        "severity": "high",
        "source": "custom",
        "score_weight": 3.0,
    },
    {
        "id": "ZERO_WIDTH_OBFUSCATION",
        "category": "emoji_unicode",
        "description": "Zero-width / invisible characters used to bypass keyword filters.",
        "regex": r"[​‌‍⁠﻿]",
        "field": "subject",
        "flags": "",
        "severity": "high",
        "source": "custom",
        "score_weight": 3.0,
    },
    {
        "id": "EMOJI_SUBJECT_WARNING_LOCK",
        "category": "emoji_unicode",
        "description": "Warning / lock / police-light emoji used to fake urgency.",
        "regex": r"[⚠\U0001F512\U0001F6A8\U0001F4E2]",
        "field": "subject",
        "flags": "",
        "severity": "medium",
        "source": "custom",
        "score_weight": 1.5,
    },

    # ------------------------------------------------------------------
    # 2. Urgency language (8-10 rules)
    # ------------------------------------------------------------------
    {
        "id": "URGENCY_ACT_NOW",
        "category": "urgency",
        "description": "Classic 'act now' urgency call-to-action.",
        "regex": r"\bact\s+now\b",
        "field": "body",
        "flags": "i",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },
    {
        "id": "URGENCY_TODAY_ONLY",
        "category": "urgency",
        "description": "'Today only' / 'this hour only' time-pressure hook.",
        "regex": r"\b(?:today|this\s+(?:hour|day|week))\s+only\b",
        "field": "body",
        "flags": "i",
        "severity": "medium",
        "source": "custom",
        "score_weight": 1.5,
    },
    {
        "id": "URGENCY_IMMEDIATE_ACTION",
        "category": "urgency",
        "description": "Demands immediate action — common in BEC and credential lures.",
        "regex": r"\bimmediate\s+(?:action|attention|response|reply)\s+(?:required|needed|requested)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "spamassassin",
        "score_weight": 2.5,
    },
    {
        "id": "URGENCY_LIMITED_TIME",
        "category": "urgency",
        "description": "'Limited-time offer' / 'while supplies last' promo language.",
        "regex": r"\b(?:limited[-\s]time\s+offer|while\s+supplies\s+last|hurry\s+(?:up|now))\b",
        "field": "body",
        "flags": "i",
        "severity": "low",
        "source": "custom",
        "score_weight": 1.0,
    },
    {
        "id": "URGENCY_EXPIRES_SOON",
        "category": "urgency",
        "description": "'Expires in N hours/days' countdown language.",
        "regex": r"\bexpires?\s+(?:in\s+)?\d+\s+(?:hour|hr|day|minute|min)s?\b",
        "field": "body",
        "flags": "i",
        "severity": "medium",
        "source": "custom",
        "score_weight": 1.5,
    },
    {
        "id": "URGENCY_FINAL_NOTICE",
        "category": "urgency",
        "description": "'Final notice' / 'last warning' pressure phrasing.",
        "regex": r"\b(?:final|last)\s+(?:notice|warning|reminder|chance)\b",
        "field": "subject",
        "flags": "i",
        "severity": "medium",
        "source": "custom",
        "score_weight": 1.5,
    },
    {
        "id": "URGENCY_RESPOND_24H",
        "category": "urgency",
        "description": "'Respond within 24 hours / 48 hours' deadline pressure.",
        "regex": r"\b(?:respond|reply|confirm)\s+within\s+\d+\s+hours?\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "custom",
        "score_weight": 2.0,
    },
    {
        "id": "URGENCY_DONT_DELAY",
        "category": "urgency",
        "description": "'Don't delay' / 'don't miss out' urgency.",
        "regex": r"\b(?:do\s*n[o']?t\s+(?:delay|wait|miss\s+out)|hurry,?\s+limited)\b",
        "field": "body",
        "flags": "i",
        "severity": "low",
        "source": "custom",
        "score_weight": 1.0,
    },
    {
        "id": "URGENCY_URGENT_BUSINESS",
        "category": "urgency",
        "description": "SpamAssassin __URG_BIZ — 'urgent business/proposal/notice' phrasing.",
        "regex": r"\burgent.{0,16}(?:assistance|business|notice|proposal|reply|response)\b",
        "field": "body",
        "flags": "i",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },

    # ------------------------------------------------------------------
    # 3. Money / discount / free claims (8-10 rules)
    # ------------------------------------------------------------------
    {
        "id": "MONEY_GUARANTEED_100",
        "category": "money_free",
        "description": "SpamAssassin GUARANTEED_100_PERCENT — '100% guaranteed' claim.",
        "regex": r"\b100\s*%\s*guarantee(?:d)?\b",
        "field": "body",
        "flags": "i",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },
    {
        "id": "MONEY_BILLION_DOLLARS",
        "category": "money_free",
        "description": "SpamAssassin BILLION_DOLLARS — sums of '$X MILLION' / 'BILLION DOLLAR'.",
        "regex": r"\b[BM]ILLION\s+DOLLARS?\b",
        "field": "body",
        "flags": "",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },
    {
        "id": "MONEY_BACK_GUARANTEE",
        "category": "money_free",
        "description": "SpamAssassin MONEY_BACK — generic money-back guarantee promo.",
        "regex": r"\bmoney[\s-]+back\s+guarantee\b",
        "field": "body",
        "flags": "i",
        "severity": "low",
        "source": "spamassassin",
        "score_weight": 1.0,
    },
    {
        "id": "MONEY_UNCLAIMED_FUNDS",
        "category": "money_free",
        "description": "SpamAssassin __FRAUD-style 'unclaimed funds/money/assets' lure.",
        "regex": r"\bunclaimed\s+(?:assets?|accounts?|money|monies|funds?|inheritance)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "spamassassin",
        "score_weight": 2.5,
    },
    {
        "id": "MONEY_FREE_QUOTE",
        "category": "money_free",
        "description": "SpamAssassin FREE_QUOTE_INSTANT — 'free instant/online/no-obligation quote'.",
        "regex": r"\bfree.{0,12}(?:instant|express|online|no[-\s]?obligation)\s+quote\b",
        "field": "body",
        "flags": "i",
        "severity": "low",
        "source": "spamassassin",
        "score_weight": 1.0,
    },
    {
        "id": "MONEY_LOTTERY_WINNER",
        "category": "money_free",
        "description": "Lottery / jackpot winning notification — overlap with 419 but pure money lure.",
        "regex": r"\byou(?:'ve|\s+have)\s+won\b.{0,60}\b(?:lottery|jackpot|prize|sweepstake|drawing)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "spamassassin",
        "score_weight": 2.5,
    },
    {
        "id": "MONEY_DOLLAR_SUBJECT",
        "category": "money_free",
        "description": "SpamAssassin SUBJ_DOLLARS — subject begins with a dollar amount.",
        "regex": r"^\s*\$[0-9.,]+\b",
        "field": "subject",
        "flags": "",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },
    {
        "id": "MONEY_BUY_SUBJECT",
        "category": "money_free",
        "description": "SpamAssassin SUBJ_BUY — subject begins with 'Buy ...'.",
        "regex": r"^\s*buy\b",
        "field": "subject",
        "flags": "i",
        "severity": "low",
        "source": "spamassassin",
        "score_weight": 1.0,
    },
    {
        "id": "MONEY_DISCOUNT_PERCENT",
        "category": "money_free",
        "description": "Aggressive percent-off promo (50% OFF / 90% off etc).",
        "regex": r"\b(?:5\d|[6-9]\d)\s*%\s*off\b",
        "field": "subject",
        "flags": "i",
        "severity": "low",
        "source": "custom",
        "score_weight": 1.0,
    },
    {
        "id": "MONEY_RISK_FREE",
        "category": "money_free",
        "description": "'Risk free' / 'no risk' — common in promotional copy.",
        "regex": r"\b(?:risk[-\s]?free|no\s+risk)\b",
        "field": "body",
        "flags": "i",
        "severity": "low",
        "source": "custom",
        "score_weight": 0.8,
    },

    # ------------------------------------------------------------------
    # 4. Credential phishing (6-8 rules) — SwiftFilter-inspired
    # ------------------------------------------------------------------
    {
        "id": "PHISH_VERIFY_ACCOUNT",
        "category": "credential_phishing",
        "description": "'Verify your account/identity' lure (SwiftFilter Tests-Phishing).",
        "regex": r"\bverify\s+your\s+(?:account|identity|email|mailbox|login|credentials?)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "swiftfilter",
        "score_weight": 3.0,
    },
    {
        "id": "PHISH_MAILBOX_FULL",
        "category": "credential_phishing",
        "description": "'Mailbox full / quota exceeded' — classic webmail credential phish.",
        "regex": r"\b(?:mailbox|inbox|email\s+storage)\s+(?:is\s+)?(?:full|quota\s+exceeded|near(?:ly|ing)\s+(?:full|capacity)|over\s+limit)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "swiftfilter",
        "score_weight": 3.0,
    },
    {
        "id": "PHISH_PASSWORD_EXPIRES",
        "category": "credential_phishing",
        "description": "'Your password (will) expire' — directs user to reset on attacker page.",
        "regex": r"\b(?:your\s+)?password\s+(?:will\s+)?expir(?:es?|ing|ed)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "swiftfilter",
        "score_weight": 3.0,
    },
    {
        "id": "PHISH_ACCOUNT_SUSPENDED",
        "category": "credential_phishing",
        "description": "'Your account has been suspended/disabled/locked' phishing trigger.",
        "regex": r"\byour\s+account\s+(?:has\s+been|will\s+be|is)\s+(?:suspend|disabl|lock|deactivat|block)(?:ed|ing)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "swiftfilter",
        "score_weight": 3.0,
    },
    {
        "id": "PHISH_CLICK_TO_VERIFY",
        "category": "credential_phishing",
        "description": "'Click here to verify / re-validate / confirm' credential-grab CTA.",
        "regex": r"\bclick\s+(?:here\s+)?(?:below\s+)?to\s+(?:verify|re-?validate|confirm|update|secure|reactivate)\s+(?:your\s+)?(?:account|password|credentials?|email|mailbox)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "swiftfilter",
        "score_weight": 3.0,
    },
    {
        "id": "PHISH_SECURE_DOC_SHARED",
        "category": "credential_phishing",
        "description": "'Secure document shared with you' SharePoint/OneDrive phish lure.",
        "regex": r"\b(?:secure\s+)?document\s+(?:has\s+been\s+)?shared\s+with\s+you\b",
        "field": "body",
        "flags": "i",
        "severity": "medium",
        "source": "swiftfilter",
        "score_weight": 2.0,
    },
    {
        "id": "PHISH_VOICEMAIL_ATTACHED",
        "category": "credential_phishing",
        "description": "'New voicemail' attachment lure — drops credential-harvest HTML.",
        "regex": r"\b(?:new\s+)?voice\s*mail\s+(?:message\s+)?(?:from|attached|received|waiting)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "swiftfilter",
        "score_weight": 2.5,
    },
    {
        "id": "PHISH_UNUSUAL_SIGNIN",
        "category": "credential_phishing",
        "description": "Fake 'unusual sign-in activity' security-alert lure.",
        "regex": r"\b(?:unusual|suspicious|unrecognised?|new)\s+(?:sign[-\s]?in|login|activity)\s+(?:detected|attempt|on\s+your)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "swiftfilter",
        "score_weight": 2.5,
    },

    # ------------------------------------------------------------------
    # 5. Payment redirect / banking change (4-6 rules) — custom (BEC/wire fraud)
    # ------------------------------------------------------------------
    {
        "id": "PAY_BANK_DETAILS_CHANGED",
        "category": "payment_redirect",
        "description": "'Our banking details have changed' — BEC wire-redirect indicator.",
        "regex": r"\b(?:our\s+)?(?:bank(?:ing)?|account|wire|payment)\s+(?:details?|info(?:rmation)?|instructions?)\s+(?:have|has)\s+(?:changed|been\s+updated)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "custom",
        "score_weight": 4.0,
    },
    {
        "id": "PAY_NEW_WIRE_INSTRUCTIONS",
        "category": "payment_redirect",
        "description": "'Please use new/updated wire instructions' — BEC redirect.",
        "regex": r"\b(?:new|updated|revised)\s+(?:wire|wiring|payment|remittance|ach)\s+(?:instruction|detail|information)s?\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "custom",
        "score_weight": 4.0,
    },
    {
        "id": "PAY_REMIT_TO_NEW_ACCOUNT",
        "category": "payment_redirect",
        "description": "'Remit/send payment to new account' phrase pattern.",
        "regex": r"\b(?:remit|send|wire|deposit|transfer)\s+(?:the\s+)?(?:payment|funds?|invoice)\s+to\s+(?:our\s+)?new\s+(?:bank\s+)?account\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "custom",
        "score_weight": 4.0,
    },
    {
        "id": "PAY_INVOICE_AMENDED",
        "category": "payment_redirect",
        "description": "'Amended/updated invoice — pay to different account' BEC lure.",
        "regex": r"\b(?:amended|revised|updated|corrected)\s+invoice\b.{0,80}\b(?:account|iban|swift|routing)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "custom",
        "score_weight": 3.5,
    },
    {
        "id": "PAY_CFO_URGENT_TRANSFER",
        "category": "payment_redirect",
        "description": "CEO/CFO impersonation — 'urgent transfer / are you available'.",
        "regex": r"\b(?:are\s+you\s+available|quick\s+task|need\s+a\s+favor)\b.{0,80}\b(?:wire|transfer|payment|gift\s*card)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "custom",
        "score_weight": 3.0,
    },

    # ------------------------------------------------------------------
    # 6. ALL-CAPS subject + multiple punctuation (3-4 rules)
    # ------------------------------------------------------------------
    {
        "id": "CAPS_SUBJECT_SHOUTING",
        "category": "caps_punct",
        "description": "Subject is mostly uppercase letters (>=10 caps with low lowercase ratio).",
        "regex": r"^[^a-z]*[A-Z][A-Z\s\W]{9,}[^a-z]*$",
        "field": "subject",
        "flags": "",
        "severity": "low",
        "source": "spamassassin",
        "score_weight": 1.0,
    },
    {
        "id": "CAPS_MULTIPLE_BANGS",
        "category": "caps_punct",
        "description": "Three or more exclamation marks anywhere in subject.",
        "regex": r"!{3,}",
        "field": "subject",
        "flags": "",
        "severity": "low",
        "source": "custom",
        "score_weight": 1.0,
    },
    {
        "id": "CAPS_PLING_QUERY",
        "category": "caps_punct",
        "description": "SpamAssassin PLING_QUERY — both '!' and '?' present in subject.",
        "regex": r"(?=.*!)(?=.*\?)",
        "field": "subject",
        "flags": "",
        "severity": "low",
        "source": "spamassassin",
        "score_weight": 0.8,
    },
    {
        "id": "CAPS_GAPPY_SUBJECT",
        "category": "caps_punct",
        "description": "SpamAssassin GAPPY_SUBJECT — 'V.I.A.G.R.A' style obfuscated words.",
        "regex": r"\b(?:[A-Za-z][-_.=~/:,*!@#$%^&+;\"'<>\\]){4,}",
        "field": "subject",
        "flags": "",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },

    # ------------------------------------------------------------------
    # 7. Lookalike / freemail abuse / suspicious domain patterns (4-6 rules)
    # ------------------------------------------------------------------
    {
        "id": "DOMAIN_FREEMAIL_BUSINESS",
        "category": "lookalike_freemail",
        "description": "Sender uses freemail provider while claiming business identity (gmail/yahoo/hotmail/outlook/aol/protonmail/icloud).",
        "regex": r"@(?:gmail|yahoo|hotmail|outlook|live|aol|protonmail|icloud|gmx|mail)\.(?:com|net|org|co\.[a-z]{2})$",
        "field": "from_domain",
        "flags": "i",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },
    {
        "id": "DOMAIN_NUMERIC_FREEMAIL",
        "category": "lookalike_freemail",
        "description": "SpamAssassin FREEMAIL_ENVFROM_END_DIGIT — freemail localpart ending in long digit run.",
        "regex": r"^[a-z0-9._-]*\d{4,}@(?:gmail|yahoo|hotmail|outlook|live|aol)\.com$",
        "field": "sender",
        "flags": "i",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },
    {
        "id": "DOMAIN_LOOKALIKE_KEYSIGHT",
        "category": "lookalike_freemail",
        "description": "Lookalike of keysight.com — keysiqht / keysight-support / keysight.co etc.",
        "regex": r"@(?:(?:keys[il1]qht|keysiqht|keyslght|keys1ght|keysiqnt|keysiglht)\.[a-z]{2,}|keysight[-.][a-z]+\.(?:com|net|info|biz|co))",
        "field": "from_domain",
        "flags": "i",
        "severity": "high",
        "source": "custom",
        "score_weight": 4.0,
    },
    {
        "id": "DOMAIN_NOVOWEL",
        "category": "lookalike_freemail",
        "description": "SpamAssassin FROM_DOMAIN_NOVOWEL — sender domain has 7+ consecutive consonants.",
        "regex": r"@\S*[bcdfgjklmnpqrstvwxz]{7}",
        "field": "sender",
        "flags": "i",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },
    {
        "id": "DOMAIN_LOCAL_HEX",
        "category": "lookalike_freemail",
        "description": "SpamAssassin FROM_LOCAL_HEX — 11+ hex chars in sender localpart (botnet random).",
        "regex": r"^[0-9a-f]{11,}@",
        "field": "sender",
        "flags": "i",
        "severity": "medium",
        "source": "spamassassin",
        "score_weight": 1.5,
    },
    {
        "id": "DOMAIN_PUNYCODE_IDN",
        "category": "lookalike_freemail",
        "description": "Punycode IDN domain (xn--...) — common in homograph phishing domains.",
        "regex": r"@xn--[a-z0-9-]+\.",
        "field": "from_domain",
        "flags": "i",
        "severity": "high",
        "source": "custom",
        "score_weight": 3.0,
    },

    # ------------------------------------------------------------------
    # 8. Advance-fee / 419 scams (3-5 rules)
    # ------------------------------------------------------------------
    {
        "id": "FRAUD_BENEFICIARY",
        "category": "advance_fee",
        "description": "SpamAssassin __FRAUD_PVN — 'as the beneficiary' 419-scam intro.",
        "regex": r"\bas\s+the\s+beneficiary\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "spamassassin",
        "score_weight": 3.0,
    },
    {
        "id": "FRAUD_DECEASED_RELATIVE",
        "category": "advance_fee",
        "description": "SpamAssassin __FRAUD_ZFJ — 'wife/son/brother/daughter of the late' bait.",
        "regex": r"\b(?:wife|son|brother|daughter|widow)\s+of\s+the\s+late\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "spamassassin",
        "score_weight": 3.5,
    },
    {
        "id": "FRAUD_NIGERIA_BANK",
        "category": "advance_fee",
        "description": "SpamAssassin __FRAUD_NEB — 'government/bank of Nigeria' reference.",
        "regex": r"\b(?:government|bank|central\s+bank)\s+of\s+nigeria\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "spamassassin",
        "score_weight": 3.5,
    },
    {
        "id": "FRAUD_INTRO_TITLE",
        "category": "advance_fee",
        "description": "SpamAssassin __FRAUD_QXX — 'I am Mrs/Engr/Barrister/Prince' intro pattern.",
        "regex": r"\b(?:my\s+name\s+is|i\s+am)\s+(?:mrs?|engr|barrister|dr|prince(?:ss)?)\.?\s+[A-Z]",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "spamassassin",
        "score_weight": 3.0,
    },
    {
        "id": "FRAUD_LARGE_USD_SUM",
        "category": "advance_fee",
        "description": "SpamAssassin __FRAUD_KDT — 'USD $X,XXX,XXX' or 'X million' sums.",
        "regex": r"\bU\.?S\.?D?\.?\s*\$?\s*(?:\d{1,3}(?:,\d{3}){2,}|\d+(?:\.\d+)?\s*milli?on)\b",
        "field": "body",
        "flags": "i",
        "severity": "high",
        "source": "spamassassin",
        "score_weight": 2.5,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compile_flags(flag_str: str) -> int:
    """Translate the rule 'flags' string ('i' or '') to an ``re`` flags int."""
    flags = 0
    if "i" in flag_str.lower():
        flags |= re.IGNORECASE
    return flags


def compiled_rules() -> Iterable[tuple[dict, "re.Pattern[str]"]]:
    """Yield ``(rule_dict, compiled_pattern)`` for every rule in the seed list."""
    for rule in SPAM_HEURISTIC_RULES:
        yield rule, re.compile(rule["regex"], _compile_flags(rule["flags"]))


# ---------------------------------------------------------------------------
# Self-test  (run as `python -m kb_seeds.spam_heuristic_rules`)
# ---------------------------------------------------------------------------

# Each entry: rule_id -> (positive_example, negative_example).
# Positive must MATCH; negative must NOT match.
_SELF_TEST_FIXTURES: dict[str, tuple[str, str]] = {
    "EMOJI_SUBJECT_MULTI": ("Sale today \U0001F525\U0001F4B0", "Quarterly review meeting"),
    "EMOJI_SUBJECT_FIRE_ROCKET": ("\U0001F680 New product launch", "Q2 roadmap update"),
    "EMOJI_SUBJECT_MONEY": ("\U0001F4B0 Save now", "Quarterly P&L review"),
    "UNICODE_HOMOGLYPH_CYRILLIC_LATIN": ("Paрment due", "Payment due"),
    "ZERO_WIDTH_OBFUSCATION": ("Veri​fy account", "Verify account"),
    "EMOJI_SUBJECT_WARNING_LOCK": ("⚠ Action required", "Status update"),

    "URGENCY_ACT_NOW": ("Act now to claim your prize", "We will action this in our next sprint"),
    "URGENCY_TODAY_ONLY": ("Today only: 50 percent off", "We are open today"),
    "URGENCY_IMMEDIATE_ACTION": ("Immediate action required on your account", "We need to plan our next action"),
    "URGENCY_LIMITED_TIME": ("Limited-time offer ends Friday", "We have limited time on the agenda"),
    "URGENCY_EXPIRES_SOON": ("Your trial expires in 3 days", "The contract expires next quarter"),
    "URGENCY_FINAL_NOTICE": ("FINAL NOTICE: payment overdue", "Quarterly meeting notice"),
    "URGENCY_RESPOND_24H": ("Please respond within 24 hours", "Please respond when you can"),
    "URGENCY_DONT_DELAY": ("Don't delay, order now", "We should not stall the project"),
    "URGENCY_URGENT_BUSINESS": ("Urgent business proposal for you", "Business as usual today"),

    "MONEY_GUARANTEED_100": ("100% guaranteed returns!", "We guarantee on-time delivery"),
    "MONEY_BILLION_DOLLARS": ("Win MILLION DOLLARS today", "Our revenue grew last year"),
    "MONEY_BACK_GUARANTEE": ("30-day money-back guarantee", "Please send the package back"),
    "MONEY_UNCLAIMED_FUNDS": ("You have unclaimed funds waiting", "The funds are allocated to Q3"),
    "MONEY_FREE_QUOTE": ("Get a free instant quote today", "Please quote our reference number"),
    "MONEY_LOTTERY_WINNER": ("You have won the international lottery", "We won the deal last week"),
    "MONEY_DOLLAR_SUBJECT": ("$1,000,000 awaits you", "Pricing update for Q3"),
    "MONEY_BUY_SUBJECT": ("Buy cheap meds online", "We bought new equipment"),
    "MONEY_DISCOUNT_PERCENT": ("80% off everything", "Conversion rate up 5%"),
    "MONEY_RISK_FREE": ("Risk-free trial available", "Please assess project risk"),

    "PHISH_VERIFY_ACCOUNT": ("Verify your account to continue", "Please confirm the meeting"),
    "PHISH_MAILBOX_FULL": ("Your mailbox is full, action needed", "The conference room is full"),
    "PHISH_PASSWORD_EXPIRES": ("Your password will expire in 24h", "Our SSO rotation policy is documented"),
    "PHISH_ACCOUNT_SUSPENDED": ("Your account has been suspended", "We suspended the project review"),
    "PHISH_CLICK_TO_VERIFY": ("Click here to verify your password", "Click the link to view the agenda"),
    "PHISH_SECURE_DOC_SHARED": ("A secure document has been shared with you", "Please share the document with the team"),
    "PHISH_VOICEMAIL_ATTACHED": ("New voicemail message attached", "Please leave a voicemail at extension 5"),
    "PHISH_UNUSUAL_SIGNIN": ("Unusual sign-in detected on your account", "Sign in to the conference room when you arrive"),

    "PAY_BANK_DETAILS_CHANGED": ("Our banking details have changed, see attached", "Please confirm the meeting details"),
    "PAY_NEW_WIRE_INSTRUCTIONS": ("Please use new wire instructions", "We will wire up the demo room"),
    "PAY_REMIT_TO_NEW_ACCOUNT": ("Please remit payment to our new account", "Payment was received yesterday"),
    "PAY_INVOICE_AMENDED": ("Amended invoice attached - new IBAN", "Invoice attached, payable in 30 days"),
    "PAY_CFO_URGENT_TRANSFER": ("Are you available? I need a wire transfer done", "Are you available for the planning call?"),

    "CAPS_SUBJECT_SHOUTING": ("URGENT PAYMENT REQUIRED NOW", "Quarterly review on Tuesday"),
    "CAPS_MULTIPLE_BANGS": ("Sale!!! Today only", "Welcome! Glad to have you."),
    "CAPS_PLING_QUERY": ("Are you ready?! Act now!", "Quick question about the agenda"),
    "CAPS_GAPPY_SUBJECT": ("V-I-A-G-R-A discount", "Q3 roadmap and milestones"),

    "DOMAIN_FREEMAIL_BUSINESS": ("ceo@gmail.com", "alice@keysight.com"),
    "DOMAIN_NUMERIC_FREEMAIL": ("john1234567@gmail.com", "john.smith@gmail.com"),
    "DOMAIN_LOOKALIKE_KEYSIGHT": ("billing@keysiqht.com", "billing@keysight.com"),
    "DOMAIN_NOVOWEL": ("alice@bcdfgklmnpq.com", "alice@example.com"),
    "DOMAIN_LOCAL_HEX": ("a1b2c3d4e5f@spam.com", "alice@example.com"),
    "DOMAIN_PUNYCODE_IDN": ("user@xn--keysght-2wa.com", "user@keysight.com"),

    "FRAUD_BENEFICIARY": ("You are named as the beneficiary", "Beneficiary list attached"),
    "FRAUD_DECEASED_RELATIVE": ("I am the widow of the late minister", "We had a late lunch yesterday"),
    "FRAUD_NIGERIA_BANK": ("Central Bank of Nigeria has approved", "Our Lagos office is fully operational"),
    "FRAUD_INTRO_TITLE": ("My name is Barrister John Doe", "My name is John from procurement"),
    "FRAUD_LARGE_USD_SUM": ("USD $25,500,000 awaits you", "Our budget is $50,000 this quarter"),
}


def _run_self_test() -> int:
    """Execute self-tests; return the number of failures."""
    failures: list[str] = []
    missing_fixtures: list[str] = []
    rule_ids = {r["id"] for r in SPAM_HEURISTIC_RULES}

    # Sanity: every rule must have a fixture.
    for rid in rule_ids:
        if rid not in _SELF_TEST_FIXTURES:
            missing_fixtures.append(rid)

    for rule, pattern in compiled_rules():
        rid = rule["id"]
        if rid not in _SELF_TEST_FIXTURES:
            continue
        positive, negative = _SELF_TEST_FIXTURES[rid]
        if not pattern.search(positive):
            failures.append(f"{rid}: positive example did NOT match: {positive!r}")
        if pattern.search(negative):
            failures.append(f"{rid}: negative example MATCHED (false positive): {negative!r}")

    # Per-category counts.
    by_cat: dict[str, int] = {}
    for rule in SPAM_HEURISTIC_RULES:
        by_cat[rule["category"]] = by_cat.get(rule["category"], 0) + 1

    print(f"Total rules: {len(SPAM_HEURISTIC_RULES)}")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:24s} {n}")

    if missing_fixtures:
        print(f"\nMissing self-test fixtures for {len(missing_fixtures)} rule(s):")
        for rid in missing_fixtures:
            print(f"  - {rid}")
        failures.extend(f"missing fixture: {rid}" for rid in missing_fixtures)

    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return len(failures)

    print("\nAll self-tests passed.")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_self_test())
