"""Deterministic orchestration around the (advisory) LLM agent.

The LLM may only: understand the task, call search_web / get_exchange_rate,
and submit ONE create_purchase_proposal. Everything from that point on,
policy evaluation, budget reservation, PayPal order creation, price
verification, capture/void, is plain Python with zero model involvement.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from openai import AsyncOpenAI

from app.agent.llm_errors import NOT_CONFIGURED_MESSAGE, humanize_llm_error
from app.agent.prompts import SYSTEM_PROMPT, build_task_prompt
from app.agent.tools import TOOL_SCHEMAS
from app.audit.integrity import record_audit
from app.config import get_settings
from app.database import models
from app.database.database import immediate_transaction
from app.exchange.rates import ExchangeRateError, convert
from app.guardrails import engine as policy_engine
from app.guardrails.policies import build_context, policy_from_row
from app.paypal import orders as paypal_orders
from app.paypal.client import PayPalError
from app.search.channel3 import Channel3Error, search_products
from app.search.duckduckgo import SearchError, search_web
from app.search.fetch import FetchError, fetch_page
from app.state_machine import TERMINAL_STATES, InvalidTransition, transition
from app.streaming.events import bus

logger = logging.getLogger("agentauth.orchestrator")

MAX_TOOL_ITERATIONS = 10

# Each pause-for-clarification round gives the model a fresh MAX_TOOL_ITERATIONS
# budget (see _run_research_loop), so this caps total human back-and-forth
# rather than raw LLM calls: past this many questions on one task, something
# is wrong (an ambiguous prompt, or a model stuck looping) and the task
# should fail with a clear message instead of asking forever.
MAX_CLARIFICATION_ROUNDS = 5


class AgentError(Exception):
    pass


class OutOfScopeError(Exception):
    """Raised when the agent itself declines a task via decline_out_of_scope_task
    because it has no reasonable connection to the agent's stated purpose and
    directive. Deliberately not an AgentError: this is the agent correctly
    refusing to act outside its delegated role, not a failure of the research
    pipeline, and it is reported to the user as a distinct, clean outcome
    rather than a generic error."""


class NeedsInputError(Exception):
    """Raised when the agent's next turn is plain conversational text (a
    clarifying question, or a check-in about a near-match it found) rather
    than a tool call. Deliberately not an AgentError: this is the agent
    correctly pausing to ask the human something, not the research pipeline
    failing. The task lands in NEEDS_INPUT, with its full conversation
    persisted, until the human replies via POST /tasks/{id}/respond."""


class AgentRetiredError(Exception):
    """Raised when, partway through a task, the agent that owns it is found
    to have been retired or deleted (see retire_agent/delete_agent below).
    Checked cooperatively at the top of every research-loop iteration, via
    _ensure_agent_active, so a task that was already mid-flight when its
    agent was removed stops itself on its very next step rather than
    continuing to research, propose, or spend after it was told to stop."""


async def emit(event_type: str, message: str, *, task_id: Optional[str] = None,
                transaction_id: Optional[str] = None, agent_id: Optional[str] = None,
                payload: Optional[dict] = None, audit: bool = True) -> None:
    payload = payload or {}
    models.add_activity(agent_id, task_id, transaction_id, event_type, message, payload)
    if audit:
        record_audit(event_type, payload, transaction_id=transaction_id, task_id=task_id, agent_id=agent_id)
    await bus.publish({
        "event": event_type,
        "task_id": task_id,
        "transaction_id": transaction_id,
        "agent_id": agent_id,
        "message": message,
        "payload": payload,
    })


def _set_tx_state(tx_id: str, current: str, target: str, **fields: Any) -> dict:
    """Validates the abstract state-machine edge AND re-checks that the row's
    actual current state in the database still matches what the caller
    believes it is, before writing. The second check is what actually makes
    agent retirement/deletion safe: without it, a background task whose
    `current` was computed before its agent got retired (and its
    transaction force-cancelled out from under it, see _cancel_task) could
    otherwise blindly overwrite CANCELLED back onto an active state once its
    slow LLM/network call finally returns.
    """
    transition(current, target)
    live = models.get_transaction(tx_id)
    if not live or live["state"] != current:
        raise InvalidTransition(
            f"Transaction {tx_id} is no longer in state {current} "
            f"(now {live['state'] if live else 'deleted'}); refusing to overwrite."
        )
    return models.update_transaction(tx_id, state=target, **fields)


def _ensure_agent_active(agent_id: str) -> None:
    agent = models.get_agent(agent_id)
    if not agent or agent["status"] != "ACTIVE":
        raise AgentRetiredError("Agent was retired or deleted while this task was in progress.")


def _openrouter_client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise AgentError(NOT_CONFIGURED_MESSAGE)
    return AsyncOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers={
            "HTTP-Referer": settings.frontend_url or "http://localhost:3000",
            "X-Title": "AgentAuth",
        },
    )


async def run_task(task_id: str) -> None:
    task = models.get_task(task_id)
    if not task:
        return
    agent = models.get_agent(task["agent_id"])
    policy_row = models.get_active_policy(agent["id"])
    if not policy_row:
        models.update_task_status(task_id, "FAILED", "No active policy for this agent.")
        await emit("TRANSACTION_FAILED", "No active policy configured for this agent.",
                    task_id=task_id, agent_id=agent["id"])
        return

    tx = models.create_transaction(task_id, agent["id"])
    tx_id = tx["id"]

    await emit("AGENT_STARTED", f"{agent['name']} started working on the task.",
                task_id=task_id, agent_id=agent["id"], transaction_id=tx_id)
    models.update_task_status(task_id, "RESEARCHING")
    _set_tx_state(tx_id, "CREATED", "RESEARCHING")

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_task_prompt(agent["purpose"], agent["directive"], task["prompt"])},
    ]
    await _continue_research(agent, task, tx_id, messages)


async def resume_task(task_id: str, reply: str) -> None:
    """Resume a task that is sitting in NEEDS_INPUT because the agent's last
    turn was a clarifying question (or a check-in like "I found X instead,
    want it?") rather than a tool call. Appends the human's reply to the
    exact conversation that was paused and re-enters the same research loop,
    so the model picks up with full context rather than starting over."""
    task = models.get_task(task_id)
    if not task:
        return
    agent = models.get_agent(task["agent_id"])
    tx = models.get_transaction_for_task(task_id)
    if not tx or tx["state"] != "NEEDS_INPUT":
        raise AgentError("This task is not currently waiting for a reply.")

    tx_id = tx["id"]
    messages: list[dict] = json.loads(tx["conversation_state"] or "[]")
    messages.append({"role": "user", "content": reply})

    _set_tx_state(tx_id, "NEEDS_INPUT", "RESEARCHING",
                   pending_question=None, conversation_state=None)
    models.update_task_status(task_id, "RESEARCHING")
    await emit("USER_REPLIED", reply, task_id=task_id, agent_id=agent["id"],
                transaction_id=tx_id, payload={"message": reply})

    await _continue_research(agent, task, tx_id, messages)


async def _continue_research(agent: dict, task: dict, tx_id: str, messages: list[dict]) -> None:
    """Shared tail end of run_task/resume_task: run the research loop from
    wherever `messages` leaves off, then (if it actually produced a
    proposal rather than pausing/declining/failing) carry it through policy
    evaluation and execution. Split out so both a brand-new task and one
    resuming after a human reply land in identical downstream handling."""
    task_id = task["id"]
    policy_row = models.get_active_policy(agent["id"])
    if not policy_row:
        await _fail(tx_id, task_id, agent["id"], "No active policy configured for this agent.")
        return

    try:
        proposal = await _run_research_loop(agent, task, tx_id, messages)
    except NeedsInputError as exc:
        await _ask_clarifying_question(tx_id, task_id, agent["id"], str(exc), messages)
        return
    except OutOfScopeError as exc:
        await _decline_out_of_scope(tx_id, task_id, agent["id"], str(exc))
        return
    except AgentRetiredError as exc:
        await _cancel_task(tx_id, task_id, agent["id"], str(exc), current_state="RESEARCHING")
        return
    except (SearchError, AgentError) as exc:
        await _fail(tx_id, task_id, agent["id"], str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error in agent research loop")
        await _fail(
            tx_id, task_id, agent["id"],
            "Something unexpected went wrong while this agent was working on the task. "
            "Please try again, and contact your administrator if it keeps happening.",
        )
        return

    try:
        amount_usd = await _normalize_to_usd(proposal["amount"], proposal["currency"])
    except ExchangeRateError as exc:
        await _fail(tx_id, task_id, agent["id"], str(exc))
        return

    # Deterministic backstop, independent of the tool-call validation in
    # _run_research_loop above: no proposal with a non-positive amount may
    # ever reach the policy engine or PayPal, no matter how it got here. A
    # $0.00 (or negative) "price" trivially clears every budget check, so
    # without this it would sail through ALLOW and only fail once PayPal
    # itself rejects a zero-amount order - after the task already looked
    # proposed and approved to the user, with a confusing PayPal error as
    # the only explanation.
    if not (amount_usd > 0):
        await _fail(
            tx_id, task_id, agent["id"],
            f"The agent proposed {proposal['merchant']} at "
            f"{proposal['amount']} {proposal['currency']}, which is not a real, positive "
            "price. No order was sent to PayPal.",
        )
        return

    models.update_transaction(
        tx_id,
        merchant=proposal["merchant"],
        amount=proposal["amount"],
        currency=proposal["currency"].upper(),
        category=proposal["category"].lower(),
        reason=proposal["reason"],
        source_url=proposal.get("source_url"),
        image_url=proposal.get("image_url"),
        retailer=proposal.get("retailer"),
        channel3_product_id=proposal.get("channel3_product_id"),
        expected_amount=round(amount_usd, 2),
    )
    _set_tx_state(tx_id, "RESEARCHING", "PROPOSED")
    await emit(
        "PROPOSAL_CREATED",
        f"Purchase proposal created: {proposal['merchant']}, ${proposal['amount']:.2f} {proposal['currency']}.",
        task_id=task_id, agent_id=agent["id"], transaction_id=tx_id,
        payload={**proposal, "amount_usd": round(amount_usd, 2)},
    )

    _set_tx_state(tx_id, "PROPOSED", "POLICY_CHECK")
    decision = _evaluate_policy_atomic(agent["id"], tx_id, amount_usd, proposal["category"], policy_row)

    models.update_transaction(
        tx_id,
        decision=decision["decision"],
        decision_reason=decision["reason"],
        authorized_amount=decision.get("authorized_amount"),
        remaining_daily_budget=decision.get("remaining_daily_budget"),
        remaining_monthly_budget=decision.get("remaining_monthly_budget"),
    )
    await emit(
        "POLICY_EVALUATED", f"Policy engine returned: {decision['decision']}.",
        task_id=task_id, agent_id=agent["id"], transaction_id=tx_id, payload=decision,
    )

    if decision["decision"] == "BLOCK":
        _set_tx_state(tx_id, "POLICY_CHECK", "BLOCKED")
        models.update_task_status(task_id, "BLOCKED")
        await emit("POLICY_BLOCKED", decision["reason"], task_id=task_id, agent_id=agent["id"],
                    transaction_id=tx_id, payload=decision)
        return

    if decision["decision"] == "APPROVAL_REQUIRED":
        _set_tx_state(tx_id, "POLICY_CHECK", "AWAITING_APPROVAL")
        models.update_task_status(task_id, "AWAITING_APPROVAL")
        await emit("APPROVAL_REQUESTED",
                    f"Human approval required for ${decision['requested_amount']:.2f}.",
                    task_id=task_id, agent_id=agent["id"], transaction_id=tx_id, payload=decision)
        return

    # ALLOW
    _set_tx_state(tx_id, "POLICY_CHECK", "AUTHORIZED")
    await emit("POLICY_ALLOWED", decision["reason"], task_id=task_id, agent_id=agent["id"],
                transaction_id=tx_id, payload=decision)
    models.update_task_status(task_id, "EXECUTING")
    await execute_payment(tx_id)


_LEAKED_REASONING_MARKERS = (
    "let me think", "let me re-read", "let me reconsider", "wait,", "wait -",
    "actually,", "actually wait", "hmm,", "so i need to", "i think i should",
    "looking more carefully", "let me check", "let me review",
)


def _looks_like_leaked_reasoning(text: str) -> bool:
    """Cheap heuristic for 'this is scratch-work, not a message to a human':
    long (a real clarifying question is a sentence or two), multi-paragraph,
    or full of first-person deliberation markers. False positives just cost
    one extra LLM call; false negatives leave the original text untouched,
    so this only needs to be good enough to catch the common, blatant case
    seen from less disciplined models."""
    if len(text) > 350:
        return True
    if text.count("\n\n") >= 2:
        return True
    lowered = text.lower()
    return sum(marker in lowered for marker in _LEAKED_REASONING_MARKERS) >= 2


async def _sanitize_human_message(client: AsyncOpenAI, settings, raw: str) -> str:
    """If `raw` looks like leaked chain-of-thought rather than an actual
    message meant for a human, ask the model to distill it into the single
    clean question/explanation it should have sent. Best-effort: any failure
    (or a result that doesn't look like an improvement) just falls back to
    the original text rather than blocking the task on a cleanup step."""
    if not _looks_like_leaked_reasoning(raw):
        return raw
    try:
        response = await client.chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "The text below is an AI assistant's internal reasoning, "
                        "accidentally about to be shown to a human instead of a "
                        "clean message. Rewrite it as ONE short, friendly message "
                        "(1-3 sentences) containing only what the human actually "
                        "needs: the final question being asked, or a brief plain "
                        "summary of what was found and why input is needed. Drop "
                        "all step-by-step deliberation, option-weighing, and "
                        "meta-commentary. Reply with ONLY the rewritten message, "
                        "nothing else."
                    ),
                },
                {"role": "user", "content": raw},
            ],
            temperature=0.1,
            max_tokens=200,
            extra_body={"reasoning": {"enabled": False}},
        )
        cleaned = (response.choices[0].message.content or "").strip()
        # Sanity check: a real cleanup should be short. If the model
        # couldn't follow even this instruction, better to show the human
        # the original raw text than a second layer of garbage.
        if cleaned and len(cleaned) < len(raw):
            return cleaned
    except Exception:  # noqa: BLE001
        logger.warning("Failed to sanitize a leaked-reasoning message; using raw text", exc_info=True)
    return raw


async def _run_research_loop(agent: dict, task: dict, tx_id: str, messages: list[dict]) -> dict:
    """Runs up to MAX_TOOL_ITERATIONS more turns of the tool-calling loop,
    mutating `messages` in place as it goes. `messages` may already contain
    prior turns from an earlier call that paused on NeedsInputError and was
    since resumed with a human reply appended - this function has no memory
    of its own, all continuity lives in the caller-owned message list."""
    client = _openrouter_client()
    settings = get_settings()

    for step in range(MAX_TOOL_ITERATIONS):
        # Cheap, cooperative check before every round-trip to the model: if
        # the agent has been retired or deleted since this loop started,
        # stop now instead of burning another LLM call researching (or
        # worse, going on to propose/spend) for an agent that no longer
        # exists or was told to stop.
        _ensure_agent_active(agent["id"])

        # Weaker/less decisive models can burn the whole research budget
        # re-searching instead of ever concluding. With 2 calls left, inject
        # an explicit countdown so the model wraps up on its own terms
        # (propose with what it already has, or ask ONE clean final
        # question) instead of silently running out of road.
        remaining = MAX_TOOL_ITERATIONS - step
        if remaining <= 2:
            messages.append({
                "role": "system",
                "content": (
                    f"You have {remaining} tool call(s) left before this task is "
                    "marked failed with no result. Stop researching now: call "
                    "create_purchase_proposal with the best real option you already "
                    "found, or, only if genuinely blocked, reply in plain text with "
                    "ONE short final question for the human and nothing else."
                ),
            })
        try:
            response = await client.chat.completions.create(
                model=settings.openrouter_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=1024,
                # Several free OpenRouter models are "reasoning" models that
                # by default spend most/all of max_tokens on an internal
                # chain-of-thought (returned separately as `reasoning`, but
                # some providers also bleed it into `content` when the
                # response gets cut off mid-thought). This agent has no use
                # for visible reasoning, only a final tool call or a short
                # clean message, so turn it off everywhere; models that don't
                # support the parameter simply ignore it.
                extra_body={"reasoning": {"enabled": False}},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenRouter chat.completions.create failed")
            raise AgentError(humanize_llm_error(exc)) from exc

        choice = response.choices[0]
        msg = choice.message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            content = (msg.content or "").strip()
            if not content:
                raise AgentError("Agent did not produce a purchase proposal, and left no message explaining why.")
            # The model chose to talk instead of calling a tool: a
            # clarifying question, a "closest match I found, want it?"
            # check-in, anything conversational. That is not a research
            # failure, so unlike every other dead end in this loop it does
            # NOT raise AgentError. Instead the caller pauses the task in
            # NEEDS_INPUT with this exact conversation preserved, so a human
            # can answer it and the loop can pick back up with full context.
            #
            # Less disciplined models sometimes ignore the system prompt's
            # instruction to keep this text human-facing only, and dump
            # their raw step-by-step reasoning here instead of a clean
            # question. That reasoning would otherwise land verbatim on a
            # human's screen, so detect anything that looks like leaked
            # scratch-work and pay for one extra, cheap call to distill it
            # into the single clean message it should have been. Short,
            # well-behaved replies (the common case) skip this entirely.
            content = await _sanitize_human_message(client, settings, content)
            raise NeedsInputError(content)

        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "channel3_search_products":
                query = args.get("query", "")
                max_price = args.get("max_price")
                await emit("CHANNEL3_SEARCH_STARTED",
                            f"Searching the product catalog for \"{query}\"...",
                            task_id=task["id"], agent_id=agent["id"], transaction_id=tx_id,
                            payload={"query": query, "max_price": max_price})
                try:
                    products = await search_products(query, max_price=max_price)
                except Channel3Error as exc:
                    logger.warning("Channel3 product search failed: %s", exc)
                    await emit("CHANNEL3_SEARCH_FAILED",
                                "Product catalog search failed; falling back to web search.",
                                task_id=task["id"], agent_id=agent["id"],
                                transaction_id=tx_id, payload={"query": query, "error": str(exc)})
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({"error": "Product catalog search unavailable; use search_web instead."}),
                    })
                    continue
                await emit("CHANNEL3_SEARCH_COMPLETED",
                            f"Found {len(products)} real product candidate(s).",
                            task_id=task["id"], agent_id=agent["id"], transaction_id=tx_id,
                            payload={"query": query, "result_count": len(products), "products": products[:8]})
                messages.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": json.dumps({"products": products[:8]}),
                })

            elif name == "search_web":
                query = args.get("query", "")
                await emit("SEARCH_STARTED", f"Searching the web for \"{query}\"...",
                            task_id=task["id"], agent_id=agent["id"], transaction_id=tx_id,
                            payload={"query": query})
                try:
                    results = await search_web(query)
                except SearchError as exc:
                    await emit("SEARCH_FAILED", str(exc), task_id=task["id"], agent_id=agent["id"],
                                transaction_id=tx_id, payload={"query": query, "error": str(exc)})
                    raise
                await emit("SEARCH_COMPLETED", f"Found {len(results)} relevant results.",
                            task_id=task["id"], agent_id=agent["id"], transaction_id=tx_id,
                            payload={"query": query, "result_count": len(results)})
                messages.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": json.dumps({"results": results[:8]}),
                })

            elif name == "fetch_page":
                url = args.get("url", "")
                await emit("PAGE_FETCH_STARTED", f"Reading {url}...",
                            task_id=task["id"], agent_id=agent["id"], transaction_id=tx_id,
                            payload={"url": url})
                try:
                    text = await fetch_page(url)
                    await emit("PAGE_FETCH_COMPLETED", f"Read {len(text)} characters from {url}.",
                                task_id=task["id"], agent_id=agent["id"], transaction_id=tx_id,
                                payload={"url": url, "chars": len(text)})
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({"url": url, "text": text}),
                    })
                except FetchError as exc:
                    await emit("PAGE_FETCH_FAILED", str(exc), task_id=task["id"], agent_id=agent["id"],
                                transaction_id=tx_id, payload={"url": url, "error": str(exc)})
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({"error": str(exc)}),
                    })

            elif name == "get_exchange_rate":
                currency = args.get("currency", "USD")
                try:
                    rate_amount = await convert(1.0, currency, "USD")
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({"currency": currency, "rate_to_usd": rate_amount}),
                    })
                except ExchangeRateError as exc:
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({"error": str(exc)}),
                    })

            elif name == "create_purchase_proposal":
                required = ["merchant", "amount", "currency", "category", "reason"]
                missing = [f for f in required if f not in args or args[f] in (None, "")]
                if missing:
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({"error": f"Missing fields: {missing}"}),
                    })
                    continue
                # `0 in (None, "")` is False, so a bogus/unfound $0.00 "price"
                # (or a negative one) sailed straight past the missing-field
                # check above, through policy evaluation (trivially within
                # any budget), and all the way to PayPal, which correctly
                # rejects a zero-amount order - but only after the task has
                # already looked ALLOWED and "proposed" to the user. Catch it
                # here instead: bounce it back to the agent as a tool error so
                # it re-researches a real price or (since it cannot invent
                # one) asks the user via a plain-text message, exactly like
                # any other genuine research dead end.
                try:
                    amount_value = float(args["amount"])
                except (TypeError, ValueError):
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({"error": "amount must be a real number."}),
                    })
                    continue
                if not (amount_value > 0):
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({
                            "error": (
                                f"amount must be a real, positive price you actually found "
                                f"on the page (got {amount_value}). $0.00 is never a valid "
                                "price for a real purchase. If you could not find a real "
                                "price for this option, research a different candidate, or "
                                "if nothing has a findable price, say so in plain text and "
                                "ask the user how to proceed instead of proposing this."
                            )
                        }),
                    })
                    continue
                args["amount"] = amount_value
                return args


            elif name == "decline_out_of_scope_task":
                reason = (args.get("reason") or "").strip() or (
                    "This task has no reasonable connection to the agent's stated purpose."
                )
                raise OutOfScopeError(reason)

            else:
                messages.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": json.dumps({"error": f"Unknown tool {name}"}),
                })

    raise AgentError("Agent exceeded maximum reasoning steps without producing a proposal.")


async def _normalize_to_usd(amount: float, currency: str) -> float:
    if currency.upper() == "USD":
        return amount
    return await convert(amount, currency, "USD")


def _evaluate_policy_atomic(agent_id: str, tx_id: str, amount_usd: float, category: str,
                              policy_row: dict) -> dict:
    """Evaluate + (if authorized) reserve budget atomically so concurrent
    transactions can never jointly overspend the daily/monthly budget."""
    policy = policy_from_row(policy_row)
    with immediate_transaction():
        ctx = build_context(agent_id, amount_usd, category, policy)
        decision = policy_engine.evaluate(policy, ctx)
        if decision["decision"] in ("ALLOW", "APPROVAL_REQUIRED"):
            models.reserve_budget(agent_id, tx_id, decision["authorized_amount"])
    return decision


async def _fail(tx_id: str, task_id: str, agent_id: str, message: str) -> None:
    tx = models.get_transaction(tx_id)
    try:
        if tx and tx["state"] not in TERMINAL_STATES:
            transition(tx["state"], "FAILED")
            # Clear any stale "action required" PayPal state so the UI never shows
            # a dead "Approve on PayPal" call-to-action for a transaction that has
            # genuinely failed. paypal_order_id (if any) is kept for audit history.
            models.update_transaction(
                tx_id, state="FAILED", error=message,
                paypal_status="FAILED" if tx.get("paypal_order_id") else tx.get("paypal_status"),
                paypal_approve_url=None,
            )
    except InvalidTransition:
        models.update_transaction(tx_id, error=message)
    models.update_task_status(task_id, "FAILED", message)
    await emit("TRANSACTION_FAILED", message, task_id=task_id, agent_id=agent_id, transaction_id=tx_id,
                payload={"error": message})


async def _ask_clarifying_question(tx_id: str, task_id: str, agent_id: str, question: str,
                                     messages: list[dict]) -> None:
    """The agent's next turn was conversational rather than a tool call (see
    NeedsInputError). Pauses the task in NEEDS_INPUT with the exact
    conversation preserved so a human can answer via POST
    /tasks/{id}/respond and the loop resumes with full context - unless this
    task has already asked MAX_CLARIFICATION_ROUNDS questions, in which case
    it fails outright rather than asking forever."""
    tx = models.get_transaction(tx_id)
    rounds = (tx.get("clarification_rounds") or 0) + 1
    if rounds > MAX_CLARIFICATION_ROUNDS:
        await _fail(
            tx_id, task_id, agent_id,
            f"The agent asked {rounds} follow-up questions without reaching a decision. "
            f"Last question: {question}",
        )
        return

    _set_tx_state(
        tx_id, "RESEARCHING", "NEEDS_INPUT",
        pending_question=question,
        conversation_state=json.dumps(messages),
        clarification_rounds=rounds,
    )
    models.update_task_status(task_id, "NEEDS_INPUT")
    await emit("AGENT_ASKED_QUESTION", question, task_id=task_id, agent_id=agent_id,
                transaction_id=tx_id, payload={"question": question, "round": rounds})


async def _decline_out_of_scope(tx_id: str, task_id: str, agent_id: str, reason: str) -> None:
    """The agent itself refused a task outside its assigned purpose, before
    any research or proposal was made. Reported as BLOCKED, the same terminal
    state a deterministic policy block ends in (no PayPal transaction is ever
    created either way), but under its own distinct event type so the
    Activity feed and Audit trail never conflate 'the agent declined this'
    with 'the deterministic policy engine blocked this'. Those are two
    different layers of this platform's guardrails, and which one actually
    fired is exactly the kind of thing this platform exists to make visible.
    """
    _set_tx_state(tx_id, "RESEARCHING", "BLOCKED", decision="BLOCK", decision_reason=reason)
    models.update_task_status(task_id, "BLOCKED")
    await emit("TASK_DECLINED_OUT_OF_SCOPE", reason, task_id=task_id, agent_id=agent_id,
                transaction_id=tx_id, payload={"reason": reason})


async def _cancel_task(tx_id: str, task_id: str, agent_id: str, reason: str,
                        *, current_state: Optional[str] = None) -> None:
    """Stop a task/transaction because the agent that owns it was retired or
    deleted, not because of anything about the task itself. Lands in
    CANCELLED, a terminal state distinct from FAILED/BLOCKED/VOIDED, so the
    Activity feed and Audit trail show this was an administrative stop, not
    a pipeline outcome. decision_reason is set but decision itself is left
    untouched (same convention as reject_transaction below): if a real
    policy decision had already been reached (e.g. APPROVAL_REQUIRED) before
    the agent was removed, that is still worth preserving as "how far this
    got" rather than being overwritten.

    Idempotent and safe to call twice for the same transaction: if another
    caller already moved it to a terminal state first (e.g. the research
    loop's own cooperative check beat a concurrent retire_agent() sweep to
    it, or vice versa), this is a silent no-op instead of a duplicate event
    or a crash.
    """
    tx = models.get_transaction(tx_id)
    state = tx["state"] if tx else current_state
    if state is None or state in TERMINAL_STATES:
        return
    if tx and tx.get("authorized_amount"):
        models.release_budget(agent_id, tx_id, tx["authorized_amount"])
    try:
        _set_tx_state(tx_id, state, "CANCELLED", decision_reason=reason)
    except InvalidTransition:
        # Lost the race to a concurrent transition already moving this
        # transaction somewhere else. Nothing more to do here.
        return
    models.update_task_status(task_id, "CANCELLED", reason)
    await emit("TASK_CANCELLED_AGENT_REMOVED", reason, task_id=task_id, agent_id=agent_id,
                transaction_id=tx_id, payload={"reason": reason})


async def _cancel_in_flight_work(agent: dict) -> None:
    """Stop every scheduled task and every non-terminal transaction/task
    belonging to this agent. Shared by retire_agent and delete_agent: both
    need identical 'stop everything in flight' behavior, they only differ in
    whether the agent row ends up disabled or gone afterward."""
    agent_id = agent["id"]
    for sched in models.list_scheduled_tasks(agent_id):
        if sched["status"] in ("ACTIVE", "PAUSED"):
            models.update_scheduled_task(sched["id"], status="CANCELLED")

    reason = f"Agent \"{agent['name']}\" was removed while this task was in progress."
    for tx in models.list_transactions(agent_id):
        if tx["state"] not in TERMINAL_STATES:
            await _cancel_task(tx["id"], tx["task_id"], agent_id, reason, current_state=tx["state"])


async def retire_agent(agent_id: str) -> dict:
    """Soft removal: the agent stops accepting new tasks immediately (see the
    status check in POST /tasks) and every task/transaction still in flight
    is cancelled, but the agent row and its full transaction/activity/audit
    history remain exactly as they are and stay visible everywhere."""
    agent = models.get_agent(agent_id)
    if not agent:
        raise AgentError("Agent not found.")
    if agent["status"] != "ACTIVE":
        return agent

    # Flip status FIRST, before touching any in-flight work: a task that is
    # mid-loop right now cooperatively notices this on its very next
    # iteration (_ensure_agent_active) and stops itself, even if this
    # function's own cleanup sweep below races with it.
    models.update_agent_status(agent_id, "RETIRED")
    await _cancel_in_flight_work(agent)
    await emit("AGENT_RETIRED", f"{agent['name']} was retired and will no longer accept new tasks.",
                agent_id=agent_id, payload={"agent_name": agent["name"]})
    return models.get_agent(agent_id)


async def delete_agent(agent_id: str) -> None:
    """Hard removal: every in-flight task/transaction is cancelled exactly as
    retire_agent does, one final AGENT_DELETED record is sealed into the
    permanent audit trail, and then the agent row itself (and, via
    ON DELETE CASCADE, its policies/tasks/transactions/scheduled_tasks/
    budget_ledger rows) is permanently deleted. activity_events and
    audit_records are never touched by the cascade (see models.delete_agent)
    so the audit trail survives even though the live entity is gone."""
    agent = models.get_agent(agent_id)
    if not agent:
        raise AgentError("Agent not found.")
    if agent["status"] == "ACTIVE":
        models.update_agent_status(agent_id, "RETIRED")
    await _cancel_in_flight_work(agent)
    await emit("AGENT_DELETED", f"{agent['name']} was permanently deleted.", agent_id=agent_id,
                payload={"agent_name": agent["name"], "purpose": agent["purpose"]})
    models.delete_agent(agent_id)


async def approve_transaction(tx_id: str) -> dict:
    tx = models.get_transaction(tx_id)
    if not tx:
        raise AgentError("Transaction not found.")
    if tx["state"] != "AWAITING_APPROVAL":
        raise AgentError(f"Transaction is not awaiting approval (state={tx['state']}).")
    _set_tx_state(tx_id, "AWAITING_APPROVAL", "AUTHORIZED")
    await emit("APPROVAL_GRANTED", f"User approved ${tx['authorized_amount']:.2f}.",
                task_id=tx["task_id"], agent_id=tx["agent_id"], transaction_id=tx_id,
                payload={"amount": tx["authorized_amount"]})
    models.update_task_status(tx["task_id"], "EXECUTING")
    await execute_payment(tx_id)
    return models.get_transaction(tx_id)


async def reject_transaction(tx_id: str, reason: str = "Rejected by user") -> dict:
    tx = models.get_transaction(tx_id)
    if not tx:
        raise AgentError("Transaction not found.")
    if tx["state"] != "AWAITING_APPROVAL":
        raise AgentError(f"Transaction is not awaiting approval (state={tx['state']}).")
    if tx.get("authorized_amount"):
        models.release_budget(tx["agent_id"], tx_id, tx["authorized_amount"])
    _set_tx_state(tx_id, "AWAITING_APPROVAL", "BLOCKED", decision_reason=reason)
    models.update_task_status(tx["task_id"], "BLOCKED")
    await emit("APPROVAL_REJECTED", reason, task_id=tx["task_id"], agent_id=tx["agent_id"],
                transaction_id=tx_id, payload={"reason": reason})
    return models.get_transaction(tx_id)


async def execute_payment(tx_id: str) -> None:
    tx = models.get_transaction(tx_id)
    agent_id = tx["agent_id"]
    task_id = tx["task_id"]
    settings = get_settings()
    task = models.get_task(task_id)
    frontend_origin = (task and task.get("frontend_origin")) or settings.frontend_url

    try:
        order = await paypal_orders.create_order(
            amount=tx["expected_amount"],
            currency="USD",
            description=f"{tx['merchant']}: {tx.get('reason', '')}"[:120],
            return_url=f"{frontend_origin}/transactions/{tx_id}?paypal=return",
            cancel_url=f"{frontend_origin}/transactions/{tx_id}?paypal=cancel",
            custom_id=tx_id,
        )
    except PayPalError as exc:
        await _fail(tx_id, task_id, agent_id, f"PayPal order creation failed: {exc}")
        return

    _set_tx_state(tx_id, "AUTHORIZED", "VERIFYING",
                   paypal_order_id=order["order_id"], paypal_status=order["status"])
    await emit("PAYPAL_ORDER_CREATED", f"PayPal order {order['order_id']} created ({order['status']}).",
                task_id=task_id, agent_id=agent_id, transaction_id=tx_id, payload=order)

    if order.get("authorization_id"):
        await _finalize_payment(tx_id, order)
    else:
        # Standard checkout: buyer must approve on PayPal before we can authorize/capture.
        models.update_transaction(tx_id, paypal_status="PAYER_ACTION_REQUIRED",
                                    paypal_approve_url=order.get("approve_url"))
        await emit("PAYPAL_APPROVAL_REQUIRED",
                    "Buyer approval required on PayPal before this order can be authorized.",
                    task_id=task_id, agent_id=agent_id, transaction_id=tx_id,
                    payload={"approve_url": order.get("approve_url")})


async def continue_after_paypal_approval(tx_id: str) -> dict:
    """Called once the shopper has approved the order on PayPal (redirect flow)."""
    tx = models.get_transaction(tx_id)
    if not tx or tx["state"] != "VERIFYING" or not tx.get("paypal_order_id"):
        raise AgentError("Transaction is not awaiting a PayPal approval.")
    try:
        order = await paypal_orders.authorize_order(tx["paypal_order_id"])
    except PayPalError as exc:
        await _fail(tx_id, tx["task_id"], tx["agent_id"], f"PayPal authorization failed: {exc}")
        return models.get_transaction(tx_id)
    await _finalize_payment(tx_id, order)
    return models.get_transaction(tx_id)


async def _finalize_payment(tx_id: str, order: dict) -> None:
    tx = models.get_transaction(tx_id)
    agent_id, task_id = tx["agent_id"], tx["task_id"]
    policy_row = models.get_active_policy(agent_id)
    policy = policy_from_row(policy_row)

    authorized_amount = order.get("authorized_amount") or order.get("requested_amount")
    variance = policy_engine.evaluate_price_variance(policy, tx["expected_amount"], authorized_amount)

    await emit("PAYMENT_VERIFIED",
                f"PayPal confirmed ${authorized_amount:.2f} (expected ${tx['expected_amount']:.2f}).",
                task_id=task_id, agent_id=agent_id, transaction_id=tx_id, payload=variance)
    models.update_transaction(tx_id, actual_amount=authorized_amount)

    over_authority = authorized_amount > (tx["authorized_amount"] or policy.max_transaction_amount) + 1e-9

    if variance["within_tolerance"] and not over_authority:
        # Opt-in sandbox QA hook (see app/paypal/orders.py / docs/NEGATIVE_TESTING.md):
        # null on every normal task, so this is a no-op and captures for real,
        # exactly as before. Only set when a task was deliberately created to
        # demonstrate PayPal itself declining this one capture, via PayPal's
        # own documented negative-testing mechanism.
        task = models.get_task(task_id)
        negative_test = task.get("paypal_negative_test") if task else None
        try:
            capture = await paypal_orders.capture_authorization(
                order["authorization_id"], mock_response=negative_test
            )
        except PayPalError as exc:
            await _fail(tx_id, task_id, agent_id, f"PayPal capture failed: {exc}")
            return

        if capture.get("status") != "COMPLETED":
            await _fail(tx_id, task_id, agent_id,
                        f"PayPal capture did not complete (status={capture.get('status')}).")
            return

        delta = (capture.get("amount") or authorized_amount) - (tx["authorized_amount"] or 0)
        if abs(delta) > 1e-9:
            models.adjust_budget(agent_id, tx_id, delta, "CAPTURE_ADJUST")

        _set_tx_state(tx_id, "VERIFYING", "CAPTURED",
                       paypal_capture_id=capture.get("capture_id"), paypal_status=capture.get("status"))
        await emit("PAYMENT_CAPTURED",
                    f"Payment of ${capture.get('amount'):.2f} captured via PayPal.",
                    task_id=task_id, agent_id=agent_id, transaction_id=tx_id, payload=capture)

        _set_tx_state(tx_id, "CAPTURED", "COMPLETED")
        models.update_task_status(task_id, "COMPLETED")
        await emit("TRANSACTION_COMPLETED", "Transaction completed successfully.",
                    task_id=task_id, agent_id=agent_id, transaction_id=tx_id,
                    payload={"transaction_id": tx_id, "amount": capture.get("amount")})
    else:
        reason = (
            f"Final PayPal amount ${authorized_amount:.2f} exceeds policy tolerance "
            f"(expected ${tx['expected_amount']:.2f}, max authority "
            f"${(tx['authorized_amount'] or policy.max_transaction_amount):.2f})."
        )
        try:
            await paypal_orders.void_authorization(order["authorization_id"])
        except PayPalError as exc:
            logger.warning("Void failed for %s: %s", tx_id, exc)

        if tx.get("authorized_amount"):
            models.release_budget(agent_id, tx_id, tx["authorized_amount"])

        _set_tx_state(tx_id, "VERIFYING", "VOIDED", decision_reason=reason)
        models.update_task_status(task_id, "VOIDED")
        await emit("PAYMENT_VOIDED", reason, task_id=task_id, agent_id=agent_id, transaction_id=tx_id,
                    payload={"reason": reason, **variance})
