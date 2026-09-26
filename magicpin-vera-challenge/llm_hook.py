"""
llm_hook.py — optional quality upgrade. Not required to submit: the composer
is fully deterministic and grounded without this. If ANTHROPIC_API_KEY is set
on the host, this rewrites tone/fluency only — it is never allowed to add a
fact, number, or name that wasn't already in the composed message, and it
must fail silently (return the original message) on any error or timeout.
"""

from __future__ import annotations

import os
from typing import Optional

_ENABLED = bool(os.environ.get("ANTHROPIC_API_KEY"))
_client = None

if _ENABLED:
    try:
        import anthropic  # type: ignore

        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=8.0)
    except Exception:
        _client = None
        _ENABLED = False


def maybe_polish(message: dict, category: Optional[dict]) -> dict:
    """Best-effort tone polish. Returns `message` unchanged on any failure,
    missing key, or if the rewrite drops/adds a number (a cheap but effective
    anti-hallucination guard)."""
    if not _ENABLED or _client is None:
        return message

    body = message.get("body", "")
    if not body:
        return message

    voice = (category or {}).get("voice", {}) if category else {}
    tone = voice.get("tone", "peer, non-promotional")

    try:
        resp = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            temperature=0,
            system=(
                f"Rewrite the WhatsApp message for tone only. Target tone: {tone}. "
                "Rules: keep every number, date, name, and offer EXACTLY as given. "
                "Do not add any fact not already present. Keep it roughly the same "
                "length. Return only the rewritten message body, nothing else."
            ),
            messages=[{"role": "user", "content": body}],
        )
        new_body = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        ).strip()
    except Exception:
        return message

    if not new_body:
        return message

    # anti-hallucination guard: same set of digit-groups must survive
    import re

    old_nums = set(re.findall(r"\d+(?:\.\d+)?", body))
    new_nums = set(re.findall(r"\d+(?:\.\d+)?", new_body))
    if old_nums != new_nums:
        return message

    out = dict(message)
    out["body"] = new_body
    return out
