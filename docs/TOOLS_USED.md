# Tools used (Devpost submission text)

This is the draft answer to Devpost's "tools used" / sponsor-technology
question for the PayPal AI Hackathon submission. Copy the relevant parts
into the form; the per-integration detail each links to lives in this repo
so judges can verify every claim against real code and real test runs, not
marketing language.

Every integration below extends the same one product — delegated financial
authority for AI agents — rather than being bolted on to chase a prize.
None of them changes who is allowed to authorize money: that is always,
only, the deterministic policy engine in `backend/app/guardrails/`.

---

## PayPal — Orders v2 API (core, "Best Use of PayPal + AI")

The entire point of AgentAuth. An AI agent (OpenRouter, tool-calling) can
research a purchase and draft a proposal, but it never has the authority to
pay. Only a deterministic, rule-based policy engine decision
(`ALLOW`, or `APPROVAL_REQUIRED` + a human click) ever reaches PayPal. Every
executed purchase runs PayPal's real two-phase flow: `create order
(intent=AUTHORIZE)` → `authorize` → re-verify the authorized amount against
the agent's proposal → `capture` on match or `void` on drift — against the
real PayPal Sandbox REST API, every time, with no mocked success path.
Failure is also always real: a PayPal sandbox decline, exercised on demand
via PayPal's own official negative-testing header (not fabricated — see
`docs/NEGATIVE_TESTING.md`), and the price-variance-triggered void path
proven against the real SDK's own model classes in
`backend/tests/test_paypal.py`.

## APIMatic ("Best Use of APIMatic")

`backend/app/paypal/` was migrated off a hand-rolled OAuth2 + `httpx` REST
client onto PayPal's own official, APIMatic-generated Server SDK
(`paypal-server-sdk`, `paypalserversdk` package). The migration itself was
done using APIMatic's Context Plugin — the mechanism that feeds a coding
agent the SDK's real, grounded method signatures and model classes instead
of letting it guess PayPal's API shape from training data — installed into
Claude Code and used to rewrite `client.py` and `orders.py` around the real
`PaypalServersdkClient`, `ClientCredentialsAuth`, typed request/response
models (`OrderRequest`, `Money`, etc.), and the SDK's own
`ApiResponse`/`ErrorException`/`ApiException` error types, with every
externally-visible function signature unchanged so the rest of the
orchestration layer needed zero changes. Live-testing the migrated client
against real Sandbox immediately caught a genuine bug the old hand-rolled
client had silently shipped with (a missing `PayPal-Request-Id` idempotency
header on card `payment_source` orders). Full trail, including the dead end
in the hackathon slide's example repo and the real plugin repo that replaced
it, is in `docs/APIMATIC.md`.

## AG Grid ("Best Use of AG Grid")

The Commerce Ledger / Agent Operations Console (`/ledger`) is a full AG Grid
Enterprise operations grid over real transaction rows: row grouping (by
agent, by outcome), aggregation, a status bar, set filters, column
visibility, and CSV export, plus a row-click evidence-chain side panel that
walks the real Agent Proposed → Policy Evaluated → PayPal Executed → Audit
Verified timeline for that transaction, with live links to the original
product listing and the full HMAC-chained audit trail entry. Run without a
license key per AG Grid's own guidance for hackathon use — it shows the
standard unlicensed watermark and a console warning, by design, not a bug.

## Bryntum ("Best Use of Bryntum")

The Agent Operations Schedule (`/schedule`) turns standing delegated
instructions ("renew this subscription every month if it's still under
$100") into real, persisted schedules fired by a backend poll loop
(`backend/app/scheduler.py`) through the exact same research → policy →
PayPal pipeline as an on-demand task — every occurrence independently
evaluated, never a fire-and-forget cron stub. The Bryntum Scheduler timeline
renders one real event per past firing, colored by its real recorded
outcome (green completed, red blocked/failed/voided, gray cancelled, blue
in progress), plus a single dashed "next run" marker per active schedule at
its real `next_run_at`, with a live current-time line and event tooltips
showing the real prompt/amount/outcome. Nothing on the timeline is a
synthetic repeat pattern — every event corresponds to a real row in the
database, verified end-to-end with a live backdated schedule that
auto-fired and completed a real $7.99 Sandbox purchase during testing.

## Channel3 ("Best Use of Channel3" / Agentic Commerce)

The agent's research step (`backend/app/search/channel3.py`) can query
Channel3's live product graph for real merchants, prices, availability, and
product imagery — purpose-built for agentic commerce — instead of relying
solely on raw web-search snippets. Real candidate products (with images,
prices, and match rationale) are surfaced inline on the transaction detail
page so a human reviewing an approval-required purchase can see exactly
what the agent compared. If Channel3 is not configured or a search
genuinely fails, the UI shows that failure and the agent falls back to
plain web research — it never fabricates a product or price.

## Render (deployment configuration)

`render.yaml` and `docker-compose.yml` describe the exact two-service
topology (API + frontend, single in-process scheduler) this project runs
locally and was demoed with, including an honestly-documented optional
separate-worker topology that is deliberately not the default (Render's
free background workers and per-service disks don't support it without a
shared database, a real architecture change rather than a config toggle).
[Deployment itself is handled directly by the project owner, not from this
build environment.]

## Also in the stack (not sponsor-prize-specific, but load-bearing)

OpenRouter (model-agnostic LLM access for the agent's tool-calling research
loop — the model is never hard-coded, selected via `OPENROUTER_MODEL`),
`ddgs`/DuckDuckGo (live web search), `open.er-api.com` (live exchange
rates), FastAPI + SQLite (WAL mode, `BEGIN IMMEDIATE` budget reservations)
for the backend, HMAC-SHA256 hash-chained audit log for tamper evidence,
Server-Sent Events for the live activity feed, Next.js 15 + TypeScript +
Tailwind CSS v4 for the frontend.
