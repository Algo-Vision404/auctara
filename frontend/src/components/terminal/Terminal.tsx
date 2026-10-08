"use client";

import { useEffect, useRef, useState } from "react";
import { api, subscribeToEvents, StreamEvent } from "@/lib/api";
import { AuditRecord } from "@/lib/types";
import { shortTime } from "@/lib/format";
import { TerminalSquare } from "lucide-react";

interface Line {
  id: string;
  time: string;
  type: string;
}

export function Terminal({ taskId, transactionId }: { taskId?: string; transactionId?: string }) {
  const [lines, setLines] = useState<Line[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    if (transactionId) {
      api
        .listAudit({ transaction_id: transactionId })
        .then((records: AuditRecord[]) => {
          if (!mounted) return;
          setLines(records.map((r) => ({ id: r.id, time: r.created_at, type: r.event_type })));
        })
        .catch(() => {});
    }

    const path = taskId ? `/tasks/${taskId}/events` : "/activity/stream";
    const unsub = subscribeToEvents(path, (evt: StreamEvent) => {
      if (!evt.event) return;
      setLines((prev) => [
        ...prev,
        { id: `${evt.timestamp}-${Math.random()}`, time: evt.timestamp || new Date().toISOString(), type: evt.event },
      ]);
    });
    return () => {
      mounted = false;
      unsub();
    };
  }, [taskId, transactionId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length]);

  return (
    <div className="card-surface overflow-hidden">
      <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-3">
        <TerminalSquare size={15} className="text-[var(--color-text-muted)]" />
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Terminal
        </span>
      </div>
      <div className="scrollbar-thin h-56 overflow-y-auto bg-[var(--color-surface-2)] px-4 py-3 font-mono-ui text-xs leading-relaxed">
        {lines.length === 0 && <p className="text-[var(--color-text-muted)]">Waiting for events…</p>}
        {lines.map((l) => (
          <div key={l.id} className="flex gap-3">
            <span className="text-[var(--color-text-muted)]">{shortTime(l.time)}</span>
            <span className="text-[var(--color-accent)]">{l.type}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
