"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { TopBar } from "@/components/nav/TopBar";
import { StatCard } from "@/components/ui/StatCard";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";
import { Agent, DashboardSummary } from "@/lib/types";
import { Bot, CircleDollarSign, WalletCards, Clock3, Plus, ArrowUpRight } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { money, titleCase } from "@/lib/format";

export default function OverviewPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      Promise.all([api.dashboardSummary(), api.listAgents()])
        .then(([s, a]) => {
          if (!mounted) return;
          setSummary(s);
          setAgents(a);
          setError(null);
          setLoading(false);
        })
        .catch((e) => {
          if (!mounted) return;
          setError(e instanceof ApiError ? e.message : "Failed to load dashboard");
          setLoading(false);
        });
    };
    load();
    const id = setInterval(load, 8000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title="Overview" subtitle="What are your agents doing right now?" />
      <main className="flex-1 space-y-6 px-5 py-6 md:px-8">
        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <div className="card-elevated flex flex-col gap-4 p-6 md:flex-row md:items-center md:justify-between">
          <div>
            {loading ? (
              <>
                <Skeleton className="h-4 w-36" />
                <h2 className="mt-2 font-sans text-2xl font-semibold tracking-tight">
                  <Skeleton className="inline-block h-7 w-40 align-middle" />
                </h2>
                <Skeleton className="mt-2 h-4 w-full max-w-md" />
              </>
            ) : agents.length === 0 ? (
              <>
                <p className="text-xs font-semibold uppercase tracking-widest text-[var(--color-accent)]">
                  Get started
                </p>
                <h2 className="mt-1 font-sans text-2xl font-semibold tracking-tight">No agents yet</h2>
                <p className="mt-1 max-w-md text-sm text-[var(--color-text-secondary)]">
                  Create your first agent and give it an explicit spending policy. It will only ever act within the
                  limits you set, checked by a deterministic policy engine before PayPal executes anything.
                </p>
              </>
            ) : (summary?.active_agents ?? 0) === 0 ? (
              <>
                <p className="text-xs font-semibold uppercase tracking-widest text-[var(--color-text-muted)]">
                  All agents paused
                </p>
                <h2 className="mt-1 font-sans text-2xl font-semibold tracking-tight">No active agents right now</h2>
                <p className="mt-1 max-w-md text-sm text-[var(--color-text-secondary)]">
                  You have {agents.length} agent{agents.length === 1 ? "" : "s"}, but none are active. Resume one
                  from the Agents page or create a new one.
                </p>
              </>
            ) : (
              <>
                <p className="text-xs font-semibold uppercase tracking-widest text-[var(--color-accent)]">
                  Your agents are working
                </p>
                <h2 className="mt-1 font-sans text-2xl font-semibold tracking-tight">
                  {summary?.active_agents ?? 0} Active Agent{summary?.active_agents === 1 ? "" : "s"}
                </h2>
                <p className="mt-1 max-w-md text-sm text-[var(--color-text-secondary)]">
                  Every purchase they propose is checked by your deterministic policy engine before PayPal ever
                  executes it.
                </p>
              </>
            )}
          </div>
          <Link href="/agents/new">
            <Button variant="primary">
              <Plus size={16} /> Create an Agent
            </Button>
          </Link>
        </div>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard
            label="Active Agents"
            value={loading ? <Skeleton className="h-8 w-12" /> : (summary?.active_agents ?? 0)}
            icon={<Bot size={16} />}
            tone="accent"
          />
          <StatCard
            label="Spent Today"
            value={loading ? <Skeleton className="h-8 w-20" /> : money(summary?.spent_today ?? 0)}
            icon={<CircleDollarSign size={16} />}
          />
          <StatCard
            label="Remaining Today"
            value={loading ? <Skeleton className="h-8 w-20" /> : money(summary?.remaining_today ?? 0)}
            icon={<WalletCards size={16} />}
          />
          <StatCard
            label="Awaiting Approval"
            value={loading ? <Skeleton className="h-8 w-12" /> : (summary?.awaiting_approval ?? 0)}
            icon={<Clock3 size={16} />}
            tone="warning"
          />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <div className="card-surface p-5">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="font-semibold">Your Agents</h3>
                <Link href="/agents" className="flex items-center gap-1 text-sm font-medium text-[var(--color-accent)]">
                  View all <ArrowUpRight size={14} />
                </Link>
              </div>
              <div className="space-y-2">
                {loading && (
                  <div className="space-y-2">
                    {[0, 1, 2].map((i) => (
                      <Skeleton key={i} className="h-14 w-full" />
                    ))}
                  </div>
                )}
                {!loading && agents.length === 0 && (
                  <p className="py-6 text-center text-sm text-[var(--color-text-muted)]">
                    No agents yet. Create one to delegate your first task.
                  </p>
                )}
                {agents.slice(0, 5).map((a) => (
                  <Link
                    key={a.id}
                    href={`/agents/${a.id}`}
                    className="flex items-center justify-between rounded-xl border border-[var(--color-border)] px-4 py-3 transition-colors hover:bg-[var(--color-surface-2)]"
                  >
                    <div className="flex items-center gap-3">
                      <span className="flex h-9 w-9 items-center justify-center text-[var(--color-accent)]">
                        <Bot size={20} />
                      </span>
                      <div>
                        <p className="text-sm font-semibold">{a.name}</p>
                        <p className="text-xs text-[var(--color-text-secondary)]">{a.purpose}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-mono-ui text-sm">{money(a.monthly_spent)}</p>
                      <Badge tone={a.status === "ACTIVE" ? "success" : "muted"}>{titleCase(a.status)}</Badge>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          </div>
          <div className="lg:col-span-2">
            <ActivityFeed />
          </div>
        </div>
      </main>
    </div>
  );
}
