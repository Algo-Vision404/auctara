# Demo Video Script

Target length: 3–4 minutes. Every beat below corresponds to a real action
in the running app — nothing here is staged or narrated-only. Screen-record
the actual browser + a terminal tail of backend logs where noted, so a
judge can see the real PayPal Sandbox network calls happening, not just the
UI reacting.

---

## 0. Cold open (10s) — the problem, in one sentence

**Say:** "AI agents can already research and decide what to buy. The open
question isn't whether an agent *can* buy something — it's who decides how
much authority it has, and how that boundary actually gets enforced.
Auctara is that boundary."

**Show:** Nothing yet, or a static title card. Keep this under 10 seconds —
don't let the intro outstay its welcome.

---

## 1. Create an agent with a plain-English spending authority (30s)

**Do:** On the dashboard, create a new agent. Type a real purpose and
directive in plain English, e.g. "Buy approved SaaS subscriptions for the
team, staying frugal." Set a budget conversationally if the drafting flow
supports it, or fill the numeric policy fields directly (max transaction,
approval threshold, daily/monthly caps, categories).

**Say:** "I'm not writing a config file. I'm describing what this agent is
allowed to do, and Auctara turns that into an explicit, numeric policy:
a hard per-transaction ceiling, an approval threshold above which a human
has to click yes, daily and monthly caps, and a fixed category list."

**Show:** The resulting policy card — call out the actual numbers that got
generated/entered.

---

## 2. Give it a real task (40s)

**Do:** Submit a task prompt with a named product and a budget, e.g. "Buy
me a Notion subscription, budget up to $20." Switch to the task's live
activity feed.

**Say:** "This isn't a scripted demo flow — the agent is about to actually
search the live web, or Channel3's real product graph, for this product."

**Show:** The live SSE activity feed updating in real time: research step,
proposal drafted with a real merchant/price, then the policy decision
(`ALLOW`, `APPROVAL_REQUIRED`, or occasionally a clarifying question if the
prompt was too vague — the specificity gate). Narrate whichever actually
happens; don't force a specific path if the live demo takes another real
one — that's the point.

---

## 3. Show the guardrail that actually blocks something (30s)

**Do:** Either show a previously-blocked transaction (categories/limits) in
the ledger, or submit a second task deliberately outside policy (wrong
category, or amount over the cap) to get a live `BLOCK`.

**Say:** "The policy decision isn't a second LLM call guessing whether this
looks okay — it's deterministic Python evaluating real numbers against the
policy row in the database. The agent cannot talk its way past this."

**Show:** The BLOCKED transaction detail page with its concrete reason.

---

## 4. The real PayPal Sandbox approval (45s) — the proof-of-life moment

**Do:** Continue the allowed task through to PayPal. Click "Approve on
PayPal" — it opens the **real PayPal Sandbox checkout** in a new tab. Log
in with a sandbox buyer account and approve.

**Say:** "This is a real PayPal Sandbox order, not a mocked success
screen." [switch back to the Auctara tab] "I didn't have to refresh or
paste anything back — the app is polling PayPal's real order status and
picks up the approval on its own."

**Show:** The app's own tab auto-transitioning from "awaiting approval" to
captured, with no manual intervention.

---

## 5. The receipt, down to PayPal's own fee (20s)

**Do:** Open the completed transaction's detail page.

**Say:** "Here's the real PayPal capture ID, and the gross/fee/net
breakdown — that's not something we calculated, it's PayPal's own
`seller_receivable_breakdown` straight off the capture response."

**Show:** Capture ID, order ID, and the gross/PayPal fee/net settled row.

---

## 6. The parts that make this an operations product, not a toy (30s)

**Do:** Quick cuts through:
- The Commerce Ledger (`/ledger`, AG Grid) — group by agent/outcome, click
  a row to open the evidence-chain side panel (Proposed → Policy Evaluated
  → PayPal Executed → Audit Verified).
- The Agent Operations Schedule (`/schedule`, Bryntum) — a real recurring
  delegated instruction and its fired-occurrence history.

**Say:** "Every one of these rows and timeline events is a real database
record from an actual run through the same pipeline — nothing here is a
synthetic demo dataset."

---

## 7. Close (15s)

**Say:** "Auctara doesn't make the agent smarter. It makes its financial
authority provable: a boundary the agent proposes against, but can never
move itself." [Show the GitHub repo URL / live demo URL on screen.]

---

## Recording checklist before you hit record

- [ ] Fresh backend + frontend restart right before recording (confirm
      `/health` shows `groq_configured: true` and `paypal_configured: true`
      — a stale/offline server mid-recording is the single most avoidable
      failure mode here).
- [ ] At least one agent with a deliberately blockable policy pre-created,
      in case you want a *guaranteed* BLOCK beat rather than relying on a
      live borderline decision.
- [ ] A PayPal Sandbox buyer login ready (not the business/receiving
      account) so the approval step in beat 4 doesn't stall the recording.
- [ ] Decide up front whether beat 3's BLOCK is live or a pre-existing
      ledger row — both are honest, but know which one you're doing before
      you're on camera.
- [ ] Fill in the real live-demo URL and this video's URL in `README.md`'s
      `## Demo` section before final submission — they're still
      placeholders.
