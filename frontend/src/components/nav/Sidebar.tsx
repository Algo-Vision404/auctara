"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import {
  LayoutDashboard,
  Bot,
  Activity,
  CalendarClock,
  ReceiptText,
  ShieldCheck,
  ScrollText,
  Settings2,
  ShieldHalf,
  Menu,
  X,
} from "lucide-react";

const items = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/schedule", label: "Schedule", icon: CalendarClock },
  { href: "/ledger", label: "Commerce Ledger", icon: ReceiptText },
  { href: "/policies", label: "Policies", icon: ShieldCheck },
  { href: "/audit", label: "Audit", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings2 },
];

function Brand() {
  return (
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
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-1 flex-col gap-1">
      {items.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
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
  );
}

export function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-64 md:flex-col md:border-r md:border-[var(--color-border)] md:bg-[var(--color-surface)] md:px-4 md:py-6">
      <Brand />
      <NavLinks />
      <div className="mt-auto px-2 pt-4 text-[11px] text-[var(--color-text-muted)]">
        Let AI agents act.
        <br />
        Keep financial authority under your control.
      </div>
    </aside>
  );
}

// Below the desktop sidebar's breakpoint there still isn't room to lay every
// item out as its own tab, but hiding half of them behind a bottom-bar
// "More" button meant some pages were only ever one tap away via a second,
// different menu than everything else - easy to miss, and visually
// inconsistent with the one clear list desktop users always see. A single
// menu button that opens the exact same full item list, every time, at
// every width, is simpler to use and simpler to reason about: there is
// never a "hidden" page, just a closed drawer.
export function MobileNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="md:hidden">
      <button
        onClick={() => setOpen(true)}
        aria-label="Open navigation menu"
        aria-expanded={open}
        className="fixed bottom-5 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-accent)] text-[var(--color-accent-ink)] shadow-lg shadow-black/20"
      >
        <Menu size={20} />
      </button>

      {open && (
        <button
          aria-label="Close navigation menu"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-40 bg-black/40"
        />
      )}

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className={clsx(
          "fixed inset-y-0 left-0 z-50 flex w-72 max-w-[80vw] flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-6 transition-transform duration-200",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="flex items-start justify-between">
          <Brand />
          <button
            onClick={() => setOpen(false)}
            aria-label="Close navigation menu"
            className="rounded-lg p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]"
          >
            <X size={18} />
          </button>
        </div>
        <NavLinks onNavigate={() => setOpen(false)} />
        <div className="mt-auto px-2 pt-4 text-[11px] text-[var(--color-text-muted)]">
          Let AI agents act.
          <br />
          Keep financial authority under your control.
        </div>
      </aside>
    </div>
  );
}
