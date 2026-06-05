"""
Language heuristic rules — seed data for rule-based language detection (EN/ES/JA + "other").

Used by the email classifier to make an early, transparent, non-ML language decision
before falling back to model-based classification. Rules are evaluated in tiered order;
the first "definitive" match wins, otherwise weights are accumulated.

Sources & credits
-----------------
* Stopword lists adapted (and heavily filtered for discriminative power) from
  stopwords-iso (MIT License) — https://github.com/stopwords-iso/stopwords-iso
    - stopwords-en.txt
    - stopwords-es.txt
    - stopwords-ja.txt
* Tiered/severity rule design inspired by lingua-py (Apache 2.0) —
  https://github.com/pemistahl/lingua-py
    - https://github.com/pemistahl/lingua-py/blob/main/lingua/builder.py
    - Concept: combine Unicode-script signals with character-n-gram / token signals,
      with explicit confidence levels rather than a single opaque score.

Notes on filtering
------------------
The raw stopwords-iso lists contain many entries that hurt discrimination in B2B email
text (single letters, ISO country codes, English/Spanish overlaps such as "no", "a",
"me", "si", "ok"). The lists below are pruned to high-precision indicators:
  * ES: function words / verb forms that are unlikely to occur as standalone tokens
        in English emails (e.g. "que", "los", "para", "estimado").
  * EN: high-frequency function words that are unambiguously English (e.g. "the",
        "and", "of", "regards", "attached").
  * JA: particles and structural words that, when present in non-script text, still
        strongly suggest Japanese (mostly redundant given Tier-1 script rules, but
        useful for kanji-only / mixed-romanization edge cases).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


# ---------------------------------------------------------------------------
# Keyword lists (pruned for high precision)
# ---------------------------------------------------------------------------

# 50 high-discriminator Spanish tokens. Words that overlap with common English
# tokens ("no", "a", "me", "si", "ok") are intentionally excluded.
ES_KEYWORDS: list[str] = [
    "que", "de", "la", "el", "en", "los", "las", "una", "por", "con",
    "para", "pero", "más", "este", "esta", "esto", "estos", "estas", "su", "sus",
    "le", "les", "lo", "ya", "también", "donde", "cuando", "porque", "sólo", "muy",
    "sin", "sobre", "entre", "hasta", "desde", "así", "según", "mientras", "además", "aunque",
    "todavía", "mismo", "mucho", "muchos", "hacer", "decir", "ser", "estar", "tiene", "había",
]

# 50 high-discriminator English tokens. Avoids items that frequently appear in
# Spanish too (numerals, single letters, "a", "no").
EN_KEYWORDS: list[str] = [
    "the", "and", "of", "to", "in", "that", "is", "it", "for", "on",
    "with", "as", "was", "at", "be", "by", "this", "have", "from", "or",
    "are", "we", "an", "but", "not", "you", "all", "can", "will", "has",
    "our", "your", "please", "thank", "thanks", "hello", "regards", "best", "kind", "dear",
    "sincerely", "attached", "find", "would", "like", "should", "could", "team", "meeting", "thanks.",
]

# 30 Japanese particles / structural words. Mostly hiragana so script rules catch
# them too, but used as a fallback signal for kanji-heavy or transliterated text.
JA_KEYWORDS: list[str] = [
    "の", "は", "を", "に", "が", "と", "で", "から", "まで", "より",
    "へ", "や", "も", "など", "して", "した", "する", "して", "ます", "です",
    "ある", "いる", "この", "その", "あの", "それ", "これ", "ため", "こと", "もの",
]

LANGUAGE_KEYWORD_LISTS: dict[str, list[str]] = {
    "es": ES_KEYWORDS,
    "en": EN_KEYWORDS,
    "ja": JA_KEYWORDS,
}


# ---------------------------------------------------------------------------
# Rule set
# ---------------------------------------------------------------------------
# Tiers run in order: 1 (script) → 2 (diacritic) → 3 (keyword density) → 4 (greeting).
# Within a tier rules are evaluated together; the highest-severity firing rule wins.
# A rule with severity == "definitive" short-circuits all lower tiers.
#
# kind values:
#   "regex"           — count regex matches in the text; fires when count >= threshold
#   "unicode_block"   — count chars in the given Unicode range; fires when count >= threshold
#                       (optional "exclude_blocks": list of (start, end) tuples to subtract)
#   "keyword_density" — tokenize text (lowercase, word-boundary), count tokens in `tokens`;
#                       fires when count >= threshold

LANGUAGE_HEURISTIC_RULES: list[dict[str, Any]] = [
    # -----------------------------------------------------------------
    # Tier 1 — Script rules (definitive)
    # -----------------------------------------------------------------
    {
        "id": "JA_HIRAGANA_PRESENT",
        "tier": 1,
        "language": "ja",
        "description": "Hiragana script (U+3040–U+309F) present — exclusive to Japanese.",
        "kind": "unicode_block",
        "block": (0x3040, 0x309F),
        "threshold": 1,
        "severity": "definitive",
        "score_weight": 1.0,
    },
    {
        "id": "JA_KATAKANA_PRESENT",
        "tier": 1,
        "language": "ja",
        "description": "Katakana script (U+30A0–U+30FF) present — exclusive to Japanese.",
        "kind": "unicode_block",
        "block": (0x30A0, 0x30FF),
        "threshold": 1,
        "severity": "definitive",
        "score_weight": 1.0,
    },
    {
        "id": "JA_CJK_IDEOGRAPHS_NO_KANA",
        "tier": 1,
        "language": "ja",
        "description": (
            "CJK ideographs (U+4E00–U+9FFF) present without hiragana/katakana. "
            "Ambiguous between Japanese and Chinese, but in our 3-language taxonomy "
            "(EN/ES/JA + other) we route to JA at high confidence."
        ),
        "kind": "unicode_block",
        "block": (0x4E00, 0x9FFF),
        "exclude_blocks": [(0x3040, 0x309F), (0x30A0, 0x30FF)],
        "threshold": 1,
        "severity": "high",
        "score_weight": 0.8,
    },

    # -----------------------------------------------------------------
    # Tier 2 — Diacritic / punctuation rules (Spanish strong indicators)
    # -----------------------------------------------------------------
    {
        "id": "ES_INVERTED_PUNCTUATION",
        "tier": 2,
        "language": "es",
        "description": "Inverted question/exclamation marks ¿ ¡ — almost exclusive to Spanish.",
        "kind": "regex",
        "pattern": r"[¿¡]",
        "threshold": 1,
        "severity": "definitive",
        "score_weight": 1.0,
    },
    {
        "id": "ES_TILDE_N",
        "tier": 2,
        "language": "es",
        "description": "Letter ñ present — extremely strong Spanish indicator.",
        "kind": "regex",
        "pattern": r"[ñÑ]",
        "threshold": 1,
        "severity": "high",
        "score_weight": 0.85,
    },
    {
        "id": "ES_ACCENTED_VOWELS",
        "tier": 2,
        "language": "es",
        "description": "Two or more accented vowels á é í ó ú — likely Spanish.",
        "kind": "regex",
        "pattern": r"[áéíóúÁÉÍÓÚ]",
        "threshold": 2,
        "severity": "medium",
        "score_weight": 0.55,
    },

    # -----------------------------------------------------------------
    # Tier 3 — Keyword density rules
    # -----------------------------------------------------------------
    {
        "id": "ES_KEYWORD_DENSITY_DEFINITIVE",
        "tier": 3,
        "language": "es",
        "description": "5+ tokens from the top-50 high-discriminator Spanish stopword list.",
        "kind": "keyword_density",
        "tokens": ES_KEYWORDS,
        "threshold": 5,
        "severity": "definitive",
        "score_weight": 1.0,
    },
    {
        "id": "ES_KEYWORD_DENSITY_HIGH",
        "tier": 3,
        "language": "es",
        "description": "3+ tokens from the top-50 high-discriminator Spanish stopword list.",
        "kind": "keyword_density",
        "tokens": ES_KEYWORDS,
        "threshold": 3,
        "severity": "high",
        "score_weight": 0.75,
    },
    {
        "id": "EN_KEYWORD_DENSITY_HIGH",
        "tier": 3,
        "language": "en",
        "description": "7+ tokens from the top-50 high-discriminator English stopword list.",
        "kind": "keyword_density",
        "tokens": EN_KEYWORDS,
        "threshold": 7,
        "severity": "high",
        "score_weight": 0.75,
    },
    {
        "id": "EN_KEYWORD_DENSITY_MEDIUM",
        "tier": 3,
        "language": "en",
        "description": "4+ tokens from the top-50 high-discriminator English stopword list.",
        "kind": "keyword_density",
        "tokens": EN_KEYWORDS,
        "threshold": 4,
        "severity": "medium",
        "score_weight": 0.55,
    },
    {
        "id": "JA_PARTICLE_DENSITY",
        "tier": 3,
        "language": "ja",
        "description": (
            "3+ Japanese particles from the top-30 list. Mostly redundant with Tier 1, "
            "but covers kanji-only or transliterated cases."
        ),
        "kind": "keyword_density",
        "tokens": JA_KEYWORDS,
        "threshold": 3,
        "severity": "high",
        "score_weight": 0.7,
    },

    # -----------------------------------------------------------------
    # Tier 4 — Greeting / idiom rules (high precision, lower recall)
    # -----------------------------------------------------------------
    {
        "id": "ES_GREETINGS",
        "tier": 4,
        "language": "es",
        "description": "Common Spanish greeting / closing words.",
        "kind": "regex",
        "pattern": r"\b(hola|gracias|por\s+favor|saludos|estimado|estimada|cordiales|atentamente)\b",
        "flags": re.IGNORECASE,
        "threshold": 1,
        "severity": "high",
        "score_weight": 0.65,
    },
    {
        "id": "EN_GREETINGS",
        "tier": 4,
        "language": "en",
        "description": (
            "Common English greeting / closing words. Lower weight: these often appear in "
            "mixed-language B2B emails written by non-native speakers."
        ),
        "kind": "regex",
        "pattern": r"\b(hello|hi|dear|regards|sincerely|best\s+regards|kind\s+regards)\b",
        "flags": re.IGNORECASE,
        "threshold": 1,
        "severity": "low",
        "score_weight": 0.35,
    },
]


# ---------------------------------------------------------------------------
# Reference detector — minimal evaluator to prove the rule set works end-to-end.
# Production code in app/services/* will load LANGUAGE_HEURISTIC_RULES and
# implement scoring with its own tracing/telemetry layer.
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"definitive": 4, "high": 3, "medium": 2, "low": 1}


def _count_unicode_block(text: str, block: tuple[int, int],
                         exclude_blocks: list[tuple[int, int]] | None = None) -> int:
    lo, hi = block
    excludes = exclude_blocks or []
    count = 0
    for ch in text:
        cp = ord(ch)
        if lo <= cp <= hi and not any(elo <= cp <= ehi for elo, ehi in excludes):
            count += 1
    return count


_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ]+|[぀-ヿ一-鿿]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _count_keywords(text: str, tokens: list[str]) -> int:
    token_set = set(tokens)
    found = 0
    seen_kanji = False
    # Latin tokens via word boundaries
    for tok in _tokenize(text):
        if tok in token_set:
            found += 1
    # JA particles need substring search since Japanese has no spaces
    if any(any(ord(c) > 0x3000 for c in t) for t in tokens):
        for ja_tok in tokens:
            if ja_tok and any(ord(c) > 0x3000 for c in ja_tok):
                # count non-overlapping occurrences
                idx = 0
                while True:
                    nxt = text.find(ja_tok, idx)
                    if nxt < 0:
                        break
                    found += 1
                    seen_kanji = True
                    idx = nxt + len(ja_tok)
    return found


def _evaluate_rule(rule: dict[str, Any], text: str) -> int:
    kind = rule["kind"]
    if kind == "regex":
        flags = rule.get("flags", 0)
        return len(re.findall(rule["pattern"], text, flags=flags))
    if kind == "unicode_block":
        return _count_unicode_block(text, rule["block"], rule.get("exclude_blocks"))
    if kind == "keyword_density":
        # For Latin-token rules use word-boundary tokenization; for JA use substring.
        tokens = rule["tokens"]
        if any(any(ord(c) > 0x3000 for c in t) for t in tokens):
            count = 0
            for tok in tokens:
                idx = 0
                while True:
                    nxt = text.find(tok, idx)
                    if nxt < 0:
                        break
                    count += 1
                    idx = nxt + len(tok)
            return count
        toks = _tokenize(text)
        token_set = set(tokens)
        return sum(1 for t in toks if t in token_set)
    raise ValueError(f"unknown rule kind: {kind}")


def detect_language(text: str) -> tuple[str, str, str]:
    """Return (language, severity, rule_id). Falls back to ('other', 'low', '<none>')."""
    text_norm = unicodedata.normalize("NFC", text)

    best: tuple[int, float, dict[str, Any]] | None = None
    # Tier 1 first: a definitive script hit short-circuits
    for tier in (1, 2, 3, 4):
        tier_best: tuple[int, float, dict[str, Any]] | None = None
        for rule in LANGUAGE_HEURISTIC_RULES:
            if rule["tier"] != tier:
                continue
            count = _evaluate_rule(rule, text_norm)
            if count >= rule["threshold"]:
                sev = _SEVERITY_ORDER[rule["severity"]]
                weight = rule["score_weight"]
                cand = (sev, weight, rule)
                if tier_best is None or cand > tier_best:
                    tier_best = cand
        if tier_best is not None:
            if best is None or tier_best > best:
                best = tier_best
            if tier_best[2]["severity"] == "definitive":
                break

    if best is None:
        return ("other", "low", "<none>")
    rule = best[2]
    return (rule["language"], rule["severity"], rule["id"])


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

_SELF_TESTS: list[tuple[str, str]] = [
    ("Hello team, please find attached the updated proposal and let us know your thoughts.", "en"),
    ("Estimado equipo, por favor encuentren adjunto el documento con los cambios solicitados.", "es"),
    ("POの送付ありがとうございます", "ja"),
    ("送付状送付状送付状", "ja"),
]


def _run_self_tests() -> int:
    failures = 0
    print("=" * 72)
    print("language_heuristic_rules self-test")
    print("=" * 72)

    tier_counts: dict[int, int] = {}
    for r in LANGUAGE_HEURISTIC_RULES:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1
    print(f"Total rules: {len(LANGUAGE_HEURISTIC_RULES)}")
    for t in sorted(tier_counts):
        print(f"  Tier {t}: {tier_counts[t]} rule(s)")
    print(f"Keyword list sizes: " + ", ".join(
        f"{lang}={len(words)}" for lang, words in LANGUAGE_KEYWORD_LISTS.items()
    ))
    print("-" * 72)

    for text, expected in _SELF_TESTS:
        lang, sev, rid = detect_language(text)
        ok = lang == expected
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        preview = text if len(text) <= 60 else text[:57] + "..."
        print(f"[{status}] expected={expected:<5} got={lang:<5} sev={sev:<10} rule={rid}")
        try:
            print(f"        text: {preview}")
        except UnicodeEncodeError:
            safe = preview.encode("ascii", "backslashreplace").decode("ascii")
            print(f"        text: {safe}")

    print("-" * 72)
    print(f"Failures: {failures}/{len(_SELF_TESTS)}")
    return failures


if __name__ == "__main__":
    raise SystemExit(_run_self_tests())
