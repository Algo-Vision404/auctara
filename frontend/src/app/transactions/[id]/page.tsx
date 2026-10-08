"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "@/components/nav/TopBar";
import { Badge, stateTone } from "@/components/ui/Badge";
import { ApprovalCard } from "@/components/transactions/ApprovalCard";
import { BlockedCard } from "@/components/transactions/BlockedCard";
import { ProposalSummary } from "@/components/transactions/ProposalSummary";
import { DecisionTimeline } from "@/components/transactions/DecisionTimeline";
import { Terminal } from "@/components/terminal/Terminal";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";
import { Transaction, Agent } from "@/lib/types";
import { money, titleCase, fullDateTime } from "@/lib/format";
import { buildTimelineStages } from "@/lib/timelineStages";
import { Loader2, ArrowRight, TriangleAlert, CircleCheck } from "lucide-react";

const TERMINAL_STATES = new Set(["COMPLETED", "BLOCKED", "VOIDED", "FAILED"]);

export default function TransactionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const [tx, setTx] = useState<Transaction | null>(null);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingPaypal, setConfirmingPaypal] = useState(false);
  const continuedRef = useRef(false);

  const load = useCallback(() => {
    api
      .getTransaction(id)
      .then(async (t) => {
        setTx(t);
        if (!agent || agent.id !== t.agent_id) {
          try {
            setAgent(await api.getAgent(t.agent_id));
          } catch {
            /* ignore */
          }
        }
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load transaction"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    load();
    const i = setInterval(() => {
      load();
    }, 2000);
    return () => clearInterval(i);
  }, [load]);

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

  if (error) {
    return (
      <div className="flex flex-1 flex-col">
        <TopBar title="Transaction" />
        <main className="px-5 py-6 md:px-8">
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        </main>
      </div>
    );
  }

  if (!tx) {
    return (
      <div className="flex flex-1 flex-col">
        <TopBar title="Transaction" />
        <main className="flex flex-1 items-center justify-center">
          <Loader2 className="animate-spin text-[var(--color-text-muted)]" />
        </main>
      </div>
    );
  }

  const stages = buildTimelineStages(tx);
  const policyEval = (tx.timeline || []).find((r) => r.event_type === "POLICY_EVALUATED")?.payload || null;

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title={`Transaction ${id.replace("tx_", "#").toUpperCase()}`} subtitle={fullDateTime(tx.created_at)} />
      <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 px-5 py-6 md:px-8">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={stateTone(tx.state)}>{titleCase(tx.state)}</Badge>
          {tx.decision && <Badge tone="accent">{titleCase(tx.decision)}</Badge>}
          {!TERMINAL_STATES.has(tx.state) && tx.state !== "AWAITING_APPROVAL" && (
            <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
              <Loader2 size={12} className="animate-spin" /> live
            </span>
          )}
        </div>

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

        {tx.state === "BLOCKED" && <BlockedCard tx={tx} agent={agent} />}

        {tx.state === "FAILED" && tx.error && (
          <div className="card-elevated space-y-2 border-l-4 border-l-[var(--color-danger)] p-6">
            <p className="flex items-center gap-2 text-sm font-semibold text-[var(--color-danger)]">
              <TriangleAlert size={16} /> Transaction Failed
            </p>
            <p className="text-sm text-[var(--color-text-secondary)]">{tx.error}</p>
          </div>
        )}

        {tx.state === "VOIDED" && (
          <div className="card-elevated space-y-2 border-l-4 border-l-[var(--color-danger)] p-6">
            <p className="flex items-center gap-2 text-sm font-semibold text-[var(--color-danger)]">
              <TriangleAlert size={16} /> Payment Voided
            </p>
            <p className="text-sm text-[var(--color-text-secondary)]">{tx.decision_reason}</p>
            <p className="text-xs text-[var(--color-text-muted)]">
              Expected {money(tx.expected_amount)} · PayPal confirmed {money(tx.actual_amount)}
            </p>
          </div>
        )}

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

        <ProposalSummary tx={tx} />

        <DecisionTimeline stages={stages} />

        <Terminal taskId={tx.task_id || undefined} transactionId={tx.id} />
      </main>
    </div>
  );
}
