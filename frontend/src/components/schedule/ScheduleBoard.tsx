"use client";

// Bryntum ships its structural CSS, icon font, and color theme as three
// separate stylesheets (see @bryntum/scheduler-react's own README). Only the
// theme file was previously imported here, which left the widget missing
// its real layout/row/event-bar styling and icons entirely.
//
// A dark theme variant was tried here before (swapping stockholm-light.css
// for stockholm-dark.css at runtime via a <link> tag keyed to the app's own
// theme toggle). That made the widget unreadable: Bryntum's trial watermark
// overlay is a fixed dark, semi-transparent layer, and stacking it on top of
// the dark skin's own near-black background produced what looked like a
// solid black panel with the watermark barely visible on top of it, not a
// usable calendar. The light skin keeps the watermark legible and the grid
// itself readable, so it is intentionally static regardless of the app's
// own light/dark toggle. This is a deliberate, accepted limitation of using
// the unlicensed trial build, not an oversight.
import "@bryntum/scheduler/fontawesome/css/fontawesome.css";
import "@bryntum/scheduler/fontawesome/css/solid.css";
import "@bryntum/scheduler/scheduler.css";
import "@bryntum/scheduler/stockholm-light.css";

import { useMemo } from "react";
import { BryntumScheduler } from "@bryntum/scheduler-react";
import type { EventModelConfig, ResourceModelConfig } from "@bryntum/scheduler";
import { money, shortTime } from "@/lib/format";
import { Agent, ScheduledTask, ScheduleRun } from "@/lib/types";

// Bryntum's named palette renders as a faint tonal tint in this theme, which
// reads as "broken" against the app's deliberately bold, high-contrast
// design system. Events are painted directly with the same brand colors
// used elsewhere in the app. These are fixed hex values, not the app's
// --color-accent/--color-success/etc. tokens, because the widget's own
// chrome is always the light Bryntum skin (see the import note above): the
// dark mode tokens are tuned for light text on a near-black app background,
// and would look washed out or neon against this permanently light grid.
const SUCCESS = "#0F9D6B";
const DANGER = "#D64545";
const MUTED = "#8A958D";
const PENDING = "#2563EB";
const ACCENT = "#0F766E";

// Maps a real transaction outcome (or its absence) to a color. A run whose
// task hasn't produced a transaction yet (still researching, or the
// pipeline failed before one was created) is deliberately distinct from
// both "succeeded" and "failed" - it is neither, and showing it as one or
// the other would misrepresent a real in-flight/unresolved state as a
// fabricated result.
function outcomeColor(state: string | null): string {
  if (state === "COMPLETED") return SUCCESS;
  if (state === "BLOCKED" || state === "FAILED" || state === "VOIDED") return DANGER;
  if (state === "CANCELLED") return MUTED;
  return PENDING;
}

function outcomeLabel(run: ScheduleRun): string {
  if (run.merchant) return run.merchant;
  if (run.transaction_state) return run.transaction_state;
  return "In progress";
}

interface ScheduleEvent extends EventModelConfig {
  kind: "run" | "upcoming";
  taskId?: string;
  scheduleId: string;
  color: string;
  tooltip: string;
}

export function ScheduleBoard({
  agents,
  schedules,
  runsBySchedule,
  onEventClick,
}: {
  agents: Agent[];
  schedules: ScheduledTask[];
  // Real past firings per schedule id (GET /schedules/{id}/runs) - see the
  // Agent Operations Schedule page, which fetches these alongside the
  // schedules themselves. Absent entries (not yet loaded, or a schedule
  // with zero firings yet) are treated as "no history", never as "nothing
  // has ever run" for schedules that simply haven't loaded yet.
  runsBySchedule: Record<string, ScheduleRun[]>;
  onEventClick?: (scheduleId: string, taskId?: string) => void;
}) {
  const resources: ResourceModelConfig[] = useMemo(
    () => agents.map((a) => ({ id: a.id, name: a.name })),
    [agents]
  );

  // Each real past firing becomes its own event, colored by its actual
  // outcome, plus - for schedules still live - exactly one "Next run"
  // marker at the real stored next_run_at. This replaces an earlier version
  // that used Bryntum's recurrenceRule to generate an infinite synthetic
  // repeating pattern: that looked like a calendar of a schedule's intent,
  // not a record of what it actually did. A true execution history (what
  // really fired, and whether it really succeeded) is both more honest and
  // a better fit for a timeline widget than a purely theoretical pattern.
  const events: ScheduleEvent[] = useMemo(() => {
    const out: ScheduleEvent[] = [];
    for (const s of schedules) {
      const runs = runsBySchedule[s.id] || [];
      for (const run of runs) {
        out.push({
          id: `run-${run.task_id}`,
          resourceId: s.agent_id,
          name: outcomeLabel(run),
          startDate: run.fired_at,
          duration: 3,
          durationUnit: "hour",
          kind: "run",
          taskId: run.task_id,
          scheduleId: s.id,
          color: outcomeColor(run.transaction_state),
          tooltip:
            `${shortTime(run.fired_at)} — ${s.prompt}` +
            (run.amount != null ? ` — ${money(run.amount, run.currency || "USD")}` : "") +
            ` — ${run.transaction_state || run.task_status}`,
          readOnly: true,
        });
      }
      if (s.status === "ACTIVE" || s.status === "PAUSED") {
        out.push({
          id: `next-${s.id}`,
          resourceId: s.agent_id,
          name: s.status === "PAUSED" ? "Next run (paused)" : "Next run",
          startDate: s.next_run_at,
          duration: 3,
          durationUnit: "hour",
          kind: "upcoming",
          scheduleId: s.id,
          color: ACCENT,
          tooltip: `${shortTime(s.next_run_at)} — ${s.prompt} — scheduled, hasn't fired yet`,
          readOnly: true,
        });
      }
    }
    return out;
  }, [schedules, runsBySchedule]);

  // The visible date window has to cover real data on both ends: the
  // earliest a schedule has ever actually fired, and the furthest-out
  // next_run_at among live schedules (a MONTHLY schedule's next run can be
  // weeks away, well past a fixed "+14 days"). Capped on both sides so one
  // very old demo record or one far-future monthly schedule can't blow the
  // view out to an unusable scale.
  const { startDate, endDate } = useMemo(() => {
    const now = Date.now();
    const DAY = 24 * 3600 * 1000;
    let earliest = now - DAY;
    let latest = now + 14 * DAY;
    for (const ev of events) {
      const t = new Date(ev.startDate as string).getTime();
      if (!Number.isNaN(t)) {
        earliest = Math.min(earliest, t);
        latest = Math.max(latest, t + DAY);
      }
    }
    earliest = Math.max(earliest, now - 60 * DAY);
    latest = Math.min(latest, now + 90 * DAY);
    return { startDate: new Date(earliest), endDate: new Date(latest) };
  }, [events]);

  return (
    <BryntumScheduler
      height={420}
      startDate={startDate}
      endDate={endDate}
      viewPreset="weekAndDay"
      rowHeight={54}
      barMargin={8}
      resources={resources}
      events={events}
      readOnly
      eventEditFeature={false}
      eventDragFeature={false}
      eventResizeFeature={false}
      eventDragCreateFeature={false}
      // Real, live current-time marker - genuinely useful on a timeline that
      // now mixes real past executions with a real future firing, so it's
      // visually obvious where "already happened" ends and "projected" begins.
      timeRangesFeature={{ showCurrentTimeLine: true }}
      eventTooltipFeature={{
        template: ({ eventRecord }: { eventRecord: unknown }) =>
          String((eventRecord as unknown as { tooltip?: string }).tooltip ?? ""),
      }}
      columns={[{ text: "Agent", field: "name", width: 180 }]}
      eventRenderer={({ eventRecord, renderData }) => {
        const rec = eventRecord as unknown as ScheduleEvent;
        const isUpcoming = rec.kind === "upcoming";
        renderData.style = isUpcoming
          ? `background-color: transparent; color: ${rec.color}; border: 2px dashed ${rec.color};`
          : `background-color: ${rec.color}; color: #FFFFFF; border: none;`;
        return String(eventRecord.name ?? "");
      }}
      onEventClick={({ eventRecord }) => {
        const rec = eventRecord as unknown as ScheduleEvent;
        onEventClick?.(rec.scheduleId, rec.taskId);
      }}
      emptyText="No agents yet. Create one before scheduling a recurring task."
    />
  );
}
