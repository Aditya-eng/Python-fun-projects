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
    opted_out: bool = False           # bot.py reads this to suppress future /v1/tick sends
    hostility_seen: bool = False      # once true, any further turn ends the conversation


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

    # 1. hard stop / opt-out — always wins, even mid auto-reply-hell. Marks
    # opted_out so bot.py can suppress this merchant/customer on ALL future
    # /v1/tick sends, not just this one conversation_id (per the official
    # example's rationale: "suppressing this conversation_id for future
    # ticks" — we go one step further and suppress the identity itself).
    if _contains_any(message, STOP_PHRASES):
        state.ended = True
        state.opted_out = True
        return {"action": "end", "rationale": "Merchant/customer signaled stop or not-interested; exiting immediately, no further nudge, and suppressing future proactive sends to this identity."}

    # 1b. hostility already de-escalated once this conversation — the
    # official examples show "closing without further engagement" as the
    # good outcome; once we've said we'd step back, we keep that commitment
    # rather than re-engaging on whatever comes next.
    if state.hostility_seen:
        state.ended = True
        return {"action": "end", "rationale": "Hostility was already acknowledged once this conversation; keeping the earlier commitment to step back rather than re-engaging."}

    # 2. auto-reply detection: canned phrase OR the exact same text seen
    # twice before. Three-strike pattern verified against
    # examples/api-call-examples.md §4.1: send one nudge, then back off with
    # `wait` (not `end`) to let the owner see it, and only end on the third
    # occurrence — ending after one repeat (as an earlier draft did) closes
    # the conversation a turn too early relative to the official scenario.
    looks_canned = _contains_any(message, AUTO_REPLY_PHRASES)
    verbatim_loop = _is_repeated_verbatim(state, message)
    if looks_canned or verbatim_loop:
        state.auto_reply_streak += 1
        if state.auto_reply_streak == 1:
            body = f"Samajh gayi{', ' + name if name else ''}. Kya aap khud 2 minute dekh sakte hain, ya main seedha owner/manager se connect karoon?"
            return {
                "action": "send",
                "body": body,
                "cta": "binary_yes_no",
                "rationale": "First canned/auto-reply detected — one polite attempt to reach a real person before backing off.",
            }
        if state.auto_reply_streak == 2:
            return {
                "action": "wait",
                "wait_seconds": 86400,
                "rationale": "Same auto-reply/canned text a second time — owner likely not at phone; backing off 24h before retrying, matching the official auto-reply-hell scenario rather than ending prematurely.",
            }
        state.ended = True
        return {
            "action": "end",
            "rationale": "Auto-reply pattern confirmed a third time with zero real engagement signal — closing per the brief's #1 flagged production weakness.",
        }
    else:
        state.auto_reply_streak = 0

    # 3. hostile / abusive — one short apology + opt-out path, matching the
    # official "acceptable alternative" (a one-line send with cta=none),
    # then commit to stepping back (enforced by the hostility_seen check above).
    if ABUSE_PATTERN.search(message):
        state.hostility_seen = True
        return {
            "action": "send",
            "body": "Apologies — I won't message again. If anything changes, you can always restart with 'Hi Vera'.",
            "cta": "none",
            "rationale": "Hostility detected; one-line acknowledgment + opt-out path, then closing on the next turn regardless of content.",
        }

    # 4. explicit intent to act — switch to action mode immediately, don't
    # re-qualify (the brief's Pattern D anti-pattern). Matches
    # examples/api-call-examples.md §4.2's "Good" response: name a concrete
    # next step and ask for one CONFIRM rather than another qualifying
    # question — and, unlike an earlier draft, don't claim the action is
    # already done before it's actually confirmed.
    if _contains_any(message, INTENT_YES_PHRASES):
        state.intent_confirmed = True
        state.unanswered_nudges = 0
        body = f"Great{', ' + name if name else ''} — drafting this now. Reply CONFIRM to have me send it, or CANCEL to hold off."
        return {
            "action": "send",
            "body": body,
            "cta": "binary_confirm_cancel",
            "rationale": "Merchant expressed explicit intent to proceed; routing straight to a concrete next step instead of another qualifying question, gated by one CONFIRM rather than claiming the action is already done.",
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
            "cta": "binary_yes_no",
            "rationale": "Off-topic ask acknowledged honestly without pretending competence; redirected to the bot's actual scope with a single binary CTA.",
        }

    # 7. default — engaged reply, advance the conversation
    state.unanswered_nudges = 0
    body = "Got it — noting that down. Want me to go ahead with the next step?"
    return {
        "action": "send",
        "body": body,
        "cta": "binary_yes_no",
        "rationale": "Generic engaged reply; advancing the conversation with a single binary next-step CTA.",
    }
