"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { TopBar } from "@/components/nav/TopBar";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { api, ApiError } from "@/lib/api";
import { AuditRecord } from "@/lib/types";
import { eventMeta } from "@/lib/eventMeta";
import { fullDateTime } from "@/lib/format";
import { ScrollText, ShieldCheck, ShieldX, Loader2 } from "lucide-react";

export default function AuditPage() {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{ valid: boolean; records_verified?: number; broken_at_seq?: number } | null>(null);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      api
        .listAudit({ limit: 300 })
        .then((data) => {
          if (!mounted) return;
          setRecords(data);
          setError(null);
        })
        .catch((e) => mounted && setError(e instanceof ApiError ? e.message : "Failed to load audit trail"))
        .finally(() => mounted && setLoading(false));
    };
    load();
    const i = setInterval(load, 6000);
    return () => {
      mounted = false;
      clearInterval(i);
    };
  }, []);

  async function verify() {
    setVerifying(true);
    setVerifyResult(null);
    setError(null);
    try {
      const r = await api.verifyAudit();
      setVerifyResult(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Verification failed");
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <TopBar title="Audit" subtitle="Immutable, HMAC-chained evidence, separate from operational activity." />
      <main className="flex-1 space-y-6 px-5 py-6 md:px-8">
        <div className="card-surface flex flex-col items-start justify-between gap-4 p-5 sm:flex-row sm:items-center">
          <div>
            <h3 className="flex items-center gap-2 font-semibold">
              <ShieldCheck size={18} className="text-[var(--color-accent)]" /> Integrity Chain
            </h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
              Every record is HMAC-SHA256 chained to the previous one. Any tampering breaks the chain.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {verifyResult && (
              <Badge tone={verifyResult.valid ? "success" : "danger"} icon={verifyResult.valid ? <ShieldCheck size={13} /> : <ShieldX size={13} />}>
                {verifyResult.valid ? `${verifyResult.records_verified} records verified` : `Broken at #${verifyResult.broken_at_seq}`}
              </Badge>
            )}
            <Button variant="primary" onClick={verify} loading={verifying}>
              Verify Chain
            </Button>
          </div>
        </div>

        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <div className="card-surface overflow-hidden">
          <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-5 py-3.5">
            <ScrollText size={16} className="text-[var(--color-text-muted)]" />
            <h3 className="font-semibold">Audit Records</h3>
          </div>
          <div className="scrollbar-thin max-h-[640px] overflow-y-auto">
            {loading && (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-[var(--color-text-muted)]">
                <Loader2 size={14} className="animate-spin" /> Loading…
              </div>
            )}
            {!loading && records.length === 0 && (
              <div className="py-10 text-center text-sm text-[var(--color-text-muted)]">
                No audit records yet. Run a task to generate real, chained evidence.
              </div>
            )}
            {records.map((r) => {
              const meta = eventMeta(r.event_type);
              const Icon = meta.icon;
              return (
                <div key={r.id} className="flex items-start gap-3 border-b border-[var(--color-border)] px-5 py-3.5 last:border-0">
                  <span
                    className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center"
                    style={{
                      color: `var(--color-${meta.tone}, var(--color-text-secondary))`,
                    }}
                  >
                    <Icon size={16} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold">{r.event_type.replace(/_/g, " ")}</p>
                      <span className="font-mono-ui text-[11px] text-[var(--color-text-muted)]">#{r.seq}</span>
                      <span className="font-mono-ui text-[11px] text-[var(--color-text-muted)]">{fullDateTime(r.created_at)}</span>
                    </div>
                    {r.transaction_id && (
                      <Link href={`/transactions/${r.transaction_id}`} className="text-xs text-[var(--color-accent)]">
                        {r.transaction_id}
                      </Link>
                    )}
                    <p className="mt-1 break-all font-mono-ui text-[11px] text-[var(--color-text-muted)]">
                      hash: {r.hash.slice(0, 24)}…
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}
