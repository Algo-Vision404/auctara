import {
  CircleCheck,
  ShieldX,
  Clock3,
  Search,
  BadgeCheck,
  CreditCard,
  ReceiptText,
  TriangleAlert,
  Bot,
  ScrollText,
  CircleDollarSign,
  FileText,
  PackageSearch,
  type LucideIcon,
} from "lucide-react";

export interface EventMeta {
  icon: LucideIcon;
  tone: "success" | "warning" | "danger" | "info" | "muted" | "accent";
  label: string;
}

const META: Record<string, EventMeta> = {
  TASK_CREATED: { icon: ScrollText, tone: "info", label: "Task created" },
  AGENT_STARTED: { icon: Bot, tone: "info", label: "Agent started" },
  CHANNEL3_SEARCH_STARTED: { icon: PackageSearch, tone: "info", label: "Channel3 product search" },
  CHANNEL3_SEARCH_COMPLETED: { icon: PackageSearch, tone: "accent", label: "Channel3 results" },
  CHANNEL3_SEARCH_FAILED: { icon: TriangleAlert, tone: "danger", label: "Channel3 search failed" },
  SEARCH_STARTED: { icon: Search, tone: "info", label: "Search started" },
  SEARCH_COMPLETED: { icon: Search, tone: "accent", label: "Search completed" },
  SEARCH_FAILED: { icon: TriangleAlert, tone: "danger", label: "Search failed" },
  PAGE_FETCH_STARTED: { icon: FileText, tone: "info", label: "Reading page" },
  PAGE_FETCH_COMPLETED: { icon: FileText, tone: "accent", label: "Page read" },
  PAGE_FETCH_FAILED: { icon: TriangleAlert, tone: "danger", label: "Page read failed" },
  PROPOSAL_CREATED: { icon: ReceiptText, tone: "accent", label: "Proposal created" },
  POLICY_EVALUATED: { icon: ShieldX, tone: "info", label: "Policy evaluated" },
  POLICY_ALLOWED: { icon: CircleCheck, tone: "success", label: "Policy allowed" },
  POLICY_BLOCKED: { icon: ShieldX, tone: "danger", label: "Policy blocked" },
  APPROVAL_REQUESTED: { icon: Clock3, tone: "warning", label: "Approval requested" },
  APPROVAL_GRANTED: { icon: BadgeCheck, tone: "success", label: "Approval granted" },
  APPROVAL_REJECTED: { icon: ShieldX, tone: "danger", label: "Approval rejected" },
  PAYPAL_ORDER_CREATED: { icon: CreditCard, tone: "info", label: "PayPal order created" },
  PAYPAL_APPROVAL_REQUIRED: { icon: Clock3, tone: "warning", label: "PayPal approval required" },
  PAYMENT_VERIFIED: { icon: CircleCheck, tone: "accent", label: "Payment verified" },
  PAYMENT_CAPTURED: { icon: CircleDollarSign, tone: "success", label: "Payment captured" },
  PAYMENT_VOIDED: { icon: ShieldX, tone: "danger", label: "Payment voided" },
  TRANSACTION_COMPLETED: { icon: CircleCheck, tone: "success", label: "Transaction completed" },
  TRANSACTION_FAILED: { icon: TriangleAlert, tone: "danger", label: "Transaction failed" },
};

export function eventMeta(type: string): EventMeta {
  return META[type] || { icon: ScrollText, tone: "muted", label: type.replace(/_/g, " ") };
}
