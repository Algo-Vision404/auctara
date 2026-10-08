"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import {
  LayoutDashboard,
  Bot,
  Activity,
  ReceiptText,
  ShieldCheck,
  ScrollText,
  Settings2,
  ShieldHalf,
} from "lucide-react";

const items = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/ledger", label: "Commerce Ledger", icon: ReceiptText },
  { href: "/policies", label: "Policies", icon: ShieldCheck },
  { href: "/audit", label: "Audit", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings2 },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex md:w-64 md:flex-col md:border-r md:border-[var(--color-border)] md:bg-[var(--color-surface)] md:px-4 md:py-6">
      <Link href="/" className="mb-8 flex items-center gap-2 px-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-accent)] text-[var(--color-accent-ink)]">
          <ShieldHalf size={18} strokeWidth={2.4} />
        </div>
        <div className="leading-tight">
          <div className="font-semibold tracking-tight">AgentAuth</div>
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
            Delegated Spending
          </div>
        </div>
      </Link>

      <nav className="flex flex-1 flex-col gap-1">
        {items.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors duration-150",
                active
                  ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]"
              )}
            >
              <Icon size={18} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto px-2 pt-4 text-[11px] text-[var(--color-text-muted)]">
        Let AI agents act.
        <br />
        Keep financial authority under your control.
      </div>
    </aside>
  );
}

export function MobileNav() {
  const pathname = usePathname();
  const mobileItems = items.slice(0, 5);
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-[var(--color-border)] bg-[var(--color-surface)] md:hidden">
      {mobileItems.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={clsx(
              "flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium",
              active ? "text-[var(--color-accent)]" : "text-[var(--color-text-muted)]"
            )}
          >
            <Icon size={18} />
            {item.label.split(" ")[0]}
          </Link>
        );
      })}
    </nav>
  );
}
