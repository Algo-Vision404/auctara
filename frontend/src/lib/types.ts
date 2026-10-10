export type Decision = "ALLOW" | "APPROVAL_REQUIRED" | "BLOCK" | null;

export type TransactionState =
  | "CREATED"
  | "RESEARCHING"
  | "NEEDS_INPUT"
  | "PROPOSED"
  | "POLICY_CHECK"
  | "BLOCKED"
  | "AWAITING_APPROVAL"
  | "AUTHORIZED"
  | "VERIFYING"
  | "CAPTURED"
  | "VOIDED"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface Policy {
  id: string;
  agent_id: string;
  max_transaction_amount: number;
  approval_threshold: number;
  daily_limit: number;
  monthly_limit: number;
  velocity_max_transactions: number;
  velocity_window_minutes: number;
  price_variance_tolerance: number;
  blocked_categories: string[];
  allowed_categories: string[];
  active: number;
  created_at: string;
}

export interface Agent {
  id: string;
  name: string;
  purpose: string;
  directive: string;
  status: string;
  created_at: string;
  policy: Policy | null;
  daily_spent: number;
  monthly_spent: number;
  daily_remaining: number | null;
  monthly_remaining: number | null;
  transactions?: Transaction[];
  activity?: ActivityEvent[];
}

export interface Transaction {
  id: string;
  task_id: string | null;
  agent_id: string;
  merchant: string | null;
  amount: number | null;
  currency: string | null;
  category: string | null;
  reason: string | null;
  source_url: string | null;
  image_url: string | null;
  retailer: string | null;
  channel3_product_id: string | null;
  agent_name?: string;
  task_prompt?: string | null;
  paypal_negative_test?: string | null;
  state: TransactionState;
  decision: Decision;
  decision_reason: string | null;
  authorized_amount: number | null;
  expected_amount: number | null;
  actual_amount: number | null;
  remaining_daily_budget: number | null;
  remaining_monthly_budget: number | null;
  paypal_order_id: string | null;
  paypal_authorization_id: string | null;
  paypal_capture_id: string | null;
  paypal_status: string | null;
  paypal_approve_url: string | null;
  error: string | null;
  pending_question: string | null;
  clarification_rounds?: number;
  created_at: string;
  updated_at: string;
  timeline?: AuditRecord[];
}

export interface ActivityEvent {
  id: string;
  task_id: string | null;
  transaction_id: string | null;
  agent_id: string | null;
  event_type: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AuditRecord {
  id: string;
  seq: number;
  transaction_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
  created_at: string;
}

export interface Task {
  id: string;
  agent_id: string;
  prompt: string;
  max_amount: number | null;
  status: string;
  error: string | null;
  paypal_negative_test?: string | null;
  created_at: string;
  updated_at: string;
  transactions?: Transaction[];
  activity?: ActivityEvent[];
}

export interface DashboardSummary {
  active_agents: number;
  total_agents: number;
  spent_today: number;
  remaining_today: number;
  awaiting_approval: number;
  completed_today: number;
  blocked_count: number;
  total_transactions: number;
}

export interface PolicyDraft {
  agent_name: string;
  agent_purpose: string;
  max_transaction_amount: number;
  approval_threshold: number;
  daily_limit: number;
  monthly_limit: number;
  velocity: { max_transactions: number; window_minutes: number };
  price_variance_tolerance: number;
  blocked_categories: string[];
  allowed_categories: string[];
  // Plain-language things the drafting AI had to decide for itself rather
  // than being told directly (e.g. "Assumed a $100 per-transaction limit
  // since none was stated") - shown to the user before they activate
  // anything, so a guess is never silently indistinguishable from
  // something they actually said. Optional only so older cached drafts
  // (or a backend rollback) don't break this type.
  assumptions?: string[];
}

// A single turn in a policy-drafting conversation, exactly as round-tripped
// to/from POST /agents/draft-policy - there is no server-side session for
// this (no agent record exists yet at draft time), so the frontend owns
// and resends the growing transcript itself.
export interface DraftConversationMessage {
  role: "user" | "assistant";
  content: string;
}

export type DraftPolicyResponse =
  | { status: "ready"; draft: PolicyDraft }
  | { status: "needs_clarification"; question: string; conversation: DraftConversationMessage[] };

export type Recurrence = "ONCE" | "DAILY" | "WEEKLY" | "MONTHLY";
export type ScheduleStatus = "ACTIVE" | "PAUSED" | "CANCELLED" | "COMPLETED";

export interface ScheduledTask {
  id: string;
  agent_id: string;
  prompt: string;
  max_amount: number | null;
  recurrence: Recurrence;
  start_at: string;
  next_run_at: string;
  last_run_at: string | null;
  last_task_id: string | null;
  status: ScheduleStatus;
  created_at: string;
  updated_at: string;
}

// One real, past firing of a schedule (GET /schedules/{id}/runs) - every
// task the scheduler ever actually spawned for it, joined with whatever
// transaction outcome exists so far. transaction_id/transaction_state are
// null when the pipeline hasn't created a transaction for that firing yet
// (e.g. it is still researching), never a fabricated placeholder outcome.
export interface ScheduleRun {
  task_id: string;
  fired_at: string;
  task_status: string;
  transaction_id: string | null;
  transaction_state: TransactionState | null;
  decision: Decision | null;
  merchant: string | null;
  amount: number | null;
  currency: string | null;
}
