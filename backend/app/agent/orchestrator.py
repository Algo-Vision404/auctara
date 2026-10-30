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

import httpx
from openai import AsyncOpenAI

from app.agent.llm_errors import (
    NOT_CONFIGURED_MESSAGE,
    call_llm_with_retry,
    humanize_llm_error,
    require_first_choice,
)
from app.agent.prompts import SYSTEM_PROMPT, build_task_prompt
from app.agent.scope_guard import check_scope
from app.agent.tools import build_terminal_tool_schemas, build_tool_schemas
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

logger = logging.getLogger("auctara.orchestrator")

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
    """Validates the abstract state-machine edge AND atomically re-checks
    that the row's actual current state in the database still matches what
    the caller believes it is, in the same write. That re-check is what
    actually makes agent retirement/deletion safe: without it, a
    background task whose `current` was computed before its agent got
    retired (and its transaction force-cancelled out from under it, see
    _cancel_task) could otherwise blindly overwrite CANCELLED back onto an
    active state once its slow LLM/network call finally returns.

    It is also what stops two genuinely concurrent callers - a double-
    click, two open tabs on the same transaction, a retried request after
    a client-side timeout - from both reading the same starting state and
    both believing they are the one making this move. That matters
    whenever a real side effect (most importantly, execute_payment
    actually calling PayPal) follows right after: at most one caller can
    ever win the atomic UPDATE below, so at most one of them proceeds.
    """
    transition(current, target)
    updated = models.atomic_transition(tx_id, current, target, **fields)
    if updated is None:
        live = models.get_transaction(tx_id)
        raise InvalidTransition(
            f"Transaction {tx_id} is no longer in state {current} "
            f"(now {live['state'] if live else 'deleted'}); refusing to overwrite."
        )
    return updated


def _ensure_agent_active(agent_id: str) -> None:
    agent = models.get_agent(agent_id)
    if not agent or agent["status"] != "ACTIVE":
        raise AgentRetiredError("Agent was retired or deleted while this task was in progress.")


# Small/free models in particular have a well-known failure mode: asked for
# an optional tool argument it has no real value for, it writes the literal
# word "none"/"null"/"n/a" as a string instead of simply omitting the key.
# That string is not absent - proposal.get(...) returns it like any other
# real value - so without this, it flows straight into the database and
# back out to the UI as if it were a genuine image/listing URL. A frontend
# truthiness check (`tx.image_url &&`) does not catch it, since a non-empty
# string is truthy regardless of what it says: the ledger would render a
# real <img>/<a> pointing at the literal text "None", which the browser
# then requests as a real (nonsensical, 404ing) path. Scrub it once, here,
# at the single point every proposal's optional fields enter the system,
# rather than re-guard it in every place that might ever render one.
_NULLISH_STRINGS = {"none", "null", "n/a", "na", "undefined", "nil", ""}


def _clean_optional_str(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return value
    return None if value.strip().lower() in _NULLISH_STRINGS else value


def _is_blank_or_nullish(value: Any) -> bool:
    """Same failure mode as above, but for *required* fields (merchant,
    amount, currency, category, reason). The existing missing-field check
    below only ever caught `None` or `""` - it does not catch the model
    writing the literal string "None"/"null"/etc. for a required field it
    has no real answer for, which would otherwise sail through as a
    "present" value and show up as a real-looking merchant name or reason
    in the ledger. Used to extend that same check, not to silently null
    out a required field (that would violate the column's own NOT NULL
    invariant) - a required field that's blank/nullish is bounced back to
    the agent as a tool error, the same as any other missing field.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _NULLISH_STRINGS
    return False


# Channel3's entire catalog is real, physical retail inventory: every
# candidate it returns comes from an actual online retailer's stock, with a
# real price and buy_url (see app/search/channel3.py's own docstring). It
# has never carried software licenses, SaaS subscriptions, or any other
# purely digital good - there is no query tuning that fixes that, because
# the product category simply does not exist in its index. Searching it for
# one doesn't return a worse result than search_web; it can only ever
# return retail products that happen to share a word with the query. The
# tool description already tells the model to prefer search_web for this
# case, but relying on it noticing "these are all T-shirts" after the fact
# is unreliable and wastes a real API call every time it doesn't - a real
# run of exactly this (a "SaaS Subscription Manager" agent asked to renew
# "team management software") burned three separate Channel3 calls on a
# page of Marvel/Star Wars/Boston Red Sox t-shirts (the catalog's semantic
# match latched onto "team") before the model finally gave up and used
# search_web, and those irrelevant candidates stayed in this task's audit
# trail and research panel even though none of them were ever a real
# candidate. Short-circuiting here, before the real API call, is strictly
# more reliable than hoping the model self-corrects, and keeps a task's
# research record limited to sources that could actually have been used.
_NON_PHYSICAL_SIGNAL_WORDS = (
    "software", "saas", "subscription", "license", "licence", "api",
    "cloud", "hosting", "platform as a service", "paas", "app",
    "application", "dashboard", "plan", "seat", "seats", "tier",
)


def _looks_like_non_physical_query(query: str) -> bool:
    q = query.lower()
    return any(word in q for word in _NON_PHYSICAL_SIGNAL_WORDS)


def _groq_client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.groq_api_key:
        raise AgentError(NOT_CONFIGURED_MESSAGE)
    return AsyncOpenAI(
        base_url=settings.groq_base_url,
        api_key=settings.groq_api_key,
        # The SDK's own default read timeout is 600s. A provider call can
        # occasionally stall for minutes under provider-side load without
        # erroring - with the default, that left a task sitting in
        # RESEARCHING with zero activity and zero error for up to 10 minutes
        # per call, indistinguishable from a genuine hang to anyone watching
        # it. A much shorter timeout here turns that silent stall into an
        # APITimeoutError within seconds, which is already treated as a
        # transient error by call_llm_with_retry (same bucket as a 429/5xx)
        # - so a slow response now gets retried with backoff and visibly
        # logged, instead of just... not happening, for minutes, with
        # nothing to show for it.
        timeout=httpx.Timeout(connect=10.0, read=45.0, write=45.0, pool=45.0),
    )


async def _check_task_specificity(task_prompt: str) -> Optional[str]:
    """Deterministic pre-flight gate run once, before a brand-new task ever
    starts researching: this is real money, even in a sandbox, so a task
    that says neither what to buy nor what it may cost should never be
    guessed at based on vibes.

    This is a dedicated, narrowly-scoped, forced tool call - NOT a plain
    instruction buried inside the long main SYSTEM_PROMPT for the model to
    remember and apply correctly on its own initiative partway through a
    multi-step tool-calling conversation. That was tried first and observed
    in practice to not reliably work with weaker/free-tier models, which
    will happily dive straight into search_web for a task as bare as "buy
    me a software" despite being told not to. A single, narrow, forced
    yes/no classification with nothing else competing for the model's
    attention is something even a weak model gets right far more
    consistently.

    Returns a short clarifying question to ask the human if the task names
    neither a specific-enough product/use case nor a budget, or None if
    either is present and research may proceed normally. Fails OPEN (returns
    None) if the check itself cannot get a usable answer, rather than
    permanently blocking every task behind a broken gate - the research
    loop's own "genuinely stuck" ask-instead-of-guessing path is still there
    as a second line of defense if the task really was too vague.
    """
    try:
        client = _groq_client()
    except Exception:
        logger.warning("Specificity pre-check failed open (could not build a Groq client)", exc_info=True)
        return None
    settings = get_settings()
    schema = [{
        "type": "function",
        "function": {
            "name": "specificity_check",
            "description": (
                "Record whether this task names a specific enough product/service "
                "or use case, AND states a budget/price constraint, before any "
                "research happens."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "names_product_or_use": {
                        "type": "boolean",
                        "description": (
                            "True if the task says what KIND of thing to buy (a "
                            "product, service, or clear use case) - it does not need "
                            "to name an exact brand or model. False for a bare "
                            "category with no product/use in it at all, like 'buy me "
                            "a software', 'get me a subscription', or 'buy something "
                            "for the office'."
                        ),
                    },
                    "states_budget": {
                        "type": "boolean",
                        "description": (
                            "True if the task ITSELF states a budget or price "
                            "constraint - an exact amount, an upper limit, or a "
                            "comparative instruction like 'the cheapest X'. False if "
                            "no price constraint appears in the task text at all."
                        ),
                    },
                    "clarifying_question": {
                        "type": "string",
                        "description": (
                            "Required only if either field above is false: ONE "
                            "short, friendly question asking for whichever is "
                            "missing. Empty string if both fields are true."
                        ),
                    },
                },
                "required": ["names_product_or_use", "states_budget", "clarifying_question"],
            },
        },
    }]

    async def _make_call():
        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": (
                    "You check exactly one thing about a shopping task before any "
                    "research happens: does it name a specific enough product/use "
                    "case, and does it state a budget? Call specificity_check "
                    "exactly once with your answer. Do not research, browse, or "
                    "guess at real products or prices - that is a separate step "
                    "that only happens after this check passes."
                )},
                {"role": "user", "content": f"Task: \"{task_prompt}\""},
            ],
            tools=schema,
            tool_choice="required",
            temperature=0,
            max_tokens=256,
            extra_body={"reasoning_effort": "low"},
        )
        return require_first_choice(response)

    try:
        choice = await call_llm_with_retry(_make_call)
    except Exception:
        logger.warning("Specificity pre-check failed open (treating task as specific enough)", exc_info=True)
        return None

    if not choice.message.tool_calls:
        return None
    try:
        args = json.loads(choice.message.tool_calls[0].function.arguments or "{}")
    except json.JSONDecodeError:
        return None

    if args.get("names_product_or_use") and args.get("states_budget"):
        return None

    question = (args.get("clarifying_question") or "").strip()
    if not question:
        missing = []
        if not args.get("names_product_or_use"):
            missing.append("what kind of product or service you'd like")
        if not args.get("states_budget"):
            missing.append("how much you'd like to spend")
        question = "Could you tell me " + " and ".join(missing) + "?"
    return question


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
    await _continue_research(agent, task, tx_id, messages, check_specificity=True)


async def resume_task(task_id: str, reply: str) -> None:
    """Resume a task that is sitting in NEEDS_INPUT because the agent's last
    turn was a clarifying question (or a check-in like "I found X instead,
    want it?") rather than a tool call. Appends the human's reply to the
    exact conversation that was paused and re-enters the same research loop,
    so the model picks up with full context rather than starting over.

    Runs fire-and-forget via asyncio.create_task from POST
    /tasks/{id}/respond, which already rejects the request synchronously if
    the transaction is not in NEEDS_INPUT at that moment. That leaves one
    narrow window unprotected: two respond calls for the same task arriving
    close enough together that both pass that same check before either one's
    background task actually runs. _set_tx_state's own atomic re-check
    still stops the loser from corrupting anything, but without catching
    its InvalidTransition here, the loser would raise inside a task nothing
    is awaiting - an unretrieved exception logged by asyncio for what is,
    from the user's point of view, just a harmless duplicate submission.
    """
    task = models.get_task(task_id)
    if not task:
        return
    agent = models.get_agent(task["agent_id"])
    tx = models.get_transaction_for_task(task_id)
    if not tx or tx["state"] != "NEEDS_INPUT":
        return

    tx_id = tx["id"]
    messages: list[dict] = json.loads(tx["conversation_state"] or "[]")
    messages.append({"role": "user", "content": reply})

    try:
        _set_tx_state(tx_id, "NEEDS_INPUT", "RESEARCHING",
                       pending_question=None, conversation_state=None)
    except InvalidTransition:
        # Lost the race to another call already resuming this same task.
        # That call owns the conversation now; nothing left to do here.
        return
    models.update_task_status(task_id, "RESEARCHING")
    await emit("USER_REPLIED", reply, task_id=task_id, agent_id=agent["id"],
                transaction_id=tx_id, payload={"message": reply})

    await _continue_research(agent, task, tx_id, messages)


async def _continue_research(agent: dict, task: dict, tx_id: str, messages: list[dict],
                               *, check_specificity: bool = False) -> None:
    """Shared tail end of run_task/resume_task: run the research loop from
    wherever `messages` leaves off, then (if it actually produced a
    proposal rather than pausing/declining/failing) carry it through policy
    evaluation and execution. Split out so both a brand-new task and one
    resuming after a human reply land in identical downstream handling.

    `check_specificity` is only ever True from run_task's brand-new-task
    path - a human's reply to an earlier question (resume_task) already
    supplied whatever this gate would have asked for, so one gate at the
    very start is enough; anything still too vague to research after that
    falls through to the research loop's own "genuinely stuck" ask instead.
    """
    task_id = task["id"]
    policy_row = models.get_active_policy(agent["id"])
    if not policy_row:
        await _fail(tx_id, task_id, agent["id"], "No active policy configured for this agent.")
        return

    if check_specificity:
        question = await _check_task_specificity(task["prompt"])
        if question:
            messages.append({"role": "assistant", "content": question})
            await _ask_clarifying_question(tx_id, task_id, agent["id"], question, messages)
            return

    try:
        proposal = await _run_research_loop(
            agent, task, tx_id, messages, policy_row.get("categories", [])
        )
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

    # Everything from here on - normalizing the price, evaluating policy
    # (which reserves budget the instant it decides ALLOW/APPROVAL_REQUIRED),
    # and recording that decision - used to have no safety net of its own.
    # The research loop above is wrapped in a catch-all that fails the
    # transaction cleanly on any unexpected error; this block, reached only
    # after that loop already succeeded, was not. A bug or a transient
    # failure anywhere here (a DB write, a bad field on the proposal, an
    # unanticipated exception out of the policy engine) would propagate out
    # of run_task entirely - it runs fire-and-forget via
    # asyncio.create_task, so nothing would ever observe that exception,
    # the transaction would sit stuck in whatever state it last reached
    # forever, and if policy had already reserved budget for it, that hold
    # would never be released either. Wrapping this block the same way the
    # research loop already is closes that gap: _fail() (which does know
    # how to release a reservation) is now guaranteed to be the last word
    # for every transaction, not just the ones that happen to fail somewhere
    # the original code anticipated.
    try:
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
            source_url=_clean_optional_str(proposal.get("source_url")),
            image_url=_clean_optional_str(proposal.get("image_url")),
            retailer=_clean_optional_str(proposal.get("retailer")),
            channel3_product_id=_clean_optional_str(proposal.get("channel3_product_id")),
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
        decision = _evaluate_policy_atomic(
            agent["id"], tx_id, amount_usd, proposal["category"], policy_row,
            merchant=proposal.get("merchant") or "",
            product_name=proposal.get("product_name") or "",
            reason=proposal.get("reason") or "",
        )

        # Independent scope check, separate from everything policy_engine
        # just decided: budget/category/velocity answer "is this transaction
        # allowed under this agent's spending rules", never "does this
        # transaction actually serve what this agent was delegated to do".
        # That question's only prior guard was the same research-loop model
        # self-reporting via decline_out_of_scope_task - this is the
        # external, independent check behind it. Skipped when policy already
        # landed on BLOCK: that is already the strictest possible outcome,
        # so there is nothing a scope opinion could usefully add.
        if decision["decision"] != "BLOCK":
            scope_verdict = await check_scope(
                _groq_client, get_settings().groq_model,
                agent_purpose=agent["purpose"], agent_directive=agent["directive"],
                merchant=proposal.get("merchant") or "", product_name=proposal.get("product_name") or "",
                category=proposal["category"], amount=proposal["amount"], currency=proposal["currency"],
                proposal_reason=proposal.get("reason") or "",
            )
            await emit(
                "SCOPE_CHECKED",
                scope_verdict.reason,
                task_id=task_id, agent_id=agent["id"], transaction_id=tx_id,
                payload={"ok": scope_verdict.ok, "in_scope": scope_verdict.in_scope, "reason": scope_verdict.reason},
            )
            # Fail closed: a check that could not run is treated exactly
            # like one that disagreed, never as a silent pass. An ALLOW
            # moves to APPROVAL_REQUIRED instead of executing unattended -
            # the independent check (or the inability to run it) is reason
            # enough for a human to look before any money moves, even
            # though the dollar amount itself was within autonomous
            # authority. An APPROVAL_REQUIRED stays APPROVAL_REQUIRED either
            # way (a human was already going to review it), but still picks
            # up the scope note so the reason a human sees is complete.
            if not scope_verdict.in_scope:
                decision = {
                    **decision,
                    "decision": "APPROVAL_REQUIRED" if decision["decision"] == "ALLOW" else decision["decision"],
                    "reason": (
                        f"{decision['reason']} However, an independent scope check flagged this "
                        f"proposal for human review: {scope_verdict.reason}"
                    ),
                }


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
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error finalizing agent proposal/policy decision")
        await _fail(
            tx_id, task_id, agent["id"],
            "Something unexpected went wrong while recording this agent's purchase decision. "
            "Please try again, and contact your administrator if it keeps happening.",
        )
        return

    # execute_payment (and _finalize_payment, which it may call directly)
    # deliberately stays outside the try/except above: by the time it runs,
    # real PayPal calls that can actually move money are in play, and it
    # already manages its own terminal transitions and budget bookkeeping
    # with that in mind (e.g. releasing the hold on a void, but never on a
    # completed capture). Routing an exception from inside it through the
    # same generic `_fail()` used above would be wrong here specifically:
    # `_fail()` cannot tell "nothing happened yet" apart from "PayPal has
    # already captured this money", and blindly releasing budget for a
    # transaction PayPal actually completed would silently under-count real
    # spend against the agent's budget while the charge still stands.
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
            model=settings.groq_model,
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
            extra_body={"reasoning_effort": "low"},
        )
        cleaned = (require_first_choice(response).message.content or "").strip()
        # Sanity check: a real cleanup should be short. If the model
        # couldn't follow even this instruction, better to show the human
        # the original raw text than a second layer of garbage.
        if cleaned and len(cleaned) < len(raw):
            return cleaned
    except Exception:  # noqa: BLE001
        logger.warning("Failed to sanitize a leaked-reasoning message; using raw text", exc_info=True)
    return raw


def _channel3_products_seen(messages: list[dict]) -> dict[str, dict]:
    """Every real product record this task's own channel3_search_products
    calls have actually returned so far - keyed by channel3_product_id,
    full normalized record (image_url, retailer, buy_url, ...) as the
    value - scanned straight from the conversation's own tool-result
    messages, the one source of continuity that survives a NEEDS_INPUT
    pause/resume (a function-local dict would not, since
    _run_research_loop starts a fresh call, and therefore fresh locals,
    every time it resumes; `messages` is the only thing the orchestrator
    actually persists and reloads).

    Used to catch two different ways a proposal's Channel3 fields could be
    a lie: (1) a channel3_product_id that does not correspond to anything
    actually searched for, and (2) a channel3_product_id that IS real, but
    paired with an image_url/retailer/source_url that does not actually
    belong to that specific product record - e.g. carried over from a
    different, nicer-looking candidate, or simply invented. Either one
    would sail straight past a check that only looks at id membership.
    """
    products: dict[str, dict] = {}
    for m in messages:
        if m.get("role") != "tool":
            continue
        try:
            payload = json.loads(m.get("content") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        for p in payload.get("products") or []:
            pid = p.get("channel3_product_id")
            if pid:
                products[pid] = p
    return products


def _channel3_product_ids_seen(messages: list[dict]) -> set[str]:
    """Thin convenience wrapper over _channel3_products_seen for callers
    that only need to know which ids are real, not their full record."""
    return set(_channel3_products_seen(messages).keys())


async def _run_research_loop(
    agent: dict, task: dict, tx_id: str, messages: list[dict], categories: list[str],
) -> dict:
    """Runs up to MAX_TOOL_ITERATIONS more turns of the tool-calling loop,
    mutating `messages` in place as it goes. `messages` may already contain
    prior turns from an earlier call that paused on NeedsInputError and was
    since resumed with a human reply appended - this function has no memory
    of its own, all continuity lives in the caller-owned message list.

    `categories` is this agent's own policy.categories: the exact
    create_purchase_proposal `category` enum built for this run, scoped to
    what this specific agent actually buys rather than one list shared by
    every agent on the platform (see app/agent/tools.py build_tool_schemas).
    """
    client = _groq_client()
    settings = get_settings()
    tool_schemas = build_tool_schemas(categories)
    terminal_tool_schemas = build_terminal_tool_schemas(categories)

    for step in range(MAX_TOOL_ITERATIONS):
        # Cheap, cooperative check before every round-trip to the model: if
        # the agent has been retired or deleted since this loop started,
        # stop now instead of burning another LLM call researching (or
        # worse, going on to propose/spend) for an agent that no longer
        # exists or was told to stop.
        _ensure_agent_active(agent["id"])

        # Weaker/less decisive models can burn the whole research budget
        # re-searching instead of ever concluding - a real, observed
        # failure: a "find the cheapest X" task kept searching for an even
        # better price round after round and ran out with real options
        # already in hand but nothing ever submitted. A soft reminder with
        # 2 calls left gives it a chance to wrap up on its own terms; the
        # actual guarantee is the hard stop below on the truly last call,
        # since a model that already ignored one warning cannot be trusted
        # to honor a second plain-text one.
        remaining = MAX_TOOL_ITERATIONS - step
        is_final_call = remaining == 1
        if is_final_call:
            # Nothing left after this. Research tools are removed from the
            # schema entirely (not just discouraged by instruction) and
            # tool_choice is forced, so the model literally cannot choose
            # to search/fetch again or reply with plain text asking for
            # more time - its only two options are to commit to its best
            # real option found so far, or explicitly decline. Either way
            # the human gets a concrete result instead of silence after
            # real research already happened.
            messages.append({
                "role": "system",
                "content": (
                    "This is your LAST available action - there are no tool calls left "
                    "after this one, and searching/fetching are no longer available. You "
                    "MUST either call create_purchase_proposal now with the single best "
                    "real option you already found above (do not invent one), or call "
                    "decline_out_of_scope_task if nothing you found is usable. Do not "
                    "attempt to search, fetch, or reply with plain text - neither is "
                    "possible anymore."
                ),
            })
        elif remaining <= 2:
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
        async def _make_call():
            response = await client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                tools=terminal_tool_schemas if is_final_call else tool_schemas,
                tool_choice="required" if is_final_call else "auto",
                temperature=0.2,
                max_tokens=1024,
                # The configured Groq model (openai/gpt-oss-120b) is a
                # "reasoning" model that by default spends real completion
                # tokens on an internal chain-of-thought, returned separately
                # as its own `reasoning` field (Groq keeps it cleanly
                # separate from `content`, never bleeding into it). This
                # agent has no use for visible reasoning, only a final tool
                # call or a short clean message, so this keeps it minimal.
                # Unlike OpenRouter's analogous `reasoning` field, Groq
                # rejects a `reasoning_effort` value outright on a model that
                # doesn't support it rather than silently ignoring it, so
                # swapping GROQ_MODEL to a non-reasoning model means this
                # needs to come out too.
                extra_body={"reasoning_effort": "low"},
            )
            # Validated here, inside the retried callable, not after
            # call_llm_with_retry returns: some providers occasionally send
            # back a 200 OK with no choices at all (no exception, nothing to
            # indicate a problem). Checking it here means that case gets
            # exactly the same retried-with-backoff treatment as a 429/5xx,
            # instead of crashing this loop with a raw TypeError on
            # response.choices[0].
            return require_first_choice(response)

        try:
            choice = await call_llm_with_retry(_make_call)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Groq chat.completions.create failed")
            raise AgentError(humanize_llm_error(exc)) from exc

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
                if _looks_like_non_physical_query(query):
                    await emit("CHANNEL3_SEARCH_SKIPPED",
                                f"Skipped the product catalog for \"{query}\": it only carries physical "
                                "retail goods, never software or digital subscriptions.",
                                task_id=task["id"], agent_id=agent["id"], transaction_id=tx_id,
                                payload={"query": query})
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({
                            "error": "Channel3's catalog only carries physical retail products from "
                                     "real online retailers - it has never carried software, SaaS, or "
                                     "any other digital subscription. Use search_web and fetch_page "
                                     "instead for this purchase.",
                        }),
                    })
                    continue
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
                missing = [f for f in required if f not in args or _is_blank_or_nullish(args[f])]
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

                # The schema's own description for these fields is
                # explicit: they only ever belong on a proposal "if this
                # candidate came from channel3_search_products" - never
                # trust that claim blindly, since the UI shows a "Verified
                # live listing" badge directly off channel3_product_id
                # being present (see ProposalSummary.tsx). Cross-check
                # against every real product this task's own
                # channel3_search_products calls have actually returned
                # (not a fresh variable each loop iteration - see
                # _channel3_products_seen - so this still works correctly
                # across a NEEDS_INPUT pause/resume).
                claimed_id = _clean_optional_str(args.get("channel3_product_id"))
                claimed_image = _clean_optional_str(args.get("image_url"))
                claimed_retailer = _clean_optional_str(args.get("retailer"))
                real_products = _channel3_products_seen(messages)

                if claimed_id and claimed_id not in real_products:
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({
                            "error": (
                                f"channel3_product_id '{claimed_id}' does not match any product "
                                "a channel3_search_products call in this conversation actually "
                                "returned. Only set channel3_product_id (and image_url/retailer) "
                                "when this proposal really is that exact candidate - omit all "
                                "three fields entirely for anything found via search_web/fetch_page."
                            )
                        }),
                    })
                    continue

                # image_url and retailer are NEVER produced by any tool
                # other than channel3_search_products - search_web only
                # returns {title, url, snippet} and fetch_page only returns
                # stripped page text, neither carries an image or a
                # retailer-domain field. So either field present without a
                # verified channel3_product_id has no legitimate source at
                # all - it can only be invented. Reject it the same way,
                # rather than letting it render a fabricated product photo
                # (ProposalSummary.tsx shows tx.image_url as a real <img>
                # unconditionally, with no badge gating it the way
                # channel3_product_id gates "Verified live listing").
                if (claimed_image or claimed_retailer) and not claimed_id:
                    messages.append({
                        "role": "tool", "tool_call_id": call.id,
                        "content": json.dumps({
                            "error": (
                                "image_url/retailer can only be set together with the real "
                                "channel3_product_id they came from - no other tool in this "
                                "agent ever returns a product image or retailer domain, so "
                                "either field without a matching channel3_product_id can only "
                                "be invented. Omit both for anything found via search_web/"
                                "fetch_page, or include the real channel3_product_id if this "
                                "candidate really did come from channel3_search_products."
                            )
                        }),
                    })
                    continue

                # The id itself being real is not enough on its own: a
                # model could still pair a genuine channel3_product_id with
                # an image_url/retailer/source_url lifted from a different
                # candidate (e.g. a cheaper item's id next to a nicer
                # item's photo), or a listing link that quietly points
                # somewhere else entirely - the one URL the "View listing"
                # button actually sends a human to. Require every
                # Channel3-sourced field to match that exact product's own
                # recorded value, not just any value that happens to be
                # present somewhere in this task's research.
                if claimed_id:
                    real_product = real_products[claimed_id]
                    claimed_source = _clean_optional_str(args.get("source_url"))
                    mismatched = []
                    if claimed_image and claimed_image != real_product.get("image_url"):
                        mismatched.append("image_url")
                    if claimed_retailer and claimed_retailer != real_product.get("retailer"):
                        mismatched.append("retailer")
                    if claimed_source and real_product.get("buy_url") and claimed_source != real_product["buy_url"]:
                        mismatched.append("source_url")
                    if mismatched:
                        messages.append({
                            "role": "tool", "tool_call_id": call.id,
                            "content": json.dumps({
                                "error": (
                                    f"{', '.join(mismatched)} do not match the real Channel3 "
                                    f"listing for channel3_product_id '{claimed_id}'. image_url "
                                    "and retailer must be copied exactly from that search "
                                    "result, and source_url must be its buy_url - never mixed "
                                    "with another candidate's values or a different link."
                                )
                            }),
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

    # Reached when the model's forced final call (tool_choice="required",
    # terminal tools only) still didn't land a valid create_purchase_proposal
    # or decline_out_of_scope_task - e.g. every candidate it tried to submit
    # failed validation (hallucinated/mismatched fields, no real product
    # pinned down) and it ran out of turns to try again. That is exactly the
    # same "genuinely stuck, needs a human" situation NeedsInputError already
    # exists for elsewhere in this loop, so it gets the same treatment: pause
    # in NEEDS_INPUT with the full conversation preserved (including every
    # validation error the model already saw) instead of failing the task
    # outright and forcing the human to retype the whole request from
    # scratch in a brand new task. _ask_clarifying_question still enforces
    # MAX_CLARIFICATION_ROUNDS, so a task that keeps landing here on repeat
    # resumes still fails eventually rather than asking forever.
    raise NeedsInputError(
        "This agent searched but couldn't settle on a specific enough result in time. "
        "Could you name a specific product, or give a price range instead of \"cheapest\"?"
    )



async def _normalize_to_usd(amount: float, currency: str) -> float:
    if currency.upper() == "USD":
        return amount
    return await convert(amount, currency, "USD")


def _evaluate_policy_atomic(agent_id: str, tx_id: str, amount_usd: float, category: str,
                              policy_row: dict, merchant: str = "", product_name: str = "",
                              reason: str = "") -> dict:
    """Evaluate + (if authorized) reserve budget atomically so concurrent
    transactions can never jointly overspend the daily/monthly budget.

    merchant/product_name/reason are passed through so the policy engine's
    blocked_term_match check (see rules.py) has real text to scan - a
    blocked_categories entry that isn't one of the fixed classification
    categories (e.g. "gambling") can only ever be enforced against what
    the proposal actually says, never against ctx.category alone.

    The transaction row's own authorized_amount is written in the exact
    same BEGIN IMMEDIATE block as the budget reservation, not left to the
    caller's own (separate, later) update_transaction call. _fail() decides
    whether a reservation needs releasing purely by reading that column off
    the transaction row - if reserve_budget and that column could ever be
    written in two different commits, any crash landing between them would
    leave a real reservation in the ledger that nothing could ever discover
    belonged to this transaction. Committing them together closes that
    window entirely: by the moment this function returns, the ledger and
    the transaction row always agree.
    """
    policy = policy_from_row(policy_row)
    with immediate_transaction():
        ctx = build_context(
            agent_id, amount_usd, category, policy,
            merchant=merchant, product_name=product_name, reason=reason,
        )
        decision = policy_engine.evaluate(policy, ctx)
        if decision["decision"] in ("ALLOW", "APPROVAL_REQUIRED"):
            models.reserve_budget(agent_id, tx_id, decision["authorized_amount"])
            models.update_transaction(tx_id, authorized_amount=decision["authorized_amount"])
    return decision


async def _fail(tx_id: str, task_id: str, agent_id: str, message: str) -> None:
    """Mark a transaction FAILED. Every other way a transaction stops short
    of COMPLETED (decline, cancel-on-agent-removal, price-variance VOID)
    releases any budget it had reserved - this is the one terminal path
    that didn't, which meant every failure from here on (PayPal order
    creation, authorization, or capture failing, or any of the earlier
    research-loop/proposal failures) permanently locked that amount out of
    the agent's daily/monthly budget forever, even though no money was
    ever actually spent. Released here, guarded the same way as every
    other release site: only on the real, first transition into a
    terminal state (never on a duplicate call to an already-terminal
    transaction, which would double-release/over-credit the ledger), and
    only if a reservation actually exists (most of this function's callers
    fail a transaction before policy ever reserved anything).
    """
    tx = models.get_transaction(tx_id)
    try:
        if tx and tx["state"] not in TERMINAL_STATES:
            transition(tx["state"], "FAILED")
            if tx.get("authorized_amount"):
                models.release_budget(agent_id, tx_id, tx["authorized_amount"])
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
    """The agent itself declined to produce a proposal, via the same
    decline_out_of_scope_task tool call for two different real situations:
    the task was plainly outside its delegated purpose (decided on its very
    first turn, before any research), or the task WAS in scope and really
    was researched, but nothing suitable turned up within budget by the
    time its last available turn forced a propose-or-decline choice. Both
    land here as BLOCKED with no proposal ever made - the frontend tells
    them apart after the fact from whether any research events exist on
    this transaction's own activity timeline, rather than this function
    needing a separate code path for each.

    Reported as BLOCKED, the same terminal state a deterministic policy
    block ends in (no PayPal transaction is ever created either way), but
    under its own distinct event type so the Activity feed and Audit trail
    never conflate 'the agent declined this' with 'the deterministic policy
    engine blocked this'. Those are two different layers of this platform's
    guardrails, and which one actually fired is exactly the kind of thing
    this platform exists to make visible.
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


async def reactivate_agent(agent_id: str) -> dict:
    """The mirror image of retire_agent: flips a RETIRED agent back to
    ACTIVE so it resumes accepting new tasks. Nothing it had cancelled while
    retired comes back with it - the transactions/tasks that were force-
    cancelled and the scheduled tasks that were force-cancelled by
    _cancel_in_flight_work stay exactly as they are, CANCELLED is a terminal
    state in the transaction state machine, and recurring schedules are not
    silently resurrected. Reactivating only restores the ability to accept
    *new* work going forward; anything the owner wants running again (a
    recurring schedule in particular) has to be recreated deliberately."""
    agent = models.get_agent(agent_id)
    if not agent:
        raise AgentError("Agent not found.")
    if agent["status"] != "RETIRED":
        return agent

    models.update_agent_status(agent_id, "ACTIVE")
    await emit("AGENT_REACTIVATED", f"{agent['name']} was reactivated and can accept new tasks again.",
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
    """Called once the shopper has approved the order on PayPal (redirect flow).

    The frontend already guards against calling this twice from the same
    page instance (a ref flag that survives React Strict Mode's double-
    effect dev behavior), but that can't protect against a page refresh
    while `?paypal=return` is still in the URL, the user hitting back/
    forward, or PayPal itself redirecting twice - any of which hits this
    endpoint again as a genuinely new, independent request. Without a
    server-side claim, two such calls could both see state=VERIFYING and
    both call PayPal's authorize/capture APIs for the same order.
    """
    tx = models.get_transaction(tx_id)
    if not tx or not tx.get("paypal_order_id"):
        raise AgentError("Transaction is not awaiting a PayPal approval.")
    if tx["state"] != "VERIFYING":
        # Already moved past VERIFYING - almost certainly a duplicate call
        # arriving after an earlier one already finished (or failed) it.
        # Report the real current state rather than erroring: from the
        # caller's point of view the payment has already been handled, and
        # a harmless duplicate request should not surface a scary "Failed
        # to confirm PayPal payment" message for a transaction that is
        # actually fine (or was already correctly marked FAILED/VOIDED).
        return tx
    if not models.claim_paypal_continue(tx_id):
        # Still VERIFYING, but another call already claimed it a moment
        # ago and may still be mid-flight. Do not race it by also calling
        # PayPal's authorize/capture APIs for the same order - just report
        # the current state; the call that won the claim will move it
        # forward (or already has, by the time this is read).
        return models.get_transaction(tx_id)
    try:
        order = await paypal_orders.authorize_order(tx["paypal_order_id"])
    except PayPalError as exc:
        await _fail(tx_id, tx["task_id"], tx["agent_id"], f"PayPal authorization failed: {exc}")
        return models.get_transaction(tx_id)
    await _finalize_payment(tx_id, order)
    return models.get_transaction(tx_id)


async def check_paypal_order_progress(tx_id: str) -> dict:
    """Safe to call at any time, including rapid repeated polling, while a
    transaction sits in VERIFYING waiting on the buyer to approve at
    PayPal - unlike continue_after_paypal_approval above (which assumes
    approval already happened, because it only ever runs off a genuine
    PayPal redirect return) or reconcile_stale_verifying_transaction below
    (which gives up and fails the transaction once it has been waiting
    past the timeout), this never fails a transaction just because the
    buyer has not finished yet; it only ever reports "still waiting" so a
    caller's poll loop can simply try again shortly.

    This is what lets the frontend open PayPal's approve_url in its own
    separate tab/window instead of navigating the whole app away, and then
    discover completion itself by polling this from the original tab -
    without ever depending on PayPal's own return redirect successfully
    reaching this app. That matters because this app's own sandboxed
    preview host can require a traffic-access token on direct browser
    navigation that an external site's redirect response can never attach,
    silently stranding the buyer on an error page after a real, successful
    approval - this endpoint gives the original tab an independent way to
    notice that the payment actually went through anyway.
    """
    tx = models.get_transaction(tx_id)
    if not tx or not tx.get("paypal_order_id"):
        raise AgentError("Transaction is not awaiting a PayPal approval.")
    if tx["state"] != "VERIFYING":
        return tx  # already resolved, one way or another - nothing to check

    try:
        order = await paypal_orders.get_order(tx["paypal_order_id"])
    except PayPalError:
        # A transient lookup hiccup is not this transaction's problem - just
        # report the current (unchanged) state and let the next poll retry.
        logger.warning("PayPal order lookup failed during a progress check", exc_info=True)
        return tx

    if not (order.get("authorization_id") or order.get("status") == "APPROVED"):
        return tx  # buyer has not finished approving yet - still waiting

    if not models.claim_paypal_continue(tx_id):
        # A concurrent call - a genuine PayPal redirect landing at the same
        # moment, another poll, or a scheduler sweep tick - already claimed
        # it. Do not race it; just report whatever it already produced.
        return models.get_transaction(tx_id)

    if order.get("authorization_id"):
        # Already approved *and* authorized - finish it exactly as the
        # redirect-driven path would.
        await _finalize_payment(tx_id, order)
        return models.get_transaction(tx_id)

    try:
        authorized = await paypal_orders.authorize_order(tx["paypal_order_id"])
    except PayPalError as exc:
        await _fail(tx_id, tx["task_id"], tx["agent_id"], f"PayPal authorization failed: {exc}")
        return models.get_transaction(tx_id)
    await _finalize_payment(tx_id, authorized)
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
                       paypal_capture_id=capture.get("capture_id"), paypal_status=capture.get("status"),
                       paypal_fee=capture.get("paypal_fee"), net_amount=capture.get("net_amount"))
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


async def reconcile_stale_verifying_transaction(tx: dict) -> None:
    """Resolve one transaction that has sat in VERIFYING since before the
    scheduler's staleness cutoff (see list_stale_verifying_transactions /
    Settings.paypal_verification_timeout_minutes) - the normal path out of
    VERIFYING is the buyer returning from PayPal's approval page and the
    frontend calling continue_after_paypal_approval, but nothing ever
    forced that to happen: a closed tab, a lost connection, or a redirect
    that simply never arrives leaves a transaction (and the budget it
    reserved) stuck there forever with no other way out.

    Shares the exact same claim (claim_paypal_continue) a real buyer-return
    call uses, so this can never race a legitimate in-flight redirect: only
    one of {a genuine return, a concurrent sweep tick, this call} can ever
    win it for a given transaction.

    Checks PayPal for what actually happened before assuming the worst -
    the buyer may well have approved (even authorized) the order with our
    own redirect callback simply never arriving, in which case this
    finishes the payment exactly as the normal flow would have, rather
    than wrongly failing (and refunding the budget hold on) a purchase
    that actually went through.
    """
    tx_id = tx["id"]
    if not models.claim_paypal_continue(tx_id):
        return  # a real buyer-return (or another sweep tick) already has it

    try:
        order = await paypal_orders.get_order(tx["paypal_order_id"])
    except PayPalError as exc:
        await _fail(tx_id, tx["task_id"], tx["agent_id"],
                    f"Lost touch with PayPal while checking on this order: {exc}")
        return

    if order.get("authorization_id"):
        # The buyer did approve *and* authorize - only our own redirect
        # callback never arrived. Complete it exactly as that would have.
        await _finalize_payment(tx_id, order)
        return

    if order.get("status") == "APPROVED":
        # The buyer approved but PayPal never got (or we never received)
        # the follow-up authorize call. Make it ourselves, same as the
        # redirect-driven path does.
        try:
            authorized = await paypal_orders.authorize_order(tx["paypal_order_id"])
        except PayPalError as exc:
            await _fail(tx_id, tx["task_id"], tx["agent_id"], f"PayPal authorization failed: {exc}")
            return
        await _finalize_payment(tx_id, authorized)
        return

    # The buyer never approved within the timeout window. PayPal's own
    # order will eventually expire on its own, but there is no reason to
    # wait on that - this will never resolve itself, so say so plainly
    # (and release the budget it was holding) instead of leaving it stuck.
    await _fail(
        tx_id, tx["task_id"], tx["agent_id"],
        "Timed out waiting for PayPal approval - no response was received in time.",
    )


async def reconcile_stale_verifying_transactions() -> int:
    """Find every transaction stuck in VERIFYING past the configured
    timeout and resolve each one. Called on every scheduler tick (see
    app/scheduler.py) - returns the count handled, for logging/tests."""
    settings = get_settings()
    cutoff = models.window_start_iso(settings.paypal_verification_timeout_minutes)
    stale = models.list_stale_verifying_transactions(cutoff)
    for tx in stale:
        await reconcile_stale_verifying_transaction(tx)
    return len(stale)


# States where a background coroutine (the research/propose/policy loop
# kicked off by run_task/resume_task via asyncio.create_task) must be the
# one actively driving the transaction forward - there is no other trigger
# that will ever move it. This deliberately excludes:
#   - NEEDS_INPUT and AWAITING_APPROVAL: both are intentional pauses for a
#     human (a clarifying reply, an approval click) with their own full
#     state persisted, not lost work - they resume correctly on demand
#     whenever that human acts, restart or no restart, so "stuck" here is
#     not actually stuck.
#   - VERIFYING: already has its own reconciler above, because resolving
#     it correctly requires checking PayPal's own state first (the buyer
#     may have actually approved with only our redirect callback lost),
#     not just giving up.
#   - every terminal state (COMPLETED, FAILED, BLOCKED, VOIDED, CANCELLED):
#     nothing to reconcile.
# A process that dies mid-flight in any of the states below - a crash, a
# deploy, a sandbox reset - takes that in-memory conversation/work with it
# permanently; nothing persisted can ever resume it. The only honest thing
# to do once one has gone quiet for Settings.orphaned_task_timeout_minutes
# is fail it cleanly (releasing any reserved budget, the same as every
# other way a transaction stops short of COMPLETED) and tell the human to
# resubmit, instead of leaving it stuck forever with no explanation.
ORPHANABLE_STATES = ["CREATED", "RESEARCHING", "PROPOSED", "POLICY_CHECK", "AUTHORIZED"]


async def reconcile_orphaned_transaction(tx: dict) -> None:
    """Resolve one transaction found sitting in an ORPHANABLE_STATE with no
    activity at all for Settings.orphaned_task_timeout_minutes. Re-checks
    the task's actual last *activity* event, not just the transaction's
    own updated_at (which only moves on a state change, not on every step
    a research loop takes while it stays in the same state) - so a
    transaction that is still genuinely working, just slowly, is correctly
    left alone here rather than failed out from under it.

    _fail() re-reads the transaction fresh and only acts if it is still
    non-terminal, so a transaction that legitimately finished (or was
    already reconciled by a concurrent tick) in the moment between this
    sweep listing it and this call running is simply a no-op, not a bug.
    """
    settings = get_settings()
    cutoff = models.window_start_iso(settings.orphaned_task_timeout_minutes)
    last_seen = models.get_last_activity_at(tx["task_id"]) or tx["updated_at"]
    if last_seen > cutoff:
        return  # still genuinely active, just slow - leave it alone
    await _fail(
        tx["id"], tx["task_id"], tx["agent_id"],
        "This task went quiet mid-flight and was never able to finish - most likely "
        "a server restart interrupted it before any result came back. No purchase "
        "was made or proposed. Please resubmit it.",
    )


async def reconcile_orphaned_transactions() -> int:
    """Find every transaction stuck in an ORPHANABLE_STATE with no activity
    for Settings.orphaned_task_timeout_minutes and resolve each one. Called
    on every scheduler tick alongside reconcile_stale_verifying_transactions
    (see app/scheduler.py) - returns the count actually resolved. Some
    candidates found by the coarse per-state/updated_at query turn out to
    still be genuinely active once checked individually (see
    reconcile_orphaned_transaction) and are correctly left alone, so this
    can be less than the number of candidates found."""
    settings = get_settings()
    cutoff = models.window_start_iso(settings.orphaned_task_timeout_minutes)
    candidates = models.list_stale_active_transactions(ORPHANABLE_STATES, cutoff)
    resolved = 0
    for tx in candidates:
        await reconcile_orphaned_transaction(tx)
        after = models.get_transaction(tx["id"])
        if after and after["state"] == "FAILED":
            resolved += 1
    return resolved
