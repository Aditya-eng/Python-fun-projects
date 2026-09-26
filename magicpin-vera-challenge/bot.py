"""
bot.py — the 5-endpoint HTTP contract from challenge-testing-brief.md §2.

Run locally:    uvicorn bot:app --host 0.0.0.0 --port 8080
Deployed via:   api/index.py (Vercel) imports `app` from this module.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from facts import build_fact_pack
from composer import compose
from validators import validate_and_repair
from conversation_handlers import ConversationState, respond as reply_respond
from llm_hook import maybe_polish

app = FastAPI(title="vera-challenge-bot")
START = time.time()

TEAM_NAME = os.environ.get("VERA_TEAM_NAME", "Team Solo")
TEAM_MEMBERS = [m for m in os.environ.get("VERA_TEAM_MEMBERS", "").split(",") if m] or ["Candidate"]
CONTACT_EMAIL = os.environ.get("VERA_CONTACT_EMAIL", "electronicsmail500@gmail.com")

# --- in-memory state (per testing-brief §12: in-memory is fine, no restarts during test) ---
contexts: dict[tuple[str, str], dict] = {}          # (scope, context_id) -> {version, payload}
conversations: dict[str, ConversationState] = {}    # conversation_id -> state
sent_suppression_keys: set[str] = set()             # global dedup across the whole test window
opted_out_merchants: set[str] = set()               # hard stop in ANY conversation suppresses ALL future ticks
opted_out_customers: set[str] = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get(scope: str, context_id: Optional[str]) -> Optional[dict]:
    if not context_id:
        return None
    entry = contexts.get((scope, context_id))
    return entry["payload"] if entry else None


@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _cid) in contexts.keys():
        counts[scope] = counts.get(scope, 0) + 1
    return {"status": "ok", "uptime_seconds": int(time.time() - START), "contexts_loaded": counts}


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": TEAM_NAME,
        "team_members": TEAM_MEMBERS,
        "model": "deterministic-composer+optional-claude-haiku-polish",
        "approach": (
            "Fact-anchored template composer with one builder per trigger.kind, reading "
            "real payload field names verified against the official dataset "
            "(e.g. competitor_opened.their_offer, recall_due.available_slots, "
            "milestone_reached.is_imminent) rather than guessed ones — never invents "
            "numbers/sources/competitor names. Post-composition validator enforces "
            "single-CTA, taboo-word, URL-hard-fail, and anti-repetition rules with a "
            "one-pass repair before falling back to a minimal grounded message. Reply "
            "handling is a rule-based state machine: 3-strike auto-reply detection "
            "(send nudge -> wait 24h -> end), explicit-intent routing to a concrete "
            "next step gated by one CONFIRM, hard stop/opt-out that suppresses future "
            "proactive sends account-wide, one hostility de-escalation then a kept "
            "commitment to step back, and a 30-min backoff on 'later'. An optional "
            "Claude Haiku tone-polish pass runs only if ANTHROPIC_API_KEY is set, and "
            "is discarded if it changes any number in the message."
        ),
        "contact_email": CONTACT_EMAIL,
        "version": "1.0.0",
        "submitted_at": _now_iso(),
    }


@app.post("/v1/context")
async def push_context(request: Request):
    body = await request.json()
    scope = body.get("scope")
    context_id = body.get("context_id")
    version = body.get("version", 1)

    if scope not in ("category", "merchant", "customer", "trigger") or not context_id:
        return JSONResponse(status_code=400, content={"accepted": False, "reason": "invalid_scope", "details": f"scope={scope!r} context_id={context_id!r}"})

    key = (scope, context_id)
    cur = contexts.get(key)
    if cur and cur["version"] == version:
        # idempotent no-op per testing-brief §2.1: same (context_id, version) is a no-op, not stale.
        return {"accepted": True, "ack_id": f"ack_{context_id}_v{version}", "stored_at": _now_iso()}
    if cur and cur["version"] > version:
        return JSONResponse(status_code=409, content={"accepted": False, "reason": "stale_version", "current_version": cur["version"]})

    contexts[key] = {"version": version, "payload": body.get("payload", {})}
    return {"accepted": True, "ack_id": f"ack_{context_id}_v{version}", "stored_at": _now_iso()}


def _resolve_merchant_id(trigger_payload: dict) -> Optional[str]:
    return trigger_payload.get("merchant_id") or (trigger_payload.get("payload") or {}).get("merchant_id")


@app.post("/v1/tick")
async def tick(request: Request):
    body = await request.json()
    available_triggers = body.get("available_triggers", []) or []

    actions: list[dict] = []
    merchants_acted_on_this_tick: set[str] = set()

    for trigger_id in available_triggers:
        if len(actions) >= 20:
            break

        trigger_ctx = _get("trigger", trigger_id)
        if not trigger_ctx:
            continue

        merchant_id = trigger_ctx.get("merchant_id") or _resolve_merchant_id(trigger_ctx)
        customer_id = trigger_ctx.get("customer_id")
        if not merchant_id or merchant_id in merchants_acted_on_this_tick:
            continue
        if merchant_id in opted_out_merchants:
            continue
        if customer_id and customer_id in opted_out_customers:
            continue

        suppression_key = trigger_ctx.get("suppression_key") or f"{trigger_ctx.get('kind')}:{merchant_id}"
        if suppression_key in sent_suppression_keys:
            continue

        merchant_ctx = _get("merchant", merchant_id)
        if not merchant_ctx:
            continue
        category_ctx = _get("category", merchant_ctx.get("category_slug"))
        customer_ctx = _get("customer", customer_id) if customer_id else None

        composed = compose(category_ctx, merchant_ctx, trigger_ctx, customer_ctx)
        fp = build_fact_pack(category_ctx, merchant_ctx, trigger_ctx, customer_ctx)
        composed = validate_and_repair(composed, fp, category_ctx)
        composed = maybe_polish(composed, category_ctx)

        conversation_id = f"conv_{merchant_id}_{trigger_id}_{uuid.uuid4().hex[:6]}"
        state = ConversationState(conversation_id=conversation_id, merchant_id=merchant_id, customer_id=customer_id)
        state.sent_bodies.append(composed["body"])
        conversations[conversation_id] = state

        is_first_outbound = not merchant_ctx.get("conversation_history")
        template_name = "vera_generic_v1" if is_first_outbound else None
        template_params = [merchant_ctx.get("identity", {}).get("name", ""), trigger_ctx.get("kind", ""), composed["body"][:60]] if is_first_outbound else None

        action = {
            "conversation_id": conversation_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed["send_as"],
            "trigger_id": trigger_id,
            "template_name": template_name,
            "template_params": template_params,
            "body": composed["body"],
            "cta": composed["cta"],
            "suppression_key": suppression_key,
            "rationale": composed["rationale"],
        }
        actions.append(action)
        sent_suppression_keys.add(suppression_key)
        merchants_acted_on_this_tick.add(merchant_id)

    return {"actions": actions}


@app.post("/v1/reply")
async def reply(request: Request):
    body = await request.json()
    conversation_id = body.get("conversation_id")
    merchant_id = body.get("merchant_id")
    customer_id = body.get("customer_id")
    from_role = body.get("from_role", "merchant")
    message = body.get("message", "")

    state = conversations.get(conversation_id)
    if state is None:
        state = ConversationState(conversation_id=conversation_id, merchant_id=merchant_id, customer_id=customer_id)
        conversations[conversation_id] = state

    merchant_ctx = _get("merchant", merchant_id or state.merchant_id)
    customer_ctx = _get("customer", customer_id or state.customer_id)
    category_ctx = _get("category", merchant_ctx.get("category_slug")) if merchant_ctx else None
    fp = build_fact_pack(category_ctx, merchant_ctx, None, customer_ctx)

    result = reply_respond(state, message, fp)

    if state.opted_out:
        if state.merchant_id:
            opted_out_merchants.add(state.merchant_id)
        if state.customer_id:
            opted_out_customers.add(state.customer_id)

    if result.get("action") == "send":
        candidate = {
            "body": result.get("body", ""),
            "cta": result.get("cta", "open_ended"),
            "send_as": "merchant_on_behalf" if from_role == "customer" else "vera",
            "suppression_key": f"reply:{conversation_id}",
            "rationale": result.get("rationale", ""),
        }
        candidate = validate_and_repair(candidate, fp, category_ctx)
        state.sent_bodies.append(candidate["body"])
        return {"action": "send", "body": candidate["body"], "cta": candidate["cta"], "rationale": candidate["rationale"]}

    if result.get("action") == "wait":
        return {"action": "wait", "wait_seconds": result.get("wait_seconds", 1800), "rationale": result.get("rationale", "")}

    return {"action": "end", "rationale": result.get("rationale", "")}


@app.post("/v1/teardown")
async def teardown():
    contexts.clear()
    conversations.clear()
    sent_suppression_keys.clear()
    opted_out_merchants.clear()
    opted_out_customers.clear()
    return {"accepted": True}
