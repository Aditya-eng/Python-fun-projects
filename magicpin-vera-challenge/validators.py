"""
validators.py — post-composition checks. The rubric penalizes exactly these
failure modes (brief §11): multi-CTA messages, taboo vocabulary, empty bodies,
verbatim repeats. This module catches them and repairs or falls back rather
than ever shipping a message that fails.
"""

from __future__ import annotations

import re
from typing import Optional

from facts import FactPack

ALLOWED_CTA = {"binary", "open_ended", "none"}

_MULTI_CTA_PATTERN = re.compile(
    r"reply\s+\w+\s+(?:for|to)\s+\w+.*(?:,|;|\bor\b).*reply\s+\w+\s+(?:for|to)\s+\w+",
    re.IGNORECASE,
)


def _category_taboos(category: Optional[dict]) -> list[str]:
    if not category:
        return []
    voice = category.get("voice", {}) or {}
    return [t.lower() for t in (voice.get("vocab_taboo") or [])]


def validate(message: dict, fp: FactPack, category: Optional[dict]) -> list[str]:
    """Returns a list of problems found. Empty list == passes."""
    problems: list[str] = []
    body = message.get("body", "") or ""
    cta = message.get("cta", "")

    if not body.strip():
        problems.append("empty_body")
        return problems  # nothing else to check

    if cta not in ALLOWED_CTA:
        problems.append("invalid_cta")

    if _MULTI_CTA_PATTERN.search(body):
        problems.append("multi_cta")

    low = body.lower()
    for taboo in _category_taboos(category):
        # skip conditional taboo entries like "FDA-approved (use only when...)"
        core = taboo.split(" (")[0].strip()
        if core and core in low:
            problems.append(f"taboo_word:{core}")

    if body in fp.prior_bodies:
        problems.append("verbatim_repeat")

    if len(body) > 1200:
        problems.append("too_long")

    return problems


def fallback_message(fp: FactPack) -> dict:
    """Never returns an empty body. Grounded in whatever real fact is cheapest
    to state honestly; otherwise a restrained, non-promotional line."""
    name = fp.owner_first_name or fp.merchant_name or "there"
    if fp.signals:
        sig = fp.signals[0].split(":")[0].replace("_", " ")
        body = f"{name}, flagging {sig} on your account — want a quick look together?"
    else:
        body = f"{name}, checking in — let me know if there's anything on your listing you'd like help with this week."
    return {
        "body": body,
        "cta": "open_ended",
        "send_as": "vera",
        "suppression_key": fp.suppression_key or "fallback",
        "rationale": "Validation repair fallback: original composition failed a check, replaced with a minimal grounded message.",
    }


def validate_and_repair(message: dict, fp: FactPack, category: Optional[dict]) -> dict:
    problems = validate(message, fp, category)
    if not problems:
        return message

    repaired = dict(message)

    if "empty_body" in problems or "too_long" in problems:
        return fallback_message(fp)

    if "invalid_cta" in problems:
        repaired["cta"] = "open_ended"

    if "verbatim_repeat" in problems:
        repaired["body"] = repaired["body"].rstrip(".") + " (circling back on this)."

    for p in problems:
        if p.startswith("taboo_word:"):
            word = p.split(":", 1)[1]
            repaired["body"] = re.sub(re.escape(word), "", repaired["body"], flags=re.IGNORECASE).strip()

    if "multi_cta" in problems:
        # keep only the first CTA sentence
        sentences = re.split(r"(?<=[.!?])\s+", repaired["body"])
        repaired["body"] = " ".join(sentences[: max(1, len(sentences) - 1)])
        repaired["cta"] = "open_ended"

    # one repair pass only — re-check, and fall back if still broken
    if validate(repaired, fp, category):
        return fallback_message(fp)

    return repaired
