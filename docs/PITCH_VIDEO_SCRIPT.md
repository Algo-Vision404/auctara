# Pitch Video Script — Auctara (read this one verbatim)

This is the actual words to say, timestamped, mapped against the stated
judging criteria. `[Bracketed lines]` are screen directions / production
notes — don't read those aloud. Everything else is spoken word-for-word.

Target run time: **~3:15**. Cut guidance for a stricter time limit is at
the bottom. Pair this with `DEMO_SCRIPT.md` (the shot list) and
`DEMO_TEST_SENTENCES.md` (the exact prompts to type live) so narration and
screen action land in sync.

Every sentence below maps to a real, working thing in the app — nothing
here is aspirational copy. That's deliberate: "Presentation" explicitly
asks whether the video *demonstrates the project working end-to-end*, and
judges can tell the difference between a narrated feature list and a
project someone actually watched run.

---

### 0:00–0:15 — Hook (lands Innovation + Impact in the first breath)

> "Here's a sentence that should make you a little nervous: 'AI agent, go
> buy me a software subscription.' Who's actually in control of what
> happens next?
>
> Right now, most answers to that are one of two extremes: hand the agent
> your card directly — no real boundary, just the agent's own judgment —
> or route every single purchase through a human, which isn't delegation,
> it's an approval queue with an AI-written description attached.
>
> Auctara is the boundary in between. I'm going to show you an AI agent
> that can act completely on its own — but only ever inside a limit it
> cannot move itself."

`[Show: title card or dashboard, nothing fancy. Keep this tight.]`

---

### 0:15–0:45 — What it does, in the product (Design + Innovation)

> "I'm not writing a config file. I'm describing, in plain English, what
> this agent is allowed to do — and Auctara turns that into an explicit,
> numeric policy underneath: a hard ceiling per transaction, an approval
> threshold above which a human has to click yes, daily and monthly caps,
> and a fixed category list it can never buy outside of."

`[Show: the agent's policy card — point at the real numbers: $150
autonomous ceiling, $200 hard max, $500/day, $3000/month, categories
limited to software/tools/subscriptions.]`

---

### 0:45–1:10 — The guardrail most demos skip: it asks before guessing (Technological Implementation)

> "Watch what happens if I'm vague with it."

`[Type: "Buy me some software"]`

> "It doesn't guess. It doesn't pick something and call it done. A
> deterministic specificity check sits in front of the AI's research step
> — no product type and no budget means it has to ask, every time, before
> a single dollar of research or authority gets spent."

`[Show: the agent's clarifying question appearing live.]`

---

### 1:10–1:45 — Real research, real AI (Technological Implementation: AI tool usage)

`[Reply: "a Notion Plus subscription, budget up to $20"]`

> "Now it actually researches. This is a live tool-calling loop on Groq —
> it's genuinely searching the web and a real product graph for this
> item right now, not replaying a script."

`[Show: the live activity feed — search step, then a proposal with a real
merchant and price.]`

> "And here's the part that matters most: that proposal is only ever a
> recommendation. The agent has no authority to approve its own purchase."

---

### 1:45–2:15 — The deterministic policy engine (Technological Implementation + Design — THE differentiator line)

> "This decision isn't a second AI model guessing whether the price looks
> okay. It's deterministic Python, evaluating real numbers against a
> policy row in the database. The agent cannot talk its way past this —
> there's no prompt that changes what happens next."

`[Show live, back to back, two real decisions:]`
`[1 — "Buy me a Windows 11 Pro license, budget up to $200" → price lands between the $150/$200 thresholds → APPROVAL_REQUIRED, you click Approve/Reject yourself.]`
`[2 — either a live over-cap attempt, or simply open the Ledger and point at the existing CpaWarehouse.com, $500, BLOCKED row.]`

> "Same agent, same AI, two completely different outcomes — because the
> boundary, not the model, made the call."

---

### 2:15–2:50 — Real PayPal, start to finish (Technological Implementation: PayPal depth + Presentation: proof it actually works)

> "Now the part that has to be real, not mocked, for any of this to mean
> anything."

`[Click Approve on an allowed/approved task → opens real PayPal Sandbox
checkout in a new tab → log in with a sandbox buyer account → approve.]`

> "That's a real PayPal Sandbox order — two-phase, authorize then capture,
> through PayPal's own official server SDK. I didn't paste anything back
> or refresh — the app is polling PayPal's real order status and picks up
> the approval on its own."

`[Switch back to the Auctara tab — show it auto-transition to completed.]`

> "And this receipt isn't something we calculated — that's PayPal's own
> fee breakdown, gross, fee, and net, straight off the real capture
> response."

`[Show the transaction detail page: capture ID, order ID, fee breakdown.]`

---

### 2:50–3:05 — It's a product, not a toy (Design)

> "Every one of these is a real record from an actual run through this
> same pipeline — the Commerce Ledger, grouped by agent and outcome, and
> an Operations Schedule for standing instructions like 'renew this every
> month if it's still under budget.' Nothing here is a synthetic demo
> dataset."

`[Quick cuts: Ledger page, Schedule page.]`

---

### 3:05–3:20 — Close (Potential Impact — land the "why this, why now")

> "Agentic commerce is coming whether we're ready or not. The real
> question was never whether an AI can shop — it's whether its financial
> authority is something you can actually prove, audit, and trust. Auctara
> doesn't make the agent smarter. It makes its authority provable: a
> boundary it proposes against, but can never move itself."

`[Show: GitHub repo URL / live demo URL on screen as you say the last line.]`

---

## How this script maps to each judging criterion

- **Technological Implementation** — explicitly named: real Groq
  tool-calling loop, real PayPal Orders v2 two-phase flow via the official
  SDK, and a deterministic non-LLM policy engine shown making two
  different real decisions on screen.
- **Design** — the policy card, the specificity gate, the Ledger, and the
  Schedule are all shown as one coherent product, not disconnected demo
  screens.
- **Potential Impact** — framed around a specific, credible problem (who
  controls an agent's spending authority) stated in plain language twice:
  once at the hook, once at the close.
- **Innovation/Idea** — the opening explicitly contrasts Auctara against
  the two existing extremes (hand over the card vs. human-approves-every-
  purchase), which is the single clearest way to show a judge *why this is
  different*, not just *what it does*.
- **Presentation** — every beat is "say it, then immediately show it
  happening live" — nothing is narrated without the corresponding real
  screen action next to it, and the full purchase loop (ask → research →
  policy decision → real PayPal approval → receipt) is shown end to end
  in one continuous recording.

---

## If you need it shorter

- **~2:00 cut:** keep 0:00–0:45 (hook + what it does), 1:45–2:50 (policy
  decision + real PayPal + receipt), and the last two sentences of the
  close. Cut the specificity-gate beat and the Ledger/Schedule beat.
- **~1:00 cut (worst case):** hook (shortened to 2 sentences) → one single
  live purchase going all the way through PayPal to a captured receipt →
  the last two sentences of the close. This still proves the product
  works end to end, which is the one thing the rubric most directly asks
  for ("clearly demonstrate the project working end-to-end").

## Before you record

- Do a full dry run of the live demo path once, off camera, so timings
  above are realistic for your own speaking pace.
- Confirm `/health` shows `paypal_configured: true` and
  `groq_configured: true` right before you hit record.
- Have a PayPal Sandbox **buyer** account logged in and ready (not the
  business account) so beat 2:15–2:50 doesn't stall.
- Decide up front whether the BLOCK beat (1:45–2:15) is a live attempt or
  the pre-existing Ledger row — both are honest, just know which one
  you're doing before you're on camera.
