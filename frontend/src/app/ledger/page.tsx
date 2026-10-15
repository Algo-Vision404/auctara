"use client";

import { useCallback, useEffect, useState } from "react";
import { TopBar } from "@/components/nav/TopBar";
import { OperationsConsoleGrid } from "@/components/ledger/OperationsConsoleGrid";
import { api, ApiError, subscribeToEvents, StreamEvent } from "@/lib/api";
import { Transaction, Agent } from "@/lib/types";
import { Wifi, WifiOff } from "lucide-react";

// The ledger used to be a dumb 5s poll of the whole transaction list. That
// works but it's wasteful (refetches hundreds of unchanged rows every tick)
// and it's not actually "live" - a row can sit stale for up to 5s after a
// real backend event. Instead we keep the full list only for the initial
// load and as a slow self-healing fallback (in case the SSE connection is
// ever down for a while), and otherwise react to the same real-time event
// bus that already powers the Live Activity feed: whenever an event names a
// transaction, we refetch just that one transaction and merge it in. AG
// Grid's immutable-data mode (via getRowId, see OperationsConsoleGrid) then
// updates/animates/flashes exactly that row without touching the rest of
// the grid's state (selection, scroll position, sort).
const FALLBACK_POLL_MS = 45_000;

export default function LedgerPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadAll = useCallback(() => {
    Promise.all([api.listTransactions(), api.listAgents()])
      .then(([t, a]) => {
        setTransactions(t);
        setAgents(a);
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load ledger"))
      .finally(() => setLoading(false));
  }, []);

  const mergeTransaction = useCallback((updated: Transaction) => {
    setTransactions((prev) => {
      const idx = prev.findIndex((t) => t.id === updated.id);
      if (idx === -1) return [updated, ...prev];
      const next = prev.slice();
      next[idx] = updated;
      return next;
    });
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    const unsub = subscribeToEvents(
      "/activity/stream",
      (evt: StreamEvent) => {
        if (evt.transaction_id) {
          api
            .getTransaction(evt.transaction_id)
            .then(mergeTransaction)
            .catch(() => {
              /* transient fetch failure: the fallback poll below will heal it */
            });
        }
        if (evt.event === "AGENT_DELETED" || evt.event === "AGENT_RETIRED") {
          api.listAgents().then(setAgents).catch(() => {});
        }
      },
      setConnected
    );
    return unsub;
  }, [mergeTransaction]);

  // Slow self-healing poll: catches anything a dropped SSE connection or a
  // missed event might have missed, without competing with the real-time
  // path for normal operation.
  useEffect(() => {
    const i = setInterval(loadAll, FALLBACK_POLL_MS);
    return () => clearInterval(i);
  }, [loadAll]);

  return (
    <div className="flex flex-1 flex-col">
      <TopBar
        title="Commerce Ledger: Agent Operations Console"
        subtitle="Every real research → proposal → policy → approval → PayPal → audit pipeline, live from the backend."
        actions={
          <span
            className={`flex items-center gap-1.5 text-xs font-medium ${
              connected ? "text-[var(--color-success)]" : "text-[var(--color-text-muted)]"
            }`}
          >
            {connected ? <Wifi size={13} /> : <WifiOff size={13} />}
            {connected ? "Live" : "Connecting…"}
          </span>
        }
      />
      <main className="flex-1 space-y-6 px-5 py-6 md:px-8">
        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}
        <OperationsConsoleGrid transactions={transactions} agents={agents} loading={loading} />
      </main>
    </div>
  );
}
