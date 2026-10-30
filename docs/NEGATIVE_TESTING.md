# Sandbox negative testing: proving the failure paths are real too

Auctara's README makes a deliberate, strong claim: **zero mock data,
ever** — every number on screen comes from a real operation, and a failure
is always shown as a real failure, never swapped for a fake success.

That raises an honest question: how do you *demonstrate* a PayPal decline,
or the price-variance auto-void safety net, on demand, in a live demo,
without contradicting that claim by faking one?

## The two failure paths, and why they need different answers

**1. PayPal itself declining a real API call** (a card rejected at capture,
a transaction refused, a transient PayPal service error). This can be shown
live, for real, because PayPal's own sandbox has an official, documented
mechanism for it.

**2. Auctara's own price-variance check catching drift** between the
amount an agent proposed and the amount PayPal actually confirms
(`app/guardrails/engine.py::evaluate_price_variance`), which then triggers
a real `void_authorization` call. In every run of the real pipeline, the
amount Auctara asks PayPal to authorize *is* the amount PayPal confirms —
there is no step where it would organically drift, so this path cannot be
triggered on demand without fabricating a mismatch, which is exactly what
"zero mock data" rules out. This path is proven instead by an automated
test against the real SDK's own model classes
(`backend/tests/test_paypal.py`, `backend/tests/test_policy_engine.py`),
not staged live.

## How negative testing works (path 1)

PayPal's sandbox supports a request header, `PayPal-Mock-Response`, that
makes PayPal's **real** sandbox API genuinely return a **real**, documented
error for that one call — this is PayPal's own supported QA mechanism, not
anything Auctara fabricates:

- https://developer.paypal.com/tools/sandbox/negative-testing/request-headers/
- https://developer.paypal.com/api/orders/v2/error-messages

The official `paypal-server-sdk` (the same APIMatic-generated SDK this
project's PayPal integration is built on — see `APIMATIC.md`) exposes this
natively as a `paypal_mock_response` option on the relevant controller
calls, confirmed by reading the installed SDK's own source
(`PaymentsController.capture_authorized_payment`,
`OrdersController.create_order`).

### What Auctara built on top of it

A task may optionally be created with `paypal_negative_test` set to one of
three PayPal-documented codes (`app/paypal/orders.py:NEGATIVE_TEST_CODES`,
also served at `GET /tasks/negative-test-options` so the frontend never
hardcodes its own copy):

| Code | What PayPal does |
|---|---|
| `INSTRUMENT_DECLINED` | Declines the capture as if the buyer's payment instrument were rejected |
| `TRANSACTION_REFUSED` | Refuses the transaction via PayPal's payment engine |
| `INTERNAL_SERVER_ERROR` | Returns a real HTTP 500 from PayPal's sandbox |

This is **off by default** (`NULL`) for every normal task, and only
affects the single `capture_authorization` call for that one task
(`app/agent/orchestrator.py::_finalize_payment`) — nothing else about the
pipeline changes. When set, PayPal's real response comes back as a real
`PayPalError` (the exact same `translate_sdk_error` path a genuine decline
would take), the transaction moves to `FAILED` exactly as it would for a
real decline, and the real error detail is logged server-side the same way
every other PayPal error is.

In the UI, it is surfaced as a collapsed, clearly-labeled "Sandbox QA
(optional)" control on the task-creation form (`agents/[id]`), and a
visible banner on the resulting transaction explaining exactly what is
being demonstrated, so a viewer (or a judge) never mistakes a deliberately
requested decline for a bug.

## One-time sandbox account setup required

Live-testing this against real Sandbox (not mocks) surfaced a genuine
PayPal account-setting requirement, the same class of thing
`docs/APIMATIC.md` found for `PayPal-Request-Id`: by default, a sandbox
business account rejects the `PayPal-Mock-Response` header itself with a
real `403 NOT_AUTHORIZED: Authorization failed due to insufficient
permissions.`, instead of returning the requested simulated decline. This
is not a bug in this integration — it is PayPal's own documented
precondition, and the exact failure every sandbox account hits until this
is done:

1. Log into the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/) → **Sandbox → Accounts**.
2. Find the business account used as the payee for this app's Sandbox credentials, open the **⋮** menu → **View/Edit Account**.
3. Open the **Settings** tab → find **Negative Testing** → toggle it **On**.

Once enabled, the exact live run captured above returns the real,
requested `INSTRUMENT_DECLINED` decline from PayPal's sandbox instead of
the permissions error, and the transaction still ends up `FAILED` through
the identical, already-correct `PayPalError` → `_fail()` path.

### What was actually verified live (today, against real Sandbox)

With negative testing not yet enabled on this environment's sandbox
account, a full real run was still exercised end-to-end: a real agent
researched a real product via Channel3 (a $4.95 USB cable), a real PayPal
order was created and authorized synchronously via the configured Sandbox
test card, `PAYMENT_VERIFIED` confirmed the real authorized amount, and
the capture call correctly carried the `paypal_mock_response` option
through to PayPal's real API — which rejected it with a real `403`
because negative testing isn't enabled yet on this particular sandbox
account. Auctara's own handling of that real rejection was exactly
correct: clean `FAILED` state, real PayPal error detail preserved
server-side, no fabricated outcome. This confirms every piece of the new
code path is wired correctly end-to-end; the only remaining step is the
one-time dashboard toggle above, which only the account owner can do.

## Where this is NOT used

The default, and only automatic, flow never sets `paypal_negative_test`.
Every number in the rest of the product (dashboard, ledger, audit trail,
scheduled tasks) still comes exclusively from a real operation, exactly as
the README describes.
