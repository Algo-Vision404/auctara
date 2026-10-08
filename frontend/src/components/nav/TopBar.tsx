"use client";

import { useEffect, useState } from "react";
import { TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Badge } from "@/components/ui/Badge";

export function TopBar({
  title,
  subtitle,
  showThemeToggle = true,
}: {
  title: string;
  subtitle?: string;
  showThemeToggle?: boolean;
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
        <h1 className="font-sans text-xl font-semibold tracking-tight text-[var(--color-text)]">{title}</h1>
        {subtitle && <p className="text-sm text-[var(--color-text-secondary)]">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-3">
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
