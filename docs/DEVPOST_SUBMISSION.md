# Devpost Submission Draft — Auctara

Copy each section into the matching Devpost field. Every claim below is
backed by real code/tests in this repo — see the file/doc pointers inline
so a judge can verify anything against the actual source, not just the
pitch.

---

## Tagline

**Delegated spending authority for AI agents — PayPal only ever executes
what a deterministic policy engine has actually authorized.**

---

## Inspiration

AI agents can already browse, compare prices, and decide what to buy. The
question that matters now isn't "can an agent complete a purchase" — it's
"who decides how much financial authority it has, and how is that boundary
enforced." Most agentic-commerce demos answer that with one of two
extremes: hand the agent a payment method directly (no real boundary at
all — the agent's own judgment, or a bad prompt, or a prompt-injected web
page, *is* the spending limit), or route every single purchase through a
human (safe, but it isn't delegation — it's an approval queue with an
AI-written description attached, and it doesn't scale to standing
instructions like "renew this subscription every month if it's still
under $100"). Auctara is our answer to the gap in the middle: an agent
that can act autonomously, but only ever within a boundary it cannot move
itself.

## What it does

Auctara lets a user describe an agent's purpose and spending authority in
plain English ("find the cheapest annual project-management software for
my team and buy it if it's under $80"). That description is converted into
an explicit, numeric policy: a hard per-transaction ceiling, an approval
threshold above which a human must click yes, daily/monthly caps, velocity
limits, and an allowed/blocked category list. The agent can then research
the live web (or Channel3's real product graph) and draft a purchase
proposal — but it never has the authority to pay. A separate, deterministic
backend policy engine (plain Python, not a second LLM call) evaluates every
proposal and decides `ALLOW`, `APPROVAL_REQUIRED`, or `BLOCK`. Only a
decision that engine actually authorized — and, where required, a human
approved — ever reaches PayPal. A real two-phase PayPal Sandbox flow
(`create order (intent=AUTHORIZE)` → `authorize` → re-verify the authorized
amount against the proposal → `capture` on match / `void` on drift) then
executes it, and every financial event is written to an HMAC-SHA256
chained, tamper-evident audit log. A Commerce Ledger (AG Grid) and an Agent
Operations Schedule (Bryntum, for recurring delegated instructions) round
out the product as something you'd actually operate, not just a one-shot
demo flow.

## How we built it

- **Backend:** FastAPI + SQLite (WAL mode, `BEGIN IMMEDIATE` for atomic
  budget reservations), Groq for the agent's tool-calling research loop
  (`search_web`, `get_exchange_rate`, `create_purchase_proposal`), a
  rule-based policy engine completely independent of the LLM, Server-Sent
  Events for the live activity feed, and a backend poll loop for recurring
  schedules.
- **PayPal:** migrated off a hand-rolled OAuth2 + `httpx` REST client onto
  PayPal's own official, APIMatic-generated `paypal-server-sdk`, installed
  and rewritten using APIMatic's Context Plugin so the coding agent doing
  the migration worked from the SDK's real, grounded method signatures
  instead of guessing PayPal's API shape from training data (see
  `docs/APIMATIC.md`). That migration immediately surfaced a real,
  previously-silent bug: a missing `PayPal-Request-Id` idempotency header
  on card-present orders.
- **Frontend:** Next.js 15 (App Router, TypeScript), Tailwind CSS v4, AG
  Grid Enterprise for the Commerce Ledger, Bryntum Scheduler for the Agent
  Operations Schedule.
- **Guardrails that are actually enforced, not advisory:** a specificity
  gate that forces a vague proposal back to the agent for clarification
  before it can even reach policy evaluation (an agent asked to "buy
  software" can't just pick something arbitrary and call it done); a
  price-variance check that voids a real PayPal authorization if the
  confirmed price drifts outside the agent's tolerance; velocity limits
  enforced at authorization time; a stale-transaction reconciliation
  safety net that resolves anything stuck mid-flight (server restart,
  expired PayPal order) into a clean terminal state automatically, rather
  than leaving it stuck or silently retrying forever.

## Challenges we ran into

- **A real financial-safety bug, not a cosmetic one.** The dashboard's
  "spent today" figure could go negative whenever a transaction's
  reserve-then-release ledger legs straddled a day boundary — because the
  function summed ledger rows by each row's own timestamp instead of the
  owning transaction's creation date. That same function fed the live
  policy engine's daily/monthly limit check, so a negative "spent" could
  have inflated an agent's perceived remaining budget. We traced it to the
  exact two ledger rows that exposed it, fixed the date-attribution logic,
  and added a regression test that reproduces the midnight-crossing
  scenario directly.
- **PayPal's own fee breakdown wasn't surfaced.** An audit against bug
  reports other teams in this same hackathon publicly shared (missing
  idempotency keys, SDK default timeout of 0, over-broad exception
  handling, stale wallet-context defaults) showed our integration already
  avoided every one of them — except we weren't surfacing PayPal's real
  `seller_receivable_breakdown` (gross/fee/net) from a completed capture.
  Fixed and now shown on the transaction detail page, backed by its own
  schema migration and tests.
- **Infrastructure, not logic, was the recurring failure mode.** Backend
  dependencies and frontend `node_modules` got wiped mid-session more than
  once (a sandbox-snapshot-size artifact, not a code bug) — each time, the
  215-test suite came back green immediately after a clean reinstall,
  which was itself useful evidence the core logic was never the problem.

## Accomplishments that we're proud of

- A policy engine that is genuinely deterministic and auditable — not an
  LLM "vibe check" dressed up as a safety feature.
- 215 passing tests covering the policy engine, the transaction state
  machine, the HMAC audit chain, budget-ledger atomicity (including the
  day-boundary edge case above), the real PayPal SDK's order/authorize/
  capture/void flows and idempotency behavior, and the scheduler.
- A UX detail that sounds small but matters: PayPal approval opens in a
  new tab and the app polls and resolves itself automatically — no
  copy-pasting a link back and forth, no manual refresh.
- Catching and fixing a real financial-safety bug during final testing,
  with a regression test proving it stays fixed — exactly the kind of
  thing a deterministic, test-covered financial system should be able to
  do.

## What we learned

That the hard part of "let an agent spend money" was never the AI — it was
building a boundary around it that doesn't trust the AI's own judgment
about where that boundary is, and proving that boundary holds under real
edge cases (day/month rollovers, expired PayPal orders, interrupted
mid-flight tasks, concurrent duplicate requests), not just the happy path.

## What's next

- Multi-currency policies and FX-aware daily/monthly limits.
- Org-level delegation (a team admin setting policy for multiple agents
  acting on shared or per-member budgets).
- Webhook-driven PayPal status updates instead of polling, once a stable
  public endpoint is available for Sandbox webhooks.
- A real deployed instance (see `render.yaml`) and recorded demo video —
  see `docs/DEMO_SCRIPT.md`.

## Built With

FastAPI · Python · SQLite · Groq · PayPal Orders v2 (via the official
APIMatic-generated `paypal-server-sdk`) · APIMatic Context Plugin ·
Channel3 · Next.js 15 · TypeScript · Tailwind CSS · AG Grid Enterprise ·
Bryntum Scheduler · Server-Sent Events · HMAC-SHA256
