"use client";

// Bryntum ships its structural CSS, icon font, and color theme as three
// separate stylesheets (see @bryntum/scheduler-react's own README). Only the
// theme file was previously imported here, which left the widget missing
// its real layout/row/event-bar styling and icons entirely. The structural
// and icon CSS never change with light/dark mode, so they are static
// imports; the color theme does, so it is swapped at runtime below via a
// <link> tag instead (two full stylesheets can't both be statically
// imported and live-toggled, since they define the same CSS variables at
// the same specificity).
import "@bryntum/scheduler/fontawesome/css/fontawesome.css";
import "@bryntum/scheduler/fontawesome/css/solid.css";
import "@bryntum/scheduler/scheduler.css";

import { useMemo } from "react";
import { useTheme } from "next-themes";
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
// design system. Events are painted directly with the same brand tokens
// used by the rest of the app's status badges (see components/ui/Badge.tsx).
// These reference the same design tokens defined in globals.css (and
// redefined under .dark there) instead of hardcoding their light mode hex
// values, so the event bars keep following the app's theme instead of
// freezing on light mode colors once the user switches to dark mode.
const STATUS_STYLE: Record<string, { bg: string; fg: string }> = {
  ACTIVE: { bg: "var(--color-accent)", fg: "var(--color-accent-ink)" },
  PAUSED: { bg: "var(--color-warning)", fg: "#FFFFFF" },
  CANCELLED: { bg: "var(--color-text-muted)", fg: "#FFFFFF" },
  COMPLETED: { bg: "var(--color-success)", fg: "#FFFFFF" },
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
  const { resolvedTheme } = useTheme();
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
    <>
      {/* React 19 hoists a <link> rendered anywhere in the tree into <head>.
          Swapping its href (rather than statically importing both theme
          files) is what actually makes the widget follow the app's own
          light/dark toggle instead of always rendering in light chrome. */}
      <link
        rel="stylesheet"
        href={resolvedTheme === "dark" ? "/bryntum/stockholm-dark.css" : "/bryntum/stockholm-light.css"}
      />
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
    </>
  );
}
