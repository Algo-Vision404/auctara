"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Transaction, Agent } from "@/lib/types";
import { money } from "@/lib/format";
import { CircleCheck, ShieldX, BadgeCheck, TriangleAlert } from "lucide-react";

export function ApprovalCard({
  tx,
  agent,
  policyEvaluation,
  onApprove,
  onReject,
}: {
  tx: Transaction;
  agent: Agent | null;
  policyEvaluation: Record<string, unknown> | null;
  onApprove: () => Promise<void>;
  onReject: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const checks = (policyEvaluation?.checks as Record<string, boolean>) || {};

  async function handle(action: "approve" | "reject") {
    setBusy(action);
    setError(null);
    try {
      if (action === "approve") await onApprove();
      else await onReject();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card-elevated animate-enter overflow-hidden">
      <div className="border-b border-[var(--color-border)] bg-[var(--color-warning-soft)] px-6 py-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-[var(--color-warning)]">
          Payment Request
        </p>
        <p className="mt-1 font-mono-ui text-4xl font-semibold tracking-tight">{money(tx.amount, tx.currency || "USD")}</p>
        <p className="mt-1 text-base font-medium">{tx.merchant}</p>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          {agent?.name || "This agent"} wants to make this purchase.
        </p>
      </div>

      <div className="space-y-4 px-6 py-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          Policy Evaluation
        </p>
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          <EvalRow label="Autonomous authority" value={agent?.policy ? money(agent.policy.approval_threshold) : "N/A"} />
          <EvalRow label="Requested" value={money(tx.amount, tx.currency || "USD")} />
          <EvalRow
            label="Monthly budget remaining"
            value={tx.remaining_monthly_budget !== null ? money(tx.remaining_monthly_budget) : "N/A"}
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <CheckPill label="Category" ok={checks.category_allowed} />
          <CheckPill label="Budget" ok={checks.daily_budget_available && checks.monthly_budget_available} />
          <CheckPill label="Velocity" ok={checks.velocity_ok} />
        </div>

        <div className="flex items-center justify-between rounded-xl bg-[var(--color-surface-2)] px-4 py-3">
          <span className="text-sm font-semibold">Result</span>
          <Badge tone="warning" icon={<TriangleAlert size={13} />}>
            Approval Required
          </Badge>
        </div>

        {tx.reason && <p className="text-sm text-[var(--color-text-secondary)]">{tx.reason}</p>}

        {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}

        <div className="flex flex-col gap-3 pt-2 sm:flex-row">
          <Button variant="danger" onClick={() => handle("reject")} loading={busy === "reject"} disabled={!!busy}>
            <ShieldX size={16} /> Block Transaction
          </Button>
          <Button
            variant="primary"
            fullWidth
            onClick={() => handle("approve")}
            loading={busy === "approve"}
            disabled={!!busy}
          >
            <BadgeCheck size={16} /> Approve {money(tx.amount, tx.currency || "USD")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function EvalRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{label}</p>
      <p className="font-mono-ui font-semibold">{value}</p>
    </div>
  );
}

function CheckPill({ label, ok }: { label: string; ok?: boolean }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs font-medium">
      {ok === false ? (
        <ShieldX size={14} className="text-[var(--color-danger)]" />
      ) : (
        <CircleCheck size={14} className="text-[var(--color-success)]" />
      )}
      {label}
    </div>
  );
}
