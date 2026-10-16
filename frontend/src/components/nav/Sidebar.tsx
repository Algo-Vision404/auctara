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
  Menu,
  X,
} from "lucide-react";
import { useLiveSidebarStatus } from "@/lib/useLiveSidebarStatus";

// The one nav item that gets a live count badge. Chosen deliberately: a
// transaction awaiting approval is actioned from its own page, and the
// ledger is the only place that page is reachable from, so this is the
// single spot in the nav where "N things need you" is both accurate and
// actually points at where to go do something about it.
const APPROVAL_BADGE_HREF = "/ledger";

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

// A bordered callout, not a line of muted text floating under the nav -
// plain small-print at the bottom of a sidebar is one of the clearest
// "this got scaffolded, not designed" tells, since nothing about its
// container signals it was placed on purpose.
function Footer() {
  return (
    <div className="mt-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2.5 text-[11px] leading-snug text-[var(--color-text-secondary)]">
      <span className="font-semibold text-[var(--color-text)]">Let AI agents act.</span>
      <br />
      Keep financial authority under your control.
    </div>
  );
}

// A custom mark instead of a stock shield/lock/checkmark glyph - every
// one of those reads as generic "security product" clip art the instant
// you've seen it on a hundred other dashboards. This is a small abstract
// scene instead: a rail with a deliberate gap in it, and an arrow rising
// up through that gap. That's literally what this product does - an
// agent's action (the arrow) passing through a checkpoint (the rail) that
// only lets it through on the terms you set - so the mark means something
// specific to AgentAuth rather than "trust us, we're secure."
function BrandMark({ size = 19 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3.5 15.5H9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M15 15.5H20.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <path
        d="M7 16L12 6L17 16"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Brand() {
  return (
    <Link href="/" className="mb-6 flex items-center gap-2.5 px-2">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--color-accent)] text-[var(--color-accent-ink)]"
        style={{ boxShadow: "0 3px 0 0 var(--tactile-depth)" }}
      >
        <BrandMark size={19} />
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight">AgentAuth</div>
        {/* An accent-colored tag, not another line of muted gray text -
            the wordmark already has a neutral subtitle's worth of visual
            weight without needing a second one. */}
        <div className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-[var(--color-accent)]">
          <span className="h-1 w-1 rounded-full bg-[var(--color-accent)]" />
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
  badge,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  active: boolean;
  // A count of things genuinely waiting on a decision, not a decorative
  // "new!" dot - only ever rendered when it's actually > 0, and gone the
  // moment that stops being true.
  badge?: number;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      // The active row is a solid tactile chip (filled accent + a hard
      // bottom-edge shadow), the same visual language as .btn-primary
      // everywhere else in the app - not the soft-tint-plus-thin-side-bar
      // treatment that shows up, pixel for pixel, in almost every
      // AI-scaffolded admin dashboard. Every row also gets the same
      // press-down feedback a real button gets on click, so the whole
      // sidebar reads as one deliberate, physical object instead of a
      // generic link list.
      className={clsx(
        "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-all duration-150 active:translate-y-px",
        active
          ? "bg-[var(--color-accent)] font-semibold text-[var(--color-accent-ink)]"
          : "font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]"
      )}
      style={active ? { boxShadow: "0 2px 0 0 var(--tactile-depth)" } : undefined}
    >
      <Icon
        size={17}
        strokeWidth={active ? 2.3 : 2}
        className={active ? "" : "text-[var(--color-text-muted)] group-hover:text-[var(--color-text)]"}
      />
      <span className="flex-1">{label}</span>
      {!!badge && (
        <span
          className={clsx(
            "flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-[10px] font-bold tabular-nums",
            active
              ? "bg-[var(--color-accent-ink)]/20 text-[var(--color-accent-ink)]"
              : "bg-[var(--color-warning-soft)] text-[var(--color-warning)]"
          )}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </Link>
  );
}

function NavSections({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  const { awaitingApproval } = useLiveSidebarStatus();

  return (
    <nav className="flex flex-1 flex-col overflow-y-auto scrollbar-thin">
      {groups.map((group, i) => (
        <div key={group.label} className={clsx("flex flex-col gap-0.5", i > 0 && "mt-5")}>
          <div className="mb-1.5 flex items-center gap-2 px-3">
            <span className="h-[3px] w-[3px] shrink-0 rounded-full bg-[var(--color-text-muted)]" />
            <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              {group.label}
            </span>
          </div>
          {group.items.map((item) => (
            <NavRow
              key={item.href}
              {...item}
              active={isActive(item.href)}
              badge={item.href === APPROVAL_BADGE_HREF ? awaitingApproval : undefined}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      ))}

      <div className="mt-5 border-t border-[var(--color-border)] pt-3">
        <NavRow {...SETTINGS_ITEM} active={isActive(SETTINGS_ITEM.href)} onNavigate={onNavigate} />
      </div>
    </nav>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-64 md:flex-col md:border-r md:border-[var(--color-border)] md:bg-[var(--color-surface)] md:px-5 md:py-6">
      <Brand />
      <NavSections />
      <Footer />
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
  const { awaitingApproval } = useLiveSidebarStatus();

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
        aria-label={
          awaitingApproval
            ? `Open navigation menu, ${awaitingApproval} transaction${awaitingApproval === 1 ? "" : "s"} awaiting approval`
            : "Open navigation menu"
        }
        aria-expanded={open}
        // rounded-2xl, not rounded-full: a plain circle is the generic
        // "Material FAB" shape every template reaches for by default. The
        // brand mark and every tactile button in this app are rounded
        // squares, so this should be too.
        className="fixed bottom-5 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--color-accent)] text-[var(--color-accent-ink)] transition-transform active:translate-y-px"
        style={{ boxShadow: "0 3px 0 0 var(--tactile-depth), 0 8px 20px rgba(0,0,0,0.18)" }}
      >
        <Menu size={20} />
        {!!awaitingApproval && (
          <span
            className="absolute -right-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full border-2 border-[var(--color-bg)] bg-[var(--color-warning)] px-1 text-[10px] font-bold tabular-nums text-[#231702]"
            aria-hidden="true"
          >
            {awaitingApproval > 99 ? "99+" : awaitingApproval}
          </span>
        )}
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
        <Footer />
      </aside>
    </div>
  );
}
