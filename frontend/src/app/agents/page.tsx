"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { TopBar } from "@/components/nav/TopBar";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { api, ApiError } from "@/lib/api";
import { Agent } from "@/lib/types";
import { Bot, Plus, ShieldCheck } from "lucide-react";
import { money, titleCase } from "@/lib/format";

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listAgents()
      .then(setAgents)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load agents"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title="Agents" subtitle="Every agent acts under an explicit, reviewable spending policy." />
      <main className="flex-1 space-y-6 px-5 py-6 md:px-8">
        <div className="flex justify-end">
          <Link href="/agents/new">
            <Button variant="primary">
              <Plus size={18} /> Create an Agent
            </Button>
          </Link>
        </div>

        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}

        {!loading && agents.length === 0 && !error && (
          <div className="card-surface flex flex-col items-center gap-3 py-16 text-center">
            <Bot size={28} className="text-[var(--color-text-muted)]" />
            <p className="text-[var(--color-text-secondary)]">No agents yet.</p>
            <Link href="/agents/new">
              <Button variant="primary">
                <Plus size={18} /> Create your first agent
              </Button>
            </Link>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {agents.map((a) => (
            <Link
              key={a.id}
              href={`/agents/${a.id}`}
              className="card-surface animate-enter flex flex-col gap-4 p-5 transition-transform hover:-translate-y-0.5"
            >
              <div className="flex items-start justify-between">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--color-accent-soft)] text-[var(--color-accent)]">
                  <Bot size={18} />
                </span>
                <Badge tone={a.status === "ACTIVE" ? "success" : "muted"}>{titleCase(a.status)}</Badge>
              </div>
              <div>
                <h3 className="font-semibold">{a.name}</h3>
                <p className="mt-0.5 text-sm text-[var(--color-text-secondary)] line-clamp-2">{a.purpose}</p>
              </div>
              <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                <ShieldCheck size={14} />
                Autonomous up to {a.policy ? money(a.policy.approval_threshold) : "—"}
              </div>
              <div className="grid grid-cols-2 gap-3 border-t border-[var(--color-border)] pt-3 text-sm">
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">
                    Monthly used
                  </p>
                  <p className="font-mono-ui font-medium">{money(a.monthly_spent)}</p>
                </div>
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">
                    Remaining
                  </p>
                  <p className="font-mono-ui font-medium">{money(a.monthly_remaining)}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}
