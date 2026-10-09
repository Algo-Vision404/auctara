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
