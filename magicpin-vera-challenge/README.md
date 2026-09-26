# Vera Challenge — submission

A deterministic, fact-anchored rewrite of Vera's message composer + reply
handler, built against `challenge-brief.md` / `challenge-testing-brief.md`
(the magicpin AI Challenge spec — see repo root for how those were sourced).

## Approach

**No LLM call is required.** The rubric's own "good message" examples
(Appendix A/B of the brief) are templates filled with real numbers — that's
what's being scored, not prose creativity. So the composer is:

1. **`facts.py`** — extracts a small `FactPack` of only the values that are
   actually present in the pushed category/merchant/trigger/customer
   payloads. Nothing downstream can invent a number, source, or name that
   isn't in here.
2. **`composer.py`** — one template family per `trigger.kind` (~25 kinds
   covering the brief's external/internal/customer-scope triggers), each
   picking a real anchor fact and 1-2 compulsion levers (brief §10). When a
   trigger fires with a thin/placeholder payload, it degrades to whatever
   real signal *is* available (a merchant's own `signals` list, peer CTR gap,
   etc.) rather than fabricating specifics — this is the anti-hallucination
   posture Phase 3 (context injection) explicitly rewards.
3. **`validators.py`** — a post-composition check for the brief's own
   anti-patterns (§11): multi-CTA, taboo vocabulary per category voice,
   verbatim repeats, empty bodies. One repair pass, then a minimal grounded
   fallback — the bot never returns an empty `send`.
4. **`conversation_handlers.py`** — the `/v1/reply` state machine: hard
   stop/opt-out (word-boundary matched, so "nonstop" doesn't misfire),
   auto-reply detection (canned phrases + verbatim-loop, one polite retry
   then graceful exit — the brief's #1 flagged production weakness),
   explicit-intent routing straight to action mode (the brief's Pattern D
   anti-pattern is: don't re-qualify after a "yes"), one de-escalation
   attempt on hostility before exiting, a 30-min backoff on "later", and an
   honest non-competence answer for off-topic asks.
5. **`llm_hook.py`** — optional. If `ANTHROPIC_API_KEY` is set on the host,
   a Claude Haiku pass polishes tone only; it's discarded if it changes any
   number in the message, and the bot works identically with it absent.

## Tradeoffs

- Deterministic-first over LLM-first: guarantees the 30s budget, needs zero
  API key to run, and can't hallucinate — at the cost of some phrasing
  variety an LLM would add. The optional polish hook is there if there's
  time to wire a key in.
- Reply handling is rule-based, not another LLM call: faster, and harder for
  a canned WhatsApp auto-responder to talk it in circles.
- In-memory state only (per testing-brief §12) — see the deployment note
  below on what that costs on a serverless host.

## What would have helped most

Real trigger payloads for local testing. The community dataset generator
this repo's `dataset/` tooling is based on stubs most non-seed triggers as
`{"placeholder": true}` (only ~25 seed triggers carry real facts) — so most
of the local `submission.jsonl` output is deliberately in "degraded/no
fabrication" mode rather than the fully-anchored mode the composer is built
for. The real judge harness pushes real payloads per its own schema
(testing-brief §3.4), so live behavior should look like the seed-trigger
outputs (T03/T04/T09 etc. in `submission.jsonl`), not the placeholder ones.

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

- `GET https://vera-challenge-bot.vercel.app/v1/healthz`
- `GET https://vera-challenge-bot.vercel.app/v1/metadata`

In-memory state can be lost on a cold start between requests. This is a
known, accepted tradeoff for a same-day deadline over provisioning a new
always-on host — flagged here rather than hidden. If the judge's 60-minute
test window sees enough steady traffic to keep the instance warm, this
shouldn't surface; if it does, `/v1/healthz` will show `contexts_loaded`
reset to zero, which is the visible symptom.

**Important — verify before submitting:** this was built and deployed from a
sandboxed session whose network policy blocks outbound requests to
`*.vercel.app`, so the deployment could not be curled from inside that
session to confirm the live endpoints actually respond (only that the build
succeeded and bundled all source files — confirmed via Vercel's deployment
file listing). Hit the two URLs above yourself before submitting the URL to
the portal.

## Files

| File | Role |
|---|---|
| `bot.py` | the 5 HTTP endpoints (submission deliverable) |
| `facts.py`, `composer.py`, `validators.py`, `conversation_handlers.py`, `llm_hook.py` | composer internals |
| `submission.jsonl` | 30-line deliverable (§7.2) |
| `generate_submission.py` | regenerates it from local test data |
| `dataset/`, `judge_simulator.py` | local dev/test tooling only — **not** submission deliverables; reused from a public participant repo to have something to iterate against while `magicpin.com` was unreachable from this environment. Not verified as magicpin's actual tooling. |
