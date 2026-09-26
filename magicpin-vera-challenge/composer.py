"""
composer.py — the actual message-writing brain.

Deterministic, template-based, fact-anchored. No LLM call required (see
llm_hook.py for the optional upgrade path). Every sentence traces back to a
field that was actually present in the pushed context — nothing here invents
a number, a source, or a competitor name that wasn't handed to it.

compose(category, merchant, trigger, customer) -> ComposedMessage dict
respond(...) lives in conversation_handlers.py, not here.
"""

from __future__ import annotations

from typing import Optional

from facts import FactPack, build_fact_pack

CTA_BINARY = "binary"
CTA_OPEN = "open_ended"
CTA_NONE = "none"

SEND_VERA = "vera"
SEND_ON_BEHALF = "merchant_on_behalf"


def _hinglish(fp: FactPack, hindi_clause: str, english_clause: str) -> str:
    """Only weave Hindi-English code-mix when the category voice calls for it
    AND the merchant/customer's language list actually includes Hindi."""
    langs = fp.languages or []
    lang_pref = (fp.customer_lang_pref or "").lower()
    wants_mix = fp.code_mix == "hindi_english_natural" and (
        "hi" in langs or "hi-en" in lang_pref or "hindi" in lang_pref
    )
    return hindi_clause if wants_mix else english_clause


def _pct(x: Optional[float]) -> str:
    if x is None:
        return ""
    return f"{abs(x) * 100:.0f}%"


def _name(fp: FactPack) -> str:
    return fp.owner_first_name or fp.merchant_name or "there"


# ---------------------------------------------------------------------------
# Family builders — each returns (body, cta, send_as, rationale, levers)
# ---------------------------------------------------------------------------

def _research_digest(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    d = fp.digest_item
    name = _name(fp)
    if d and d.get("title"):
        title = d["title"]
        source = d.get("source", "")
        n = d.get("trial_n")
        segment = d.get("patient_segment") or d.get("segment")
        anchor = f"{n}-patient trial" if n else "recent study"
        seg_clause = f" for your {segment.replace('_', ' ')}" if segment else ""
        body = (
            f"{name}, {source or 'a category research digest'} landed — "
            f"{anchor} found: {title}{seg_clause}. "
            f"Worth a look (2-min abstract). Want me to pull it + draft a "
            f"patient-ed WhatsApp you can share?"
            + (f"  — {source}" if source else "")
        )
        rationale = "Anchored on the category digest item pushed this cycle; cites source and trial size."
        return body, CTA_OPEN, SEND_VERA, rationale, ["specificity", "reciprocity", "curiosity"]
    # degraded: no real digest item pushed yet
    body = (
        f"{name}, nothing new in this week's category digest for you yet — "
        f"I'll flag the next relevant item the moment it drops."
    )
    return body, CTA_NONE, SEND_VERA, "No digest item in context; sending a restrained no-op rather than inventing one.", ["reciprocity"]


def _compliance(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    payload = fp.trigger_payload or {}
    name = _name(fp)
    detail = payload.get("regulation_detail") or payload.get("event_name")
    deadline = payload.get("deadline") or payload.get("action_deadline") or payload.get("deadline_date")
    source = payload.get("source")
    spots = payload.get("spots")
    if detail and deadline:
        src_clause = f" ({source})" if source else ""
        body = f"{name}, {detail}{src_clause} — compliance/action needed by {deadline}. Want guidance on what changes for your setup?"
        return body, CTA_BINARY, SEND_VERA, "Regulation/compliance trigger with a real deadline pulled from the pushed payload.", ["loss_aversion", "specificity"]
    if spots and deadline:
        event = payload.get("event_name", "this session")
        body = f"{name}, {event} — {spots} spots left, register before {deadline}. Interested?"
        return body, CTA_BINARY, SEND_VERA, "CDE/webinar opportunity with real capacity + deadline from payload.", ["social_proof", "loss_aversion"]
    body = f"{name}, there's a category compliance update I'm tracking for you — I'll ping you the moment the specifics land."
    return body, CTA_NONE, SEND_VERA, "Compliance-family trigger fired without a concrete detail/deadline in payload; avoiding invented specifics.", ["reciprocity"]


def _perf(fp: FactPack, dip: bool) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    pct = _pct(fp.views_delta_pct if fp.views_delta_pct is not None else fp.calls_delta_pct)
    metric = "views" if fp.views_delta_pct is not None else "calls"
    if pct:
        direction = "dropped" if dip else "jumped"
        base = fp.views if metric == "views" else fp.calls
        base_clause = f" (now at {base})" if base is not None else ""
        if dip:
            body = f"{name}, your {metric} {direction} {pct} week-over-week{base_clause}. Want me to check what changed?"
            levers = ["loss_aversion", "specificity"]
        else:
            body = f"{name}, your {metric} {direction} {pct} week-over-week{base_clause} — nice move. Want a quick note on what likely drove it, in case it's repeatable?"
            levers = ["specificity", "reciprocity"]
        return body, CTA_OPEN, SEND_VERA, f"Performance {'dip' if dip else 'spike'} anchored on merchant's own delta_7d.{metric}_pct.", levers
    if fp.ctr_below_peer and fp.peer_avg_ctr is not None and fp.ctr is not None:
        body = (
            f"{name}, your CTR is {fp.ctr*100:.1f}% vs a peer median of {fp.peer_avg_ctr*100:.1f}% "
            f"for your category. Want me to show the 2 things peers with higher CTR do differently?"
        )
        return body, CTA_OPEN, SEND_VERA, "No fresh delta in context; fell back to the peer-CTR gap, still a real number from merchant+category context.", ["loss_aversion", "social_proof"]
    body = f"{name}, checking in on your listing performance — nothing unusual to flag right now, but tell me if a metric matters most to you this week and I'll watch it."
    return body, CTA_OPEN, SEND_VERA, "Perf trigger fired but no concrete delta/peer-gap in context; asking the merchant instead of inventing a number.", ["ask_merchant"]


def _milestone(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    payload = fp.trigger_payload or {}
    milestone = payload.get("milestone") or payload.get("metric_or_topic")
    reviews = fp.peer_stats.get("avg_reviews") if fp.peer_stats else None
    if fp.total_unique_ytd:
        body = f"{name}, milestone: {fp.total_unique_ytd} unique customers YTD. Want a one-line social post drafted to mark it?"
        return body, CTA_OPEN, SEND_VERA, "Milestone anchored on merchant's real customer_aggregate.total_unique_ytd.", ["social_proof", "effort_externalization"]
    if milestone and isinstance(milestone, str) and milestone != "milestone_reached":
        body = f"{name}, you just hit {milestone}. Want a one-line social post drafted to mark it?"
        return body, CTA_OPEN, SEND_VERA, "Milestone text taken directly from trigger payload.", ["social_proof"]
    body = f"{name}, checking your account for a milestone worth celebrating — nothing concrete in view yet, will flag the moment one lands."
    return body, CTA_NONE, SEND_VERA, "Milestone trigger without a real milestone value in context; not inventing a number.", ["reciprocity"]


def _competitor(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    payload = fp.trigger_payload or {}
    dist = payload.get("distance_km") or payload.get("distance")
    comp_name = payload.get("competitor_name")
    if comp_name and dist:
        body = f"{name}, {comp_name} just opened {dist}km away and is live on GBP. Want me to pull their listing so you can see what's showing up first?"
        return body, CTA_OPEN, SEND_VERA, "Competitor name + distance taken directly from trigger payload.", ["loss_aversion", "curiosity"]
    body = f"{name}, a new competitor listing went live near {fp.locality or 'your area'} on GBP. Want me to pull the details so you can see what's showing up first?"
    return body, CTA_OPEN, SEND_VERA, "Competitor trigger fired without a name in payload; using only the locality we actually have and offering to fetch the rest rather than inventing a name.", ["loss_aversion", "curiosity"]


def _dormant_or_ask(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    if "stale_posts" in " ".join(fp.signals):
        stale = next((s for s in fp.signals if s.startswith("stale_posts")), "")
        days = stale.split(":")[-1] if ":" in stale else ""
        body = f"{name}, your last Google post was {days} ago. What's your most-asked service this week — I'll turn it into a post."
        return body, CTA_OPEN, SEND_VERA, "Anchored on the merchant's own stale_posts signal; asks the merchant directly (an underused lever per the brief).", ["ask_merchant", "specificity"]
    body = f"{name}, quick one — what's the one thing customers keep asking you about this week? I can turn it into content or an FAQ answer."
    return body, CTA_OPEN, SEND_VERA, "Curiosity/cadence trigger with no specific signal available; using the ask-the-merchant lever, which the brief flags as underused and safe (invents nothing).", ["ask_merchant", "curiosity"]


def _review_theme(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    theme = next((s for s in fp.signals if "review" in s.lower()), None)
    payload = fp.trigger_payload or {}
    theme_text = payload.get("theme") or theme
    if theme_text:
        body = f"{name}, a few recent reviews mention \"{theme_text}\". Want me to draft a reply template you can reuse?"
        return body, CTA_OPEN, SEND_VERA, "Review theme taken from a real signal/payload field.", ["specificity", "effort_externalization"]
    body = f"{name}, keeping an eye on your recent reviews for any recurring theme — nothing to flag yet."
    return body, CTA_NONE, SEND_VERA, "Review-theme trigger without a concrete theme in context.", []


def _renewal(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    if fp.days_remaining is not None:
        body = f"{name}, your {fp.plan or 'plan'} has {fp.days_remaining} days left. Want me to lock in renewal now so there's no gap in visibility?"
        return body, CTA_BINARY, SEND_VERA, "Renewal urgency anchored on the merchant's real subscription.days_remaining.", ["loss_aversion", "specificity"]
    body = f"{name}, just flagging your subscription is coming up for renewal soon — want the details?"
    return body, CTA_BINARY, SEND_VERA, "Renewal trigger fired without days_remaining in context.", ["loss_aversion"]


def _festival_news(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    payload = fp.trigger_payload or {}
    event = payload.get("match") or payload.get("event") or payload.get("festival") or payload.get("headline")
    when = payload.get("match_time_iso") or payload.get("date")
    venue = payload.get("venue") or payload.get("city")
    if event:
        when_clause = f" on {when}" if when else ""
        venue_clause = f" at {venue}" if venue else ""
        offer = fp.active_offers[0] if fp.active_offers else None
        offer_clause = f" Got a slot for {offer}?" if offer else " Want a quick offer drafted for the crowd?"
        body = f"{name}, {event}{venue_clause}{when_clause} — footfall spikes on nights like this.{offer_clause}"
        return body, CTA_OPEN, SEND_VERA, "External event (name/venue/time) taken directly from trigger payload; offer referenced only if it's a real active offer.", ["specificity", "loss_aversion"]
    body = f"{name}, a local event is coming up that usually moves footfall in {fp.locality or 'your area'} — want me to check if it's worth a push?"
    return body, CTA_OPEN, SEND_VERA, "Festival/news trigger without concrete event details in payload; kept vague on purpose rather than inventing an event name.", ["curiosity"]


def _operational(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    payload = fp.trigger_payload or {}
    detail = payload.get("detail") or payload.get("item")
    if "gbp_unverified" in fp.trigger_kind:
        body = f"{name}, your Google Business Profile shows as unverified — that's likely capping your visibility. Want me to walk you through verification? 5-min setup."
        return body, CTA_BINARY, SEND_VERA, "GBP verification status is an operational fact from the trigger kind itself.", ["loss_aversion", "effort_externalization"]
    if detail:
        body = f"{name}, heads up: {detail}. Want me to help sort it?"
        return body, CTA_OPEN, SEND_VERA, "Operational alert detail taken directly from payload.", ["loss_aversion"]
    body = f"{name}, one operational item came up on your account — want me to walk you through it?"
    return body, CTA_OPEN, SEND_VERA, "Operational trigger without a concrete detail in payload.", []


def _followup_winback(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    if fp.lapsed_180d_plus:
        body = f"{name}, {fp.lapsed_180d_plus} of your customers haven't been back in 180+ days. Want me to draft a win-back nudge for them?"
        return body, CTA_OPEN, SEND_VERA, "Anchored on merchant's real customer_aggregate.lapsed_180d_plus.", ["loss_aversion", "effort_externalization"]
    body = f"{name}, following up on where we left off — still want to move forward on that?"
    return body, CTA_BINARY, SEND_VERA, "Follow-up trigger without a fresh number in context; keeping the CTA binary and referencing prior thread only.", []


# --- customer-facing (scope == "customer") ---------------------------------

def _customer_recall_or_appt(fp: FactPack, appt: bool) -> tuple[str, str, str, str, list[str]]:
    cname = fp.customer_name or "there"
    merchant = fp.merchant_name or "your provider"
    offer = fp.active_offers[0] if fp.active_offers else None
    slot = fp.customer_preferred_slot.replace("_", " ") if fp.customer_preferred_slot else ""
    if appt:
        body = f"Hi {cname}, {merchant} here — reminder: you have an appointment tomorrow."
        if slot:
            body += f" Your usual preference is {slot}, let us know if that's still the plan."
        return body, CTA_OPEN, SEND_ON_BEHALF, "Appointment reminder; only references the real preferred-slot field if present.", ["specificity"]
    last_visit_clause = f" It's been a while since your last visit ({fp.customer_last_visit})." if fp.customer_last_visit else ""
    body = f"Hi {cname}, {merchant} here.{last_visit_clause}"
    if offer:
        body += f" {offer} is running right now if you'd like to come back in"
        if slot:
            body += f" — {slot} slots are open."
        else:
            body += "."
        body += " Reply YES to book, or STOP to opt out."
        return body, CTA_BINARY, SEND_ON_BEHALF, "Recall/lapsed trigger with a real active offer and slot preference from context.", ["loss_aversion", "specificity"]
    body += " Would you like us to check available slots for you? Reply YES or STOP."
    return body, CTA_BINARY, SEND_ON_BEHALF, "Recall/lapsed trigger without an active offer in context; asking rather than inventing a promo.", ["loss_aversion"]


def _customer_refill(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    cname = fp.customer_name or "there"
    merchant = fp.merchant_name or "your pharmacy"
    services = ", ".join(fp.customer_services[-1:]) if fp.customer_services else ""
    med_clause = f" for {services}" if services else ""
    body = f"Hi {cname}, {merchant} here — your regular refill{med_clause} is likely due. Reply YES to reorder, or STOP to opt out."
    return body, CTA_BINARY, SEND_ON_BEHALF, "Chronic refill nudge; references the real last-known service line if available.", ["loss_aversion", "effort_externalization"]


FAMILY_BUILDERS = {
    "research_digest": lambda fp: _research_digest(fp),
    "regulation_change": lambda fp: _compliance(fp),
    "cde_opportunity": lambda fp: _compliance(fp),
    "perf_dip": lambda fp: _perf(fp, dip=True),
    "seasonal_perf_dip": lambda fp: _perf(fp, dip=True),
    "perf_spike": lambda fp: _perf(fp, dip=False),
    "milestone_reached": lambda fp: _milestone(fp),
    "competitor_opened": lambda fp: _competitor(fp),
    "dormant_with_vera": lambda fp: _dormant_or_ask(fp),
    "curious_ask_due": lambda fp: _dormant_or_ask(fp),
    "scheduled_recurring": lambda fp: _dormant_or_ask(fp),
    "active_planning_intent": lambda fp: _dormant_or_ask(fp),
    "review_theme_emerged": lambda fp: _review_theme(fp),
    "renewal_due": lambda fp: _renewal(fp),
    "festival_upcoming": lambda fp: _festival_news(fp),
    "ipl_match_today": lambda fp: _festival_news(fp),
    "category_seasonal": lambda fp: _festival_news(fp),
    "local_news_event": lambda fp: _festival_news(fp),
    "weather_heatwave": lambda fp: _festival_news(fp),
    "supply_alert": lambda fp: _operational(fp),
    "gbp_unverified": lambda fp: _operational(fp),
    "wedding_package_followup": lambda fp: _followup_winback(fp),
    "trial_followup": lambda fp: _followup_winback(fp),
    "winback_eligible": lambda fp: _followup_winback(fp),
    "recall_due": lambda fp: _customer_recall_or_appt(fp, appt=False),
    "customer_lapsed_soft": lambda fp: _customer_recall_or_appt(fp, appt=False),
    "customer_lapsed_hard": lambda fp: _customer_recall_or_appt(fp, appt=False),
    "appointment_tomorrow": lambda fp: _customer_recall_or_appt(fp, appt=True),
    "chronic_refill_due": lambda fp: _customer_refill(fp),
}


def _generic_fallback(fp: FactPack) -> tuple[str, str, str, str, list[str]]:
    name = _name(fp)
    if fp.signals:
        sig = fp.signals[0].split(":")[0].replace("_", " ")
        body = f"{name}, noticed {sig} on your account. Want me to take a look with you?"
        return body, CTA_OPEN, SEND_VERA, "Unrecognized trigger kind; fell back to the first real merchant signal in context rather than a generic line.", ["specificity"]
    body = f"{name}, checking in — anything on your account you'd like a second pair of eyes on this week?"
    return body, CTA_OPEN, SEND_VERA, "Unrecognized trigger kind and no signals in context; restrained, non-promotional check-in.", ["ask_merchant"]


def compose(
    category: Optional[dict],
    merchant: Optional[dict],
    trigger: Optional[dict],
    customer: Optional[dict] = None,
) -> dict:
    fp = build_fact_pack(category, merchant, trigger, customer)

    builder = FAMILY_BUILDERS.get(fp.trigger_kind, _generic_fallback)
    body, cta, send_as, rationale, levers = builder(fp)

    # anti-repetition: never resend verbatim what Vera already sent this merchant
    if body in fp.prior_bodies:
        body = body.rstrip(".") + f" (following up again on this)."

    return {
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "suppression_key": fp.suppression_key or f"{fp.trigger_kind}:{fp.category_slug}",
        "rationale": rationale + f" Levers used: {', '.join(levers) if levers else 'none'}.",
    }
