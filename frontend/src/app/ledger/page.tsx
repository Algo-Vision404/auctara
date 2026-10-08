"use client";

import { useEffect, useState } from "react";
import { TopBar } from "@/components/nav/TopBar";
import { OperationsConsoleGrid } from "@/components/ledger/OperationsConsoleGrid";
import { api, ApiError } from "@/lib/api";
import { Transaction, Agent } from "@/lib/types";

export default function LedgerPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      Promise.all([api.listTransactions(), api.listAgents()])
        .then(([t, a]) => {
          if (!mounted) return;
          setTransactions(t);
          setAgents(a);
        })
        .catch((e) => mounted && setError(e instanceof ApiError ? e.message : "Failed to load ledger"));
    };
    load();
    const i = setInterval(load, 5000);
    return () => {
      mounted = false;
      clearInterval(i);
    };
  }, []);

  return (
    <div className="flex flex-1 flex-col">
      <TopBar
        title="Commerce Ledger: Agent Operations Console"
        subtitle="Every real research → proposal → policy → approval → PayPal → audit pipeline, live from the backend."
      />
      <main className="flex-1 space-y-6 px-5 py-6 md:px-8">
        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}
        <OperationsConsoleGrid transactions={transactions} agents={agents} />
      </main>
    </div>
  );
}
