"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { TopBar } from "@/components/nav/TopBar";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { api, ApiError } from "@/lib/api";
import { Agent } from "@/lib/types";
import { titleCase } from "@/lib/format";
import { ShieldCheck, Save, FlaskConical, Plus } from "lucide-react";

export default function PoliciesPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listAgents()
      .then(setAgents)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load policies"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title="Policies" subtitle="The deterministic rules your policy engine enforces — never the AI." />
      <main className="flex-1 space-y-6 px-5 py-6 md:px-8">
        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}

        {!loading && agents.length === 0 && !error && (
          <div className="card-surface flex flex-col items-center gap-3 py-16 text-center">
            <ShieldCheck size={28} className="text-[var(--color-text-muted)]" />
            <p className="text-[var(--color-text-secondary)]">
              No agents yet. Create an agent to define and tune its spending policy.
            </p>
            <Link href="/agents/new">
              <Button variant="primary">
                <Plus size={18} /> Create your first agent
              </Button>
            </Link>
          </div>
        )}

        {!loading && agents.length > 0 && (
          <>
            <PolicySandbox agents={agents} />
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
              {agents.map((a) => (
                <PolicyEditor key={a.id} agent={a} />
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function PolicySandbox({ agents }: { agents: Agent[] }) {
  const [agentId, setAgentId] = useState("");
  const [amount, setAmount] = useState("63.99");
  const [category, setCategory] = useState("software");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!agentId && agents.length > 0) setAgentId(agents[0].id);
  }, [agents, agentId]);

  async function run() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.evaluatePolicy({ agent_id: agentId, amount: Number(amount), category });
      setResult(r as Record<string, unknown>);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Evaluation failed");
    } finally {
      setLoading(false);
    }
  }

  const decision = result?.decision as string | undefined;
  const tone = decision === "ALLOW" ? "success" : decision === "APPROVAL_REQUIRED" ? "warning" : decision === "BLOCK" ? "danger" : "muted";

  return (
    <div className="card-surface space-y-4 p-6">
      <h3 className="flex items-center gap-2 font-semibold">
        <FlaskConical size={18} className="text-[var(--color-accent)]" /> Policy Sandbox
      </h3>
      <p className="text-sm text-[var(--color-text-secondary)]">
        Dry-run the deterministic engine against a hypothetical proposal. This never reserves budget or creates a
        transaction.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <select
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          className="field-input rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm"
        >
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          type="number"
          placeholder="Amount"
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm"
        />
        <input
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          placeholder="Category"
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm"
        />
        <Button variant="primary" onClick={run} loading={loading} disabled={!agentId}>
          Evaluate
        </Button>
      </div>
      {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
      {result && (
        <div className="flex flex-wrap items-center gap-4 rounded-xl bg-[var(--color-surface-2)] px-4 py-3">
          <Badge tone={tone as "success" | "warning" | "danger"}>{titleCase(decision)}</Badge>
          <span className="text-sm text-[var(--color-text-secondary)]">{result.reason as string}</span>
        </div>
      )}
    </div>
  );
}

function PolicyEditor({ agent }: { agent: Agent }) {
  const p = agent.policy;
  const [form, setForm] = useState(
    p || {
      max_transaction_amount: 150,
      approval_threshold: 100,
      daily_limit: 300,
      monthly_limit: 2000,
      velocity_max_transactions: 5,
      velocity_window_minutes: 60,
      price_variance_tolerance: 0.05,
      blocked_categories: [] as string[],
      allowed_categories: [] as string[],
    }
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.updatePolicy(agent.id, {
        max_transaction_amount: form.max_transaction_amount,
        approval_threshold: form.approval_threshold,
        daily_limit: form.daily_limit,
        monthly_limit: form.monthly_limit,
        velocity: { max_transactions: form.velocity_max_transactions, window_minutes: form.velocity_window_minutes },
        price_variance_tolerance: form.price_variance_tolerance,
        blocked_categories: form.blocked_categories,
        allowed_categories: form.allowed_categories,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save policy");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card-surface space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 font-semibold">
          <ShieldCheck size={18} className="text-[var(--color-accent)]" /> {agent.name}
        </h3>
        <Badge tone={agent.status === "ACTIVE" ? "success" : "muted"}>{titleCase(agent.status)}</Badge>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <NumField
          label="Autonomous authority"
          value={form.approval_threshold}
          onChange={(v) => setForm({ ...form, approval_threshold: v })}
        />
        <NumField
          label="Max transaction"
          value={form.max_transaction_amount}
          onChange={(v) => setForm({ ...form, max_transaction_amount: v })}
        />
        <NumField label="Daily limit" value={form.daily_limit} onChange={(v) => setForm({ ...form, daily_limit: v })} />
        <NumField
          label="Monthly limit"
          value={form.monthly_limit}
          onChange={(v) => setForm({ ...form, monthly_limit: v })}
        />
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          Blocked categories
        </label>
        <input
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm"
          defaultValue={form.blocked_categories.join(", ")}
          onChange={(e) =>
            setForm({ ...form, blocked_categories: e.target.value.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean) })
          }
        />
      </div>
      {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
      <Button variant="primary" onClick={save} loading={saving}>
        {saved ? "Saved" : <>
          <Save size={16} /> Save Policy
        </>}
      </Button>
    </div>
  );
}

function NumField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
        {label}
      </label>
      <div className="flex items-center gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2">
        <span className="font-mono-ui text-sm text-[var(--color-text-muted)]">$</span>
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full bg-transparent font-mono-ui text-sm font-semibold outline-none"
        />
      </div>
    </div>
  );
}
