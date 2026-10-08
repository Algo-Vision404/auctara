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
import { money, titleCase, shortTime } from "@/lib/format";
import { Badge, decisionTone, stateTone } from "@/components/ui/Badge";
import { DecisionTimeline } from "@/components/transactions/DecisionTimeline";
import { buildTimelineStages } from "@/lib/timelineStages";
import { api, ApiError } from "@/lib/api";
import {
  Download,
  Search,
  X,
  SlidersHorizontal,
  ExternalLink,
  ArrowUpRight,
  PackageSearch,
} from "lucide-react";

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

const PAYPAL_TONE: Record<string, "success" | "warning" | "danger" | "info" | "muted"> = {
  COMPLETED: "success",
  PAYER_ACTION_REQUIRED: "warning",
  FAILED: "danger",
  CREATED: "info",
  APPROVED: "info",
};

type ConsoleRow = Transaction & { agent_name: string };

const ALL_COLUMNS = [
  "created_at",
  "agent_name",
  "task_prompt",
  "merchant",
  "category",
  "amount",
  "decision",
  "state",
  "paypal_status",
  "authorized_amount",
  "paypal_order_id",
  "paypal_capture_id",
  "id",
] as const;

const DEFAULT_HIDDEN = new Set(["task_prompt", "paypal_order_id", "paypal_capture_id", "id"]);

function MerchantCell(p: ICellRendererParams<ConsoleRow>) {
  if (!p.data) return null;
  return (
    <div className="flex h-full items-center gap-2">
      {p.data.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={p.data.image_url} alt="" className="h-6 w-6 rounded object-contain bg-[var(--color-surface-2)]" />
      ) : p.data.channel3_product_id ? (
        <PackageSearch size={14} className="text-[var(--color-text-muted)]" />
      ) : null}
      <span className="truncate">{p.data.merchant || "—"}</span>
    </div>
  );
}

function DecisionCell(p: ICellRendererParams<ConsoleRow>) {
  if (!p.data?.decision) return <span className="text-[var(--color-text-muted)]">—</span>;
  return <Badge tone={decisionTone(p.data.decision)}>{titleCase(p.data.decision)}</Badge>;
}

function StateCell(p: ICellRendererParams<ConsoleRow>) {
  if (!p.data) return null;
  return <Badge tone={stateTone(p.data.state)}>{titleCase(p.data.state)}</Badge>;
}

function PaypalCell(p: ICellRendererParams<ConsoleRow>) {
  if (!p.data?.paypal_status) return <span className="text-[var(--color-text-muted)]">—</span>;
  const tone = PAYPAL_TONE[p.data.paypal_status] || "muted";
  return <Badge tone={tone}>{titleCase(p.data.paypal_status)}</Badge>;
}

export function OperationsConsoleGrid({ transactions, agents }: { transactions: Transaction[]; agents: Agent[] }) {
  const { resolvedTheme } = useTheme();
  const router = useRouter();
  const gridRef = useRef<AgGridReact>(null);
  const [quickFilter, setQuickFilter] = useState("");
  const [mounted, setMounted] = useState(false);
  const [agentFilter, setAgentFilter] = useState("");
  const [decisionFilter, setDecisionFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [columnMenuOpen, setColumnMenuOpen] = useState(false);
  const [hiddenColumns, setHiddenColumns] = useState<Set<string>>(DEFAULT_HIDDEN);
  const [selected, setSelected] = useState<Transaction | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<Transaction | null>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!selected) {
      setSelectedDetail(null);
      return;
    }
    let cancelled = false;
    api
      .getTransaction(selected.id)
      .then((tx) => !cancelled && setSelectedDetail(tx))
      .catch(() => !cancelled && setSelectedDetail(selected));
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const agentNameById = useMemo(() => {
    const m = new Map<string, string>();
    agents.forEach((a) => m.set(a.id, a.name));
    return m;
  }, [agents]);

  const rows = useMemo<ConsoleRow[]>(
    () =>
      transactions.map((t) => ({
        ...t,
        agent_name: t.agent_name || agentNameById.get(t.agent_id) || t.agent_id,
      })),
    [transactions, agentNameById]
  );

  const filteredRows = useMemo(() => {
    return rows.filter((r) => {
      if (agentFilter && r.agent_id !== agentFilter) return false;
      if (decisionFilter && r.decision !== decisionFilter) return false;
      if (stateFilter && r.state !== stateFilter) return false;
      if (minAmount && (r.amount || 0) < parseFloat(minAmount)) return false;
      if (maxAmount && (r.amount || 0) > parseFloat(maxAmount)) return false;
      return true;
    });
  }, [rows, agentFilter, decisionFilter, stateFilter, minAmount, maxAmount]);

  const columnDefs = useMemo<ColDef[]>(() => {
    const defs: Record<string, ColDef> = {
      created_at: {
        headerName: "Timestamp",
        field: "created_at",
        valueFormatter: (p) => shortTime(p.value),
        sort: "desc",
        minWidth: 170,
        cellClass: "font-mono-ui",
      },
      agent_name: { headerName: "Agent", field: "agent_name", minWidth: 150 },
      task_prompt: { headerName: "Task", field: "task_prompt", minWidth: 220, flex: 1 },
      merchant: { headerName: "Merchant", field: "merchant", minWidth: 180, cellRenderer: MerchantCell },
      category: { headerName: "Category", field: "category", minWidth: 130, valueFormatter: (p) => titleCase(p.value) },
      amount: {
        headerName: "Amount",
        field: "amount",
        minWidth: 110,
        valueFormatter: (p) => money(p.value, p.data?.currency || "USD"),
        cellClass: "font-mono-ui",
        type: "numericColumn",
      },
      decision: { headerName: "Decision", field: "decision", cellRenderer: DecisionCell, minWidth: 150 },
      state: { headerName: "State", field: "state", cellRenderer: StateCell, minWidth: 140 },
      paypal_status: { headerName: "Payment", field: "paypal_status", cellRenderer: PaypalCell, minWidth: 160 },
      authorized_amount: {
        headerName: "Authority",
        field: "authorized_amount",
        minWidth: 110,
        valueFormatter: (p) => (p.value ? money(p.value) : "—"),
        cellClass: "font-mono-ui",
      },
      paypal_order_id: { headerName: "PayPal Order", field: "paypal_order_id", minWidth: 170, cellClass: "font-mono-ui" },
      paypal_capture_id: { headerName: "Capture ID", field: "paypal_capture_id", minWidth: 170, cellClass: "font-mono-ui" },
      id: { headerName: "Transaction ID", field: "id", minWidth: 170, cellClass: "font-mono-ui" },
    };
    return ALL_COLUMNS.filter((c) => !hiddenColumns.has(c)).map((c) => defs[c]);
  }, [hiddenColumns]);

  const defaultColDef = useMemo<ColDef>(
    () => ({ sortable: true, resizable: true, filter: true, floatingFilter: false }),
    []
  );

  function exportCsv() {
    gridRef.current?.api.exportDataAsCsv({ fileName: "agentauth-operations-console.csv" });
  }

  function toggleColumn(col: string) {
    setHiddenColumns((prev) => {
      const next = new Set(prev);
      if (next.has(col)) next.delete(col);
      else next.add(col);
      return next;
    });
  }

  const hasActiveFilters = agentFilter || decisionFilter || stateFilter || minAmount || maxAmount;

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="card-surface flex min-w-0 flex-1 flex-col gap-3 p-4">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full sm:max-w-xs">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
              <input
                value={quickFilter}
                onChange={(e) => setQuickFilter(e.target.value)}
                placeholder="Search operations…"
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] py-2 pl-9 pr-3 text-sm outline-none focus:border-[var(--color-accent)]"
              />
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <button
                  onClick={() => setColumnMenuOpen((v) => !v)}
                  className="btn-block btn-secondary flex items-center gap-2"
                >
                  <SlidersHorizontal size={15} /> Columns
                </button>
                {columnMenuOpen && (
                  <div className="absolute right-0 z-20 mt-2 w-56 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-2 shadow-lg">
                    {ALL_COLUMNS.map((c) => (
                      <label
                        key={c}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-[var(--color-surface-2)]"
                      >
                        <input
                          type="checkbox"
                          checked={!hiddenColumns.has(c)}
                          onChange={() => toggleColumn(c)}
                        />
                        {titleCase(c)}
                      </label>
                    ))}
                  </div>
                )}
              </div>
              <button onClick={exportCsv} className="btn-block btn-secondary flex items-center gap-2">
                <Download size={15} /> Export CSV
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-1.5 text-sm outline-none focus:border-[var(--color-accent)]"
            >
              <option value="">All agents</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <select
              value={decisionFilter}
              onChange={(e) => setDecisionFilter(e.target.value)}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-1.5 text-sm outline-none focus:border-[var(--color-accent)]"
            >
              <option value="">All decisions</option>
              <option value="ALLOW">Allow</option>
              <option value="APPROVAL_REQUIRED">Approval Required</option>
              <option value="BLOCK">Block</option>
            </select>
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-1.5 text-sm outline-none focus:border-[var(--color-accent)]"
            >
              <option value="">All states</option>
              {["CREATED", "RESEARCHING", "PROPOSED", "POLICY_CHECK", "AWAITING_APPROVAL", "AUTHORIZED",
                "VERIFYING", "CAPTURED", "COMPLETED", "BLOCKED", "VOIDED", "FAILED"].map((s) => (
                <option key={s} value={s}>
                  {titleCase(s)}
                </option>
              ))}
            </select>
            <input
              value={minAmount}
              onChange={(e) => setMinAmount(e.target.value)}
              type="number"
              placeholder="Min $"
              className="w-24 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-1.5 text-sm outline-none focus:border-[var(--color-accent)]"
            />
            <input
              value={maxAmount}
              onChange={(e) => setMaxAmount(e.target.value)}
              type="number"
              placeholder="Max $"
              className="w-24 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-1.5 text-sm outline-none focus:border-[var(--color-accent)]"
            />
            {hasActiveFilters && (
              <button
                onClick={() => {
                  setAgentFilter("");
                  setDecisionFilter("");
                  setStateFilter("");
                  setMinAmount("");
                  setMaxAmount("");
                }}
                className="flex items-center gap-1 text-xs font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              >
                <X size={13} /> Clear filters
              </button>
            )}
            <span className="ml-auto text-xs text-[var(--color-text-muted)]">
              {filteredRows.length} of {rows.length} transactions
            </span>
          </div>
        </div>

        <div style={{ height: 560, width: "100%" }}>
          {mounted && (
            <AgGridReact
              ref={gridRef}
              rowData={filteredRows}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              theme={resolvedTheme === "dark" ? darkTheme : lightTheme}
              pagination
              paginationPageSize={20}
              paginationPageSizeSelector={[10, 20, 50, 100]}
              quickFilterText={quickFilter}
              animateRows
              onRowClicked={(e) => e.data && setSelected(e.data)}
              rowStyle={{ cursor: "pointer" }}
            />
          )}
        </div>
        <p className="px-1 text-xs text-[var(--color-text-muted)]">
          Click any row to see its evidence chain. Every value above comes straight from the real backend —
          nothing here is sample data.
        </p>
      </div>

      {selected && (
        <div className="card-surface flex w-full flex-col gap-4 p-5 lg:w-[380px] lg:flex-shrink-0">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
                Evidence Chain
              </p>
              <h3 className="truncate text-base font-semibold">{selected.merchant || "Transaction"}</h3>
              <p className="font-mono-ui text-xs text-[var(--color-text-muted)]">{selected.id}</p>
            </div>
            <button
              onClick={() => setSelected(null)}
              className="rounded-lg p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)]"
            >
              <X size={16} />
            </button>
          </div>

          <div className="flex items-center gap-2">
            <Badge tone={stateTone(selected.state)}>{titleCase(selected.state)}</Badge>
            {selected.decision && <Badge tone={decisionTone(selected.decision)}>{titleCase(selected.decision)}</Badge>}
          </div>

          {selectedDetail ? (
            <DecisionTimeline stages={buildTimelineStages(selectedDetail)} />
          ) : (
            <p className="text-sm text-[var(--color-text-muted)]">Loading timeline…</p>
          )}

          <button
            onClick={() => router.push(`/transactions/${selected.id}`)}
            className="btn-block btn-primary flex items-center justify-center gap-2"
          >
            Open full timeline <ArrowUpRight size={15} />
          </button>
          {selected.source_url && (
            <a
              href={selected.source_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-center gap-1.5 text-sm font-medium text-[var(--color-accent)]"
            >
              View original listing <ExternalLink size={14} />
            </a>
          )}
        </div>
      )}
    </div>
  );
}
