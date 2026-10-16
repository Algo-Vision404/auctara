import {
  CircleCheck,
  Shield,
  ShieldX,
  Clock3,
  Search,
  BadgeCheck,
  CreditCard,
  ReceiptText,
  TriangleAlert,
  Bot,
  Ban,
  ScrollText,
  CircleDollarSign,
  FileText,
  PackageSearch,
  UserX,
  UserCheck,
  Trash2,
  XCircle,
  MessageCircleQuestion,
  MessageCircle,
  ShieldQuestion,
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
  CHANNEL3_SEARCH_STARTED: { icon: PackageSearch, tone: "info", label: "Product search" },
  CHANNEL3_SEARCH_COMPLETED: { icon: PackageSearch, tone: "accent", label: "Product results" },
  CHANNEL3_SEARCH_FAILED: { icon: TriangleAlert, tone: "danger", label: "Product search failed" },
  // The agent asked to search the physical-retail product catalog for
  // something that is obviously software/SaaS/a digital subscription -
  // Channel3 has never carried any of those, so the call is rejected
  // before it ever reaches the real API, rather than letting it come back
  // with a page of irrelevant retail junk. Its own icon/tone distinguishes
  // "we didn't bother" from an actual CHANNEL3_SEARCH_FAILED (a real API
  // error), which is a different, unexpected condition worth its own color.
  CHANNEL3_SEARCH_SKIPPED: { icon: PackageSearch, tone: "muted", label: "Product search skipped" },
  SEARCH_STARTED: { icon: Search, tone: "info", label: "Search started" },
  SEARCH_COMPLETED: { icon: Search, tone: "accent", label: "Search completed" },
  SEARCH_FAILED: { icon: TriangleAlert, tone: "danger", label: "Search failed" },
  PAGE_FETCH_STARTED: { icon: FileText, tone: "info", label: "Reading page" },
  PAGE_FETCH_COMPLETED: { icon: FileText, tone: "accent", label: "Page read" },
  PAGE_FETCH_FAILED: { icon: TriangleAlert, tone: "danger", label: "Page read failed" },
  PROPOSAL_CREATED: { icon: ReceiptText, tone: "accent", label: "Proposal created" },
  // Deliberately a different icon from POLICY_BLOCKED (ShieldX): this fires
  // when the agent itself refuses a task as outside its assigned purpose,
  // before any proposal or policy evaluation ever happens. Giving it its own
  // Ban icon keeps "the agent declined this" visually distinct from "the
  // deterministic policy engine blocked this" in the Activity feed and Audit
  // trail, since they are two different layers of this platform's
  // guardrails and which one fired is meaningful.
  TASK_DECLINED_OUT_OF_SCOPE: { icon: Ban, tone: "danger", label: "Declined: outside agent's scope" },
  // Fires on every evaluation, before the outcome (allow/block) is known, so
  // it needs a neutral icon. It previously reused ShieldX, the same icon as
  // POLICY_BLOCKED below: a shield-with-X reads as "blocked" on sight
  // regardless of its blue "info" color, so every transaction looked like it
  // had been denied in the Activity feed and Audit trail, even ones that
  // went on to be allowed.
  POLICY_EVALUATED: { icon: Shield, tone: "info", label: "Policy evaluated" },
  POLICY_ALLOWED: { icon: CircleCheck, tone: "success", label: "Policy allowed" },
  POLICY_BLOCKED: { icon: ShieldX, tone: "danger", label: "Policy blocked" },
  // A second, independent model call - fresh context, no access to the
  // research loop's own conversation - judging the finished proposal
  // against the agent's own stated purpose/directive. Deliberately its own
  // icon/tone, distinct from POLICY_EVALUATED (the deterministic
  // budget/category/velocity engine): this is a different guardrail,
  // answering a different question ("does this serve what the agent was
  // actually delegated to do", not "is this within its spending rules"),
  // and it can fire on a transaction that policy alone would have allowed
  // outright.
  SCOPE_CHECKED: { icon: ShieldQuestion, tone: "info", label: "Scope checked" },
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
  // The agent paused to ask the human something (a clarifying question, or
  // a "found X instead, want it?" check-in) instead of guessing or just
  // giving up - not a failure, so it gets its own neutral/warning icon
  // rather than reusing TRANSACTION_FAILED's TriangleAlert.
  AGENT_ASKED_QUESTION: { icon: MessageCircleQuestion, tone: "warning", label: "Agent asked a question" },
  USER_REPLIED: { icon: MessageCircle, tone: "accent", label: "You replied" },
  // Agent lifecycle: retiring/deleting an agent and the resulting in-flight
  // cancellations are administrative actions, not pipeline outcomes, so they
  // get their own neutral/muted icons rather than reusing POLICY_BLOCKED's
  // ShieldX or TASK_DECLINED_OUT_OF_SCOPE's Ban (both of which mean "the
  // agent's own guardrails stopped a purchase", a different thing).
  AGENT_RETIRED: { icon: UserX, tone: "muted", label: "Agent retired" },
  // The reverse of AGENT_RETIRED: it only means "accepting new tasks again",
  // not "everything that was cancelled came back" (see
  // orchestrator.reactivate_agent), so it gets a positive but still neutral
  // tone rather than reusing one of the transaction-outcome colors.
  AGENT_REACTIVATED: { icon: UserCheck, tone: "accent", label: "Agent reactivated" },
  AGENT_DELETED: { icon: Trash2, tone: "danger", label: "Agent deleted" },
  TASK_CANCELLED_AGENT_REMOVED: { icon: XCircle, tone: "muted", label: "Cancelled: agent removed" },
};

export function eventMeta(type: string): EventMeta {
  return META[type] || { icon: ScrollText, tone: "muted", label: type.replace(/_/g, " ") };
}
