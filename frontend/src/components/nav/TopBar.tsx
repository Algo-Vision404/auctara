"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Badge } from "@/components/ui/Badge";

export function TopBar({
  title,
  subtitle,
  showThemeToggle = true,
  backHref,
  backLabel = "Back",
  actions,
}: {
  title: string;
  subtitle?: string;
  showThemeToggle?: boolean;
  // When set, renders a back link above the title pointing at this page -
  // the page's natural "parent" (e.g. an agent's chat page always goes back
  // to that same agent), not browser history, so it behaves the same
  // whether the page was reached by clicking through or opened directly
  // from a link/bookmark.
  backHref?: string;
  backLabel?: string;
  // Page-specific status/controls (e.g. the ledger's live-connection
  // indicator) rendered alongside the theme toggle, so pages don't need
  // their own separate header row for a single badge.
  actions?: ReactNode;
}) {
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    const poll = () =>
      api
        .health()
        .then(() => mounted && setError(false))
        .catch(() => mounted && setError(true));
    poll();
    const id = setInterval(poll, 20000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  return (
    <header className="sticky top-0 z-30 flex items-center justify-between gap-4 border-b border-[var(--color-border)] bg-[var(--color-bg)]/90 px-5 py-4 backdrop-blur md:px-8">
      <div>
        {backHref && (
          <Link
            href={backHref}
            className="mb-1 flex w-fit items-center gap-1 text-xs font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          >
            <ArrowLeft size={13} /> {backLabel}
          </Link>
        )}
        <h1 className="font-sans text-xl font-semibold tracking-tight text-[var(--color-text)]">{title}</h1>
        {subtitle && <p className="text-sm text-[var(--color-text-secondary)]">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-3">
        {actions}
        {error && (
          <Badge tone="danger" icon={<TriangleAlert size={13} />}>
            Backend unreachable
          </Badge>
        )}
        {showThemeToggle && <ThemeToggle />}
      </div>
    </header>
  );
}

