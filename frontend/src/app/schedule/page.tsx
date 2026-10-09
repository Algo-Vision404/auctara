"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/nav/TopBar";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { api, ApiError } from "@/lib/api";
import { Agent, Recurrence, ScheduledTask, ScheduleRun } from "@/lib/types";
import { fullDateTime, money, titleCase } from "@/lib/format";
import { CalendarClock, Pause, Play, Ban, Trash2, ArrowRight, Loader2, CircleCheck } from "lucide-react";

// The Bryntum widget touches `document` on import, so it must never run
// during server rendering.
const ScheduleBoard = dynamic(() => import("@/components/schedule/ScheduleBoard").then((m) => m.ScheduleBoard), {
  ssr: false,
  loading: () => (
    <div className="card-surface flex h-[420px] items-center justify-center text-sm text-[var(--color-text-secondary)]">
      <Loader2 size={16} className="mr-2 animate-spin" /> Loading schedule timeline…
    </div>
  ),
});

const RECURRENCE_OPTIONS: { value: Recurrence; label: string }[] = [
  { value: "ONCE", label: "Once" },
  { value: "DAILY", label: "Daily" },
  { value: "WEEKLY", label: "Weekly" },
  { value: "MONTHLY", label: "Monthly" },
];

function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function SchedulePage() {
  const router = useRouter();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [schedules, setSchedules] = useState<ScheduledTask[]>([]);
  const [runsBySchedule, setRunsBySchedule] = useState<Record<string, ScheduleRun[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<string | null>(null);

  const [agentId, setAgentId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [maxAmount, setMaxAmount] = useState("50");
  const [recurrence, setRecurrence] = useState<Recurrence>("DAILY");
  const [startAt, setStartAt] = useState(() => toLocalInputValue(new Date()));
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      Promise.all([api.listAgents(), api.listSchedules()])
        .then(async ([a, s]) => {
          if (!mounted) return;
          setAgents(a);
          setSchedules(s);
          setError(null);
          if (!agentId && a.length > 0) setAgentId(a[0].id);

          // Run history per schedule, for the timeline's real execution
          // record (see ScheduleBoard). One request per schedule, same
          // per-item fetch pattern already used elsewhere in this app (e.g.
          // the ledger's agent-name lookups) - fine at this project's scale,
          // and simpler than adding a bulk endpoint for what is always a
          // short, human-curated list of standing instructions.
          try {
            const pairs = await Promise.all(
              s.map(async (sched) => [sched.id, await api.listScheduleRuns(sched.id)] as const)
            );
            if (!mounted) return;
            setRunsBySchedule(Object.fromEntries(pairs));
          } catch {
            // Non-fatal: the board still renders (just without run history)
            // if this secondary fetch fails; the schedules themselves loaded fine.
          }
        })
        .catch((e) => mounted && setError(e instanceof ApiError ? e.message : "Failed to load schedule data"));
    };
    load();
    const i = setInterval(load, 5000);
    return () => {
      mounted = false;
      clearInterval(i);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeAgents = useMemo(() => agents.filter((a) => a.status === "ACTIVE"), [agents]);

  async function handleCreate() {
    setFormError(null);
    if (!agentId) {
      setFormError("Choose an agent to delegate this recurring instruction to.");
      return;
    }
    if (prompt.trim().length < 3) {
      setFormError("Describe what the agent should do each time this fires.");
      return;
    }
    setCreating(true);
    try {
      const iso = new Date(startAt).toISOString();
      const created = await api.createSchedule({
        agent_id: agentId,
        prompt: prompt.trim(),
        max_amount: maxAmount ? Number(maxAmount) : null,
        recurrence,
        start_at: iso,
      });
      setSchedules((prev) => [created, ...prev]);
      setPrompt("");
      setHighlighted(created.id);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Failed to create scheduled task");
    } finally {
      setCreating(false);
    }
  }

  async function handleStatusChange(id: string, status: "ACTIVE" | "PAUSED" | "CANCELLED") {
    setActingOn(id);
    try {
      const updated = await api.updateSchedule(id, { status });
      setSchedules((prev) => prev.map((s) => (s.id === id ? updated : s)));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to update schedule");
    } finally {
      setActingOn(null);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm("Permanently delete this scheduled task? This cannot be undone.")) return;
    setActingOn(id);
    try {
      await api.deleteSchedule(id);
      setSchedules((prev) => prev.filter((s) => s.id !== id));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to delete schedule");
    } finally {
      setActingOn(null);
    }
  }

  function agentName(id: string) {
    return agents.find((a) => a.id === id)?.name || id;
  }

  return (
    <div className="flex flex-1 flex-col">
      <TopBar
        title="Agent Operations Schedule"
        subtitle="Standing delegated-spending instructions the backend fires on a real recurring clock, not simulated runs."
      />
      <main className="min-w-0 flex-1 space-y-6 px-5 py-6 md:px-8">
        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <div className="card-surface space-y-4 p-6">
          <div className="flex items-center gap-2">
            <CalendarClock size={18} className="text-[var(--color-accent)]" />
            <h2 className="font-semibold">New scheduled task</h2>
          </div>
          <p className="text-sm text-[var(--color-text-secondary)]">
            Give an agent a standing instruction. The scheduler fires it through the same research → policy → PayPal
            pipeline as an on-demand task. Every occurrence is a real, independently evaluated purchase decision.
          </p>

          {activeAgents.length === 0 ? (
            <p className="text-sm text-[var(--color-text-muted)]">
              No active agents yet.{" "}
              <Link href="/agents/new" className="font-semibold text-[var(--color-accent)]">
                Create one first
              </Link>
              .
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Agent">
                <select className="field-input" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                  {activeAgents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Recurrence">
                <select
                  className="field-input"
                  value={recurrence}
                  onChange={(e) => setRecurrence(e.target.value as Recurrence)}
                >
                  {RECURRENCE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="md:col-span-2">
                <Field label="Instruction">
                  <textarea
                    className="field-input"
                    rows={2}
                    placeholder="e.g. Renew our analytics subscription if the price is still under $100"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                  />
                </Field>
              </div>
              <Field label="Max amount (USD, optional)">
                <input
                  className="field-input"
                  type="number"
                  min={0}
                  step="0.01"
                  value={maxAmount}
                  onChange={(e) => setMaxAmount(e.target.value)}
                />
              </Field>
              <Field label="First run">
                <input
                  className="field-input"
                  type="datetime-local"
                  value={startAt}
                  onChange={(e) => setStartAt(e.target.value)}
                />
              </Field>
              <div className="md:col-span-2 flex items-center gap-3">
                <Button variant="primary" onClick={handleCreate} loading={creating}>
                  Schedule it <ArrowRight size={16} />
                </Button>
                {formError && <p className="text-sm text-[var(--color-danger)]">{formError}</p>}
              </div>
            </div>
          )}
        </div>

        <div className="card-surface min-w-0 overflow-x-auto p-3">
          <ScheduleBoard
            agents={activeAgents}
            schedules={schedules}
            runsBySchedule={runsBySchedule}
            onEventClick={(scheduleId, taskId) => {
              // A real past firing has a concrete task behind it - jump
              // straight to its live task/transaction view. The "Next run"
              // ghost marker has no task yet, so it just highlights that
              // schedule's row below instead.
              if (taskId) {
                router.push(`/tasks/${taskId}`);
              } else {
                setHighlighted(scheduleId);
              }
            }}
          />
          <p className="mt-2 text-xs text-[var(--color-text-muted)]">
            Solid blocks are real past firings, colored by their actual outcome (green completed, red
            blocked/failed, blue in progress); dashed outlines are each schedule&apos;s real next run. Click
            any past firing to open its live task. Calendar view runs on an evaluation build of a
            third-party scheduling widget, shown here in its own light theme with a small trial watermark.
          </p>
        </div>

        <div className="card-surface overflow-hidden">
          <div className="border-b border-[var(--color-border)] px-6 py-4">
            <h2 className="font-semibold">All scheduled tasks</h2>
          </div>
          {schedules.length === 0 ? (
            <p className="px-6 py-8 text-sm text-[var(--color-text-muted)]">
              No scheduled tasks yet. Create one above to delegate a recurring instruction.
            </p>
          ) : (
            <ul className="divide-y divide-[var(--color-border)]">
              {schedules.map((s) => (
                <li
                  key={s.id}
                  className={`flex flex-col gap-3 px-6 py-4 transition-colors md:flex-row md:items-center md:justify-between ${
                    highlighted === s.id ? "bg-[var(--color-accent-soft)]" : ""
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{agentName(s.agent_id)}</span>
                      <Badge tone={statusTone(s.status)}>{titleCase(s.status)}</Badge>
                      <Badge tone="muted">{titleCase(s.recurrence)}</Badge>
                      {s.max_amount != null && <Badge tone="muted">cap {money(s.max_amount)}</Badge>}
                    </div>
                    <p className="mt-1 truncate text-sm text-[var(--color-text-secondary)]">{s.prompt}</p>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--color-text-muted)]">
                      {s.status === "ACTIVE" || s.status === "PAUSED" ? (
                        <span>Next run: {fullDateTime(s.next_run_at)}</span>
                      ) : null}
                      {s.last_run_at && (
                        <span>
                          Last fired: {fullDateTime(s.last_run_at)}
                          {s.last_task_id && (
                            <>
                              {" "}
                              ·{" "}
                              <Link href={`/tasks/${s.last_task_id}`} className="font-semibold text-[var(--color-accent)]">
                                view task
                              </Link>
                            </>
                          )}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {s.status === "ACTIVE" && (
                      <IconAction
                        label="Pause"
                        icon={<Pause size={14} />}
                        onClick={() => handleStatusChange(s.id, "PAUSED")}
                        loading={actingOn === s.id}
                      />
                    )}
                    {s.status === "PAUSED" && (
                      <IconAction
                        label="Resume"
                        icon={<Play size={14} />}
                        onClick={() => handleStatusChange(s.id, "ACTIVE")}
                        loading={actingOn === s.id}
                      />
                    )}
                    {(s.status === "ACTIVE" || s.status === "PAUSED") && (
                      <IconAction
                        label="Cancel"
                        icon={<Ban size={14} />}
                        onClick={() => handleStatusChange(s.id, "CANCELLED")}
                        loading={actingOn === s.id}
                      />
                    )}
                    {s.status === "COMPLETED" && (
                      <span className="flex items-center gap-1 text-xs text-[var(--color-success)]">
                        <CircleCheck size={14} /> Completed
                      </span>
                    )}
                    <IconAction
                      label="Delete"
                      icon={<Trash2 size={14} />}
                      variant="danger"
                      onClick={() => handleDelete(s.id)}
                      loading={actingOn === s.id}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
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

function statusTone(status: string): "success" | "warning" | "muted" | "danger" {
  if (status === "ACTIVE") return "success";
  if (status === "PAUSED") return "warning";
  if (status === "CANCELLED") return "danger";
  return "muted";
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

function IconAction({
  label,
  icon,
  onClick,
  loading,
  variant = "secondary",
}: {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  loading?: boolean;
  variant?: "secondary" | "danger";
}) {
  return (
    <button
      type="button"
      title={label}
      onClick={onClick}
      disabled={loading}
      className={`btn-block flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
        variant === "danger"
          ? "text-[var(--color-danger)] hover:bg-[var(--color-danger-soft)]"
          : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]"
      } disabled:opacity-50`}
    >
      {loading ? <Loader2 size={14} className="animate-spin" /> : icon}
      {label}
    </button>
  );
}
