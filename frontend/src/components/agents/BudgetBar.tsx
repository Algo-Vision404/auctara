import { money } from "@/lib/format";

export function BudgetBar({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number;
}) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const remaining = Math.max(limit - used, 0);
  const danger = pct > 90;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          {label}
        </span>
        <span className="font-mono-ui text-sm font-medium">{money(used)} used</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-[var(--color-surface-2)]">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${pct}%`,
            background: danger ? "var(--color-warning)" : "var(--color-accent)",
          }}
        />
      </div>
      <div className="mt-1.5 font-mono-ui text-xs text-[var(--color-text-muted)]">
        {money(remaining)} remaining of {money(limit)}
      </div>
    </div>
  );
}
