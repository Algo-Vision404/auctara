import Link from "next/link";
import { Transaction, Agent } from "@/lib/types";
import { money } from "@/lib/format";
import { ShieldX, Ban, Search, Send } from "lucide-react";

// decline_out_of_scope_task is the model's only way to conclude a task
// without a proposal, and it gets called for two genuinely different
// reasons: (1) the task plainly has no connection to this agent's purpose,
// decided on the model's very first turn before any research tool is ever
// called, and (2) the task WAS in scope and genuinely researched, but
// nothing suitable turned up within budget by the time the model's last
// available turn forced it to either propose or decline. Both land in the
// exact same BLOCKED state with tx.amount still null, but they are not the
// same outcome to a human reading this card - "this request doesn't belong
// here, try something else" is only true for (1). Rather than add a new
// backend field for this, the activity timeline this card already has on
// hand is enough to tell them apart after the fact: any research-tool
// event at all means real research happened first.
const RESEARCH_EVENT_TYPES = new Set([
  "SEARCH_STARTED", "SEARCH_COMPLETED", "SEARCH_FAILED",
  "PAGE_FETCH_STARTED", "PAGE_FETCH_COMPLETED", "PAGE_FETCH_FAILED",
  "CHANNEL3_SEARCH_STARTED", "CHANNEL3_SEARCH_COMPLETED", "CHANNEL3_SEARCH_FAILED",
]);

export function BlockedCard({ tx, agent }: { tx: Transaction; agent: Agent | null }) {
  // The agent itself can decline a task as outside its assigned purpose
  // or as genuinely unfulfillable, before ever producing a proposal (see
  // orchestrator.OutOfScopeError on the backend), in which case
  // tx.amount/merchant were never set. That is a meaningfully different
  // outcome from a real proposal hitting a dollar or category limit, so it
  // gets its own heading and skips the amount figure entirely instead of
  // showing a bare, confusing "N/A".
  const declinedBeforeProposal = tx.amount == null;
  const researchHappened = (tx.timeline || []).some((r) => RESEARCH_EVENT_TYPES.has(r.event_type));
  const declinedAfterResearch = declinedBeforeProposal && researchHappened;

  return (
    <div className="card-elevated animate-enter overflow-hidden">
      <div className="border-b border-[var(--color-border)] bg-[var(--color-danger-soft)] px-6 py-5">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-[var(--color-danger)]">
          {declinedAfterResearch ? (
            <>
              <Search size={14} /> Nothing Suitable Found
            </>
          ) : declinedBeforeProposal ? (
            <>
              <Ban size={14} /> Task Declined
            </>
          ) : (
            <>
              <ShieldX size={14} /> Transaction Blocked
            </>
          )}
        </p>
        {declinedAfterResearch ? (
          <p className="mt-1 text-base font-medium">
            The agent researched this task but could not find anything suitable to propose.
          </p>
        ) : declinedBeforeProposal ? (
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
        {/* Out-of-scope declines are a judgment call about fit with this
            specific agent's own delegated purpose (see orchestrator.py's
            OutOfScopeError), not a dollar/category limit. Showing that
            purpose right here, in the user's own words from when they set
            this agent up, lets them immediately see what IS in scope and
            self-correct their next request - no back-and-forth needed. */}
        {declinedBeforeProposal && !declinedAfterResearch && agent?.purpose && (
          <div className="rounded-xl border border-[var(--color-border)] px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              What {agent.name} can actually help with
            </p>
            <p className="mt-1 text-sm text-[var(--color-text)]">{agent.purpose}</p>
          </div>
        )}
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
          {declinedAfterResearch
            ? "Real research was performed (see the activity log below) but nothing fit; no PayPal transaction was ever created."
            : declinedBeforeProposal
            ? "No research was performed and no PayPal transaction was ever created."
            : "No PayPal transaction was captured."}
        </div>
        {declinedBeforeProposal && (
          <Link
            href={`/agents/${tx.agent_id}`}
            className="flex w-fit items-center gap-2 rounded-lg border border-[var(--color-border)] px-3 py-2 text-sm font-medium text-[var(--color-accent)] hover:bg-[var(--color-surface-2)]"
          >
            <Send size={16} />
            {declinedAfterResearch ? "Try a higher budget or a different product" : "Try a different request"}
          </Link>
        )}
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
