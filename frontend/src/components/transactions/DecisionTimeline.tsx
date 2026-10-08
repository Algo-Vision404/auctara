import { LucideIcon, Circle } from "lucide-react";
import { shortTime } from "@/lib/format";
import clsx from "clsx";

export interface TimelineStage {
  key: string;
  label: string;
  icon: LucideIcon;
  status: "done" | "current" | "pending" | "skipped" | "failed";
  timestamp?: string | null;
  detail?: string;
}

const toneForStatus: Record<TimelineStage["status"], string> = {
  done: "success",
  current: "info",
  pending: "muted",
  skipped: "muted",
  failed: "danger",
};

export function DecisionTimeline({ stages }: { stages: TimelineStage[] }) {
  return (
    <div className="card-surface p-6">
      <div className="flex flex-col gap-0">
        {stages.map((stage, i) => {
          const Icon = stage.icon;
          const tone = toneForStatus[stage.status];
          const isLast = i === stages.length - 1;
          return (
            <div key={stage.key} className="flex gap-4">
              <div className="flex flex-col items-center">
                <span
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2"
                  style={{
                    borderColor: stage.status === "pending" || stage.status === "skipped"
                      ? "var(--color-border)"
                      : `var(--color-${tone})`,
                    color: stage.status === "pending" || stage.status === "skipped"
                      ? "var(--color-text-muted)"
                      : `var(--color-${tone})`,
                    background: stage.status === "done" || stage.status === "current"
                      ? `var(--color-${tone}-soft)`
                      : "transparent",
                  }}
                >
                  {stage.status === "pending" ? <Circle size={14} /> : <Icon size={16} />}
                </span>
                {!isLast && (
                  <span
                    className="my-1 w-0.5 flex-1"
                    style={{
                      minHeight: "28px",
                      background:
                        stage.status === "done" ? "var(--color-success)" : "var(--color-border)",
                    }}
                  />
                )}
              </div>
              <div className={clsx("pb-7", isLast && "pb-0")}>
                <div className="flex items-center gap-2">
                  <p
                    className={clsx(
                      "text-sm font-semibold",
                      stage.status === "pending" || stage.status === "skipped"
                        ? "text-[var(--color-text-muted)]"
                        : "text-[var(--color-text)]"
                    )}
                  >
                    {stage.label}
                  </p>
                  {stage.timestamp && (
                    <span className="font-mono-ui text-[11px] text-[var(--color-text-muted)]">
                      {shortTime(stage.timestamp)}
                    </span>
                  )}
                </div>
                {stage.detail && (
                  <p className="mt-0.5 max-w-md text-xs text-[var(--color-text-secondary)]">{stage.detail}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
