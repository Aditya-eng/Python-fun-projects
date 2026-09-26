"""
composer.py — the actual message-writing brain.

Deterministic, template-based, fact-anchored. No LLM call required (see
llm_hook.py for the optional upgrade path). Every sentence traces back to a
field that was actually present in the pushed context — nothing here invents
a number, a source, or a competitor name that wasn't handed to it.

Trigger-payload field names below are verified against the real
dataset/triggers_seed.json shipped in the official challenge zip (not
guessed from prose) — see each family builder's comment for the source kind.

compose(category, merchant, trigger, customer) -> ComposedMessage dict
respond(...) lives in conversation_handlers.py, not here.
"""

from __future__ import annotations

from typing import Optional

from facts import FactPack, build_fact_pack

# CTA vocabulary — verified against examples/api-call-examples.md. This is a
# descriptive slug, not a fixed 3-value enum: the official examples use
# "open_ended", "none", "binary_yes_no", "multi_choice_slot", and
# "binary_confirm_cancel" depending on what the message is actually asking.
CTA_OPEN = "open_ended"
CTA_NONE = "none"
CTA_YES_NO = "binary_yes_no"
CTA_CONFIRM_CANCEL = "binary_confirm_cancel"
CTA_MULTI_SLOT = "multi_choice_slot"

SEND_VERA = "vera"
SEND_ON_BEHALF = "merchant_on_behalf"

BuilderResult = tuple[str, str, str, str, list[str]]  # body, cta, send_as, rationale, levers


def _pct(x: Optional[float]) -> str:
    if x is None:
        return ""
    return f"{abs(x) * 100:.0f}%"


def _name(fp: FactPack) -> str:
    return fp.owner_first_name or fp.merchant_name or "there"


def _slot_labels(slots: object) -> list[str]:
    if not isinstance(slots, list):
        return []
    return [s.get("label") for s in slots if isinstance(s, dict) and s.get("label")]


# ---------------------------------------------------------------------------
# Digest-referencing families: research_digest, regulation_change,
# cde_opportunity all carry {category, top_item_id / digest_item_id} in
# trigger.payload — the actual item lives in category.digest[], looked up by id.
# ---------------------------------------------------------------------------

def _research_digest(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    item = fp.digest_by_id(fp.trigger_payload.get("top_item_id")) or fp.digest_item
    if item and item.get("title"):
        title = item["title"]
        source = item.get("source", "")
        n = item.get("trial_n")
        segment = item.get("patient_segment")
        actionable = item.get("actionable")
        anchor = f"{n}-patient trial" if n else "recent item"
        seg_clause = f" for your {segment.replace('_', ' ')}" if segment else ""
        action_clause = f" {actionable}." if actionable else ""
        body = (
            f"{name}, {source or 'this week’s category digest'} landed — "
            f"{anchor}: {title}{seg_clause}.{action_clause} "
            f"Want me to pull the abstract + draft something you can share?"
        )
        return (
            body, CTA_OPEN, SEND_VERA,
            f"Anchored on category.digest item '{item.get('id')}' referenced by trigger.payload.top_item_id; used its own 'actionable' field rather than inventing next steps.",
            ["specificity", "reciprocity", "curiosity"],
        )
    body = f"{name}, nothing new in this week's category digest for you yet — I'll flag the next relevant item the moment it drops."
    return body, CTA_NONE, SEND_VERA, "research_digest fired but top_item_id didn't resolve to a real digest item; restrained no-op.", ["reciprocity"]


def _regulation_change(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    item = fp.digest_by_id(payload.get("top_item_id"))
    deadline = payload.get("deadline_iso") or (item or {}).get("date")
    if item and deadline:
        title = item.get("title", "")
        source = item.get("source", "")
        actionable = item.get("actionable", "")
        body = f"{name}, {title} ({source}) — effective {deadline}. {actionable + '.' if actionable else ''} Want guidance on what this changes for your setup?"
        return body, CTA_YES_NO, SEND_VERA, f"Regulation deadline pulled from trigger.payload.deadline_iso; content from category.digest item '{item.get('id')}'.", ["loss_aversion", "specificity"]
    body = f"{name}, there's a compliance update I'm tracking for you — I'll ping you the moment the specifics are confirmed."
    return body, CTA_NONE, SEND_VERA, "regulation_change fired without a resolvable digest item/deadline; avoiding invented specifics.", ["reciprocity"]


def _cde_opportunity(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    item = fp.digest_by_id(payload.get("digest_item_id"))
    credits = payload.get("credits")
    fee = payload.get("fee")
    if item:
        title = item.get("title", "")
        source = item.get("source", "")
        when = item.get("date")
        fee_clause = (fee or "").replace("_", " ")
        credit_clause = f"{credits} CE credits" if credits else "CE credits"
        when_clause = f" on {when}" if when else ""
        body = f"{name}, {title} — {source}{when_clause}. {credit_clause}, {fee_clause}. Want me to hold a spot?"
        return body, CTA_YES_NO, SEND_VERA, f"CDE opportunity from category.digest item '{item.get('id')}', credits/fee from trigger.payload.", ["social_proof", "loss_aversion"]
    body = f"{name}, a category learning opportunity is coming up — I'll share the details once confirmed."
    return body, CTA_NONE, SEND_VERA, "cde_opportunity fired without a resolvable digest item; restrained.", ["reciprocity"]


# ---------------------------------------------------------------------------
# Performance: perf_dip / perf_spike / seasonal_perf_dip.
# Real payload: {metric, delta_pct, window, vs_baseline, likely_driver?, is_expected_seasonal?, season_note?}
# ---------------------------------------------------------------------------

def _perf(fp: FactPack, dip: bool) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    metric = payload.get("metric")
    delta_pct = payload.get("delta_pct")
    window = payload.get("window", "week")
    vs_baseline = payload.get("vs_baseline")
    likely_driver = payload.get("likely_driver")
    is_seasonal = payload.get("is_expected_seasonal")
    season_note = payload.get("season_note")

    if metric and delta_pct is not None:
        direction = "dropped" if delta_pct < 0 else "jumped"
        base_clause = f" (baseline was {vs_baseline})" if vs_baseline is not None else ""
        if is_seasonal and season_note:
            body = f"{name}, your {metric} {direction} {_pct(delta_pct)} over the last {window}{base_clause} — expected seasonal pattern ({season_note.replace('_', ' ')}), not a red flag. Want me to suggest one thing to try anyway?"
            return body, CTA_OPEN, SEND_VERA, "Expected seasonal dip flagged from trigger.payload.is_expected_seasonal/season_note, framed to avoid false alarm.", ["specificity"]
        driver_clause = f" Likely driver: {likely_driver.replace('_', ' ')}." if likely_driver else ""
        if dip:
            body = f"{name}, your {metric} {direction} {_pct(delta_pct)} over the last {window}{base_clause}.{driver_clause} Want me to dig in?"
            levers = ["loss_aversion", "specificity"]
        else:
            body = f"{name}, your {metric} {direction} {_pct(delta_pct)} over the last {window}{base_clause} — nice move.{driver_clause} Want a quick note on what to repeat?"
            levers = ["specificity", "reciprocity"]
        return body, CTA_OPEN, SEND_VERA, "Performance number taken directly from trigger.payload (metric/delta_pct/vs_baseline/likely_driver), not merchant.performance.", levers

    # fall back to merchant.performance.delta_7d if the trigger payload itself is thin
    pct = _pct(fp.views_delta_pct if fp.views_delta_pct is not None else fp.calls_delta_pct)
    fallback_metric = "views" if fp.views_delta_pct is not None else "calls"
    if pct:
        body = f"{name}, your {fallback_metric} moved {pct} week-over-week. Want me to check what changed?"
        return body, CTA_OPEN, SEND_VERA, "trigger.payload lacked metric/delta_pct; fell back to merchant.performance.delta_7d.", ["specificity"]
    if fp.ctr_below_peer and fp.peer_avg_ctr is not None and fp.ctr is not None:
        body = f"{name}, your CTR is {fp.ctr*100:.1f}% vs a peer median of {fp.peer_avg_ctr*100:.1f}%. Want me to show what higher-CTR peers do differently?"
        return body, CTA_OPEN, SEND_VERA, "No delta in trigger payload or merchant deltas; used the real peer-CTR gap instead.", ["loss_aversion", "social_proof"]
    body = f"{name}, checking in on performance — nothing concrete to flag right now. Tell me what metric matters most this week and I'll watch it."
    return body, CTA_OPEN, SEND_VERA, "Perf-family trigger with no usable number anywhere in context; asking rather than inventing one.", ["ask_merchant"]


# ---------------------------------------------------------------------------
# milestone_reached: real payload {metric, value_now, milestone_value, is_imminent}
# is_imminent=true means APPROACHING, not yet reached — framing must differ.
# ---------------------------------------------------------------------------

def _milestone(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    metric = payload.get("metric")
    value_now = payload.get("value_now")
    milestone_value = payload.get("milestone_value")
    is_imminent = payload.get("is_imminent")

    if metric and value_now is not None and milestone_value is not None:
        metric_label = metric.replace("_", " ")
        if is_imminent and value_now < milestone_value:
            gap = milestone_value - value_now
            body = f"{name}, you're {gap} {metric_label} away from {milestone_value}. Want a one-line social post ready to fire the moment you hit it?"
            return body, CTA_OPEN, SEND_VERA, "Approaching-milestone framing from trigger.payload.is_imminent (value_now < milestone_value) — not claiming it's already reached.", ["social_proof", "curiosity"]
        body = f"{name}, milestone: {value_now} {metric_label} (past {milestone_value}). Want a one-line social post drafted to mark it?"
        return body, CTA_OPEN, SEND_VERA, "Milestone already reached per trigger.payload.value_now >= milestone_value.", ["social_proof", "effort_externalization"]
    if fp.total_unique_ytd:
        body = f"{name}, milestone: {fp.total_unique_ytd} unique customers YTD. Want a one-line social post drafted?"
        return body, CTA_OPEN, SEND_VERA, "trigger.payload lacked metric fields; fell back to merchant.customer_aggregate.total_unique_ytd.", ["social_proof"]
    body = f"{name}, checking your account for a milestone worth marking — nothing concrete yet, will flag it the moment one lands."
    return body, CTA_NONE, SEND_VERA, "milestone_reached fired without usable payload fields; not inventing a number.", ["reciprocity"]


# ---------------------------------------------------------------------------
# competitor_opened: real payload {competitor_name, distance_km, their_offer, opened_date}
# ---------------------------------------------------------------------------

def _competitor(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    comp_name = payload.get("competitor_name")
    dist = payload.get("distance_km")
    their_offer = payload.get("their_offer")
    if comp_name and dist is not None:
        offer_clause = f" — running {their_offer}" if their_offer else ""
        body = f"{name}, {comp_name} opened {dist}km away{offer_clause}. Want me to pull their full listing so you can see what's showing up first?"
        return body, CTA_OPEN, SEND_VERA, "Competitor name, distance, and their live offer taken directly from trigger.payload.", ["loss_aversion", "curiosity", "social_proof"]
    body = f"{name}, a new competitor listing went live near {fp.locality or 'your area'} on GBP. Want me to pull the details?"
    return body, CTA_OPEN, SEND_VERA, "competitor_opened fired without a name/distance in payload; using only the real locality we have.", ["loss_aversion", "curiosity"]


# ---------------------------------------------------------------------------
# dormant_with_vera: real payload {days_since_last_merchant_message, last_topic}
# ---------------------------------------------------------------------------

def _dormant(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    days = payload.get("days_since_last_merchant_message")
    topic = payload.get("last_topic")
    if days is not None:
        topic_clause = f" — we left off on {topic.replace('_', ' ')}" if topic else ""
        body = f"{name}, it's been {days} days since your last message{topic_clause}. Still want to pick that up, or is there something else on your mind this week?"
        return body, CTA_OPEN, SEND_VERA, "Dormancy days + last topic taken directly from trigger.payload.", ["specificity", "curiosity"]
    body = f"{name}, been a while — what's the one thing customers keep asking you about this week? I can turn it into content."
    return body, CTA_OPEN, SEND_VERA, "dormant_with_vera fired without payload fields; using the ask-the-merchant lever (safe, invents nothing).", ["ask_merchant", "curiosity"]


# ---------------------------------------------------------------------------
# curious_ask_due: real payload {ask_template, last_ask_at}
# ---------------------------------------------------------------------------

_ASK_TEMPLATES = {
    "what_service_in_demand_this_week": "What's the one service customers keep asking about this week?",
    "what_would_help_you_this_week": "What's one thing that would actually help your business this week?",
}


def _curious_ask(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    template = fp.trigger_payload.get("ask_template")
    question = _ASK_TEMPLATES.get(template, "What's the one thing customers keep asking you about this week?")
    body = f"{name}, quick one — {question[0].lower() + question[1:]} I can turn it into content or an FAQ answer."
    return body, CTA_OPEN, SEND_VERA, f"Question text driven by trigger.payload.ask_template ('{template}'), not a hardcoded line.", ["ask_merchant", "curiosity"]


# ---------------------------------------------------------------------------
# active_planning_intent: real payload {intent_topic, merchant_last_message}
# The merchant already expressed interest — respond to what they actually said.
# ---------------------------------------------------------------------------

def _active_planning_intent(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    topic = payload.get("intent_topic")
    last_msg = payload.get("merchant_last_message")
    if topic:
        topic_label = topic.replace("_", " ")
        quote_clause = f" You said: \"{last_msg}\"." if last_msg else ""
        body = f"{name}, following up on {topic_label}.{quote_clause} Want me to draft a first version so you have something concrete to react to?"
        return body, CTA_YES_NO, SEND_VERA, "Merchant's own expressed intent (trigger.payload.intent_topic/merchant_last_message) — responding to what they actually said, not a generic pitch.", ["effort_externalization", "reciprocity"]
    body = f"{name}, following up on what you mentioned earlier — want me to put together a first draft?"
    return body, CTA_YES_NO, SEND_VERA, "active_planning_intent fired without intent_topic in payload; kept generic.", ["effort_externalization"]


# ---------------------------------------------------------------------------
# review_theme_emerged: real payload {theme, occurrences_30d, trend, common_quote}
# ---------------------------------------------------------------------------

def _review_theme(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    theme = payload.get("theme")
    occurrences = payload.get("occurrences_30d")
    quote = payload.get("common_quote")
    if theme:
        theme_label = theme.replace("_", " ")
        freq_clause = f" ({occurrences}x in the last 30 days)" if occurrences else ""
        quote_clause = f" One review said: \"{quote}\"." if quote else ""
        body = f"{name}, a theme is showing up in your reviews: {theme_label}{freq_clause}.{quote_clause} Want me to draft a reply template you can reuse?"
        return body, CTA_OPEN, SEND_VERA, "Review theme, frequency, and a real customer quote all taken directly from trigger.payload.", ["specificity", "effort_externalization"]
    body = f"{name}, keeping an eye on your recent reviews for any recurring theme — nothing to flag yet."
    return body, CTA_NONE, SEND_VERA, "review_theme_emerged fired without a theme in payload.", []


# ---------------------------------------------------------------------------
# renewal_due: real payload {days_remaining, plan, renewal_amount}
# ---------------------------------------------------------------------------

def _renewal(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    days = payload.get("days_remaining", fp.days_remaining)
    plan = payload.get("plan", fp.plan)
    amount = payload.get("renewal_amount")
    if days is not None:
        amount_clause = f" (₹{amount})" if amount else ""
        body = f"{name}, your {plan or 'plan'} has {days} days left{amount_clause}. Want me to lock in renewal now so there's no visibility gap?"
        return body, CTA_YES_NO, SEND_VERA, "Renewal days/plan/amount taken from trigger.payload where present, merchant.subscription otherwise.", ["loss_aversion", "specificity"]
    body = f"{name}, your subscription is coming up for renewal soon — want the details?"
    return body, CTA_YES_NO, SEND_VERA, "renewal_due fired without days_remaining anywhere in context.", ["loss_aversion"]


# ---------------------------------------------------------------------------
# winback_eligible: real payload {days_since_expiry, perf_dip_pct, lapsed_customers_added_since_expiry}
# This is about winning back the MERCHANT's own lapsed subscription, not their
# end-customers — a different meaning than the trigger name might suggest.
# ---------------------------------------------------------------------------

def _winback_merchant(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    days_since = payload.get("days_since_expiry")
    perf_dip = payload.get("perf_dip_pct")
    lapsed_added = payload.get("lapsed_customers_added_since_expiry")
    if days_since is not None:
        perf_clause = f" Visibility is down {_pct(perf_dip)} since then." if perf_dip is not None else ""
        lapsed_clause = f" {lapsed_added} more of your customers have gone quiet in that window." if lapsed_added else ""
        body = f"{name}, it's been {days_since} days since your plan expired.{perf_clause}{lapsed_clause} Want me to walk you through renewing?"
        return body, CTA_YES_NO, SEND_VERA, "Lapsed-subscription win-back anchored on trigger.payload.days_since_expiry/perf_dip_pct/lapsed_customers_added_since_expiry.", ["loss_aversion", "specificity"]
    body = f"{name}, following up on your account status — want me to walk you through getting back to full visibility?"
    return body, CTA_YES_NO, SEND_VERA, "winback_eligible fired without payload fields.", ["loss_aversion"]


# ---------------------------------------------------------------------------
# wedding_package_followup: real payload {wedding_date, trial_completed, days_to_wedding, next_step_window_open}
# ---------------------------------------------------------------------------

def _wedding_followup(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    days_to = payload.get("days_to_wedding")
    next_step = payload.get("next_step_window_open")
    if days_to is not None and next_step:
        step_label = next_step.replace("_", " ")
        body = f"{name}, {days_to} days to the wedding — the {step_label} window just opened. Want me to draft the next steps for the client?"
        return body, CTA_YES_NO, SEND_VERA, "Wedding countdown and next-step window taken directly from trigger.payload.", ["specificity", "effort_externalization"]
    body = f"{name}, following up on the wedding package — still on track? Want me to check the next step for the client?"
    return body, CTA_YES_NO, SEND_VERA, "wedding_package_followup fired without payload fields.", []


# ---------------------------------------------------------------------------
# trial_followup: real payload {trial_date, next_session_options:[{iso,label}]}
# ---------------------------------------------------------------------------

def _trial_followup(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    trial_date = payload.get("trial_date")
    options = _slot_labels(payload.get("next_session_options"))
    if options:
        opts_clause = " or ".join(options)
        trial_clause = f" since the {trial_date} trial" if trial_date else ""
        body = f"{name}, following up{trial_clause} — next session options are {opts_clause}. Want me to book one in?"
        cta = CTA_MULTI_SLOT if len(options) > 1 else CTA_YES_NO
        return body, cta, SEND_VERA, "Trial date and real next-session slot options taken directly from trigger.payload.", ["specificity", "effort_externalization"]
    body = f"{name}, following up on the trial — want me to line up the next session?"
    return body, CTA_YES_NO, SEND_VERA, "trial_followup fired without next_session_options in payload.", []


# ---------------------------------------------------------------------------
# category_seasonal: real payload {season, trends:[...], shelf_action_recommended}
# ---------------------------------------------------------------------------

def _category_seasonal(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    trends = payload.get("trends") or []
    season = payload.get("season")
    if trends:
        top = ", ".join(t.replace("_", " ") for t in trends[:3])
        season_clause = f" for {season.replace('_', ' ')}" if season else ""
        body = f"{name}, category trends{season_clause}: {top}. Want a quick shelf/stock note based on these?"
        return body, CTA_OPEN, SEND_VERA, "Seasonal category trends taken directly from trigger.payload.trends.", ["specificity", "social_proof"]
    body = f"{name}, a seasonal category shift is coming — want me to check what it means for your stock?"
    return body, CTA_OPEN, SEND_VERA, "category_seasonal fired without a trends list in payload.", []


# ---------------------------------------------------------------------------
# gbp_unverified: real payload {verified, verification_path, estimated_uplift_pct}
# ---------------------------------------------------------------------------

def _gbp_unverified(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    uplift = payload.get("estimated_uplift_pct")
    path = payload.get("verification_path")
    uplift_clause = f" — roughly {_pct(uplift)} more visibility once verified" if uplift is not None else ""
    path_clause = f" via {path.replace('_', ' ')}" if path else ""
    body = f"{name}, your Google Business Profile is unverified{uplift_clause}. Verification{path_clause} is a 5-min setup. Want me to walk you through it?"
    return body, CTA_YES_NO, SEND_VERA, "Uplift estimate and verification path taken directly from trigger.payload.", ["loss_aversion", "effort_externalization", "specificity"]


# ---------------------------------------------------------------------------
# supply_alert: real payload {alert_id, molecule, affected_batches, manufacturer}
# ---------------------------------------------------------------------------

def _supply_alert(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    molecule = payload.get("molecule")
    batches = payload.get("affected_batches") or []
    manufacturer = payload.get("manufacturer")
    if molecule:
        batch_clause = f" (batches {', '.join(batches)})" if batches else ""
        mfr_clause = f" from {manufacturer}" if manufacturer else ""
        body = f"{name}, supply alert: {molecule}{mfr_clause}{batch_clause}. Want me to check your current stock against this?"
        return body, CTA_YES_NO, SEND_VERA, "Molecule, batch numbers, and manufacturer taken directly from trigger.payload.", ["loss_aversion", "specificity"]
    body = f"{name}, a supply alert came in for your category — want me to check if it affects your stock?"
    return body, CTA_YES_NO, SEND_VERA, "supply_alert fired without molecule details in payload.", ["loss_aversion"]


# --- customer-facing (scope == "customer") ---------------------------------
# recall_due real payload: {service_due, last_service_date, due_date, available_slots:[{iso,label}]}

def _customer_recall(fp: FactPack) -> BuilderResult:
    cname = fp.customer_name or "there"
    merchant = fp.merchant_name or "your provider"
    payload = fp.trigger_payload
    service_due = payload.get("service_due")
    due_date = payload.get("due_date")
    options = _slot_labels(payload.get("available_slots"))
    offer = fp.active_offers[0] if fp.active_offers else None

    service_clause = f" your {service_due.replace('_', ' ')} recall is due" if service_due else "you're due for a recall"
    due_clause = f" (due {due_date})" if due_date else ""

    if options:
        opts_clause = " or ".join(options)
        offer_clause = f" {offer}." if offer else ""
        body = f"Hi {cname}, {merchant} here — {service_clause}{due_clause}. Slots open: {opts_clause}.{offer_clause} Reply with the slot that works, or STOP to opt out."
        cta = CTA_MULTI_SLOT if len(options) > 1 else CTA_YES_NO
        return body, cta, SEND_ON_BEHALF, "Real available_slots from trigger.payload used verbatim as the slot options — matches the recall_due schema exactly.", ["loss_aversion", "specificity"]

    body = f"Hi {cname}, {merchant} here — {service_clause}{due_clause}. Want us to check available slots for you? Reply YES or STOP."
    return body, CTA_YES_NO, SEND_ON_BEHALF, "recall_due fired without available_slots in payload; asking rather than inventing times.", ["loss_aversion"]


def _customer_lapsed(fp: FactPack, hard: bool) -> BuilderResult:
    cname = fp.customer_name or "there"
    merchant = fp.merchant_name or "your provider"
    payload = fp.trigger_payload
    days = payload.get("days_since_last_visit")
    offer = fp.active_offers[0] if fp.active_offers else None
    days_clause = f" It's been {days} days since your last visit." if days else ""
    if offer:
        body = f"Hi {cname}, {merchant} here.{days_clause} {offer} is running right now if you'd like to come back in. Reply YES to book, or STOP to opt out."
        return body, CTA_YES_NO, SEND_ON_BEHALF, "Lapse days from trigger.payload + a real active offer.", ["loss_aversion", "specificity"]
    body = f"Hi {cname}, {merchant} here.{days_clause} Would you like us to check available slots? Reply YES or STOP."
    return body, CTA_YES_NO, SEND_ON_BEHALF, f"customer_lapsed_{'hard' if hard else 'soft'} fired without an active offer in context.", ["loss_aversion"]


def _customer_refill(fp: FactPack) -> BuilderResult:
    cname = fp.customer_name or "there"
    merchant = fp.merchant_name or "your pharmacy"
    payload = fp.trigger_payload
    molecules = payload.get("molecule_list") or fp.customer_services
    runs_out = payload.get("stock_runs_out_iso")
    med_clause = f" for {', '.join(molecules)}" if molecules else ""
    timing_clause = f" (stock runs out around {runs_out[:10]})" if runs_out else ""
    body = f"Hi {cname}, {merchant} here — your regular refill{med_clause} is coming due{timing_clause}. Reply YES to reorder, or STOP to opt out."
    return body, CTA_YES_NO, SEND_ON_BEHALF, "Molecule list and stock-out timing taken directly from trigger.payload.chronic_refill_due.", ["loss_aversion", "effort_externalization"]


FAMILY_BUILDERS = {
    "research_digest": _research_digest,
    "regulation_change": _regulation_change,
    "cde_opportunity": _cde_opportunity,
    "perf_dip": lambda fp: _perf(fp, dip=True),
    "seasonal_perf_dip": lambda fp: _perf(fp, dip=True),
    "perf_spike": lambda fp: _perf(fp, dip=False),
    "milestone_reached": _milestone,
    "competitor_opened": _competitor,
    "dormant_with_vera": _dormant,
    "curious_ask_due": _curious_ask,
    "scheduled_recurring": _curious_ask,
    "active_planning_intent": _active_planning_intent,
    "review_theme_emerged": _review_theme,
    "renewal_due": _renewal,
    "winback_eligible": _winback_merchant,
    "wedding_package_followup": _wedding_followup,
    "trial_followup": _trial_followup,
    "category_seasonal": _category_seasonal,
    "gbp_unverified": _gbp_unverified,
    "supply_alert": _supply_alert,
    "festival_upcoming": lambda fp: _festival_news(fp),
    "ipl_match_today": lambda fp: _festival_news(fp),
    "local_news_event": lambda fp: _festival_news(fp),
    "weather_heatwave": lambda fp: _festival_news(fp),
    "recall_due": _customer_recall,
    "customer_lapsed_soft": lambda fp: _customer_lapsed(fp, hard=False),
    "customer_lapsed_hard": lambda fp: _customer_lapsed(fp, hard=True),
    "appointment_tomorrow": lambda fp: _customer_recall(fp),
    "chronic_refill_due": _customer_refill,
}


def _festival_news(fp: FactPack) -> BuilderResult:
    name = _name(fp)
    payload = fp.trigger_payload
    event = payload.get("match") or payload.get("festival") or payload.get("event") or payload.get("headline")
    when = payload.get("match_time_iso") or payload.get("date")
    venue = payload.get("venue") or payload.get("city")
    if event:
        when_clause = f" on {when}" if when else ""
        venue_clause = f" at {venue}" if venue else ""
        offer = fp.active_offers[0] if fp.active_offers else None
        offer_clause = f" Got a slot for {offer}?" if offer else " Want a quick offer drafted for the crowd?"
        body = f"{name}, {event}{venue_clause}{when_clause} — footfall spikes on nights like this.{offer_clause}"
        return body, CTA_OPEN, SEND_VERA, "External event (name/venue/time) taken directly from trigger payload; offer referenced only if real and active.", ["specificity", "loss_aversion"]
    body = f"{name}, a local event is coming up that usually moves footfall in {fp.locality or 'your area'} — want me to check if it's worth a push?"
    return body, CTA_OPEN, SEND_VERA, "Festival/news trigger without concrete event details in payload; kept vague on purpose rather than inventing an event name.", ["curiosity"]


def _generic_fallback(fp: FactPack) -> BuilderResult:
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
        body = body.rstrip(".") + " (following up again on this)."

    return {
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "suppression_key": fp.suppression_key or f"{fp.trigger_kind}:{fp.category_slug}",
        "rationale": rationale + f" Levers used: {', '.join(levers) if levers else 'none'}.",
    }
