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
import { api } from "@/lib/api";

// Grouped (rather than one flat list) so the sidebar reads as a map of the
// product's actual shape - what you watch day to day, where money and
// schedules live, and where the rules/evidence behind them live - instead
// of eight visually-identical rows with no hierarchy.
const groups: { label: string; items: { href: string; label: string; icon: typeof LayoutDashboard }[] }[] = [
  {
    label: "Workspace",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/agents", label: "Agents", icon: Bot },
      { href: "/activity", label: "Activity", icon: Activity },
    ],
  },
  {
    label: "Commerce",
    items: [
      { href: "/schedule", label: "Schedule", icon: CalendarClock },
      { href: "/ledger", label: "Commerce Ledger", icon: ReceiptText },
    ],
  },
  {
    label: "Governance",
    items: [
      { href: "/policies", label: "Policies", icon: ShieldCheck },
      { href: "/audit", label: "Audit", icon: ScrollText },
    ],
  },
];

const SETTINGS_ITEM = { href: "/settings", label: "Settings", icon: Settings2 };

function Brand() {
  return (
    <Link href="/" className="mb-6 flex items-center gap-2.5 px-2">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--color-accent)] text-[var(--color-accent-ink)]"
        style={{ boxShadow: "0 3px 0 0 var(--tactile-depth)" }}
      >
        <ShieldHalf size={19} strokeWidth={2.4} />
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

function NavRow({
  href,
  label,
  icon: Icon,
  active,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  active: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={clsx(
        "group relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors duration-150",
        active
          ? "bg-[var(--color-accent-soft)] font-semibold text-[var(--color-accent)]"
          : "font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]"
      )}
    >
      {active && (
        <span className="absolute -left-4 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-[var(--color-accent)]" />
      )}
      <Icon
        size={17}
        strokeWidth={active ? 2.3 : 2}
        className={active ? "" : "text-[var(--color-text-muted)] group-hover:text-[var(--color-text)]"}
      />
      {label}
    </Link>
  );
}

function NavSections({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <nav className="flex flex-1 flex-col overflow-y-auto scrollbar-thin">
      {groups.map((group, i) => (
        <div key={group.label} className={clsx("flex flex-col gap-0.5", i > 0 && "mt-5")}>
          <div className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
            {group.label}
          </div>
          {group.items.map((item) => (
            <NavRow key={item.href} {...item} active={isActive(item.href)} onNavigate={onNavigate} />
          ))}
        </div>
      ))}

      <div className="mt-5 border-t border-[var(--color-border)] pt-3">
        <NavRow {...SETTINGS_ITEM} active={isActive(SETTINGS_ITEM.href)} onNavigate={onNavigate} />
      </div>
    </nav>
  );
}

function SystemStatus() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    const poll = () =>
      api
        .health()
        .then(() => mounted && setOnline(true))
        .catch(() => mounted && setOnline(false));
    poll();
    const id = setInterval(poll, 20000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="card-surface mt-4 flex items-center gap-2 px-3 py-2.5 text-xs">
      <span className="relative flex h-2 w-2 shrink-0">
        {online !== false && (
          <span
            className={clsx(
              "absolute inline-flex h-full w-full rounded-full opacity-75",
              online === null ? "bg-[var(--color-text-muted)]" : "animate-ping bg-[var(--color-success)]"
            )}
          />
        )}
        <span
          className={clsx(
            "relative inline-flex h-2 w-2 rounded-full",
            online === null && "bg-[var(--color-text-muted)]",
            online === true && "bg-[var(--color-success)]",
            online === false && "bg-[var(--color-danger)]"
          )}
        />
      </span>
      <span className="font-medium text-[var(--color-text-secondary)]">
        {online === null ? "Checking backend..." : online ? "Backend online" : "Backend unreachable"}
      </span>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-64 md:flex-col md:border-r md:border-[var(--color-border)] md:bg-[var(--color-surface)] md:px-5 md:py-6">
      <Brand />
      <NavSections />
      <SystemStatus />
      <p className="mt-3 px-1 text-[11px] leading-snug text-[var(--color-text-muted)]">
        Let AI agents act.
        <br />
        Keep financial authority under your control.
      </p>
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
        className="fixed bottom-5 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-accent)] text-[var(--color-accent-ink)]"
        style={{ boxShadow: "0 3px 0 0 var(--tactile-depth), 0 8px 20px rgba(0,0,0,0.18)" }}
      >
        <Menu size={20} />
      </button>

      {open && (
        <button
          aria-label="Close navigation menu"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
        />
      )}

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className={clsx(
          "fixed inset-y-0 left-0 z-50 flex w-72 max-w-[80vw] flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] px-5 py-6 shadow-2xl transition-transform duration-200",
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
        <NavSections onNavigate={() => setOpen(false)} />
        <SystemStatus />
        <p className="mt-3 px-1 text-[11px] leading-snug text-[var(--color-text-muted)]">
          Let AI agents act.
          <br />
          Keep financial authority under your control.
        </p>
      </aside>
    </div>
  );
}
