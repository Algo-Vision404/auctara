# Demo Test Sentences

Exact sentences to type during the live demo (see `DEMO_SCRIPT.md` for the
beat-by-beat narration these slot into). All of these are built against the
**live Procurement Agent already running in this environment**:

- Purpose: "Buy software, tools, and subscriptions the user asks for."
- Directive: "Research the best real option available online within
  budget, then purchase it. Prefer official vendors or well-known
  retailers. Never buy anything unrelated to software, tools, or digital
  subscriptions."
- Policy: $150 autonomous-approval ceiling, $200 hard max per transaction,
  $500/day, $3000/month, blocked categories: gambling, adult.

Live web prices can drift day to day — if a sentence below doesn't land in
the exact decision band listed, that's the real policy engine reacting to
a real live price, not a bug. Each one notes a safe fallback.

---

## 1. Specificity gate — vague prompt gets a clarifying question

> **Buy me some software**

Expected: no research happens yet. The agent responds in plain text asking
for product type + budget (task goes to `NEEDS_INPUT`). Good moment to show
the reply box: answer with e.g. **"a password manager, budget $15"** to
carry it forward into a normal proposal.

---

## 2. Clean auto-approve path (ALLOW, no human click needed)

> **Buy me a Notion Plus subscription, budget up to $20**

Expected: research → proposal around $10/seat/month → price is well under
the $150 autonomous ceiling → `ALLOW` → proceeds straight to PayPal.

Other reliable options from this agent's own purchase history (all
previously completed at these real prices, well under $150):
- **Buy me a Grammarly Premium subscription, budget up to $150** (landed at $139.95 last time)
- **Buy me a Bitwarden Premium subscription, budget up to $10** (landed at $1.65 last time)

---

## 3. Approval-required band (between $150 and $200 → human must click yes)

> **Buy me a Windows 11 Pro license, budget up to $200**

Microsoft's standard retail price for this is $199.99, which sits right
between the $150 autonomous ceiling and the $200 hard cap → should trigger
`APPROVAL_REQUIRED`, i.e. the task pauses for you to click Approve/Reject
before it ever touches PayPal. Good beat to explicitly show the human-in-
the-loop click.

---

## 4. Deterministic BLOCK (price exceeds the $200 hard cap)

> **Buy me the Microsoft Office Home & Business 2024 license, budget up to $300**

Retail price for this is normally ~$249.99 — over the agent's $200 max
transaction authority regardless of the budget you stated → `BLOCK`, with
a reason citing the exact dollar ceiling.

**Zero-risk fallback (no live dependency):** skip the live attempt and
just open the Ledger — there's already a real historical BLOCK sitting in
the database: **CpaWarehouse.com, $500, category "software" → BLOCKED**.
Safer if you don't want to gamble on a live price during recording.

---

## 5. Out-of-scope decline (nothing to do with software)

> **Order lunch for the team, budget $50**

or

> **Book me a flight to Accra, budget $400**

Expected: the agent declines immediately with `decline_out_of_scope_task`
— no research tool calls at all — citing that this agent's purpose is
software/tools/subscriptions only. Good contrast beat: show that this is
instant and makes zero tool calls, versus the research path above.

---

## 6. PayPal sandbox approval + receipt

Use whichever task from #2 or #3 reached `ALLOW`/`APPROVAL_REQUIRED` above
and carry it through to "Approve on PayPal" with a sandbox buyer login —
no new sentence needed here, this is the same task continuing.

---

## 7. Recurring instruction (Schedule page)

No scheduled task exists yet in this environment, so for that beat you'd
create one live:

> **Renew our Grammarly Premium subscription every month, budget up to $20 each time**

---

## Housekeeping before you record

- A test task I created while reproducing an earlier bug report is still
  sitting in your task list: `task_10b4602c0bf6`, prompt "buy me a
  software" → "render" → `NEEDS_INPUT`. It's harmless (no purchase was
  ever proposed), but I did **not** delete it or its activity rows,
  because doing so would require deleting rows out of the append-only,
  hash-chained audit log (`audit_records`), which must never be altered —
  that chain is exactly what beat 6 of the demo proves is tamper-evident.
  It's safe to just ignore it; it won't interfere with anything below it,
  it'll just be visible as one extra row in the task list.
- Confirmed right now: `/audit/verify` → `valid: true, records_verified: 230`.
