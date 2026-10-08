import { Transaction, Agent } from "@/lib/types";
import { money } from "@/lib/format";
import { ShieldX, Ban } from "lucide-react";

export function BlockedCard({ tx, agent }: { tx: Transaction; agent: Agent | null }) {
  // The agent itself can decline a task as outside its assigned purpose
  // before ever producing a proposal (see orchestrator.OutOfScopeError on
  // the backend), in which case tx.amount/merchant were never set. That is
  // a meaningfully different outcome from a real proposal hitting a dollar
  // or category limit, so it gets its own heading and skips the amount
  // figure entirely instead of showing a bare, confusing "N/A".
  const declinedBeforeProposal = tx.amount == null;

  return (
    <div className="card-elevated animate-enter overflow-hidden">
      <div className="border-b border-[var(--color-border)] bg-[var(--color-danger-soft)] px-6 py-5">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-[var(--color-danger)]">
          {declinedBeforeProposal ? (
            <>
              <Ban size={14} /> Task Declined
            </>
          ) : (
            <>
              <ShieldX size={14} /> Transaction Blocked
            </>
          )}
        </p>
        {declinedBeforeProposal ? (
          <p className="mt-1 text-base font-medium">
            The agent declined this task before researching or proposing anything.
          </p>
        ) : (
          <>
            <p className="mt-1 font-mono-ui text-4xl font-semibold tracking-tight">
              {money(tx.amount, tx.currency || "USD")}
            </p>
            {tx.merchant && <p className="mt-1 text-base font-medium">{tx.merchant}</p>}
          </>
        )}
      </div>
      <div className="space-y-4 px-6 py-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">Reason</p>
          {/* decision_reason is the deterministic engine's own, specific explanation
              (the exact category, limit, or velocity rule that fired, or the human's
              rejection note). It is never paraphrased or replaced with a generic
              policy fact here, since the actual rule that blocked this transaction
              can be any one of several, not always the same one. */}
          <p className="mt-1 text-sm text-[var(--color-text)]">{tx.decision_reason}</p>
        </div>
        {agent?.policy && (
          <div className="grid grid-cols-2 gap-3 border-t border-[var(--color-border)] pt-4 text-sm sm:grid-cols-4">
            <PolicyFact label="Max / txn" value={money(agent.policy.max_transaction_amount)} />
            <PolicyFact label="Daily limit" value={money(agent.policy.daily_limit)} />
            <PolicyFact label="Monthly limit" value={money(agent.policy.monthly_limit)} />
            <PolicyFact
              label="Velocity"
              value={`${agent.policy.velocity_max_transactions} / ${agent.policy.velocity_window_minutes}min`}
            />
          </div>
        )}
        <div className="rounded-xl bg-[var(--color-surface-2)] px-4 py-3 text-sm font-medium text-[var(--color-text-secondary)]">
          {declinedBeforeProposal
            ? "No research was performed and no PayPal transaction was ever created."
            : "No PayPal transaction was captured."}
        </div>
      </div>
    </div>
  );
}

function PolicyFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{label}</p>
      <p className="font-mono-ui font-semibold">{value}</p>
    </div>
  );
}
