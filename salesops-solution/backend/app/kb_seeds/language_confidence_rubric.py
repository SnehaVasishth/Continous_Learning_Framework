"""Seed rules for the `language_confidence_rubric` KB namespace.

Stage 1 sub-step 1.4 returns a `language` (en | es | ja | other) plus a
`confidence` percentage. Without a rubric, that percentage is whatever the
LLM training data implies — opaque to operators. This rubric makes the
score deterministic + auditable: the LLM evaluates each rule and reports a
per-rule contribution; we recompute the final number server-side from
`base + sum(matched deltas)` clamped to [0.0, 1.0].

Operators tune the rubric in Settings → Knowledge Base → "Language
confidence rubric" — change a delta, deactivate a rule, add a per-language
override — without a code change.

Companion to `language_heuristic` (which is the deterministic regex/script
detector). The heuristic decides "what language?" structurally; this
rubric decides "how confident should we be?" once the LLM reads the email.

Each rule:
  - `default_delta`         applied to ALL languages unless overridden
  - `per_language_overrides`{lang_key: delta} for tuning
  - `kind`                  trigger / clearance / penalty / base
  - `description`           what the LLM looks for
  - `examples`              concrete cues per language
"""
from __future__ import annotations

from typing import Any

LANGUAGE_CONFIDENCE_BASE = 0.40


LANGUAGE_CONFIDENCE_RUBRIC_RULES: list[dict[str, Any]] = [
    # ---- meta: starting prior ---------------------------------------------
    {
        "id": "_base",
        "label": "Base confidence (calibration prior, default 0.40)",
        "description": (
            "Starting score before any rubric rule applies. Final confidence = "
            "base + sum(matched deltas), clamped to [0.0, 1.0]. "
            "We use 0.40 — sized DOWN from the intent rubric's 0.50 because language "
            "detection has only 4 buckets (en / es / ja / other), so:\n"
            "  • The textbook uniform prior is 1 / 4 = 0.25 (max-entropy over equally-likely "
            "    classes). That's the right floor when the model is blind to the text.\n"
            "  • The LLM has decent pretrained priors over script + alphabet (recognizes "
            "    hiragana on sight, recognizes Latin diacritics, etc.) before any rubric rule "
            "    fires — so we splash a small bump over uniform: +0.15 above 0.25 = 0.40.\n"
            "  • The intent rubric's 0.50 reflects that intent has 13 buckets — the LLM's "
            "    'is this intent or not' decision is closer to a binary outcome (Laplacian neutral "
            "    Beta(1,1) prior).\n"
            "Tune this number if calibration data shows over- or under-confidence — change here, "
            "no code change required."
        ),
        "kind": "base",
        "value": LANGUAGE_CONFIDENCE_BASE,
        "default_delta": 0.0,
        "per_language_overrides": {},
        "active": True,
    },
    # ---- triggers ---------------------------------------------------------
    {
        "id": "script_definitive_match",
        "label": "Script unambiguously belongs to the candidate language",
        "description": (
            "What it does: rewards the chosen language when the text contains a "
            "script that's near-definitive for it (hiragana/katakana for ja, "
            "Cyrillic / Devanagari / Arabic / Hangul for 'other'). For Latin-script "
            "languages (en / es) this rule alone isn't strong because Latin is shared "
            "— per-language overrides drop the delta accordingly.\n\n"
            "Heaviest single signal in the rubric (default +0.50) because script "
            "presence is the most reliable language cue we have.\n\n"
            "How to optimize:\n"
            "  • Per-language override is the main lever here — already set: ja=+0.55 "
            "    (script is unambiguous), es=+0.30 / en=+0.30 (Latin script alone is "
            "    weak), other=+0.30.\n"
            "  • Bump ja override even higher (e.g. +0.60) if you're seeing valid "
            "    JA emails get sent to HITL because they have lots of English SKUs "
            "    embedded — the script signal should trump the mix.\n"
            "  • Don't lower below +0.30 for any language — script is fundamental.\n"
            "  • If you add support for a new language (e.g. de, fr, zh), add a new "
            "    per-language override here."
        ),
        "kind": "trigger",
        "default_delta": 0.50,
        "per_language_overrides": {
            "ja": 0.55,
            "es": 0.30,
            "en": 0.30,
            "other": 0.30,
        },
        "examples": {
            "ja": ["hiragana あ-ん", "katakana ア-ン", "kanji 一-鿿", "full-width 、。"],
            "es": ["ñ", "á é í ó ú", "¿ ¡"],
            "en": ["pure ASCII Latin set, no diacritics, no CJK"],
            "other": ["Cyrillic а-я", "Devanagari अ-ह", "Arabic ا-ي", "Hangul ㄱ-ㅎ"],
        },
        "active": True,
    },
    {
        "id": "diacritic_signature",
        "label": "Diacritic signature characteristic of the candidate language",
        "description": (
            "What it does: rewards the chosen language when distinctive diacritics "
            "or punctuation patterns are present — `ñ ¿ ¡` for Spanish, full-width "
            "punctuation 「」・ for Japanese, plain ASCII apostrophes / no diacritics "
            "for English. Weaker than full script presence but a strong corroborating "
            "signal for Latin-script languages.\n\n"
            "How to optimize:\n"
            "  • Per-language overrides handle most tuning: es=+0.18 (diacritics are "
            "    common and load-bearing in Spanish), en=+0.05 (most English doesn't "
            "    use diacritics, so absence-of-diacritics is the signal — kept low).\n"
            "  • Raise es override if Spanish emails are getting under-scored because "
            "    only 1-2 diacritics appear (e.g., 'año' alone, no '¿' or '¡').\n"
            "  • Don't conflate this with keyword_density_high — they should fire "
            "    independently. If both fire, that's strong corroboration."
        ),
        "kind": "trigger",
        "default_delta": 0.15,
        "per_language_overrides": {
            "es": 0.18,
            "en": 0.05,
        },
        "examples": {
            "es": ["¿qué?", "¡hola!", "está", "más", "año"],
            "en": ["plain ASCII apostrophe ', clean en-dash sentences"],
            "ja": ["「 」 brackets", "・ middle dot"],
        },
        "active": True,
    },
    {
        "id": "keyword_density_high",
        "label": "≥3 high-frequency tokens of the candidate language present",
        "description": (
            "What it does: rewards the chosen language when ≥3 top-50 stopwords / "
            "function words appear in the text (e.g. 'que', 'de', 'la', 'el', 'en' "
            "for es; 'the', 'and', 'of', 'to' for en; 'です', 'ます', 'して' for ja). "
            "This is THE primary signal for distinguishing English vs Spanish where "
            "script gives us nothing.\n\n"
            "How to optimize:\n"
            "  • Raise default_delta if real-world Latin-script email is being "
            "    classified as 'other' too often — the keyword test is the disambiguator.\n"
            "  • Lower the threshold from 3 → 2 in the prompt examples if you're "
            "    seeing short Spanish emails ('Hola, gracias') get under-credited.\n"
            "  • The actual word lists live in the language_heuristic KB namespace "
            "    (LANGUAGE_KEYWORD_LISTS) — extend those to support new languages.\n"
            "  • Pairs well with greeting_or_signoff_match; together they should "
            "    push a clean monolingual email to ~0.85 even without diacritics."
        ),
        "kind": "trigger",
        "default_delta": 0.15,
        "per_language_overrides": {},
        "examples": {
            "en": ["the", "and", "of", "to", "a", "is", "in", "we", "for"],
            "es": ["que", "de", "la", "el", "en", "los", "una", "por", "con"],
            "ja": ["です", "ます", "して", "ください", "について"],
        },
        "active": True,
    },
    {
        "id": "greeting_or_signoff_match",
        "label": "Opening / closing greeting matches the candidate language",
        "description": (
            "What it does: rewards the chosen language when the opening salutation "
            "or closing sign-off matches its conventions — 'Hi/Hello/Best regards' "
            "for en, 'Hola/Estimado/Saludos/Cordialmente' for es, 'お世話になっております"
            "/敬具' for ja. Especially useful for short emails where the body itself "
            "doesn't carry enough function words.\n\n"
            "How to optimize:\n"
            "  • Default +0.10 is intentionally low — greetings can leak across "
            "    languages (an English speaker writing 'Saludos' to a Spanish customer).\n"
            "  • Raise to +0.15 if your customer base is multilingual and short emails "
            "    are common.\n"
            "  • If you observe operators consistently fixing language detection on "
            "    short emails in HITL, raise this AND keyword_density_high together — "
            "    short emails benefit from both."
        ),
        "kind": "trigger",
        "default_delta": 0.10,
        "per_language_overrides": {},
        "examples": {
            "en": ["Hi team", "Hello", "Best regards", "Thanks", "Sincerely"],
            "es": ["Estimado", "Hola", "Saludos", "Cordialmente", "Atentamente"],
            "ja": ["お世話になっております", "宜しくお願い致します", "敬具", "拝啓"],
        },
        "active": True,
    },
    {
        "id": "single_language_throughout",
        "label": "No competing-language signals (single-language coherence)",
        "description": (
            "What it does: rewards clarity. Fires when the text shows signals from "
            "ONLY the chosen language — no code-switching to another, no foreign-"
            "script intrusion. Counterpart to mixed_language_penalty.\n\n"
            "How to optimize:\n"
            "  • Don't raise above ~+0.15 — clarity is corroboration, the triggers "
            "    (script / diacritic / keyword / greeting) should do the primary work.\n"
            "  • If both this AND mixed_language_penalty fire on the same email, "
            "    your LLM is hedging — tighten the rule's prompt examples or accept "
            "    the net (-0.10) effect (penalty wins).\n"
            "  • Lower to +0.05 if you're seeing systematic over-scoring on emails "
            "    that have a few foreign tokens but the LLM still calls them "
            "    monolingual."
        ),
        "kind": "clearance",
        "default_delta": 0.10,
        "per_language_overrides": {},
        "active": True,
    },
    # ---- penalties --------------------------------------------------------
    {
        "id": "mixed_language_penalty",
        "label": "Strong tokens from another language present (code-switching)",
        "description": (
            "What it does: drops confidence when the text has clear tokens from a "
            "second language alongside the chosen one — Spanish body with English "
            "PO line items, Japanese body with English SKUs, etc. Mixed-language "
            "email is genuinely harder to translate cleanly, so the system should "
            "be less confident.\n\n"
            "How to optimize:\n"
            "  • Default -0.20 is the floor for most languages.\n"
            "  • ja=-0.10 is the existing override — Japanese B2B email routinely "
            "    embeds English part numbers / SKUs and we don't want to penalize "
            "    that pattern as heavily.\n"
            "  • Lower magnitude (e.g. -0.10 across the board) if too many "
            "    legitimate code-switching emails are being routed to HITL.\n"
            "  • Raise magnitude (e.g. -0.30) if you've started supporting machine "
            "    translation downstream and need cleaner monolingual input."
        ),
        "kind": "penalty",
        "default_delta": -0.20,
        "per_language_overrides": {
            "ja": -0.10,  # JA emails often embed English part-numbers/SKUs — softer penalty
        },
        "active": True,
    },
    {
        "id": "too_short_for_signal",
        "label": "Text too short to confidently infer language (< 30 chars)",
        "description": (
            "What it does: drops confidence on extremely short emails (< 30 non-"
            "whitespace chars). Even strong signals like a Japanese kanji can "
            "mislead with little text — a one-word forwarded email shouldn't "
            "trip L4 auto.\n\n"
            "How to optimize:\n"
            "  • Raise the threshold from 30 to e.g. 50 chars in the rule's "
            "    description if you're seeing short auto-replies (out-of-office, "
            "    'Got it, thanks') get over-confident detection.\n"
            "  • Lower magnitude (e.g. -0.10) if your real inbound is mostly "
            "    short and you're seeing too many emails route to HITL.\n"
            "  • Keep this rule active — short emails are inherently uncertain "
            "    and the penalty is the right behavior."
        ),
        "kind": "penalty",
        "default_delta": -0.20,
        "per_language_overrides": {},
        "active": True,
    },
    {
        "id": "script_signal_disagreement",
        "label": "Script suggests one language but other signals contradict",
        "description": (
            "What it does: drops confidence when the script signal points to one "
            "language but greeting, keyword, or idiom signals point to a different "
            "one. Rare in practice but it's a real phishing / translation-leak "
            "pattern (e.g., Spanish-looking diacritics with English-only function "
            "words could be a machine-translation artifact). Force HITL review.\n\n"
            "How to optimize:\n"
            "  • Default -0.20 is appropriate. Raise to -0.30 if you start supporting "
            "    high-stakes auto-actions (purchase orders > $500K) and need extra "
            "    safety.\n"
            "  • Lower to -0.10 if you're seeing legitimate emails get penalized "
            "    because the LLM can't reconcile two valid signals (e.g., Spanish "
            "    body with English greeting from a corporate template).\n"
            "  • The rule fires rarely. If it never fires across thousands of runs, "
            "    that's expected — keep it active for safety."
        ),
        "kind": "penalty",
        "default_delta": -0.20,
        "per_language_overrides": {},
        "active": True,
    },
]


def all_rules() -> list[dict[str, Any]]:
    """Return all rubric rules — used by the seeder."""
    return LANGUAGE_CONFIDENCE_RUBRIC_RULES
