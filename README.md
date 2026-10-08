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

## Technology

**Backend:** Python 3.11+, FastAPI, SQLite (WAL mode, `BEGIN IMMEDIATE` for
budget reservations), httpx, Uvicorn, `ddgs` (DuckDuckGo search), the
`openai` SDK pointed at OpenRouter, PayPal REST APIs (OAuth2 + Orders v2),
HMAC-SHA256 chained audit log, Server-Sent Events for live streaming.

**Frontend:** Next.js 15 (App Router, TypeScript), Tailwind CSS v4,
`next-themes`, AG Grid Community, Lucide React.

## Project structure

```text
agentauth/
├── backend/            FastAPI service (agent orchestration, policy engine,
│                       PayPal client, audit trail, SSE, SQLite)
├── frontend/           Next.js 15 app (dashboard, agents, ledger, audit, etc.)
├── .env.example
├── docker-compose.yml
├── render.yaml
└── README.md
```

See `backend/app/` for the module layout described in the design spec
(`api/routes`, `agent/`, `guardrails/`, `search/`, `paypal/`, `exchange/`,
`streaming/`, `database/`, `audit/`).

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
| `AUDIT_HMAC_SECRET` | Long random string used to chain-sign the audit log |
| `FRONTEND_URL` | Used for PayPal return/cancel URLs and CORS |

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

Covers: the deterministic policy engine (allow/approval/block thresholds,
daily/monthly limits, velocity, category rules, price-variance tolerance),
the transaction state machine (valid/invalid transitions, blocked/approval/
success/failure flows), the HMAC audit chain (canonical serialization,
tamper detection), budget-ledger atomicity, and the core FastAPI routes
(including a check that a missing AI key fails the task visibly instead of
silently faking a result).

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
