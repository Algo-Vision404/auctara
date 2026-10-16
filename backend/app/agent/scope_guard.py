"""Independent scope-relevance guard for a finished purchase proposal.

Everything else this app enforces before a purchase executes - budget,
category, velocity, price variance - is adjudicated by deterministic Python
the research-loop model never sees and cannot influence (see
app/guardrails/engine.py). Whether a proposal actually serves the agent's
own stated purpose has historically been the one exception to that: the
system prompt tells the research-loop model to call decline_out_of_scope_task
when a task doesn't fit, but the ONLY thing standing behind that instruction
was the same model's own self-report. Nothing independently re-checked it.
A long conversation, a cleverly-worded task, or simply a model misjudging
its own purpose had no backstop - the exact "never trust the actor to grade
its own homework" gap this platform closes everywhere else (PayPal
idempotency, schedule status transitions, Channel3 field provenance, ...).

check_scope() is a second, narrowly-scoped model call: a brand new
conversation with no access to the research loop's own context, tool
history, or any instructions beyond this one judgment. It is given only
the agent's purpose/directive and the FINAL concrete proposal (merchant,
product, category, amount, the agent's own stated reason) and asked a
single yes/no question. It can, and sometimes will, disagree with the
research loop's own conclusion.

This is still a model call, not literal arithmetic like the policy engine -
"does this serve that stated purpose" is a semantic question with no
rule-based answer - so it cannot be made perfectly deterministic the way
budget math can. What it DOES provide is independence: a fresh judge that
never saw the primary loop's conversation and has nothing to gain by
agreeing with it, instead of asking the same agent to self-certify.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.agent.llm_errors import call_llm_with_retry

logger = logging.getLogger("agentauth.scope_guard")

_SYSTEM_PROMPT = """You are an independent compliance reviewer. You did NOT \
do the research behind this purchase proposal and you know nothing about it \
beyond what is given to you below - you are not the agent that found it, and \
you must not assume its judgment was correct. Your only job is to decide \
whether this ONE finished, concrete purchase proposal plausibly serves the \
agent's own stated purpose and standing directive.

Apply exactly this standard, no stricter and no looser:
- IN SCOPE: the proposal plausibly relates to the stated purpose, even if it \
names a specific brand/item/plan the purpose only described generically, or \
does not restate the purpose's exact wording. A reasonable, imperfect fit \
still counts as in scope.
- NOT IN SCOPE: the proposal has no reasonable relationship at all to the \
agent's stated purpose and directive - it looks like something a \
differently-purposed agent would buy, or something no reasonable reading of \
this agent's own purpose would cover.

Call report_scope_verdict exactly once with your judgment and a one-sentence reason."""

_TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "report_scope_verdict",
            "description": "Report whether this purchase proposal is in scope for this agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "in_scope": {"type": "boolean"},
                    "reason": {
                        "type": "string",
                        "description": "One short sentence explaining the verdict.",
                    },
                },
                "required": ["in_scope", "reason"],
            },
        },
    }
]


@dataclass
class ScopeVerdict:
    # Whether the check actually ran and produced a real verdict. False on
    # any provider error, timeout, or malformed response - callers must
    # treat ok=False as "could not confirm this is in scope", never as a
    # silent pass, since the whole point of this check is to never let an
    # unverified proposal through on blind trust.
    ok: bool
    in_scope: bool
    reason: str


async def check_scope(
    client_factory, model: str, *, agent_purpose: str, agent_directive: str,
    merchant: str, product_name: str, category: str, amount: float,
    currency: str, proposal_reason: str,
) -> ScopeVerdict:
    proposal_summary = (
        f"Merchant: {merchant}\n"
        f"Product: {product_name or '(not specified)'}\n"
        f"Category: {category}\n"
        f"Amount: {amount} {currency}\n"
        f"The researching agent's own stated reason for proposing this: {proposal_reason}"
    )
    try:
        client = client_factory()
        response = await call_llm_with_retry(lambda: client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Agent purpose: {agent_purpose}\n"
                        f"Agent standing directive: {agent_directive}\n\n"
                        f"Finished proposal to review:\n{proposal_summary}"
                    ),
                },
            ],
            tools=_TOOL_SCHEMA,
            tool_choice="required",
            temperature=0,
            max_tokens=200,
            extra_body={"reasoning": {"enabled": False}},
        ))
        call = response.choices[0].message.tool_calls[0]
        args = json.loads(call.function.arguments or "{}")
        in_scope = bool(args.get("in_scope"))
        verdict_reason = str(args.get("reason") or "").strip() or (
            "Plausibly serves this agent's stated purpose."
            if in_scope
            else "Does not plausibly serve this agent's stated purpose."
        )
        return ScopeVerdict(ok=True, in_scope=in_scope, reason=verdict_reason)
    except Exception:  # noqa: BLE001
        logger.exception("Independent scope check failed to run")
        return ScopeVerdict(
            ok=False,
            in_scope=False,
            reason="The independent scope check could not be completed.",
        )
