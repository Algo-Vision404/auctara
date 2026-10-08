"use client";

import { useEffect, useState } from "react";
import { TopBar } from "@/components/nav/TopBar";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Badge } from "@/components/ui/Badge";
import { api } from "@/lib/api";
import { CircleCheck, TriangleAlert, ShieldCheck, Settings2 } from "lucide-react";

export default function SettingsPage() {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setError("Could not reach the AgentAuth backend."));
  }, []);

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title="Settings" subtitle="Appearance and backend configuration status." />
      <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-5 py-6 md:px-8">
        <div className="card-surface flex items-center justify-between p-6">
          <div>
            <h3 className="flex items-center gap-2 font-semibold">
              <Settings2 size={18} className="text-[var(--color-accent)]" /> Appearance
            </h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">System, light, or dark.</p>
          </div>
          <ThemeToggle />
        </div>

        <div className="card-surface space-y-4 p-6">
          <h3 className="flex items-center gap-2 font-semibold">
            <ShieldCheck size={18} className="text-[var(--color-accent)]" /> Backend Configuration
          </h3>
          {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
          {health && (
            <div className="space-y-3 text-sm">
              <Row label="API status" ok={health.status === "ok"} value={health.status} />
              <Row label="PayPal Sandbox" ok={health.paypal_configured} value={health.paypal_configured ? `configured (${health.paypal_environment})` : "not configured"} />
              <Row label="OpenRouter / AI model" ok={health.openrouter_configured} value={health.openrouter_configured ? health.model : "not configured"} />
            </div>
          )}
          <p className="text-xs text-[var(--color-text-muted)]">
            Secrets are never sent to the browser. Configure credentials in the backend&apos;s <code className="font-mono-ui">.env</code> file.
            See <code className="font-mono-ui">.env.example</code> in the project root.
          </p>
        </div>
      </main>
    </div>
  );
}

function Row({ label, ok, value }: { label: string; ok: boolean; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--color-border)] py-2 last:border-0">
      <span className="text-[var(--color-text-secondary)]">{label}</span>
      <Badge tone={ok ? "success" : "warning"} icon={ok ? <CircleCheck size={13} /> : <TriangleAlert size={13} />}>
        {value}
      </Badge>
    </div>
  );
}
