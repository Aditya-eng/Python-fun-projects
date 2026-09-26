# Vera Challenge — submission

A deterministic, fact-anchored rewrite of Vera's message composer + reply
handler, built and verified against magicpin's own official challenge zip
(`challenge-brief.md`, `challenge-testing-brief.md`, `examples/`,
`dataset/`), which the person running this session downloaded directly from
the challenge page and shared here mid-build.

## Approach

**No LLM call is required.** The rubric's own "good message" examples are
templates filled with real numbers — that's what's being scored, not prose
creativity. So the composer is:

1. **`facts.py`** — extracts a small `FactPack` of only the values that are
   actually present in the pushed category/merchant/trigger/customer
   payloads, including a `digest_by_id()` lookup since `research_digest`,
   `regulation_change`, and `cde_opportunity` triggers reference a specific
   `category.digest[]` item by id rather than embedding it inline (verified
   against the real `dataset/triggers_seed.json`). Nothing downstream can
   invent a number, source, or name that isn't in here.
2. **`composer.py`** — one builder per `trigger.kind` (~28 kinds), each
   reading the *actual* payload field names for that kind — e.g.
   `competitor_opened` uses `competitor_name`/`distance_km`/`their_offer`;
   `recall_due` uses the real `available_slots: [{iso, label}]` list;
   `milestone_reached` distinguishes an *approaching* milestone
   (`is_imminent`, `value_now < milestone_value`) from one already hit;
   `winback_eligible` is about the merchant's own lapsed subscription
   (`days_since_expiry`), not their customers. These field names come from
   the real seed data, not from guessing off the prose brief — an earlier
   draft got roughly half of them wrong before the real dataset was
   available to check against. Every builder degrades to whatever real
   signal *is* available rather than fabricating specifics when a payload is
   thin — the anti-hallucination posture Phase 3 (context injection)
   explicitly rewards.
3. **`validators.py`** — catches the brief's anti-patterns: multi-CTA,
   taboo vocabulary per category voice, verbatim repeats, empty bodies, and
   **any URL in the body** (a hard -3-per-URL fail per
   `examples/api-call-examples.md` F.4 — Meta would reject the template;
   this overrides the more lenient line in the prose brief). CTA is treated
   as a descriptive slug, not a fixed 3-value enum — the real examples use
   `open_ended`, `none`, `binary_yes_no`, `multi_choice_slot`, and
   `binary_confirm_cancel` depending on what's actually being asked; an
   earlier draft was silently downgrading all of these to `open_ended`,
   which actively hurt message quality. One repair pass, then a minimal
   grounded fallback — the bot never returns an empty `send`.
4. **`conversation_handlers.py`** — the `/v1/reply` state machine, matched
   turn-by-turn against `examples/api-call-examples.md` §4:
   - **Auto-reply**: 3-strike pattern — first canned/repeated message gets
     one `send` nudge (`binary_yes_no`), the second gets `wait` (24h,
     matching the official scenario), the third gets `end`. (An earlier
     draft ended on the second strike — a turn too early relative to the
     scored replay scenario.)
   - **Hard stop/opt-out**: word-boundary matched (so "nonstop" doesn't
     misfire) and immediately ends — and now also marks the merchant (or
     customer) opted-out account-wide, since `bot.py`'s `/v1/tick` checks
     that set before ever composing a new proactive send to them again, not
     just suppressing that one `conversation_id`.
   - **Hostility**: one short apology + opt-out line (`cta: none`, matching
     the official "acceptable alternative"), then the conversation ends on
     *any* next turn regardless of content — keeping the stated commitment
     to step back rather than re-engaging.
   - **Intent transition**: routes straight to a concrete next step with one
     `binary_confirm_cancel` ask, rather than re-qualifying (the brief's
     Pattern D anti-pattern) *or* falsely claiming the action is already
     done before it's confirmed.
   - Off-topic asks get an honest non-competence answer and redirect back to
     the bot's actual scope.
5. **`llm_hook.py`** — optional. If `ANTHROPIC_API_KEY` is set on the host,
   a Claude Haiku pass polishes tone only; it's discarded if it changes any
   number in the message, and the bot works identically with it absent.

## Tradeoffs

- Deterministic-first over LLM-first: guarantees the latency budget, needs
  zero API key to run, and can't hallucinate — at the cost of some phrasing
  variety an LLM would add. The optional polish hook is there if there's
  time to wire a key in.
- Reply handling is rule-based, not another LLM call: faster, and harder for
  a canned WhatsApp auto-responder to talk it in circles.
- In-memory state only (per testing-brief §12) — see the deployment note
  below on what that costs on a serverless host.

## Running it

```bash
pip install -r requirements.txt
uvicorn bot:app --host 0.0.0.0 --port 8080

# in another shell:
python dataset/generate_dataset.py --seed-dir dataset --out dataset/expanded
python generate_submission.py   # writes submission.jsonl
```

## Deployment note

Deployed to Vercel (serverless): **https://vera-challenge-bot.vercel.app**

- `GET https://vera-challenge-bot.vercel.app/v1/healthz` — confirmed live and
  responding by the person running this session.
- `GET https://vera-challenge-bot.vercel.app/v1/metadata`

In-memory state can be lost on a cold start between requests. This is a
known, accepted tradeoff for a same-day deadline over provisioning a new
always-on host — flagged here rather than hidden. If the judge's 60-minute
test window sees enough steady traffic to keep the instance warm, this
shouldn't surface; if it does, `/v1/healthz` will show `contexts_loaded`
reset to zero, which is the visible symptom.

This session's own network policy blocks outbound requests to
`*.vercel.app`, so redeploys after the healthz confirmation were verified
by re-running the full local endpoint test suite against the same code
before pushing, and via Vercel's own deployment-file listing (confirms the
build bundled all source files) — not by re-curling the live URL a second
time. If you change anything after this point, re-check `/v1/healthz`
yourself before submitting.

## Files

| File | Role |
|---|---|
| `bot.py` | the 5 HTTP endpoints (submission deliverable) |
| `facts.py`, `composer.py`, `validators.py`, `conversation_handlers.py`, `llm_hook.py` | composer internals |
| `submission.jsonl` | 30-line deliverable (§7.2) |
| `generate_submission.py` | regenerates it from local test data |
| `challenge-brief.md`, `challenge-testing-brief.md`, `examples/`, `dataset/`, `judge_simulator.py` | the official spec + local dev/test tooling, from magicpin's own challenge zip — **not** submission deliverables, kept here for reproducibility |
