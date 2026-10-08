import clsx from "clsx";
import { ReactNode } from "react";

type Tone = "success" | "warning" | "danger" | "info" | "muted" | "accent";

const toneClass: Record<Tone, string> = {
  success: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
  warning: "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
  danger: "bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
  info: "bg-[var(--color-info-soft)] text-[var(--color-info)]",
  accent: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  muted: "bg-[var(--color-surface-2)] text-[var(--color-text-muted)]",
};

export function Badge({
  tone = "muted",
  children,
  icon,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold tracking-wide",
        toneClass[tone],
        className
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export function decisionTone(decision: string | null | undefined): Tone {
  if (decision === "ALLOW") return "success";
  if (decision === "APPROVAL_REQUIRED") return "warning";
  if (decision === "BLOCK") return "danger";
  return "muted";
}

export function stateTone(state: string | null | undefined): Tone {
  switch (state) {
    case "COMPLETED":
    case "CAPTURED":
    case "AUTHORIZED":
      return "success";
    case "AWAITING_APPROVAL":
      return "warning";
    case "BLOCKED":
    case "VOIDED":
    case "FAILED":
      return "danger";
    case "RESEARCHING":
    case "PROPOSED":
    case "POLICY_CHECK":
    case "VERIFYING":
      return "info";
    // An administrative stop (the owning agent was retired/deleted mid-task),
    // not an error or a policy block, so it gets the same neutral tone as an
    // "N/A"/pending state rather than the red used for BLOCKED/FAILED/VOIDED.
    case "CANCELLED":
      return "muted";
    default:
      return "muted";
  }
}
