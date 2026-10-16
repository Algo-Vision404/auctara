export function money(amount: number | null | undefined, currency = "USD"): string {
  if (amount === null || amount === undefined) return "N/A";
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount);
}

export function shortTime(iso: string | null | undefined): string {
  if (!iso) return "N/A";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "N/A";
  return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fullDateTime(iso: string | null | undefined): string {
  if (!iso) return "N/A";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "N/A";
  return d.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "medium" });
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "N/A";
  return s
    .toLowerCase()
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// A plain-English line for "what is actually happening right now", for the
// one spot (the brief Task Execution loading screen, before a transaction
// exists to redirect to) that was printing the raw backend status enum
// verbatim - "Status: RESEARCHING", underscores and all caps included, is
// the backend's own internal state-machine vocabulary leaking straight
// onto the screen, not something written for a person to read next to a
// spinner. titleCase alone would only get as far as "Researching" / "Needs
// Input" - still a label, not a sentence that reads naturally in context.
// Task.status and Transaction.state share the same backend vocabulary (see
// app/state_machine.py / orchestrator.update_task_status) with a few states
// only ever appearing on one or the other, so one shared map safely covers
// both callers below.
const FRIENDLY_TASK_STATUS: Record<string, string> = {
  CREATED: "Getting started…",
  RESEARCHING: "Searching for the best option…",
  NEEDS_INPUT: "Waiting for your reply",
  PROPOSED: "Reviewing what it found…",
  POLICY_CHECK: "Checking this against policy…",
  AWAITING_APPROVAL: "Waiting for your approval",
  AUTHORIZED: "Approved, sending to PayPal…",
  EXECUTING: "Completing the purchase…",
  VERIFYING: "Confirming payment with PayPal…",
  CAPTURED: "Payment captured",
  BLOCKED: "Blocked by policy",
  VOIDED: "Payment voided",
  COMPLETED: "Completed",
  FAILED: "Something went wrong",
  CANCELLED: "Cancelled",
};

export function friendlyTaskStatus(status: string | null | undefined): string {
  if (!status) return FRIENDLY_TASK_STATUS.CREATED;
  return FRIENDLY_TASK_STATUS[status] || titleCase(status);
}


export const decisionColor: Record<string, string> = {
  ALLOW: "success",
  APPROVAL_REQUIRED: "warning",
  BLOCK: "danger",
};

export const stateColor: Record<string, string> = {
  CREATED: "muted",
  RESEARCHING: "info",
  NEEDS_INPUT: "warning",
  PROPOSED: "info",
  POLICY_CHECK: "info",
  BLOCKED: "danger",
  AWAITING_APPROVAL: "warning",
  AUTHORIZED: "success",
  VERIFYING: "info",
  CAPTURED: "success",
  VOIDED: "danger",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "muted",
};
