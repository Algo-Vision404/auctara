"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "@/components/nav/TopBar";
import { Badge, stateTone } from "@/components/ui/Badge";
import { ApprovalCard } from "@/components/transactions/ApprovalCard";
import { NeedsInputCard } from "@/components/transactions/NeedsInputCard";
import { BlockedCard } from "@/components/transactions/BlockedCard";
import { VoidedCard } from "@/components/transactions/VoidedCard";
import { ProposalSummary } from "@/components/transactions/ProposalSummary";
import { Channel3Candidates } from "@/components/transactions/Channel3Candidates";
import { DecisionTimeline } from "@/components/transactions/DecisionTimeline";
import { Terminal } from "@/components/terminal/Terminal";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { api, ApiError, subscribeToEvents } from "@/lib/api";
import { Transaction, Agent } from "@/lib/types";
import { money, titleCase, fullDateTime } from "@/lib/format";
import { buildTimelineStages } from "@/lib/timelineStages";
import { Loader2, ArrowRight, TriangleAlert, CircleCheck, XCircle, FlaskConical } from "lucide-react";

const TERMINAL_STATES = new Set(["COMPLETED", "BLOCKED", "VOIDED", "FAILED", "CANCELLED"]);

export default function TransactionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const [tx, setTx] = useState<Transaction | null>(null);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingPaypal, setConfirmingPaypal] = useState(false);
  const continuedRef = useRef(false);
  const txStateRef = useRef<string | null>(null);

  const load = useCallback(() => {
    api
      .getTransaction(id)
      .then(async (t) => {
        setTx(t);
        txStateRef.current = t.state;
        setError(null);
        if (!agent || agent.id !== t.agent_id) {
          try {
            setAgent(await api.getAgent(t.agent_id));
          } catch {
            /* ignore */
          }
        }
      })
      .catch((e) => {
        // Only block the whole page before the transaction has ever loaded.
        // Once it is showing, a single failed background poll should not
        // discard the live view; surface it as a non-blocking banner instead.
        setError(e instanceof ApiError ? e.message : "Failed to load transaction");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    load();
    const i = setInterval(() => {
      // Stop polling once the transaction has reached a terminal state:
      // nothing more will ever change, so there is no real event left to
      // discover by continuing to hit the backend every 2 seconds.
      if (txStateRef.current && TERMINAL_STATES.has(txStateRef.current)) {
        clearInterval(i);
        return;
      }
      load();
    }, 2000);
    return () => clearInterval(i);
  }, [load]);

  // The 2-second poll above is a fallback, not the real mechanism - most of
  // a transaction's life (proposal -> policy -> PayPal -> audit) runs as
  // one uninterrupted, synchronous backend sequence that can finish in well
  // under 2 seconds once research is done. A fixed poll interval can only
  // ever catch "nothing happened yet" and then "everything is already
  // done" for a run that fast, which is exactly why the stage-by-stage
  // timeline above used to appear to jump straight from empty to fully
  // resolved - the Terminal log below was already live (it listens to this
  // same event stream directly), the staged timeline just wasn't. Refetching
  // immediately on every real backend event, the instant it happens, makes
  // the stage timeline advance in lockstep with the Terminal log instead of
  // lagging behind it on its own slower clock.
  useEffect(() => {
    if (!tx?.task_id) return;
    const unsub = subscribeToEvents(`/tasks/${tx.task_id}/events`, () => load());
    return unsub;
  }, [tx?.task_id, load]);

  useEffect(() => {
    if (search.get("paypal") === "return" && !continuedRef.current) {
      continuedRef.current = true;
      setConfirmingPaypal(true);
      api
        .continuePaypal(id)
        .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to confirm PayPal payment"))
        .finally(() => {
          setConfirmingPaypal(false);
          router.replace(`/transactions/${id}`);
          load();
        });
    }
  }, [search, id, router, load]);

  async function handleApprove() {
    await api.approveTransaction(id);
    load();
  }
  async function handleReject() {
    await api.rejectTransaction(id);
    load();
  }
  async function handleReply(message: string) {
    if (!tx?.task_id) return;
    await api.respondToTask(tx.task_id, message);
    load();
  }

  if (error && !tx) {
    return (
      <div className="flex flex-1 flex-col">
        <TopBar title="Transaction" backHref="/activity" backLabel="Back to activity" />
        <main className="px-5 py-6 md:px-8">
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        </main>
      </div>
    );
  }

  if (!tx) {
    // Shape-matched skeletons instead of a blank page + spinner: every
    // transaction renders into roughly this same vertical sequence
    // (status row, one state card, research/decision evidence, terminal)
    // regardless of which state it turns out to be in, so we already know
    // enough to avoid a jarring blank-then-pop-in.
    return (
      <div className="flex flex-1 flex-col">
        <TopBar title="Transaction" backHref="/activity" backLabel="Back to activity" />
        <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 px-5 py-6 md:px-8">
          <div className="flex items-center gap-3">
            <Skeleton className="h-5 w-24 rounded-full" />
            <Skeleton className="h-5 w-28 rounded-full" />
          </div>
          <div className="card-elevated space-y-3 p-6">
            <Skeleton className="h-5 w-56" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-24 w-full rounded-xl" />
            ))}
          </div>
          <div className="card-surface space-y-4 p-6">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="h-6 w-6 shrink-0 rounded-full" />
                <Skeleton className="h-4 w-full" />
              </div>
            ))}
          </div>
        </main>
      </div>
    );
  }

  const stages = buildTimelineStages(tx);
  const policyEval = (tx.timeline || []).find((r) => r.event_type === "POLICY_EVALUATED")?.payload || null;

  return (
    <div className="flex flex-1 flex-col">
      <TopBar
        title={`Transaction ${id.replace("tx_", "#").toUpperCase()}`}
        subtitle={fullDateTime(tx.created_at)}
        backHref={tx.agent_id ? `/agents/${tx.agent_id}` : "/activity"}
        backLabel="Back to agent"
      />
      <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 px-5 py-6 md:px-8">
        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-warning)] p-4 text-sm text-[var(--color-warning)]">
            {error} Showing the last data AgentAuth successfully loaded.
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={stateTone(tx.state)}>{titleCase(tx.state)}</Badge>
          {tx.decision && <Badge tone="accent">{titleCase(tx.decision)}</Badge>}
          {!TERMINAL_STATES.has(tx.state) && tx.state !== "AWAITING_APPROVAL" && tx.state !== "NEEDS_INPUT" && (
            <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
              <Loader2 size={12} className="animate-spin" /> live
            </span>
          )}
        </div>

        {tx.paypal_negative_test && (
          <div className="card-surface flex items-start gap-3 border-l-4 border-l-[var(--color-warning)] p-4">
            <FlaskConical size={18} className="mt-0.5 shrink-0 text-[var(--color-warning)]" />
            <p className="text-sm text-[var(--color-text-secondary)]">
              <span className="font-semibold text-[var(--color-text)]">Sandbox QA active:</span> this task
              requested PayPal&apos;s own official negative-testing header (
              <code className="font-mono-ui text-xs">{tx.paypal_negative_test}</code>) for its capture
              step. Any decline or failure below is a real response from PayPal&apos;s own sandbox, not a
              bug or fabricated data &mdash; it exists to prove this exact failure path works.
            </p>
          </div>
        )}

        {confirmingPaypal && (
          <div className="card-elevated flex items-center gap-3 border-l-4 border-l-[var(--color-accent)] p-6">
            <Loader2 size={18} className="animate-spin text-[var(--color-accent)]" />
            <div>
              <p className="font-semibold">Confirming your PayPal payment…</p>
              <p className="text-sm text-[var(--color-text-secondary)]">
                You approved this on PayPal. AgentAuth is now authorizing and verifying the price before
                capture. This takes a few seconds.
              </p>
            </div>
          </div>
        )}

        {tx.state === "AWAITING_APPROVAL" && (
          <ApprovalCard tx={tx} agent={agent} policyEvaluation={policyEval} onApprove={handleApprove} onReject={handleReject} />
        )}

        {tx.state === "NEEDS_INPUT" && <NeedsInputCard tx={tx} onReply={handleReply} />}

        {tx.state === "BLOCKED" && <BlockedCard tx={tx} agent={agent} />}

        {tx.state === "FAILED" && tx.error && (
          <div className="card-elevated space-y-2 border-l-4 border-l-[var(--color-danger)] p-6">
            <p className="flex items-center gap-2 text-sm font-semibold text-[var(--color-danger)]">
              <TriangleAlert size={16} /> Transaction Failed
            </p>
            <p className="text-sm text-[var(--color-text-secondary)]">{tx.error}</p>
          </div>
        )}

        {tx.state === "CANCELLED" && (
          <div className="card-elevated space-y-2 border-l-4 border-l-[var(--color-text-muted)] p-6">
            <p className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text-secondary)]">
              <XCircle size={16} /> Task Cancelled
            </p>
            <p className="text-sm text-[var(--color-text-secondary)]">{tx.decision_reason}</p>
            <p className="text-xs text-[var(--color-text-muted)]">
              This was stopped because the agent that owned it was retired or deleted, not because of
              anything about this task itself.
            </p>
          </div>
        )}

        {tx.state === "VOIDED" && <VoidedCard tx={tx} agent={agent} />}

        {tx.state === "COMPLETED" && (
          <div className="card-elevated flex flex-col items-center gap-4 border-t-4 border-t-[var(--color-success)] px-6 py-10 text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[var(--color-success-soft)]">
              <CircleCheck size={32} className="text-[var(--color-success)]" />
            </span>
            <div className="space-y-1">
              <h2 className="font-sans text-2xl font-semibold text-[var(--color-text)]">Payment Completed</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">
                PayPal captured {money(tx.actual_amount ?? tx.amount, tx.currency || "USD")} for{" "}
                {tx.merchant}, authorized by your policy engine.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-1 font-mono-ui text-xs text-[var(--color-text-muted)]">
              <span>Capture ID: {tx.paypal_capture_id}</span>
              <span>Order ID: {tx.paypal_order_id}</span>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
              <Button variant="primary" onClick={() => router.push("/ledger")}>
                View in Commerce Ledger
              </Button>
              <Button variant="secondary" onClick={() => router.push(`/agents/${tx.agent_id}`)}>
                Back to Agent
              </Button>
            </div>
          </div>
        )}

        {!confirmingPaypal && !TERMINAL_STATES.has(tx.state) &&
          tx.paypal_status === "PAYER_ACTION_REQUIRED" && tx.paypal_approve_url && (
          <div className="card-elevated flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-semibold">PayPal buyer approval required</p>
              <p className="text-sm text-[var(--color-text-secondary)]">
                Complete this Sandbox order on PayPal to continue the two-phase payment flow.
              </p>
            </div>
            <a href={tx.paypal_approve_url}>
              <Button variant="primary">
                Approve on PayPal <ArrowRight size={16} />
              </Button>
            </a>
          </div>
        )}

        <Channel3Candidates tx={tx} />

        <ProposalSummary tx={tx} />

        <DecisionTimeline stages={stages} />

        <Terminal taskId={tx.task_id || undefined} transactionId={tx.id} />
      </main>
    </div>
  );
}
