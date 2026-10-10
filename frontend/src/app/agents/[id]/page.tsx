"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { TopBar } from "@/components/nav/TopBar";
import { Button } from "@/components/ui/Button";
import { Badge, stateTone } from "@/components/ui/Badge";
import { BudgetBar } from "@/components/agents/BudgetBar";
import { api, ApiError } from "@/lib/api";
import { Agent } from "@/lib/types";
import { money, titleCase, shortTime } from "@/lib/format";
import {
  Bot, ShieldCheck, Ban, Send, Loader2, ArrowUpRight, ReceiptText, UserX, UserCheck, Trash2,
  FlaskConical, ChevronDown, ChevronUp,
} from "lucide-react";

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [retiring, setRetiring] = useState(false);
  const [reactivating, setReactivating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [negativeTestOptions, setNegativeTestOptions] = useState<{ code: string; description: string }[]>([]);
  const [negativeTest, setNegativeTest] = useState("");
  const [showQaPanel, setShowQaPanel] = useState(false);

  useEffect(() => {
    // Sandbox QA options rarely change and never depend on this agent, so
    // this is a one-time fetch, not part of the 6s agent poll below.
    api.negativeTestOptions().then(setNegativeTestOptions).catch(() => {});
  }, []);

  function load() {
    api
      .getAgent(id)
      .then((a) => {
        setAgent(a);
        setError(null);
      })
      .catch((e) => {
        // Only block the whole page on an error before we have ever loaded
        // this agent. Once it is showing, a single failed background poll
        // (a brief network blip, a backend restart) should not discard the
        // last known-good view; surface it as a non-blocking banner instead.
        setError(e instanceof ApiError ? e.message : "Failed to load agent");
      });
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleSubmitTask() {
    if (!agent) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const task = await api.createTask({
        agent_id: agent.id,
        prompt,
        max_amount: maxAmount ? Number(maxAmount) : null,
        paypal_negative_test: negativeTest || null,
      });
      router.push(`/tasks/${task.id}`);
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "Failed to submit task");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRetire() {
    if (!agent) return;
    if (
      !window.confirm(
        `Retire ${agent.name}? It will stop accepting new tasks immediately, and anything it has in ` +
          "progress right now will be cancelled. Its full history stays exactly as it is, and you can " +
          "reactivate it later."
      )
    )
      return;
    setRetiring(true);
    setActionError(null);
    try {
      const updated = await api.retireAgent(agent.id);
      setAgent(updated);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Failed to retire agent");
    } finally {
      setRetiring(false);
    }
  }

  async function handleReactivate() {
    if (!agent) return;
    if (
      !window.confirm(
        `Reactivate ${agent.name}? It will be able to accept new tasks again. Anything that was ` +
          "cancelled while it was retired stays cancelled \u2014 recreate anything you want running again."
      )
    )
      return;
    setReactivating(true);
    setActionError(null);
    try {
      const updated = await api.reactivateAgent(agent.id);
      setAgent(updated);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Failed to reactivate agent");
    } finally {
      setReactivating(false);
    }
  }

  async function handleDelete() {
    if (!agent) return;
    if (
      !window.confirm(
        `Permanently delete ${agent.name}? Everything it has in progress will be cancelled, and the ` +
          "agent, its policy, tasks, and transactions will be erased. This cannot be undone. " +
          "(Its audit trail entries are kept permanently, as with every agent.)"
      )
    )
      return;
    setDeleting(true);
    setActionError(null);
    try {
      await api.deleteAgent(agent.id);
      router.push("/agents");
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Failed to delete agent");
      setDeleting(false);
    }
  }

  if (error && !agent) {
    return (
      <div className="flex flex-1 flex-col">
        <TopBar title="Agent" backHref="/agents" />
        <main className="px-5 py-6 md:px-8">
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        </main>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex flex-1 flex-col">
        <TopBar title="Agent" backHref="/agents" />
        <main className="flex flex-1 items-center justify-center">
          <Loader2 className="animate-spin text-[var(--color-text-muted)]" />
        </main>
      </div>
    );
  }

  const policy = agent.policy;

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title={agent.name} subtitle={agent.purpose} backHref="/agents" backLabel="Back to agents" />
      <main className="flex-1 space-y-6 px-5 py-6 md:px-8">
        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-warning)] p-4 text-sm text-[var(--color-warning)]">
            {error} Showing the last data AgentAuth successfully loaded.
          </div>
        )}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="space-y-6 lg:col-span-3">
            <div className="card-surface space-y-4 p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center text-[var(--color-accent)]">
                    <Bot size={22} />
                  </span>
                  <div>
                    <h3 className="font-semibold">{agent.name}</h3>
                    <p className="text-xs text-[var(--color-text-muted)]">Created {shortTime(agent.created_at)}</p>
                  </div>
                </div>
                <Badge tone={agent.status === "ACTIVE" ? "success" : "muted"}>{titleCase(agent.status)}</Badge>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)]">{agent.directive}</p>

              {policy && (
                <div className="space-y-4 border-t border-[var(--color-border)] pt-4">
                  <BudgetBar label="Daily Authority" used={agent.daily_spent} limit={policy.daily_limit} />
                  <BudgetBar label="Monthly Authority" used={agent.monthly_spent} limit={policy.monthly_limit} />
                </div>
              )}
            </div>

            {policy && (
              <div className="card-surface space-y-4 p-6">
                <h3 className="flex items-center gap-2 font-semibold">
                  <ShieldCheck size={18} className="text-[var(--color-accent)]" /> Policy
                </h3>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <PolicyTile label="Autonomous" value={money(policy.approval_threshold)} />
                  <PolicyTile label="Max / Txn" value={money(policy.max_transaction_amount)} />
                  <PolicyTile label="Daily Limit" value={money(policy.daily_limit)} />
                  <PolicyTile label="Monthly Limit" value={money(policy.monthly_limit)} />
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="text-[var(--color-text-muted)]">Velocity:</span>
                  <span className="font-mono-ui">
                    {policy.velocity_max_transactions} / {policy.velocity_window_minutes}min
                  </span>
                </div>
                {policy.blocked_categories.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Ban size={14} className="text-[var(--color-danger)]" />
                    {policy.blocked_categories.map((c) => (
                      <Badge tone="danger" key={c}>
                        {titleCase(c)}
                      </Badge>
                    ))}
                  </div>
                )}
                <Link href="/policies" className="flex w-fit items-center gap-1 text-sm font-medium text-[var(--color-accent)]">
                  Review full policy <ArrowUpRight size={14} />
                </Link>
              </div>
            )}

            <div className="card-surface space-y-3 p-6">
              <h3 className="flex items-center gap-2 font-semibold">
                <ReceiptText size={18} className="text-[var(--color-accent)]" /> Recent Transactions
              </h3>
              {(agent.transactions || []).length === 0 && (
                <p className="text-sm text-[var(--color-text-muted)]">No transactions yet.</p>
              )}
              <div className="space-y-2">
                {(agent.transactions || []).slice(0, 8).map((t) => (
                  <Link
                    key={t.id}
                    href={`/transactions/${t.id}`}
                    className="flex items-center justify-between rounded-lg border border-[var(--color-border)] px-3 py-2.5 hover:bg-[var(--color-surface-2)]"
                  >
                    <div>
                      <p className="text-sm font-medium">{t.merchant || "Researching…"}</p>
                      <p className="text-xs text-[var(--color-text-muted)]">{shortTime(t.created_at)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono-ui text-sm">{t.amount ? money(t.amount) : "N/A"}</span>
                      <Badge tone={stateTone(t.state)}>{titleCase(t.state)}</Badge>
                    </div>
                  </Link>
                ))}
              </div>
            </div>

            <div className="card-surface space-y-3 border-l-4 border-l-[var(--color-danger)] p-6">
              <h3 className="font-semibold text-[var(--color-danger)]">Danger Zone</h3>
              {actionError && <p className="text-sm text-[var(--color-danger)]">{actionError}</p>}
              {agent.status === "RETIRED" ? (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-border)] p-3">
                  <div>
                    <p className="text-sm font-medium">Reactivate this agent</p>
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      Lets it accept new tasks again. Whatever was cancelled while it was retired (in-flight
                      tasks, scheduled tasks) stays cancelled &mdash; recreate anything you want running again.
                    </p>
                  </div>
                  <Button variant="secondary" loading={reactivating} onClick={handleReactivate}>
                    <UserCheck size={16} /> Reactivate
                  </Button>
                </div>
              ) : (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-border)] p-3">
                  <div>
                    <p className="text-sm font-medium">Retire this agent</p>
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      Stops it from accepting new tasks and cancels anything in progress. Full history stays
                      visible, and it can be reactivated later.
                    </p>
                  </div>
                  <Button variant="secondary" loading={retiring} onClick={handleRetire}>
                    <UserX size={16} /> Retire
                  </Button>
                </div>
              )}
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--color-border)] p-3">
                <div>
                  <p className="text-sm font-medium">Permanently delete this agent</p>
                  <p className="text-xs text-[var(--color-text-secondary)]">
                    Erases the agent, its policy, tasks, and transactions. Not reversible. Its audit trail
                    entries are kept permanently.
                  </p>
                </div>
                <Button variant="danger" loading={deleting} onClick={handleDelete}>
                  <Trash2 size={16} /> Delete
                </Button>
              </div>
            </div>
          </div>

          <div className="lg:col-span-2">
            <div className="card-elevated sticky top-20 space-y-4 p-6">
              <h3 className="flex items-center gap-2 font-semibold">
                <Send size={18} className="text-[var(--color-accent)]" /> Give this agent a task
              </h3>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={5}
                placeholder="Find the cheapest annual project-management software for my team and purchase it if it costs less than $80."
                className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3 text-sm outline-none focus:border-[var(--color-accent)]"
              />
              <div>
                <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
                  Max amount (optional)
                </label>
                <input
                  type="number"
                  value={maxAmount}
                  onChange={(e) => setMaxAmount(e.target.value)}
                  placeholder="80"
                  className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)]"
                />
              </div>
              {negativeTestOptions.length > 0 && (
                <div className="rounded-xl border border-dashed border-[var(--color-border)] p-3">
                  <button
                    type="button"
                    onClick={() => setShowQaPanel((v) => !v)}
                    className="flex w-full items-center justify-between text-left"
                  >
                    <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
                      <FlaskConical size={14} /> Sandbox QA (optional)
                    </span>
                    {showQaPanel ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                  {showQaPanel && (
                    <div className="mt-3 space-y-2">
                      <p className="text-xs text-[var(--color-text-secondary)]">
                        Forces PayPal&apos;s own official sandbox <em>negative-testing</em> header on this
                        task&apos;s one capture call, so PayPal&apos;s real API genuinely returns a real,
                        documented decline instead of capturing for real. This is PayPal&apos;s own
                        documented QA mechanism, not fabricated data. Leave as &quot;None&quot; for a normal
                        task.
                      </p>
                      <select
                        value={negativeTest}
                        onChange={(e) => setNegativeTest(e.target.value)}
                        className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)]"
                      >
                        <option value="">None (normal flow)</option>
                        {negativeTestOptions.map((opt) => (
                          <option key={opt.code} value={opt.code}>
                            {opt.code} &mdash; {opt.description}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}
              {submitError && <p className="text-sm text-[var(--color-danger)]">{submitError}</p>}
              <Button
                variant="primary"
                fullWidth
                loading={submitting}
                disabled={prompt.trim().length < 5 || agent.status !== "ACTIVE"}
                onClick={handleSubmitTask}
              >
                Run Task
              </Button>
              {agent.status !== "ACTIVE" && (
                <p className="text-xs text-[var(--color-warning)]">This agent is not active.</p>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function PolicyTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">{label}</p>
      <p className="font-mono-ui text-base font-semibold">{value}</p>
    </div>
  );
}
