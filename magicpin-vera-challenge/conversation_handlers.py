"""
conversation_handlers.py — the reply/state-machine layer for /v1/reply.

This is where the brief's "open challenges" (§12) and the Phase-4 replay
scenarios (auto-reply hell, intent transition, hostile/off-topic) actually get
scored. Deliberately rule-based rather than another LLM call: it needs to be
fast, deterministic, and hard for a canned WhatsApp auto-responder to fool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

AUTO_REPLY_PHRASES = [
    "thank you for contacting",
    "we will get back to you",
    "we'll get back to you",
    "currently unavailable",
    "automated assistant",
    "automated reply",
    "this is an automated",
    "aapki jaankari ke liye",
    "shukriya",
    "hamari team tak pahuncha",
    "team tak pahuncha",
    "will respond shortly",
    "out of office",
    "busy right now",
]

STOP_PHRASES = [
    "stop", "unsubscribe", "not interested", "nahi chahiye", "band karo",
    "no thanks", "leave me alone", "don't message", "do not contact",
]

INTENT_YES_PHRASES = [
    "yes", "yeah", "yep", "sure", "ok", "okay", "go ahead", "let's do it",
    "lets do it", "haan", "karo", "kar do", "sign me up", "i want to join",
    "join karna hai", "interested", "start", "please proceed", "proceed",
]

WAIT_PHRASES = [
    "later", "busy", "call me tomorrow", "not now", "abhi busy",
    "give me some time", "will get back", "next week",
]

ABUSE_PATTERN = re.compile(
    r"\b(idiot|stupid|useless|shut up|nonsense|bakwas|bewakoof)\b", re.IGNORECASE
)

MAX_UNANSWERED_NUDGES = 3


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    turns: list[dict] = field(default_factory=list)         # {from, message}
    sent_bodies: list[str] = field(default_factory=list)     # bot's own outbound bodies
    auto_reply_streak: int = 0
    unanswered_nudges: int = 0
    ended: bool = False
    intent_confirmed: bool = False


def _norm(msg: str) -> str:
    return re.sub(r"\s+", " ", msg.strip().lower())


def _contains_any(msg: str, phrases: list[str]) -> bool:
    low = _norm(msg)
    return any(re.search(r"\b" + re.escape(p) + r"\b", low) for p in phrases)


def _is_repeated_verbatim(state: ConversationState, message: str) -> bool:
    prior_merchant_msgs = [t["message"] for t in state.turns if t.get("from") == "merchant"]
    same = [m for m in prior_merchant_msgs if _norm(m) == _norm(message)]
    return len(same) >= 2  # this message + at least 2 identical priors seen before


def respond(state: ConversationState, message: str, fp=None) -> dict:
    """fp: optional FactPack for the merchant/customer this conversation is
    with, used only to personalize the reply — never required for the
    control-flow decision itself."""

    state.turns.append({"from": "merchant", "message": message})
    name = ""
    if fp is not None:
        name = fp.owner_first_name or fp.merchant_name or ""
    greet = f"{name}, " if name else ""

    # 1. hard stop / opt-out — always wins, even mid auto-reply-hell
    if _contains_any(message, STOP_PHRASES):
        state.ended = True
        return {"action": "end", "rationale": "Merchant/customer signaled stop or not-interested; exiting immediately, no further nudge."}

    # 2. auto-reply detection: canned phrase OR the exact same text seen twice before
    looks_canned = _contains_any(message, AUTO_REPLY_PHRASES)
    verbatim_loop = _is_repeated_verbatim(state, message)
    if looks_canned or verbatim_loop:
        state.auto_reply_streak += 1
        if state.auto_reply_streak == 1:
            body = f"Samajh gayi. {greet}kya aap khud 2 minute dekh sakte hain, ya main seedha owner/manager se connect karoon?" if not name else f"Samajh gayi, {name}. Kya aap khud 2 minute dekh sakte hain, ya main seedha owner/manager se connect karoon?"
            return {
                "action": "send",
                "body": body,
                "cta": "open_ended",
                "rationale": "First canned/auto-reply detected — one polite attempt to reach a real person before standing down.",
            }
        # second+ time: stop burning turns, exit gracefully
        state.ended = True
        return {
            "action": "end",
            "rationale": "Auto-reply pattern confirmed a second time (or exact text repeated 3+ times) — graceful exit rather than burning more turns, per the brief's #1 flagged production weakness.",
        }
    else:
        state.auto_reply_streak = 0

    # 3. hostile / abusive — de-escalate once, then exit if it continues
    if ABUSE_PATTERN.search(message):
        prior_abuse = any(ABUSE_PATTERN.search(t["message"]) for t in state.turns[:-1] if t.get("from") == "merchant")
        if prior_abuse:
            state.ended = True
            return {"action": "end", "rationale": "Repeated hostility after a de-escalation attempt — exiting politely."}
        return {
            "action": "send",
            "body": "No worries — happy to step back if this isn't useful right now. Is there something specific I can help with instead?",
            "cta": "open_ended",
            "rationale": "One de-escalation attempt on hostile input; staying on-mission without matching the tone.",
        }

    # 4. explicit intent to act — switch to action mode immediately, don't re-qualify
    if _contains_any(message, INTENT_YES_PHRASES):
        state.intent_confirmed = True
        state.unanswered_nudges = 0
        body = f"Great — {greet}doing it now, will confirm here once it's done." if greet else "Great — doing it now, will confirm here once it's done."
        return {
            "action": "send",
            "body": body,
            "cta": "none",
            "rationale": "Merchant expressed explicit intent to proceed; routing straight to action instead of another qualifying question (the brief's Pattern D anti-pattern).",
        }

    # 5. asked for time — back off instead of nudging again immediately
    if _contains_any(message, WAIT_PHRASES):
        return {
            "action": "wait",
            "wait_seconds": 1800,
            "rationale": "Merchant asked for time; backing off 30 minutes rather than re-nudging immediately.",
        }

    # 6. off-topic but not hostile — answer briefly, redirect to the single CTA
    off_topic_markers = ["gst", "loan", "insurance", "unrelated"]
    if _contains_any(message, off_topic_markers):
        return {
            "action": "send",
            "body": "That's outside what I handle directly, so I can't help with that one — but I can keep going on your Google profile / offers if that's still useful. Want me to continue?",
            "cta": "binary",
            "rationale": "Off-topic ask acknowledged honestly without pretending competence; redirected to the bot's actual scope with a single binary CTA.",
        }

    # 7. default — engaged reply, advance the conversation
    state.unanswered_nudges = 0
    body = "Got it — noting that down. Want me to go ahead with the next step?"
    return {
        "action": "send",
        "body": body,
        "cta": "binary",
        "rationale": "Generic engaged reply; advancing the conversation with a single binary next-step CTA.",
    }
