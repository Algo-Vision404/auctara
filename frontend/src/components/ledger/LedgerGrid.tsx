"use client";

import { useMemo, useRef, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { AgGridReact } from "ag-grid-react";
import {
  ModuleRegistry,
  AllCommunityModule,
  themeQuartz,
  type ColDef,
  type ICellRendererParams,
} from "ag-grid-community";
import { Transaction, Agent } from "@/lib/types";
import { money, titleCase, fullDateTime } from "@/lib/format";
import { Badge, decisionTone, stateTone } from "@/components/ui/Badge";
import { Download, Search } from "lucide-react";

ModuleRegistry.registerModules([AllCommunityModule]);

const lightTheme = themeQuartz.withParams({
  backgroundColor: "#FFFFFF",
  foregroundColor: "#17211B",
  borderColor: "#DDE5DF",
  headerBackgroundColor: "#EEF2EE",
  headerTextColor: "#647067",
  oddRowBackgroundColor: "#FBFCFB",
  rowHoverColor: "#DDF5EF",
  accentColor: "#0F766E",
  fontFamily: "var(--font-sora)",
  headerFontWeight: 600,
  wrapperBorderRadius: 16,
});

const darkTheme = themeQuartz.withParams({
  backgroundColor: "#151A17",
  foregroundColor: "#F4F7F4",
  borderColor: "rgba(255,255,255,0.08)",
  headerBackgroundColor: "#1C231F",
  headerTextColor: "#A6B0A9",
  oddRowBackgroundColor: "#171D1A",
  rowHoverColor: "rgba(45,212,191,0.12)",
  accentColor: "#2DD4BF",
  fontFamily: "var(--font-sora)",
  headerFontWeight: 600,
  wrapperBorderRadius: 16,
});

function DecisionCell(p: ICellRendererParams<Transaction>) {
  if (!p.data?.decision) return <span className="text-[var(--color-text-muted)]">—</span>;
  return <Badge tone={decisionTone(p.data.decision)}>{titleCase(p.data.decision)}</Badge>;
}

function StateCell(p: ICellRendererParams<Transaction>) {
  if (!p.data) return null;
  return <Badge tone={stateTone(p.data.state)}>{titleCase(p.data.state)}</Badge>;
}

export function LedgerGrid({ transactions, agents }: { transactions: Transaction[]; agents: Agent[] }) {
  const { resolvedTheme } = useTheme();
  const router = useRouter();
  const gridRef = useRef<AgGridReact>(null);
  const [quickFilter, setQuickFilter] = useState("");
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const agentNameById = useMemo(() => {
    const m = new Map<string, string>();
    agents.forEach((a) => m.set(a.id, a.name));
    return m;
  }, [agents]);

  const rows = useMemo(
    () =>
      transactions.map((t) => ({
        ...t,
        agent_name: agentNameById.get(t.agent_id) || t.agent_id,
      })),
    [transactions, agentNameById]
  );

  const columnDefs = useMemo<ColDef[]>(
    () => [
      {
        headerName: "Timestamp",
        field: "created_at",
        valueFormatter: (p) => fullDateTime(p.value),
        sort: "desc",
        minWidth: 190,
        cellClass: "font-mono-ui",
      },
      { headerName: "Agent", field: "agent_name", minWidth: 150 },
      { headerName: "Merchant", field: "merchant", minWidth: 170, filter: true },
      {
        headerName: "Category",
        field: "category",
        minWidth: 160,
        valueFormatter: (p) => titleCase(p.value),
      },
      {
        headerName: "Amount",
        field: "amount",
        minWidth: 120,
        valueFormatter: (p) => money(p.value, p.data?.currency || "USD"),
        cellClass: "font-mono-ui",
        type: "numericColumn",
      },
      { headerName: "Policy Decision", field: "decision", cellRenderer: DecisionCell, minWidth: 160 },
      { headerName: "PayPal Status", field: "state", cellRenderer: StateCell, minWidth: 150 },
      {
        headerName: "Authority",
        field: "authorized_amount",
        minWidth: 120,
        valueFormatter: (p) => (p.value ? money(p.value) : "—"),
        cellClass: "font-mono-ui",
      },
      {
        headerName: "Transaction ID",
        field: "id",
        minWidth: 180,
        cellClass: "font-mono-ui",
      },
    ],
    []
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      sortable: true,
      resizable: true,
      filter: true,
      floatingFilter: false,
    }),
    []
  );

  function exportCsv() {
    gridRef.current?.api.exportDataAsCsv({ fileName: "agentauth-commerce-ledger.csv" });
  }

  return (
    <div className="card-surface flex flex-col gap-3 p-4">
      <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            value={quickFilter}
            onChange={(e) => setQuickFilter(e.target.value)}
            placeholder="Search ledger…"
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] py-2 pl-9 pr-3 text-sm outline-none focus:border-[var(--color-accent)]"
          />
        </div>
        <button
          onClick={exportCsv}
          className="btn-block btn-secondary flex items-center gap-2 self-start sm:self-auto"
        >
          <Download size={15} /> Export CSV
        </button>
      </div>
      <div style={{ height: 560, width: "100%" }}>
        {mounted && (
          <AgGridReact
            ref={gridRef}
            rowData={rows}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            theme={resolvedTheme === "dark" ? darkTheme : lightTheme}
            pagination
            paginationPageSize={20}
            paginationPageSizeSelector={[10, 20, 50, 100]}
            quickFilterText={quickFilter}
            animateRows
            onRowClicked={(e) => e.data && router.push(`/transactions/${e.data.id}`)}
            rowStyle={{ cursor: "pointer" }}
          />
        )}
      </div>
      <p className="px-1 text-xs text-[var(--color-text-muted)]">
        Click any row to open its full transaction timeline and audit evidence.
      </p>
    </div>
  );
}
