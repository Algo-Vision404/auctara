"use client";

import { useEffect, useState } from "react";
import { CircleCheck, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Badge } from "@/components/ui/Badge";

export function TopBar({ title, subtitle }: { title: string; subtitle?: string }) {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    const poll = () =>
      api
        .health()
        .then((h) => mounted && (setHealth(h), setError(false)))
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
        {error ? (
          <Badge tone="danger" icon={<TriangleAlert size={13} />}>
            Backend unreachable
          </Badge>
        ) : health ? (
          <div className="hidden items-center gap-2 sm:flex">
            <Badge tone={health.paypal_configured ? "success" : "warning"} icon={<CircleCheck size={13} />}>
              PayPal {health.paypal_environment}
            </Badge>
            <Badge tone={health.openrouter_configured ? "success" : "warning"} icon={<CircleCheck size={13} />}>
              {health.model}
            </Badge>
          </div>
        ) : null}
        <ThemeToggle />
      </div>
    </header>
  );
}
