import { Transaction, Agent } from "@/lib/types";
import { money } from "@/lib/format";
import { ShieldX } from "lucide-react";

export function BlockedCard({ tx, agent }: { tx: Transaction; agent: Agent | null }) {
  return (
    <div className="card-elevated animate-enter overflow-hidden">
      <div className="border-b border-[var(--color-border)] bg-[var(--color-danger-soft)] px-6 py-5">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-[var(--color-danger)]">
          <ShieldX size={14} /> Transaction Blocked
        </p>
        <p className="mt-1 font-mono-ui text-4xl font-semibold tracking-tight">
          {money(tx.amount, tx.currency || "USD")}
        </p>
        {tx.merchant && <p className="mt-1 text-base font-medium">{tx.merchant}</p>}
      </div>
      <div className="space-y-4 px-6 py-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Reason</p>
          <p className="mt-1 text-sm text-[var(--color-text)]">{tx.decision_reason}</p>
        </div>
        {agent?.policy && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Policy</p>
            <p className="mt-1 font-mono-ui text-sm text-[var(--color-text)]">
              Maximum transaction amount: {money(agent.policy.max_transaction_amount)}
            </p>
          </div>
        )}
        <div className="rounded-xl bg-[var(--color-surface-2)] px-4 py-3 text-sm font-medium text-[var(--color-text-secondary)]">
          No PayPal transaction was captured.
        </div>
      </div>
    </div>
  );
}
