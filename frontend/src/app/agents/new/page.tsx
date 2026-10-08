"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/nav/TopBar";
import { Button } from "@/components/ui/Button";
import { api, ApiError } from "@/lib/api";
import { PolicyDraft } from "@/lib/types";
import { Sparkles, ShieldCheck, Ban, ArrowRight, Loader2, CircleCheck, TriangleAlert } from "lucide-react";

const EXAMPLE =
  "Manage our SaaS subscriptions.\n\nYou can spend up to $100 without asking me.\n\nAnything above that needs approval.\n\nNever buy gambling or crypto products.\n\nMonthly budget is $2,000.";

export default function NewAgentPage() {
  const router = useRouter();
  const [instructions, setInstructions] = useState(EXAMPLE);
  const [draft, setDraft] = useState<PolicyDraft | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [activating, setActivating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDraft() {
    setError(null);
    setDrafting(true);
    setDraft(null);
    try {
      const d = await api.draftPolicy(instructions);
      setDraft(d);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to draft policy");
    } finally {
      setDrafting(false);
    }
  }

  async function handleActivate() {
    if (!draft) return;
    setActivating(true);
    setError(null);
    try {
      const agent = await api.createAgent({
        name: draft.agent_name,
        purpose: draft.agent_purpose,
        directive: instructions,
        policy: {
          max_transaction_amount: draft.max_transaction_amount,
          approval_threshold: draft.approval_threshold,
          daily_limit: draft.daily_limit,
          monthly_limit: draft.monthly_limit,
          velocity: draft.velocity,
          price_variance_tolerance: draft.price_variance_tolerance,
          blocked_categories: draft.blocked_categories,
          allowed_categories: draft.allowed_categories,
        },
      });
      router.push(`/agents/${agent.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to activate agent");
    } finally {
      setActivating(false);
    }
  }

  function updateDraft<K extends keyof PolicyDraft>(key: K, value: PolicyDraft[K]) {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  }

  // The backend rejects a negative, zero, or missing policy value outright
  // (max_transaction_amount must be greater than zero, the rest zero or
  // greater), but it should never be possible to even press Activate with
  // one: catch it here too so the mistake is obvious before the round trip.
  const hasInvalidPolicyValue =
    !!draft &&
    (!Number.isFinite(draft.max_transaction_amount) ||
      draft.max_transaction_amount <= 0 ||
      [draft.approval_threshold, draft.daily_limit, draft.monthly_limit].some((v) => !Number.isFinite(v) || v < 0));

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title="Create an Agent" subtitle="Natural language → explicit financial authority." />
      <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-5 py-6 md:px-8">
        <div className="card-surface space-y-4 p-6">
          <label className="text-sm font-semibold">Describe what this agent should do</label>
          <textarea
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            rows={7}
            className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-2)] p-4 font-mono-ui text-sm leading-relaxed text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]"
            placeholder="Describe the agent's purpose and spending authority in plain language..."
          />
          <Button variant="primary" onClick={handleDraft} loading={drafting} disabled={instructions.trim().length < 5}>
            <Sparkles size={16} /> {drafting ? "Drafting policy…" : "Generate Policy"}
          </Button>
          {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
        </div>

        {drafting && (
          <div className="card-surface flex items-center gap-3 p-6 text-sm text-[var(--color-text-secondary)]">
            <Loader2 size={16} className="animate-spin" />
            Converting your instructions into an explicit policy…
          </div>
        )}

        {draft && (
          <div className="card-elevated animate-enter space-y-5 p-6">
            <div className="flex items-center gap-2 text-[var(--color-accent)]">
              <ShieldCheck size={18} />
              <h3 className="font-semibold">Review before activating</h3>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Agent name">
                <input
                  className="field-input"
                  value={draft.agent_name}
                  onChange={(e) => updateDraft("agent_name", e.target.value)}
                />
              </Field>
              <Field label="Purpose">
                <input
                  className="field-input"
                  value={draft.agent_purpose}
                  onChange={(e) => updateDraft("agent_purpose", e.target.value)}
                />
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <PolicyStat
                label="Autonomous Authority"
                value={draft.approval_threshold}
                onChange={(v) => updateDraft("approval_threshold", v)}
              />
              <PolicyStat
                label="Max Transaction"
                value={draft.max_transaction_amount}
                onChange={(v) => updateDraft("max_transaction_amount", v)}
              />
              <PolicyStat label="Daily Limit" value={draft.daily_limit} onChange={(v) => updateDraft("daily_limit", v)} />
              <PolicyStat
                label="Monthly Limit"
                value={draft.monthly_limit}
                onChange={(v) => updateDraft("monthly_limit", v)}
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-2)] p-4">
                <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--color-danger)]">
                  <Ban size={13} /> Blocked Categories
                </p>
                <CategoryEditor
                  values={draft.blocked_categories}
                  onChange={(v) => updateDraft("blocked_categories", v)}
                  placeholder="gambling, crypto"
                />
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-2)] p-4">
                <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--color-success)]">
                  <CircleCheck size={13} /> Permitted Categories
                </p>
                <CategoryEditor
                  values={draft.allowed_categories}
                  onChange={(v) => updateDraft("allowed_categories", v)}
                  placeholder="empty = any non-blocked category"
                />
                {draft.allowed_categories.length === 0 && (
                  <p className="mt-2 flex items-start gap-1.5 text-[11px] text-[var(--color-warning)]">
                    <TriangleAlert size={12} className="mt-0.5 shrink-0" />
                    No category restriction: this agent can attempt to purchase anything not explicitly
                    blocked, not just what its purpose describes. Scope it to specific categories (e.g.
                    software, subscriptions) unless you actually intend broad purchasing authority.
                  </p>
                )}
              </div>
            </div>

            <div className="flex items-center justify-between border-t border-[var(--color-border)] pt-4 text-xs text-[var(--color-text-muted)]">
              <span>
                Velocity: {draft.velocity.max_transactions} transactions / {draft.velocity.window_minutes} min ·
                Price tolerance: {(draft.price_variance_tolerance * 100).toFixed(0)}%
              </span>
            </div>

            {hasInvalidPolicyValue && (
              <p className="text-sm text-[var(--color-danger)]">
                Policy amounts must be zero or greater before this agent can be activated.
              </p>
            )}
            <Button
              variant="primary"
              fullWidth
              onClick={handleActivate}
              loading={activating}
              disabled={hasInvalidPolicyValue}
            >
              Activate Agent <ArrowRight size={16} />
            </Button>
          </div>
        )}
      </main>
      <style jsx global>{`
        .field-input {
          width: 100%;
          border-radius: 10px;
          border: 1px solid var(--color-border);
          background: var(--color-surface-2);
          padding: 0.6rem 0.75rem;
          font-size: 0.875rem;
          color: var(--color-text);
          outline: none;
        }
        .field-input:focus {
          border-color: var(--color-accent);
        }
      `}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
        {label}
      </label>
      {children}
    </div>
  );
}

function PolicyStat({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] p-3">
      <label className="block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
        {label}
      </label>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="font-mono-ui text-sm text-[var(--color-text-muted)]">$</span>
        <input
          type="number"
          min="0"
          step="0.01"
          value={value}
          onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
          className="w-full bg-transparent font-mono-ui text-lg font-semibold text-[var(--color-text)] outline-none"
        />
      </div>
    </div>
  );
}

function CategoryEditor({
  values,
  onChange,
  placeholder,
}: {
  values: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
}) {
  const [text, setText] = useState(values.join(", "));
  return (
    <input
      className="w-full bg-transparent text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-text-muted)]"
      value={text}
      placeholder={placeholder}
      onChange={(e) => {
        setText(e.target.value);
        onChange(
          e.target.value
            .split(",")
            .map((s) => s.trim().toLowerCase())
            .filter(Boolean)
        );
      }}
    />
  );
}
