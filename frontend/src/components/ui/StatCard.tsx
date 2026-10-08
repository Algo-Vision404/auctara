import { ReactNode } from "react";
import clsx from "clsx";

export function StatCard({
  label,
  value,
  icon,
  tone = "default",
  sub,
}: {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  tone?: "default" | "accent" | "warning";
  sub?: ReactNode;
}) {
  return (
    <div className="card-surface animate-enter flex flex-col gap-3 p-5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {label}
        </span>
        {icon && (
          <span
            className={clsx(
              "flex h-8 w-8 items-center justify-center",
              tone === "accent" && "text-[var(--color-accent)]",
              tone === "warning" && "text-[var(--color-warning)]",
              tone === "default" && "text-[var(--color-text-secondary)]"
            )}
          >
            {icon}
          </span>
        )}
      </div>
      <div className="font-mono-ui text-3xl font-medium tracking-tight text-[var(--color-text)]">{value}</div>
      {sub && <div className="text-xs text-[var(--color-text-secondary)]">{sub}</div>}
    </div>
  );
}
