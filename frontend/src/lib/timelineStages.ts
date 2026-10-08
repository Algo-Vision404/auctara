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

  const stages: TimelineStage[] = [
    {
      key: "proposed",
      label: "Agent Proposed",
      icon: Bot,
      status: find("PROPOSAL_CREATED") ? "done" : "pending",
      timestamp: find("PROPOSAL_CREATED")?.created_at,
      detail: tx.merchant ? `${tx.merchant}: ${money(tx.amount, tx.currency || "USD")}` : undefined,
    },
    {
      key: "policy",
      label: "Policy Evaluated",
      icon: ShieldCheck,
      status: find("POLICY_EVALUATED") ? "done" : "pending",
      timestamp: find("POLICY_EVALUATED")?.created_at,
      detail: tx.decision ? `${tx.decision.replace("_", " ")}: ${tx.decision_reason || ""}` : undefined,
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
      status: find("POLICY_BLOCKED") ? "done" : "pending",
      timestamp: find("POLICY_BLOCKED")?.created_at,
      detail: "Block decision permanently recorded. No PayPal transaction created.",
    });
  }

  return stages;
}
