"use client";

import { useEffect, useState } from "react";
import { api, subscribeToEvents, StreamEvent } from "@/lib/api";
import { ActivityEvent } from "@/lib/types";
import { eventMeta } from "@/lib/eventMeta";
import { shortTime } from "@/lib/format";
import { Wifi, WifiOff } from "lucide-react";

export function ActivityFeed({ taskId, limit = 30 }: { taskId?: string; limit?: number }) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let mounted = true;
    api
      .recentActivity(limit)
      .then((data) => mounted && setEvents(data as ActivityEvent[]))
      .catch(() => {});

    const path = taskId ? `/tasks/${taskId}/events` : "/activity/stream";
    const unsub = subscribeToEvents(
      path,
      (evt: StreamEvent) => {
        if (!evt.message) return;
        setEvents((prev) => [
          {
            id: `${evt.timestamp}-${Math.random()}`,
            task_id: evt.task_id ?? null,
            transaction_id: evt.transaction_id ?? null,
            agent_id: evt.agent_id ?? null,
            event_type: evt.event,
            message: evt.message!,
            payload: evt.payload || {},
            created_at: evt.timestamp || new Date().toISOString(),
          },
          ...prev,
        ].slice(0, 200));
      },
      setConnected
    );
    return () => {
      mounted = false;
      unsub();
    };
  }, [taskId, limit]);

  return (
    <div className="card-surface flex max-h-[520px] flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-5 py-3.5">
        <h3 className="font-semibold text-[var(--color-text)]">Live Activity</h3>
        <span
          className={`flex items-center gap-1.5 text-xs font-medium ${
            connected ? "text-[var(--color-success)]" : "text-[var(--color-text-muted)]"
          }`}
        >
          {connected ? <Wifi size={13} /> : <WifiOff size={13} />}
          {connected ? "Live" : "Connecting…"}
        </span>
      </div>
      <div className="scrollbar-thin flex-1 overflow-y-auto px-2 py-2">
        {events.length === 0 && (
          <div className="px-3 py-8 text-center text-sm text-[var(--color-text-muted)]">
            No activity yet. Submit a task to an agent to see it work in real time.
          </div>
        )}
        {events.map((e) => {
          const meta = eventMeta(e.event_type);
          const Icon = meta.icon;
          return (
            <div
              key={e.id}
              className="animate-enter flex items-start gap-3 rounded-lg px-3 py-2.5 hover:bg-[var(--color-surface-2)]"
            >
              <span
                className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center"
                style={{
                  color: `var(--color-${meta.tone}, var(--color-text-secondary))`,
                }}
              >
                <Icon size={16} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-snug text-[var(--color-text)]">{e.message}</p>
                <p className="font-mono-ui text-[11px] text-[var(--color-text-muted)]">{shortTime(e.created_at)}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
