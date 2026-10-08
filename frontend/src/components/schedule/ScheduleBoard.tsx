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
import { Agent, ScheduledTask } from "@/lib/types";

const RECURRENCE_RULE: Record<string, string | undefined> = {
  ONCE: undefined,
  DAILY: "FREQ=DAILY;INTERVAL=1",
  WEEKLY: "FREQ=WEEKLY;INTERVAL=1",
  MONTHLY: "FREQ=MONTHLY;INTERVAL=1",
};

// Bryntum's named palette renders as a faint tonal tint in this theme, which
// reads as "broken" against the app's deliberately bold, high-contrast
// design system. Events are painted directly with the same brand colors
// used elsewhere in the app. These are fixed hex values, not the app's
// --color-accent/--color-success/etc. tokens, because the widget's own
// chrome is always the light Bryntum skin (see the import note above): the
// dark mode tokens are tuned for light text on a near-black app background,
// and would look washed out or neon against this permanently light grid.
const STATUS_STYLE: Record<string, { bg: string; fg: string }> = {
  ACTIVE: { bg: "#0F766E", fg: "#FFFFFF" },
  PAUSED: { bg: "#C98516", fg: "#FFFFFF" },
  CANCELLED: { bg: "#8A958D", fg: "#FFFFFF" },
  COMPLETED: { bg: "#159A68", fg: "#FFFFFF" },
};

export function ScheduleBoard({
  agents,
  schedules,
  onEventClick,
}: {
  agents: Agent[];
  schedules: ScheduledTask[];
  onEventClick?: (scheduleId: string) => void;
}) {
  const resources: ResourceModelConfig[] = useMemo(
    () => agents.map((a) => ({ id: a.id, name: a.name })),
    [agents]
  );

  const events: EventModelConfig[] = useMemo(
    () =>
      schedules.map((s) => {
        // Anchor point in time this block represents: the next upcoming fire
        // for live schedules, or the last known run time for finished ones.
        const anchor = s.status === "COMPLETED" || s.status === "CANCELLED" ? s.last_run_at || s.start_at : s.next_run_at;
        return {
          id: s.id,
          resourceId: s.agent_id,
          name: s.prompt.length > 60 ? `${s.prompt.slice(0, 57)}...` : s.prompt,
          startDate: anchor,
          // Purely a visual marker for a point in time: a few hours wide so the
          // block reads clearly at day-level zoom, not a literal execution duration.
          duration: 6,
          durationUnit: "hour",
          status: s.status,
          recurrenceRule: s.status === "ACTIVE" ? RECURRENCE_RULE[s.recurrence] : undefined,
          readOnly: true,
        };
      }),
    [schedules]
  );

  const now = useMemo(() => new Date(), []);
  const startDate = useMemo(() => new Date(now.getTime() - 24 * 3600 * 1000), [now]);
  const endDate = useMemo(() => new Date(now.getTime() + 14 * 24 * 3600 * 1000), [now]);

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
      columns={[{ text: "Agent", field: "name", width: 180 }]}
      eventRenderer={({ eventRecord, renderData }) => {
        const status = String((eventRecord as unknown as { status?: string }).status || "ACTIVE");
        const { bg, fg } = STATUS_STYLE[status] || STATUS_STYLE.ACTIVE;
        renderData.style = `background-color: ${bg}; color: ${fg}; border: none;`;
        return String(eventRecord.name ?? "");
      }}
      onEventClick={({ eventRecord }) => onEventClick?.(String(eventRecord.id))}
      emptyText="No agents yet. Create one before scheduling a recurring task."
    />
  );
}
