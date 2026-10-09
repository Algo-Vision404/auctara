import { Transaction, Agent } from "@/lib/types";
import { money } from "@/lib/format";
import { ShieldAlert, Undo2 } from "lucide-react";

export function VoidedCard({ tx, agent }: { tx: Transaction; agent: Agent | null }) {
  const expected = tx.expected_amount ?? 0;
  const actual = tx.actual_amount ?? 0;
  const variancePct = expected === 0 ? 0 : (Math.abs(actual - expected) / expected) * 100;
  const tolerancePct = (agent?.policy?.price_variance_tolerance ?? 0) * 100;

  return (
    <div className="card-elevated animate-enter overflow-hidden">
      <div className="border-b border-[var(--color-border)] bg-[var(--color-danger-soft)] px-6 py-5">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-[var(--color-danger)]">
          <ShieldAlert size={14} /> Payment Automatically Voided
        </p>
        <p className="mt-1 text-base font-medium">
          PayPal confirmed a different amount than the agent proposed, outside this agent&apos;s allowed
          price-variance tolerance &mdash; so the authorization was voided instead of captured.
        </p>
      </div>
      <div className="space-y-4 px-6 py-5">
        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <PriceFact label="Expected" value={money(tx.expected_amount)} />
          <PriceFact label="PayPal confirmed" value={money(tx.actual_amount)} />
          <PriceFact label="Variance" value={`${variancePct.toFixed(2)}%`} warn={variancePct > tolerancePct} />
          <PriceFact label="Policy tolerance" value={`${tolerancePct.toFixed(2)}%`} />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Reason</p>
          <p className="mt-1 text-sm text-[var(--color-text)]">{tx.decision_reason}</p>
        </div>
        <div className="flex items-start gap-2 rounded-xl bg-[var(--color-surface-2)] px-4 py-3 text-sm font-medium text-[var(--color-text-secondary)]">
          <Undo2 size={16} className="mt-0.5 shrink-0" />
          <span>
            No money was captured. PayPal&apos;s own authorization was released in full via a real void
            call, the same protection that would apply if a live merchant price changed between proposal
            and checkout.
          </span>
        </div>
      </div>
    </div>
  );
}

function PriceFact({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{label}</p>
      <p
        className={`font-mono-ui font-semibold ${warn ? "text-[var(--color-danger)]" : ""}`}
      >
        {value}
      </p>
    </div>
  );
}
