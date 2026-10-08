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

from openai import APIStatusError, AsyncOpenAI

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
from app.state_machine import InvalidTransition, transition
from app.streaming.events import bus

logger = logging.getLogger("agentauth.orchestrator")

MAX_TOOL_ITERATIONS = 8


def _humanize_llm_error(exc: Exception) -> str:
    """Turn a raw OpenRouter/OpenAI SDK exception into a short, human-readable
    message for the UI and activity log, while the full original exception is
    still logged server-side (and chained via `from exc`) for real debugging.
    Never fabricates a cause. Only reformats the genuine one.
    """
    if isinstance(exc, APIStatusError):
        inner = None
        if isinstance(exc.body, dict):
            inner = (exc.body.get("error") or {}).get("message") if isinstance(exc.body.get("error"), dict) else None
        inner = inner or getattr(exc, "message", None) or str(exc)
        if exc.status_code == 402:
            return (
                "OpenRouter rejected the request: the account doesn't have enough "
                "credit for this model/response length. Add credits at "
                "openrouter.ai/settings/credits or lower OPENROUTER_MODEL's cost."
            )
        if exc.status_code == 401:
            return "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in the backend's .env."
        if exc.status_code == 429:
            return "OpenRouter rate-limited this request. Try again in a moment."
        return f"OpenRouter returned an error (HTTP {exc.status_code}): {inner}"
    return f"AI model request failed: {type(exc).__name__}: {str(exc)[:200]}"


class AgentError(Exception):
    pass


class OutOfScopeError(Exception):
    """Raised when the agent itself declines a task via decline_out_of_scope_task
    because it has no reasonable connection to the agent's stated purpose and
    directive. Deliberately not an AgentError: this is the agent correctly
    refusing to act outside its delegated role, not a failure of the research
    pipeline, and it is reported to the user as a distinct, clean outcome
    rather than a generic error."""


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
    transition(current, target)
    return models.update_transaction(tx_id, state=target, **fields)


def _openrouter_client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise AgentError("OpenRouter is not configured. Set OPENROUTER_API_KEY.")
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

    try:
        proposal = await _run_research_loop(agent, task, tx_id)
    except OutOfScopeError as exc:
        await _decline_out_of_scope(tx_id, task_id, agent["id"], str(exc))
        return
    except (SearchError, AgentError) as exc:
        await _fail(tx_id, task_id, agent["id"], str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error in agent research loop")
        await _fail(tx_id, task_id, agent["id"], f"Agent execution failed: {type(exc).__name__}: {str(exc)[:200]}")
        return

    try:
        amount_usd = await _normalize_to_usd(proposal["amount"], proposal["currency"])
    except ExchangeRateError as exc:
        await _fail(tx_id, task_id, agent["id"], str(exc))
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


async def _run_research_loop(agent: dict, task: dict, tx_id: str) -> dict:
    client = _openrouter_client()
    settings = get_settings()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_task_prompt(agent["purpose"], agent["directive"], task["prompt"])},
    ]

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            response = await client.chat.completions.create(
                model=settings.openrouter_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=1024,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenRouter chat.completions.create failed")
            raise AgentError(_humanize_llm_error(exc)) from exc

        choice = response.choices[0]
        msg = choice.message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            raise AgentError(
                "Agent did not produce a purchase proposal. Last message: "
                + (msg.content or "(empty)")
            )

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
                            f"Channel3: searching real-time product catalog for \"{query}\"...",
                            task_id=task["id"], agent_id=agent["id"], transaction_id=tx_id,
                            payload={"query": query, "max_price": max_price})
                try:
                    products = await search_products(query, max_price=max_price)
                except Channel3Error as exc:
                    await emit("CHANNEL3_SEARCH_FAILED", str(exc), task_id=task["id"], agent_id=agent["id"],
                                transaction_id=tx_id, payload={"query": query, "error": str(exc)})
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({"error": str(exc)}),
                    })
                    continue
                await emit("CHANNEL3_SEARCH_COMPLETED",
                            f"Channel3 found {len(products)} real product candidate(s).",
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
        if tx and tx["state"] not in ("BLOCKED", "COMPLETED", "VOIDED", "FAILED"):
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
        try:
            capture = await paypal_orders.capture_authorization(order["authorization_id"])
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
