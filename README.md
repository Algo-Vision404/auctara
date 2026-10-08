# AgentAuth

### Delegated Spending Authority for AI Agents

> **Let AI agents act. Keep financial authority under your control.**

## What is AgentAuth?

AgentAuth lets you delegate a real purchasing task to an AI agent — "find the
cheapest annual project-management software for my team and buy it if it's
under $80" — while keeping every dollar of authority under deterministic,
backend-enforced policy. The agent can research the live web, compare real
merchants and prices, and draft a purchase proposal. It can never authorize
that proposal itself. Every transaction is independently evaluated by a
rule-based policy engine, optionally routed to you for human approval, and
only then executed through the real PayPal Sandbox Orders API.

AgentAuth is not a shopping assistant, a PayPal wallet, or a banking app. It
is the authorization layer that sits between an autonomous agent and real
money.

## Problem

AI agents are becoming capable of taking actions on behalf of users,
including commerce. As agents get more capable, the open question is no
longer "can an agent buy something" but "who decides how much authority it
has, and how is that boundary enforced."

## Solution

AgentAuth provides delegated spending authority with deterministic financial
policies:

- Users describe an agent's purpose and spending authority in plain English.
- AgentAuth converts that into an explicit, numeric policy (autonomous limit,
  approval threshold, daily/monthly caps, velocity limits, blocked/allowed
  categories).
- The agent proposes; a separate, deterministic backend policy engine
  decides `ALLOW`, `APPROVAL_REQUIRED`, or `BLOCK`.
- PayPal Sandbox only ever executes a transaction the policy engine has
  authorized (and, where required, a human has approved).
- Every financial event is written to an HMAC-SHA256 chained audit log.

## Architecture

```text
User
 ↓
Natural-language task
 ↓
AI Agent (OpenRouter, tool-calling: search_web, get_exchange_rate, create_purchase_proposal)
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
decides a financial outcome — it only renders what the backend already
decided.

## Zero mock data

Every number in the UI comes from a real backend operation:

- Web research uses the live `ddgs` (DuckDuckGo) search API. If it fails, the
  UI shows `SEARCH_FAILED` and the task fails — it never substitutes a fake
  merchant.
- AI reasoning calls OpenRouter with the model set by `OPENROUTER_MODEL`.
- Exchange rates come from `https://open.er-api.com/v6/latest/USD`, fetched
  live (no hard-coded rates).
- PayPal order creation, authorization, capture, and void all call the real
  PayPal Sandbox REST API. If PayPal is not configured, the app says so
  explicitly instead of pretending a payment succeeded.
- All dashboard numbers, activity events, and audit records are read from
  SQLite rows written by the above real operations.
- Product discovery (Channel3) returns real merchants, prices, and product
  images, or a real, visible failure — never a hard-coded fallback item.
- Scheduled/recurring tasks (the Agent Operations Schedule) are fired by a
  real poll loop through the same pipeline as an on-demand task; nothing
  about a "next run" is simulated.

## Technology

**Backend:** Python 3.11+, FastAPI, SQLite (WAL mode, `BEGIN IMMEDIATE` for
budget reservations), httpx, Uvicorn, `ddgs` (DuckDuckGo search), the
`openai` SDK pointed at OpenRouter, PayPal REST APIs (OAuth2 + Orders v2),
[Channel3](https://trychannel3.com) for real-time product discovery,
HMAC-SHA256 chained audit log, Server-Sent Events for live streaming, an
in-process (or standalone-worker) scheduler for recurring delegated tasks.

**Frontend:** Next.js 15 (App Router, TypeScript), Tailwind CSS v4,
`next-themes`, AG Grid Community (the Commerce Ledger / Agent Operations
Console), [Bryntum Scheduler](https://bryntum.com/products/scheduler/) (the
Agent Operations Schedule timeline), Lucide React.

## Beyond the core: how each integration earns its place

Every addition here extends the one product — delegated financial authority
for AI agents — instead of bolting on an unrelated feature. None of them
changes who is allowed to authorize money: that is still, always, the
deterministic policy engine in `backend/app/guardrails/`.

- **AG Grid — Agent Operations Console** (`/ledger`). The Commerce Ledger is
  a full operations grid over real transactions: filtering, column
  visibility, CSV export, and a row-click evidence-chain side panel showing
  the real Agent Proposed → Policy Evaluated → PayPal Executed → Audit
  Verified timeline for that transaction, with live links to the original
  listing and the full audit trail.
- **Channel3 — real product discovery** (`backend/app/search/channel3.py`).
  The agent's research step can search Channel3's live product graph for
  real merchants, prices, and availability instead of relying solely on raw
  web search snippets. If Channel3 is not configured or a search genuinely
  fails, the UI shows that failure — it never falls back to an invented
  product.
- **Bryntum — Agent Operations Schedule** (`/schedule`). Standing delegated
  instructions ("renew this subscription every month if it's still under
  $100") are real, persisted schedules. A backend poll loop
  (`backend/app/scheduler.py`) fires each one, when due, through the exact
  same research → policy → PayPal pipeline as an on-demand task — every
  occurrence is independently evaluated, not a fire-and-forget cron stub.
  The frontend visualizes it with Bryntum's native recurrence engine
  (`FREQ=DAILY/WEEKLY/MONTHLY`), not a hand-rolled calendar.
- **APIMatic — API developer experience** (`docs/APIMATIC.md`). The backend's
  real OpenAPI spec (tagged by domain: agents, tasks, transactions, policies,
  audit, schedules) is exported to `docs/openapi.json` and documented as the
  input to APIMatic's SDK generation and developer-portal tooling, so a third
  party can integrate with AgentAuth's policy/transaction API without
  hand-rolling an HTTP client.
- **Render — deployment configuration** (`render.yaml`, `docker-compose.yml`).
  Config only: this project was not deployed to a live Render account from
  this environment. The blueprint and compose files describe exactly how it
  would run, including an honestly-documented optional topology for running
  the scheduler as its own process.

## Project structure

```text
agentauth/
├── backend/            FastAPI service (agent orchestration, policy engine,
│                       PayPal client, Channel3 search, scheduler, audit
│                       trail, SSE, SQLite)
│   └── worker.py       Standalone entrypoint for running the Agent
│                       Operations Schedule poll loop as its own process
├── frontend/           Next.js 15 app (dashboard, agents, ledger, schedule,
│                       policies, audit, etc.)
├── docs/
│   ├── APIMATIC.md     How the real OpenAPI spec maps to APIMatic SDK/portal generation
│   └── openapi.json    The live OpenAPI spec, pulled from the running backend
├── .env.example
├── docker-compose.yml  Local multi-container topology (+ optional separate worker profile)
├── render.yaml         Render Blueprint (config only — not deployed from this environment)
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
| `PAYPAL_TEST_CARD_*` | Optional. A card generated from **your** Sandbox account's *Testing Tools → Generate credit cards*. If set, the agent can authorize a payment directly (no buyer redirect) — the realistic analog of a corporate card already on file. If left blank, AgentAuth falls back to the standard PayPal Checkout approve-link flow, where the frontend shows an **Approve on PayPal** button that opens the real Sandbox checkout. |
| `OPENROUTER_API_KEY` | From [openrouter.ai](https://openrouter.ai/) |
| `OPENROUTER_MODEL` | Any OpenRouter model id, e.g. `openai/gpt-4o-mini`, `anthropic/claude-3.5-haiku` |
| `CHANNEL3_API_KEY` | Optional. From [trychannel3.com](https://trychannel3.com/sign-up/developer) (free, 1,000 searches/month). Without it, Channel3 product search is skipped and the agent falls back to plain web research — never a fabricated product |
| `AUDIT_HMAC_SECRET` | Long random string used to chain-sign the audit log |
| `FRONTEND_URL` | Used for PayPal return/cancel URLs and CORS |
| `RUN_SCHEDULER_INPROCESS` | Default `true`. Whether this process also polls and fires due Agent Operations Schedule tasks; set `false` only if running `python worker.py` as a separate process instead |

### 4. PayPal Sandbox

1. Create a Sandbox app at developer.paypal.com → get a Client ID/Secret.
2. Optionally generate a Sandbox test card under *Testing Tools* and set the
   `PAYPAL_TEST_CARD_*` variables for frictionless two-phase (authorize →
   verify → capture/void) demos without a buyer redirect.
3. Without a test card, AgentAuth still works end-to-end — it just shows an
   **Approve on PayPal** link that opens the real PayPal Sandbox checkout in
   a new tab for a Sandbox test buyer to approve, exactly like a production
   PayPal Checkout integration.

### 5. OpenRouter

Create a key at openrouter.ai and set `OPENROUTER_API_KEY`. The model is
never hard-coded — set `OPENROUTER_MODEL` to whichever model you want the
agent to reason with.

## Running the tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

44 tests. Covers: the deterministic policy engine (allow/approval/block
thresholds, daily/monthly limits, velocity, category rules, price-variance
tolerance), the transaction state machine (valid/invalid transitions,
blocked/approval/success/failure flows), the HMAC audit chain (canonical
serialization, tamper detection), budget-ledger atomicity, mocked PayPal
order/authorize/capture/void flows, the Agent Operations Schedule
(recurrence math, due-schedule firing through the real task pipeline,
inactive-agent safety), and the core FastAPI routes (including a check that
a missing AI key fails the task visibly instead of silently faking a
result).

## Demo

```text
Live Demo:
[URL]

Demo Video:
[URL]
```

## Honest notes on this being a hackathon project

- This runs comfortably on a single small instance; there is no attempt at
  "production-grade" infrastructure. SQLite with WAL mode is intentionally
  simple rather than a distributed financial ledger.
- Free-tier Render services cold-start: the first request after idling can
  take 30–60 seconds while the instance spins back up.
- The agent's two-phase payment flow uses PayPal's Orders v2 API with
  `intent=AUTHORIZE`, so a price-variance or policy failure after order
  creation results in a real `void`, not merely "we didn't click capture."
