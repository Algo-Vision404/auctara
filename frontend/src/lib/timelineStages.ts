import { Bot, ShieldCheck, BadgeCheck, CreditCard, ScrollText } from "lucide-react";
import { Transaction } from "@/lib/types";
import { TimelineStage } from "@/components/transactions/DecisionTimeline";
import { money } from "@/lib/format";

/** Builds the "evidence chain" pipeline (Research → Proposal → Policy →
 * Approval → PayPal → Audit) for a transaction from its real audit timeline.
 * Shared by the transaction detail page and the Agent Operations Console
 * row-detail panel so both surfaces always tell the identical story. */
export function buildTimelineStages(tx: Transaction): TimelineStage[] {
  const timeline = tx.timeline || [];
  const find = (type: string) => timeline.find((r) => r.event_type === type);

  // The agent itself can refuse a task as outside its assigned purpose,
  // before any proposal or policy evaluation ever happens (see
  // orchestrator.OutOfScopeError on the backend). The first two stages below
  // need to reflect that distinctly from "not reached yet", otherwise an
  // already-terminal, declined transaction looks like it is stuck waiting.
  const declined = find("TASK_DECLINED_OUT_OF_SCOPE");
  // The agent's owner can also retire/delete the agent while a task is
  // still mid-flight (see orchestrator.retire_agent/delete_agent), at any
  // point in the pipeline, not just at the start like a scope decline. That
  // is handled as a post-process pass below, after the stages have been
  // built normally from whatever real events actually happened.
  const cancelled = find("TASK_CANCELLED_AGENT_REMOVED");
  // The agent can also pause mid-research to ask the human something (a
  // clarifying question, or a "found X instead, want it?" check-in) rather
  // than guessing or giving up. That is a real, "waiting on you" state for
  // this stage, not just "nothing has happened yet", as long as no proposal
  // has actually landed since (a later AGENT_ASKED_QUESTION after resuming
  // would mean another round is in progress; PROPOSAL_CREATED firing after
  // it means the question was already answered and resolved).
  const askedQuestion = find("AGENT_ASKED_QUESTION");
  const proposalCreated = find("PROPOSAL_CREATED");
  const awaitingReply = askedQuestion && !proposalCreated && !declined;

  const stages: TimelineStage[] = [
    {
      key: "proposed",
      label: "Agent Proposed",
      icon: Bot,
      status: declined ? "failed" : proposalCreated ? "done" : awaitingReply ? "current" : "pending",
      timestamp: declined?.created_at || proposalCreated?.created_at || askedQuestion?.created_at,
      detail: declined
        ? `Declined: ${tx.decision_reason || "outside this agent's assigned purpose"}`
        : proposalCreated
        ? tx.merchant
          ? `${tx.merchant}: ${money(tx.amount, tx.currency || "USD")}`
          : undefined
        : awaitingReply
        ? `Waiting for your reply: ${tx.pending_question || String(askedQuestion?.payload?.question ?? "")}`
        : undefined,
    },
    {
      key: "policy",
      label: "Policy Evaluated",
      icon: ShieldCheck,
      status: declined ? "skipped" : find("POLICY_EVALUATED") ? "done" : "pending",
      timestamp: find("POLICY_EVALUATED")?.created_at,
      detail: declined
        ? "Skipped: the agent declined this task before any proposal reached the policy engine."
        : tx.decision
        ? `${tx.decision.replace("_", " ")}: ${tx.decision_reason || ""}`
        : undefined,
    },
  ];

  if (tx.decision === "APPROVAL_REQUIRED") {
    const granted = find("APPROVAL_GRANTED");
    const rejected = find("APPROVAL_REJECTED");
    stages.push({
      key: "approval",
      label: "User Approval",
      icon: BadgeCheck,
      status: granted ? "done" : rejected ? "failed" : "current",
      timestamp: (granted || rejected)?.created_at,
      detail: granted ? "Approved by user" : rejected ? "Rejected by user" : "Awaiting human decision",
    });
  }

  if (tx.decision !== "BLOCK") {
    const captured = find("PAYMENT_CAPTURED");
    const voided = find("PAYMENT_VOIDED");
    const orderCreated = find("PAYPAL_ORDER_CREATED");
    stages.push({
      key: "paypal",
      label: "PayPal Executed",
      icon: CreditCard,
      status: captured ? "done" : voided ? "failed" : orderCreated ? "current" : "pending",
      timestamp: (captured || voided || orderCreated)?.created_at,
      detail: captured
        ? `Captured ${tx.paypal_capture_id || ""}`
        : voided
        ? "Voided: price verification failed"
        : orderCreated
        ? "PayPal order created, verifying…"
        : undefined,
    });
    stages.push({
      key: "audit",
      label: "Audit Verified",
      icon: ScrollText,
      status: find("TRANSACTION_COMPLETED") ? "done" : "pending",
      timestamp: find("TRANSACTION_COMPLETED")?.created_at,
      detail: find("TRANSACTION_COMPLETED") ? "Sealed with HMAC-chained audit record" : undefined,
    });
  } else {
    stages.push({
      key: "audit",
      label: "Audit Sealed",
      icon: ScrollText,
      status: find("POLICY_BLOCKED") || declined ? "done" : "pending",
      timestamp: (find("POLICY_BLOCKED") || declined)?.created_at,
      detail: declined
        ? "Decline decision permanently recorded. No proposal or PayPal transaction was ever created."
        : "Block decision permanently recorded. No PayPal transaction created.",
    });
  }

  if (cancelled) {
    // Whatever stage the pipeline had genuinely reached (done/failed) stays
    // exactly as it was - those are real, permanent outcomes. Anything that
    // hadn't happened yet gets relabeled "skipped" instead of being left
    // looking like it is still pending or in progress forever, since nothing
    // further will ever happen to this transaction now. The final audit
    // stage is handled separately: the cancellation itself is a real,
    // permanently sealed outcome, so it always ends up "done".
    const audit = stages[stages.length - 1];
    let labeled = false;
    for (const stage of stages) {
      if (stage === audit) continue;
      if (stage.status === "pending" || stage.status === "current") {
        stage.status = "skipped";
        stage.timestamp = stage.timestamp || cancelled.created_at;
        stage.detail = labeled
          ? "Skipped: the agent was removed before this step was reached."
          : `Cancelled: ${tx.decision_reason || "the agent was removed while this task was in progress."}`;
        labeled = true;
      }
    }
    if (audit.status !== "done") {
      audit.status = "done";
      audit.timestamp = cancelled.created_at;
      audit.detail = "Cancellation permanently recorded. No further action occurs on this transaction.";
    }
  }

  return stages;
}

