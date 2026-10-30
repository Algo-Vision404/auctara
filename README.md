# Auctara

### Delegated Spending Authority for AI Agents

> **Let AI agents act. Keep financial authority under your control.**

## What is Auctara?

Auctara lets you delegate a real purchasing task to an AI agent, such as
"find the cheapest annual project-management software for my team and buy it
if it's under $80," while keeping every dollar of authority under deterministic,
backend-enforced policy. The agent can research the live web, compare real
merchants and prices, and draft a purchase proposal. It can never authorize
that proposal itself. Every transaction is independently evaluated by a
rule-based policy engine, optionally routed to you for human approval, and
only then executed through the real PayPal Sandbox Orders API.

Auctara is not a shopping assistant, a PayPal wallet, or a banking app. It
is the authorization layer that sits between an autonomous agent and real
money.

## Problem

AI agents are becoming capable of taking actions on behalf of users,
including commerce. As agents get more capable, the open question is no
longer "can an agent buy something" but "who decides how much authority it
has, and how is that boundary enforced."

## Solution

Auctara provides delegated spending authority with deterministic financial
policies:

- Users describe an agent's purpose and spending authority in plain English.
- Auctara converts that into an explicit, numeric policy (autonomous limit,
  approval threshold, daily/monthly caps, velocity limits, blocked/allowed
  categories).
- The agent proposes; a separate, deterministic backend policy engine
  decides `ALLOW`, `APPROVAL_REQUIRED`, or `BLOCK`.
- PayPal Sandbox only ever executes a transaction the policy engine has
  authorized (and, where required, a human has approved).
- Every financial event is written to an HMAC-SHA256 chained audit log.

## Why not just give the agent a card, or approve every purchase by hand?

Agentic-commerce demos tend toward one of two extremes, and Auctara is
deliberately neither:

- **Hand the agent a payment method directly.** Fast to build, but there is
  no enforced boundary: the agent's own judgment (or a prompt-injected
  web page, or a bug) *is* the spending limit.
- **Route every single purchase through a human.** Safe, but it isn't
  delegation — it's an approval queue with an AI-written description
  attached, and it doesn't scale to standing/recurring instructions.

Auctara's bet is that the interesting problem is the middle: an agent
that can act autonomously *within a boundary it cannot move itself*. That
shows up as concrete, testable mechanics, not just a tagline — a
specificity gate that forces a vague proposal back for clarification
before it can even reach policy evaluation; a policy engine that is plain
Python, not a second LLM call, so `ALLOW`/`APPROVAL_REQUIRED`/`BLOCK` is
deterministic and auditable; velocity limits and price-variance tolerance
enforced at authorization time, not just at proposal time; and standing
delegated instructions (recurring schedules) that still get evaluated by
that same policy engine on every single firing, rather than being
trusted once and left to run unchecked.

## Architecture

```text
User
 ↓
Natural-language task
 ↓
AI Agent (Groq, tool-calling: search_web, get_exchange_rate, create_purchase_proposal)
 ↓
Live web research (DuckDuckGo)
 ↓
Purchase proposal (advisory only)
 ↓
Deterministic Policy Engine  →  ALLOW / APPROVAL_REQUIRED / BLOCK
 ↓                                        ↓
 ↓                                 Human approval
 ↓                                        ↓
PayPal Sandbox Orders API (authorize → verify price → capture / void)
 ↓
HMAC-chained Audit Trail
```

The LLM is advisory. The policy engine is authoritative. The frontend never
decides a financial outcome. It only renders what the backend already
decided.

## Zero mock data

Every number in the UI comes from a real backend operation:

- Web research uses the live `ddgs` (DuckDuckGo) search API. If it fails, the
  UI shows `SEARCH_FAILED` and the task fails. It never substitutes a fake
  merchant.
- AI reasoning calls Groq with the model set by `GROQ_MODEL`.
- Exchange rates come from `https://open.er-api.com/v6/latest/USD`, fetched
  live (no hard-coded rates).
- PayPal order creation, authorization, capture, and void all call the real
  PayPal Sandbox REST API. If PayPal is not configured, the app says so
  explicitly instead of pretending a payment succeeded. A completed
  transaction's fee/net breakdown (gross, PayPal fee, net settled) comes
  straight from PayPal's own `seller_receivable_breakdown` on the capture
  response, not an estimate.
- All dashboard numbers, activity events, and audit records are read from
  SQLite rows written by the above real operations.
- Product discovery (Channel3) returns real merchants, prices, and product
  images, or a real, visible failure. It never returns a hard-coded fallback item.
- Scheduled/recurring tasks (the Agent Operations Schedule) are fired by a
  real poll loop through the same pipeline as an on-demand task; nothing
  about a "next run" is simulated.

The one deliberate, clearly-labeled exception is an opt-in "Sandbox QA"
control for demonstrating PayPal failure handling on demand: it uses
PayPal's own official sandbox negative-testing header to get a real,
PayPal-documented decline from PayPal's real API for one task's capture
step, never a fabricated result. Off by default for every normal task. See
[`docs/NEGATIVE_TESTING.md`](docs/NEGATIVE_TESTING.md).

## Technology

**Backend:** Python 3.11+, FastAPI, SQLite (WAL mode, `BEGIN IMMEDIATE` for
budget reservations), httpx, Uvicorn, `ddgs` (DuckDuckGo search), the
`openai` SDK pointed at Groq, PayPal REST APIs (OAuth2 + Orders v2),
[Channel3](https://trychannel3.com) for real-time product discovery,
HMAC-SHA256 chained audit log, Server-Sent Events for live streaming, an
in-process (or standalone-worker) scheduler for recurring delegated tasks.

**Frontend:** Next.js 15 (App Router, TypeScript), Tailwind CSS v4,
`next-themes`, AG Grid Enterprise (the Commerce Ledger / Agent Operations
Console: row grouping, aggregation, status bar, set filters), used without a
license key per AG Grid's own sanctioned guidance for hackathon use (shows
the standard unlicensed watermark and a console warning, by design),
[Bryntum Scheduler](https://bryntum.com/products/scheduler/) (the Agent
Operations Schedule timeline, likewise an unlicensed trial build), Lucide
React.

## Beyond the core: how each integration earns its place

Every addition here extends the one product, delegated financial authority
for AI agents, instead of bolting on an unrelated feature. None of them
changes who is allowed to authorize money: that is still, always, the
deterministic policy engine in `backend/app/guardrails/`.

- **AG Grid: Agent Operations Console** (`/ledger`). The Commerce Ledger is
  a full AG Grid Enterprise operations grid over real transactions: row
  grouping (by agent, by outcome), aggregation, a status bar, set filters,
  column visibility, CSV export, and a row-click evidence-chain side panel
  showing the real Agent Proposed → Policy Evaluated → PayPal Executed →
  Audit Verified timeline for that transaction, with live links to the
  original listing and the full audit trail.
- **Channel3: real product discovery** (`backend/app/search/channel3.py`).
  The agent's research step can search Channel3's live product graph for
  real merchants, prices, and availability instead of relying solely on raw
  web search snippets. If Channel3 is not configured or a search genuinely
  fails, the UI shows that failure. It never falls back to an invented
  product.
- **Bryntum: Agent Operations Schedule** (`/schedule`). Standing delegated
  instructions ("renew this subscription every month if it's still under
  $100") are real, persisted schedules. A backend poll loop
  (`backend/app/scheduler.py`) fires each one, when due, through the exact
  same research → policy → PayPal pipeline as an on-demand task. Every
  occurrence is independently evaluated, not a fire-and-forget cron stub.
  The Bryntum timeline plots one real event per past firing, colored by its
  real outcome (completed, blocked/failed, cancelled, in progress), plus a
  single dashed "next run" marker per live schedule at its real
  `next_run_at`. Nothing about the timeline is a synthetic repeat pattern;
  every event you see corresponds to a real row in the database.
- **APIMatic: the PayPal integration itself** (`docs/APIMATIC.md`). The
  PayPal client (`backend/app/paypal/`) was migrated off a hand-rolled OAuth2
  + httpx REST client onto PayPal's own official, APIMatic-generated Server
  SDK (`paypal-server-sdk`), installed and built against using APIMatic's
  Context Plugin: the mechanism that feeds a coding agent the SDK's real,
  grounded facts instead of letting it guess PayPal's API from training
  data. Live-testing the migration against real Sandbox immediately caught
  a genuine requirement (`PayPal-Request-Id`) the old client had silently
  missed. See `docs/APIMATIC.md` for the full trail, including the dead end
  in the hackathon slide's example repo and the real one that replaced it.
- **Render: deployment configuration** (`render.yaml`, `docker-compose.yml`).
  Config only: this project was not deployed to a live Render account from
  this environment. The blueprint and compose files describe exactly how it
  would run, including an honestly-documented optional topology for running
  the scheduler as its own process.

## Project structure

```text
auctara/
├── backend/            FastAPI service (agent orchestration, policy engine,
│                       PayPal client, Channel3 search, scheduler, audit
│                       trail, SSE, SQLite)
│   └── worker.py       Standalone entrypoint for running the Agent
│                       Operations Schedule poll loop as its own process
├── frontend/           Next.js 15 app (dashboard, agents, ledger, schedule,
│                       policies, audit, etc.)
├── docs/
│   ├── APIMATIC.md          How the PayPal client was rebuilt on PayPal's official APIMatic-generated SDK
│   ├── NEGATIVE_TESTING.md  How the opt-in "Sandbox QA" PayPal decline demo works, and why it doesn't break "zero mock data"
│   ├── TOOLS_USED.md        Devpost "tools used" draft, per sponsor technology
│   ├── DEMO_SCRIPT.md       Shot-by-shot demo video script
│   ├── DEVPOST_SUBMISSION.md  Full written submission draft (inspiration, what it does, how it was built, etc.)
│   └── openapi.json         The live OpenAPI spec, pulled from the running backend
├── .env.example
├── docker-compose.yml  Local multi-container topology (+ optional separate worker profile)
├── render.yaml         Render Blueprint (config only, not deployed from this environment)
└── README.md
```

See `backend/app/` for the module layout described in the design spec
(`api/routes`, `agent/`, `guardrails/`, `search/`, `paypal/`, `exchange/`,
`streaming/`, `database/`, `audit/`, `scheduler.py`).

## Setup

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # then fill in the values below
python run.py             # http://localhost:8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev                # http://localhost:3000, proxies /api/* to the backend
```

The frontend calls its own `/api/*` routes, which `next.config.ts` rewrites
to `BACKEND_INTERNAL_URL` (defaults to `http://localhost:8000`). The browser
never talks to the backend directly, and no secret ever reaches client code.

### 3. Environment variables

Copy `.env.example` to `backend/.env` and fill in:

| Variable | Purpose |
|---|---|
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | Sandbox REST app credentials from the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/applications) |
| `PAYPAL_ENVIRONMENT` | `sandbox` (default) or `live` |
| `PAYPAL_TEST_CARD_*` | Optional. A card generated from **your** Sandbox account's *Testing Tools → Generate credit cards*. If set, the agent can authorize a payment directly (no buyer redirect), the realistic analog of a corporate card already on file. If left blank, Auctara falls back to the standard PayPal Checkout approve-link flow, where the frontend shows an **Approve on PayPal** button that opens the real Sandbox checkout. |
| `GROQ_API_KEY` | From [console.groq.com/keys](https://console.groq.com/keys) |
| `GROQ_MODEL` | Any Groq-hosted model id, e.g. `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` |
| `CHANNEL3_API_KEY` | Optional. From [trychannel3.com](https://trychannel3.com/sign-up/developer) (free, 1,000 searches/month). Without it, Channel3 product search is skipped and the agent falls back to plain web research. It never returns a fabricated product |
| `AUDIT_HMAC_SECRET` | Long random string used to chain-sign the audit log |
| `FRONTEND_URL` | Used for PayPal return/cancel URLs and CORS |
| `RUN_SCHEDULER_INPROCESS` | Default `true`. Whether this process also polls and fires due Agent Operations Schedule tasks; set `false` only if running `python worker.py` as a separate process instead |

### 4. PayPal Sandbox

1. Create a Sandbox app at developer.paypal.com → get a Client ID/Secret.
2. Optionally generate a Sandbox test card under *Testing Tools* and set the
   `PAYPAL_TEST_CARD_*` variables for frictionless two-phase (authorize →
   verify → capture/void) demos without a buyer redirect.
3. Without a test card, Auctara still works end-to-end. It just shows an
   **Approve on PayPal** link that opens the real PayPal Sandbox checkout in
   a new tab for a Sandbox test buyer to approve, exactly like a production
   PayPal Checkout integration.

### 5. Groq

Create a key at [console.groq.com/keys](https://console.groq.com/keys) and
set `GROQ_API_KEY`. The model is never hard-coded. Set `GROQ_MODEL` to
whichever Groq-hosted model you want the agent to reason with (this project
runs on `openai/gpt-oss-120b`).

## Running the tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

215 tests. Covers: the deterministic policy engine (allow/approval/block
thresholds, daily/monthly limits, velocity, category rules, price-variance
tolerance), the transaction state machine (valid/invalid transitions,
blocked/approval/success/failure flows), the HMAC audit chain (canonical
serialization, tamper detection), budget-ledger atomicity and its date
attribution (a transaction's full ledger effect is counted on the day the
transaction itself was created, not whichever day an individual
reserve/release leg happens to post — covered by a dedicated
day-boundary-crossing regression test), the real APIMatic-generated PayPal
Server SDK order/authorize/capture/void flows, idempotency-key behavior,
the PayPal fee/net (`seller_receivable_breakdown`) capture breakdown, and
error translation, the agent's clarification (`NEEDS_INPUT`) flow and
zero-amount proposal validation guard, the Agent Operations Schedule
(recurrence math, due-schedule firing through the real task pipeline,
inactive-agent safety, run-history retrieval), stale-transaction
reconciliation safety nets, and the core FastAPI routes (including a check
that a missing AI key fails the task visibly instead of silently faking a
result).

## Demo

```text
Live Demo:
[URL]   <!-- fill in after deploying, e.g. via render.yaml -->

Demo Video:
[URL]   <!-- fill in after recording -->
```

See [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) for the shot-by-shot script
used to record the demo video — every beat in it is a real action against
the running app, not a narrated mockup. See
[`docs/DEVPOST_SUBMISSION.md`](docs/DEVPOST_SUBMISSION.md) for the full
written submission draft (inspiration, what it does, how it was built,
challenges, accomplishments, what's next).

## Honest notes on this being a hackathon project

- This runs comfortably on a single small instance; there is no attempt at
  "production-grade" infrastructure. SQLite with WAL mode is intentionally
  simple rather than a distributed financial ledger.
- Free-tier Render services cold-start: the first request after idling can
  take 30–60 seconds while the instance spins back up.
- The agent's two-phase payment flow uses PayPal's Orders v2 API with
  `intent=AUTHORIZE`, so a price-variance or policy failure after order
  creation results in a real `void`, not merely "we didn't click capture."
