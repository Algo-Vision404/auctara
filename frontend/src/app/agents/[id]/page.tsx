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
import { Bot, ShieldCheck, Ban, Send, Loader2, ArrowUpRight, ReceiptText } from "lucide-react";

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

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
      });
      router.push(`/tasks/${task.id}`);
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "Failed to submit task");
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !agent) {
    return (
      <div className="flex flex-1 flex-col">
        <TopBar title="Agent" />
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
        <TopBar title="Agent" />
        <main className="flex flex-1 items-center justify-center">
          <Loader2 className="animate-spin text-[var(--color-text-muted)]" />
        </main>
      </div>
    );
  }

  const policy = agent.policy;

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title={agent.name} subtitle={agent.purpose} />
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
