"""
facts.py — turns raw context dicts (category, merchant, trigger, customer) into a
small "fact pack": only values that actually appear in the pushed context.

The judge penalizes hallucination hardest of everything else in the rubric, so this
module is deliberately conservative: if a fact isn't in the payload, it does not
appear here, and the composer downstream must not invent it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FactPack:
    # identity
    merchant_name: str = ""
    owner_first_name: str = ""
    locality: str = ""
    city: str = ""
    category_slug: str = ""

    # language
    languages: list[str] = field(default_factory=list)
    code_mix: str = "english_only"  # "hindi_english_natural" | "english_only"

    # performance
    ctr: Optional[float] = None
    peer_avg_ctr: Optional[float] = None
    ctr_below_peer: bool = False
    views: Optional[int] = None
    calls: Optional[int] = None
    directions: Optional[int] = None
    views_delta_pct: Optional[float] = None
    calls_delta_pct: Optional[float] = None

    # offers
    active_offers: list[str] = field(default_factory=list)

    # signals / research
    signals: list[str] = field(default_factory=list)
    digest_item: Optional[dict] = None       # {title, source, trial_n, summary, ...}
    peer_stats: Optional[dict] = None

    # subscription
    days_remaining: Optional[int] = None
    plan: Optional[str] = None

    # customer aggregate
    lapsed_180d_plus: Optional[int] = None
    retention_6mo_pct: Optional[float] = None
    total_unique_ytd: Optional[int] = None

    # trigger-specific (only what's really in trigger.payload)
    trigger_kind: str = ""
    trigger_scope: str = "merchant"
    trigger_urgency: int = 1
    trigger_payload: dict = field(default_factory=dict)
    suppression_key: str = ""

    # customer (optional)
    customer_name: str = ""
    customer_state: str = ""
    customer_last_visit: str = ""
    customer_services: list[str] = field(default_factory=list)
    customer_lang_pref: str = ""
    customer_preferred_slot: str = ""

    # conversation history (for anti-repetition)
    prior_bodies: list[str] = field(default_factory=list)

    def has_real_trigger_payload(self) -> bool:
        """The community dataset generator stubs most non-seed triggers with
        {"placeholder": true}. Real judge triggers won't do this, but we must
        handle both: this tells the composer whether trigger.payload has any
        actual fact to anchor on, or whether it must lean on merchant/category
        signals instead."""
        p = self.trigger_payload or {}
        if not p:
            return False
        if p.get("placeholder") is True and len(p) <= 2:
            return False
        return True


def build_fact_pack(
    category: Optional[dict],
    merchant: Optional[dict],
    trigger: Optional[dict],
    customer: Optional[dict] = None,
) -> FactPack:
    fp = FactPack()

    if merchant:
        identity = merchant.get("identity", {}) or {}
        fp.merchant_name = identity.get("name", "") or ""
        fp.owner_first_name = identity.get("owner_first_name", "") or ""
        fp.locality = identity.get("locality", "") or ""
        fp.city = identity.get("city", "") or ""
        fp.languages = identity.get("languages", []) or []
        fp.category_slug = merchant.get("category_slug", "") or ""

        perf = merchant.get("performance", {}) or {}
        fp.ctr = perf.get("ctr")
        fp.views = perf.get("views")
        fp.calls = perf.get("calls")
        fp.directions = perf.get("directions")
        delta = perf.get("delta_7d", {}) or {}
        fp.views_delta_pct = delta.get("views_pct")
        fp.calls_delta_pct = delta.get("calls_pct")

        fp.active_offers = [
            o.get("title", "") for o in (merchant.get("offers", []) or [])
            if o.get("status") == "active" and o.get("title")
        ]

        fp.signals = merchant.get("signals", []) or []

        sub = merchant.get("subscription", {}) or {}
        fp.days_remaining = sub.get("days_remaining")
        fp.plan = sub.get("plan")

        agg = merchant.get("customer_aggregate", {}) or {}
        fp.lapsed_180d_plus = agg.get("lapsed_180d_plus")
        fp.retention_6mo_pct = agg.get("retention_6mo_pct")
        fp.total_unique_ytd = agg.get("total_unique_ytd")

        fp.prior_bodies = [
            h.get("body", "") for h in (merchant.get("conversation_history", []) or [])
            if h.get("from") == "vera" and h.get("body")
        ]

    if category:
        voice = category.get("voice", {}) or {}
        fp.code_mix = voice.get("code_mix", "english_only") or "english_only"
        fp.peer_stats = category.get("peer_stats") or None
        if fp.peer_stats:
            peer_ctr = fp.peer_stats.get("avg_ctr")
            fp.peer_avg_ctr = peer_ctr
            if peer_ctr is not None and fp.ctr is not None:
                fp.ctr_below_peer = fp.ctr < peer_ctr
        digest = category.get("digest", []) or []
        if digest:
            fp.digest_item = digest[0]

    if trigger:
        fp.trigger_kind = trigger.get("kind", "") or ""
        fp.trigger_scope = trigger.get("scope", "merchant") or "merchant"
        fp.trigger_urgency = trigger.get("urgency", 1) or 1
        fp.trigger_payload = trigger.get("payload", {}) or {}
        fp.suppression_key = trigger.get("suppression_key", "") or ""

    if customer:
        cident = customer.get("identity", {}) or {}
        fp.customer_name = cident.get("name", "") or ""
        fp.customer_lang_pref = cident.get("language_pref", "") or ""
        fp.customer_state = customer.get("state", "") or ""
        rel = customer.get("relationship", {}) or {}
        fp.customer_last_visit = rel.get("last_visit", "") or ""
        fp.customer_services = rel.get("services_received", []) or []
        prefs = customer.get("preferences", {}) or {}
        fp.customer_preferred_slot = prefs.get("preferred_slots", "") or ""

    return fp
