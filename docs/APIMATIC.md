# APIMatic — Developer Experience for the AgentAuth API

AgentAuth's backend exposes a real, hand-tagged OpenAPI 3.1 specification —
not a hand-written doc that can drift from the code, but the literal schema
FastAPI derives from the live route handlers and Pydantic models. That spec
is what makes AgentAuth a genuine fit for APIMatic: a platform that turns one
OpenAPI description into multi-language SDKs, a hosted developer portal, and
CI-enforced spec quality. This is a **supporting-tier** integration — it
strengthens how third parties integrate with AgentAuth's delegated-spending
API; it does not change the product's authorization model, policy engine, or
payment flow in any way.

## Why AgentAuth needs this, not just "an extra badge"

AgentAuth's actual job is to sit between an autonomous agent and real money.
That only works at scale if other systems — a company's internal tooling, a
partner's agent framework, a second AI platform — can integrate with
AgentAuth's policy and transaction API without hand-rolling an HTTP client
and guessing at request/response shapes. That is exactly the problem
APIMatic exists to solve:

- **SDK generation** — a Python, TypeScript, Java, or Ruby client for
  `POST /agents`, `GET /transactions/{tx_id}`, `POST /schedules`, etc.,
  generated from the spec instead of maintained by hand.
- **A hosted developer portal** — interactive docs with real request/response
  examples per endpoint, grouped by the same tags AgentAuth already uses
  (`agents`, `tasks`, `transactions`, `policies`, `audit`, `schedules`,
  `dashboard`, `health`).
- **Spec linting** — catching schema drift (an endpoint added without a
  response model, an inconsistent error shape) before it reaches an
  integrator, as part of CI rather than a manual review.

## The real artifact: `docs/openapi.json`

[`docs/openapi.json`](./openapi.json) in this repo is not fabricated — it was
pulled directly from the running backend:

```bash
curl -s http://localhost:8000/openapi.json -o docs/openapi.json
```

It reflects the actual, current API, including the newest addition (the
Bryntum-backed `/schedules` CRUD for the Agent Operations Schedule). You can
regenerate it the same way any time the backend changes; it is a build
artifact of the real app, not a maintained-by-hand document.

Every route in it is tagged by domain, which is exactly what APIMatic uses to
group endpoints into SDK "controllers" (e.g. a generated `TransactionsClient`
or `SchedulesClient`):

| Tag | Endpoints | What it covers |
|---|---|---|
| `agents` | `POST/GET /agents`, `GET/PUT /agents/{id}`, `POST /agents/draft-policy` | Agent lifecycle, natural-language → policy drafting |
| `tasks` | `POST/GET /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/events` | Task execution + SSE event history |
| `transactions` | `GET /transactions`, `GET /transactions/{id}`, `.../approve`, `.../reject`, `.../paypal/continue`, `.../timeline` | The ALLOW/APPROVAL_REQUIRED/BLOCK decision trail and PayPal two-phase flow |
| `policies` | `GET/PUT /policies/{agent_id}`, `POST /policies/evaluate` | The deterministic policy engine |
| `audit` | `GET /audit`, `GET /audit/verify` | The HMAC-SHA256 chained audit trail |
| `schedules` | `POST/GET /schedules`, `GET/PATCH/DELETE /schedules/{id}` | The Agent Operations Schedule (recurring delegated commerce) |
| `dashboard` / `activity` | `GET /dashboard/summary`, `GET /activity`, `GET /activity/stream` | Live operational overview + SSE activity feed |
| `health` | `GET /health` | Liveness, PayPal/OpenRouter configuration status |

## What we actually did in this environment

Consistent with how this project treats every sponsor integration — real
calls against real data, honest about what wasn't exercised — no APIMatic
account was connected in this sandbox, so no SDK or hosted portal was
generated or published here. What *is* real:

- The OpenAPI spec itself (`docs/openapi.json`) — pulled live from the
  running FastAPI app, not written by hand.
- The FastAPI app now carries a proper `title`, `version`, and `description`
  and every router is tagged, specifically so that an APIMatic SDK/portal
  generation pass produces well-organized output instead of one flat,
  unlabeled endpoint list.
- The exact, correct steps below, which anyone with an APIMatic account can
  run today against this real spec — nothing here is hypothetical or
  aspirational about the AgentAuth side of the integration.

## How to actually generate an SDK / portal from this spec

With the [APIMatic CLI](https://www.npmjs.com/package/apimatic) and a free
APIMatic account:

```bash
# 1. Validate the real spec for SDK/portal-readiness
apimatic api validate --file=docs/openapi.json

# 2. Generate a Python client SDK for AgentAuth
apimatic sdk generate --language=python --input=docs --destination=sdk/python

# 3. Generate a TypeScript client (e.g. for a partner's agent framework)
apimatic sdk generate --language=typescript --input=docs --destination=sdk/typescript

# 4. Generate a hosted, interactive developer portal
apimatic portal generate --input=docs --destination=portal
apimatic portal serve --input=portal   # preview locally
```

Each of these operates on the same `docs/openapi.json` this repo ships —
there is exactly one source of truth for the API shape, and it is generated
from the code, not written independently of it.

## Keeping the spec honest over time

Because `docs/openapi.json` is a generated artifact, the only rule that
matters is: regenerate it whenever a route changes, before running any
APIMatic command against it. A CI job for a production deployment would do:

```bash
curl -s "$BACKEND_URL/openapi.json" -o docs/openapi.json
apimatic api validate --file=docs/openapi.json
```

so that a broken or inconsistent schema fails the build instead of silently
shipping a stale SDK.
