# APIMatic: building the PayPal integration on a Context Plugin, not a guess

This is a **supporting-tier** integration (dev/infra, like Render): it does
not touch AgentAuth's authorization model, policy engine, or payment state
machine. What it changes is *how the PayPal integration itself was built*:
replacing a hand-rolled REST client with PayPal's own official,
APIMatic-generated Server SDK, installed and used the way APIMatic's
hackathon mechanism intends: by feeding an AI coding agent the SDK's real,
grounded facts instead of letting it guess at PayPal's API from training
data.

## What "Best Use of APIMatic" actually asks for

It is not about generating a developer portal for AgentAuth's own API (an
earlier, mistaken reading of this requirement, reverted). The real
mechanism, per the hackathon's own materials, is APIMatic's **Context
Plugin**: a package of "skills" for Claude Code, Cursor, Codex, and VS Code
that teaches the coding agent to install and use PayPal's real Server SDK
correctly, grounded in the SDK's own generated source and docs, not in
whatever a model remembers about PayPal's API. Qualifying for the prize
means two things:

1. Build the PayPal integration using, or informed by, that plugin.
2. Separately answer a plugin question on the submission form. **A form
   field only the project owner can fill in**; not something achievable from
   inside this codebase, and not attempted here.

## Finding the real plugin

The slide text pasted into this project named an example install command
pointing at a placeholder repo (`paypaldev/server-sdk`) that has no plugin
manifest, so running it fails immediately:

```
$ npx --yes context-plugins install https://github.com/paypaldev/server-sdk context-plugin-preview
paypaldev/server-sdk@main does not look like a plugin. No plugin manifest there.
```

That is a dead end in the slide's own example, not in the mechanism.
Searching turned up the actual hackathon preview repo:
`https://github.com/paypaldev/server-sdk-context-plugin-preview` (marked
explicitly as experimental and hackathon-only, not a long-term PayPal
product). Installing *that* URL works:

```
$ npx --yes context-plugins install https://github.com/paypaldev/server-sdk-context-plugin-preview
Installing 'paypal' from paypaldev/server-sdk-context-plugin-preview@main
  Integrate and consume the APIMatic-generated PayPal Server SDK.
  Bundled skills for csharp, java, php, Python, ruby, TypeScript.
------------------------------------------------------------------------------
[Harnesses]
      Claude Code is not installed (looked in claude on PATH).
      ...
  XX  No supported editor found on this machine.
```

The CLI only installs into one of the four supported coding-agent harnesses
(Claude Code, Cursor, VS Code, Codex), none of which run inside this
project's own sandboxed agent runtime by default. To get past that and
genuinely exercise the plugin rather than stop at a second dead end, Claude
Code was installed directly into the workspace (`npm install -g
@anthropic-ai/claude-code` under a user-writable prefix), and the install
was retried:

```
$ npx --yes context-plugins install https://github.com/paypaldev/server-sdk-context-plugin-preview
[Harnesses]
      Continuing with Claude Code.
      Installing into: Claude Code
[Fetch]
  ✓   Plugin source ready
[Claude Code]
  ✓   Added marketplace 'context-plugins-local'
  ✓   Installed paypal@context-plugins-local (user scope)
  ✓   Installed into: Claude Code
```

This pulled down the real plugin content: eight skills per language
(`python-getting-started`, `python-client-initialization`,
`python-authentication`, `python-calling-endpoints`, `python-models`,
`python-error-handling`, `python-configuration-resilience`,
`python-testing`) across six languages, each grounded in the actual
generated SDK source rather than general PayPal API knowledge.

## What the plugin actually taught, and how it shaped the migration

Reading the installed `python-*` skills (not a model's prior assumptions)
is what drove the rewrite of `backend/app/paypal/`. Concretely, the skills
state, and the installed `paypal-server-sdk==2.4.0` package confirms,
facts a hand-rolled integration has no reason to get right on the first try:

- The client is `PaypalServersdkClient` (package `paypalserversdk`,
  `pip install paypal-server-sdk`), constructed with **flat keyword
  arguments**, no builder, no nested options object, and should be built
  **once** and reused; building a new client per request throws away
  connection pooling and the cached OAuth token.
- Auth for this API is `ClientCredentialsAuth`: pass a
  `ClientCredentialsAuthCredentials(o_auth_client_id=..., o_auth_client_secret=...)`
  via the `client_credentials_auth_credentials=` kwarg. The SDK fetches and
  refreshes the OAuth2 token itself; this project's old `_get_token()` /
  token-cache code was reimplementing exactly that.
- Controllers are **properties**, not classes you construct:
  `client.orders`, `client.payments`.
- Every operation returns an `ApiResponse` envelope (`.body`, `.status_code`,
  `.headers`, `.is_success()`), and raises on non-2xx. It never returns a silent
  wrong-shape dict.
- Errors come in two shapes: a **typed** exception when the API documents an
  error model for that status (PayPal's does, almost everywhere:
  `ErrorException`, carrying real `.name` / `.message` / `.debug_id` /
  `.details` unboxed from PayPal's actual error body), or the base
  `ApiException` otherwise. A separate `AuthValidationException` (not an
  `ApiException` subclass) covers credentials the auth scheme itself
  rejects before a request is even sent, a distinct failure mode a
  from-scratch client typically does not model at all.

None of this is API trivia the old httpx client got wrong out of
carelessness. It is exactly the class of detail an AI coding agent
guesses at (and often gets subtly wrong) when it has only its training data
to go on, which is the whole premise of the Context Plugin.

## The migration

`backend/app/paypal/client.py` and `backend/app/paypal/orders.py` were
rewritten to use the real SDK, with every externally visible function
signature and return shape **unchanged**: `create_order`, `get_order`,
`authorize_order`, `capture_authorization`, `void_authorization` all still
return the same plain dicts they always did, so
`backend/app/agent/orchestrator.py` needed zero changes.

- `client.py` builds one long-lived `PaypalServersdkClient` from
  `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` / `PAYPAL_ENVIRONMENT`
  (`Environment.SANDBOX` / `Environment.PRODUCTION`), replacing the
  hand-rolled OAuth2 token cache entirely. It translates whatever the SDK
  raises (`ApiException` and its typed subclasses, `AuthValidationException`,
  `requests` transport errors) into AgentAuth's existing `PayPalError`,
  keeping PayPal's real error detail (`name`/`message`/`debug_id`/`details`)
  attached instead of discarding it.
- `orders.py` builds requests from the SDK's own typed models
  (`OrderRequest`, `PurchaseUnitRequest`, `Money`, `OrderApplicationContext`,
  `PaymentSource`, `CardRequest`) and calls `client.orders.create_order`,
  `client.orders.get_order`, `client.orders.authorize_order`,
  `client.payments.capture_authorized_payment`,
  `client.payments.void_payment`: PayPal's real Orders v2 / Payments v2
  controllers, not a `path` string this project had to get exactly right.
- A small generic helper, `to_wire_dict`, converts an SDK response model
  back into the same plain snake_case dict PayPal's raw JSON uses, via each
  model's own `_names` map (confirmed, by reading the generated source, to
  be an identity map throughout this SDK, since PayPal's wire format is
  already snake_case), so the existing `_summarize_order` / `_amount_value`
  logic needed no changes either.

## What building against the real SDK caught immediately

Live-testing the migrated code against real PayPal Sandbox (not mocks)
surfaced a genuine requirement the old hand-rolled client had silently
missed: PayPal rejects a single-step "create order with a card
payment_source attached" request unless it carries a `PayPal-Request-Id`
idempotency header:

```
400 INVALID_REQUEST: PAYPAL_REQUEST_ID_REQUIRED: "A PayPal-Request-Id is
required if you are trying to process payment for an Order..."
```

This was a latent bug in the pre-migration code (same failure would have
happened there too, the first time that path actually ran against
Sandbox). The SDK's typed, controller-per-operation surface made the gap
obvious the moment it was exercised; `orders.create_order` now generates a
per-call idempotency key (`paypal_request_id`) whenever a card
`payment_source` is attached.

## Live verification against real PayPal Sandbox

- **Order creation**: verified live, end to end, no mocks. A real
  `Environment.SANDBOX` order was created via OAuth2 client-credentials
  auth through the real SDK, returning a genuine PayPal order id, approve
  URL, and self URL.
- **Error translation**: verified live with two distinct real PayPal
  rejections (missing idempotency key, and a sandbox business account not
  enabled for direct card processing: `PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING`,
  an account-level PayPal setting, unrelated to this code and unrelated to
  the migration). Both surfaced through `translate_sdk_error` as a real
  `PayPalError` carrying PayPal's actual `name` / `message` / `debug_id`,
  never a swallowed or faked result.
- **Authorize / capture / void**: exercised against the real SDK's own
  model classes in the automated test suite (`backend/tests/test_paypal.py`
  builds fake controller responses with `Order.from_dictionary(...)`,
  `CapturedPayment.from_dictionary(...)`, etc., real SDK models, not
  hand-written stand-ins), all passing. A full live run of this path
  specifically requires a PayPal Sandbox business account enabled for
  direct card (ACDC) processing, which this project's sandbox account is
  not; that is a PayPal dashboard setting, not a code path this migration
  left unverified by choice.

## What's left for the submission form

Everything above is a code and research deliverable. The submission form's
plugin question is a human action on the hackathon's own form. It cannot
be completed from inside this repository, and is intentionally left for
the project owner to answer directly.
