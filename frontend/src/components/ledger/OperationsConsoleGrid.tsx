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
  type StatusPanelDef,
} from "ag-grid-community";
import { AllEnterpriseModule } from "ag-grid-enterprise";
import { Transaction, Agent } from "@/lib/types";
import { money, titleCase, shortTime } from "@/lib/format";
import { Badge, decisionTone, stateTone } from "@/components/ui/Badge";
import { DecisionTimeline } from "@/components/transactions/DecisionTimeline";
import { buildTimelineStages } from "@/lib/timelineStages";
import { api } from "@/lib/api";
import {
  Download,
  Search,
  X,
  SlidersHorizontal,
  ExternalLink,
  ArrowUpRight,
  PackageSearch,
  Rows3,
  CheckCircle2,
  TriangleAlert,
  XCircle,
  Loader2,
} from "lucide-react";

// Row Grouping, the drag-to-group panel, Set Filters, and the Status Bar
// below are AG Grid Enterprise features. This project has no Enterprise
// license key, so they render with AG Grid's standard unlicensed watermark
// and a console warning - which AG Grid's own team has said is expected and
// fine for hackathon/evaluation use (not something to "fix" away). We use
// them anyway because they're the real feature, not a mock of it: an agent
// operations console genuinely benefits from grouping transactions by agent
// and seeing live aggregate totals, not just a flat row list.
ModuleRegistry.registerModules([AllCommunityModule, AllEnterpriseModule]);

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
  "price_check",
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
  const [imageFailed, setImageFailed] = useState(false);
  if (!p.data) return null;
  return (
    <div className="flex h-full items-center gap-2">
      {p.data.image_url && !imageFailed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={p.data.image_url}
          alt=""
          onError={() => setImageFailed(true)}
          className="h-6 w-6 rounded object-contain bg-[var(--color-surface-2)]"
        />
      ) : p.data.channel3_product_id ? (
        <PackageSearch size={14} className="text-[var(--color-text-muted)]" />
      ) : null}
      <span className="truncate">{p.data.merchant || "N/A"}</span>
      {p.data.source_url && (
        // The detail panel already links to the original listing, but
        // requiring two clicks (open panel, then click the link) to check
        // where a price actually came from is friction a reviewer skimming
        // dozens of rows won't take. stopPropagation keeps this from also
        // triggering the row's onRowClicked (which would pop the detail
        // panel open behind the new tab).
        <a
          href={p.data.source_url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          title="View original listing"
          className="ml-auto shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-accent)]"
        >
          <ExternalLink size={13} />
        </a>
      )}
    </div>
  );
}

function DecisionCell(p: ICellRendererParams<ConsoleRow>) {
  if (!p.data?.decision) return <span className="text-[var(--color-text-muted)]">N/A</span>;
  return <Badge tone={decisionTone(p.data.decision)}>{titleCase(p.data.decision)}</Badge>;
}

function StateCell(p: ICellRendererParams<ConsoleRow>) {
  if (!p.data) return null;
  return <Badge tone={stateTone(p.data.state)}>{titleCase(p.data.state)}</Badge>;
}

function PaypalCell(p: ICellRendererParams<ConsoleRow>) {
  if (!p.data?.paypal_status) return <span className="text-[var(--color-text-muted)]">N/A</span>;
  const tone = PAYPAL_TONE[p.data.paypal_status] || "muted";
  return <Badge tone={tone}>{titleCase(p.data.paypal_status)}</Badge>;
}

// Surfaces the policy engine's actual price-variance check (expected_amount,
// what the agent proposed, vs actual_amount, what PayPal/the research step
// confirmed at execution time) instead of only exposing it three clicks deep
// in the evidence-chain timeline. Real numbers straight from the backend -
// there is no separate "drift" field anywhere, this is computed client-side
// from the same two columns a viewer could otherwise compare by eye, just
// surfaced as a single glanceable signal across hundreds of rows.
function PriceCheckCell(p: ICellRendererParams<ConsoleRow>) {
  const tx = p.data;
  if (!tx || tx.expected_amount == null || tx.actual_amount == null) {
    return <span className="text-[var(--color-text-muted)]">N/A</span>;
  }
  const diff = tx.actual_amount - tx.expected_amount;
  const pct = tx.expected_amount !== 0 ? (diff / tx.expected_amount) * 100 : 0;
  const absPct = Math.abs(pct);

  if (absPct < 0.01) {
    return (
      <Badge tone="success" icon={<CheckCircle2 size={13} />}>
        Exact match
      </Badge>
    );
  }
  const tone = absPct <= 5 ? "warning" : "danger";
  const Icon = absPct <= 5 ? TriangleAlert : XCircle;
  const sign = diff > 0 ? "+" : "";
  return (
    <Badge tone={tone} icon={<Icon size={13} />}>
      {sign}
      {money(diff, tx.currency || "USD")} ({absPct.toFixed(1)}%)
    </Badge>
  );
}

// AG Grid's built in "No Rows To Show" overlay is generic, unstyled text
// that does not match the rest of the app's empty states (e.g. "No agents
// yet.", "No activity yet."). It also never explains the difference between
// "there is genuinely nothing here" and "your filters are hiding everything",
// which looks identical to a user and is a common source of a false "this is
// broken" impression.
//
// `loading` covers a third, separate case this overlay used to conflate with
// "genuinely empty": the very first render, before the ledger page's initial
// listTransactions() call has resolved. transactions starts as [], so
// without this, every single page load briefly - but really - showed "No
// transactions yet." even for an account with a long history, for however
// long that first fetch took.
function NoRowsOverlay({ filtered, loading }: { filtered: boolean; loading: boolean }) {
  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <Loader2 size={28} className="animate-spin text-[var(--color-text-muted)]" />
        <p className="text-sm font-medium text-[var(--color-text)]">Loading transactions…</p>
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
      <PackageSearch size={28} className="text-[var(--color-text-muted)]" />
      <p className="text-sm font-medium text-[var(--color-text)]">
        {filtered ? "No transactions match these filters." : "No transactions yet."}
      </p>
      <p className="max-w-xs text-xs text-[var(--color-text-muted)]">
        {filtered
          ? "Clear a filter or widen the amount range to see more."
          : "Give an agent a task and its proposals, approvals, and PayPal activity will appear here."}
      </p>
    </div>
  );
}

export function OperationsConsoleGrid({
  transactions,
  agents,
  loading = false,
}: {
  transactions: Transaction[];
  agents: Agent[];
  loading?: boolean;
}) {
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
  // Defaults to grouping by agent, since "what has each agent been doing"
  // is the first question this console answers - but it's just a starting
  // point: the AG Grid Enterprise row-group panel (always visible below)
  // lets the viewer drag any other groupable column header in instead, or
  // stack a second level on top, same as this dropdown's options.
  const [groupBy, setGroupBy] = useState<string>("agent_name");
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
        // Falls back to a label, never the raw internal agent_id string
        // (e.g. "agent_1d359c7e73bb") - that's a database key, not
        // something a viewer of this console should ever see standing in
        // for a name. The only time this lookup can miss is a brief window
        // right after a backend event names a transaction whose agent
        // isn't in the locally-loaded `agents` list yet.
        agent_name: t.agent_name || agentNameById.get(t.agent_id) || "Unknown agent",
      })),
    [transactions, agentNameById]
  );

  // If the detail panel is open for a transaction that then changes (a live
  // SSE-driven update flows a fresh object in via the `transactions` prop),
  // re-point `selected` at that fresh copy so the panel's header badges and
  // timeline refetch instead of silently going stale while the grid row
  // beneath it keeps moving.
  useEffect(() => {
    if (!selected) return;
    const fresh = rows.find((r) => r.id === selected.id);
    if (fresh && fresh !== selected) setSelected(fresh);
  }, [rows, selected]);

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
      agent_name: {
        headerName: "Agent",
        field: "agent_name",
        minWidth: 150,
        enableRowGroup: true,
        filter: "agSetColumnFilter",
        rowGroup: groupBy === "agent_name",
        hide: groupBy === "agent_name",
      },
      task_prompt: { headerName: "Task", field: "task_prompt", minWidth: 220, flex: 1 },
      merchant: { headerName: "Merchant", field: "merchant", minWidth: 180, cellRenderer: MerchantCell },
      category: {
        headerName: "Category",
        field: "category",
        minWidth: 130,
        valueFormatter: (p) => titleCase(p.value),
        enableRowGroup: true,
        filter: "agSetColumnFilter",
        rowGroup: groupBy === "category",
        hide: groupBy === "category",
      },
      amount: {
        headerName: "Amount",
        field: "amount",
        minWidth: 110,
        valueFormatter: (p) => money(p.value, p.data?.currency || "USD"),
        cellClass: "font-mono-ui",
        type: "numericColumn",
        enableValue: true,
        aggFunc: "sum",
      },
      price_check: {
        headerName: "Price Check",
        colId: "price_check",
        minWidth: 170,
        // Derived purely from two already-real backend fields (what the
        // agent proposed vs. what was actually verified at execution time) -
        // see PriceCheckCell. valueGetter (not `field`) so sorting/row-group
        // aggregation on this column operate on the actual dollar drift,
        // not the rendered badge text.
        valueGetter: (p) =>
          p.data?.expected_amount != null && p.data?.actual_amount != null
            ? p.data.actual_amount - p.data.expected_amount
            : null,
        cellRenderer: PriceCheckCell,
        enableCellChangeFlash: true,
      },
      decision: {
        headerName: "Decision",
        field: "decision",
        cellRenderer: DecisionCell,
        minWidth: 150,
        enableCellChangeFlash: true,
        enableRowGroup: true,
        filter: "agSetColumnFilter",
        rowGroup: groupBy === "decision",
        hide: groupBy === "decision",
        tooltipValueGetter: (p) => p.data?.decision_reason || undefined,
      },
      state: {
        headerName: "State",
        field: "state",
        cellRenderer: StateCell,
        minWidth: 140,
        enableCellChangeFlash: true,
        enableRowGroup: true,
        filter: "agSetColumnFilter",
        rowGroup: groupBy === "state",
        hide: groupBy === "state",
        // Only ever populated for FAILED/BLOCKED/etc rows, so a healthy
        // COMPLETED row simply shows no tooltip at all.
        tooltipValueGetter: (p) => p.data?.error || undefined,
      },
      paypal_status: {
        headerName: "Payment",
        field: "paypal_status",
        cellRenderer: PaypalCell,
        minWidth: 160,
        enableCellChangeFlash: true,
        enableRowGroup: true,
        filter: "agSetColumnFilter",
        rowGroup: groupBy === "paypal_status",
        hide: groupBy === "paypal_status",
      },
      authorized_amount: {
        headerName: "Authority",
        field: "authorized_amount",
        minWidth: 110,
        valueFormatter: (p) => (p.value ? money(p.value) : "N/A"),
        cellClass: "font-mono-ui",
        enableCellChangeFlash: true,
      },
      paypal_order_id: { headerName: "PayPal Order", field: "paypal_order_id", minWidth: 170, cellClass: "font-mono-ui" },
      paypal_capture_id: {
        headerName: "Capture ID",
        field: "paypal_capture_id",
        minWidth: 170,
        cellClass: "font-mono-ui",
        enableCellChangeFlash: true,
      },
      id: { headerName: "Transaction ID", field: "id", minWidth: 170, cellClass: "font-mono-ui" },
    };
    return ALL_COLUMNS.filter((c) => !hiddenColumns.has(c)).map((c) => defs[c]);
  }, [hiddenColumns, groupBy]);

  const defaultColDef = useMemo<ColDef>(
    () => ({ sortable: true, resizable: true, filter: true, floatingFilter: false }),
    []
  );

  // The auto-generated group column AG Grid Enterprise builds for whichever
  // field is currently grouped (the dropdown below, or a column dragged
  // into the row-group panel). Header name is intentionally generic ("Group")
  // rather than hardcoded to "Agent", since this same column is reused no
  // matter which field ends up grouped.
  const autoGroupColumnDef = useMemo<ColDef>(
    () => ({
      headerName: "Group",
      minWidth: 220,
      cellRendererParams: { suppressCount: false },
    }),
    []
  );

  const statusBar = useMemo<{ statusPanels: StatusPanelDef[] }>(
    () => ({
      statusPanels: [
        { statusPanel: "agTotalAndFilteredRowCountComponent", align: "left" },
        { statusPanel: "agAggregationComponent", align: "right" },
      ],
    }),
    []
  );

  function handleGroupByChange(value: string) {
    setGroupBy(value);
    if (value) {
      // A column that's hidden via the "Columns" menu has no colDef at all,
      // so it can't be grouped - force it visible when it becomes the
      // active group field.
      setHiddenColumns((prev) => {
        if (!prev.has(value)) return prev;
        const next = new Set(prev);
        next.delete(value);
        return next;
      });
    }
  }

  function exportCsv() {
    gridRef.current?.api.exportDataAsCsv({ fileName: "auctara-operations-console.csv" });
  }

  function toggleColumn(col: string) {
    setHiddenColumns((prev) => {
      const next = new Set(prev);
      if (next.has(col)) next.delete(col);
      else next.add(col);
      return next;
    });
  }

  const hasActiveFilters = Boolean(
    agentFilter || decisionFilter || stateFilter || minAmount || maxAmount || quickFilter.trim()
  );

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
            <div className="flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2.5 py-1.5">
              <Rows3 size={14} className="text-[var(--color-text-muted)]" />
              <select
                value={groupBy}
                onChange={(e) => handleGroupByChange(e.target.value)}
                className="bg-transparent text-sm outline-none"
                title="Group rows by"
              >
                <option value="">No grouping</option>
                <option value="agent_name">Group by agent</option>
                <option value="category">Group by category</option>
                <option value="decision">Group by decision</option>
                <option value="state">Group by state</option>
                <option value="paypal_status">Group by payment status</option>
              </select>
            </div>
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
              {["CREATED", "RESEARCHING", "NEEDS_INPUT", "PROPOSED", "POLICY_CHECK", "AWAITING_APPROVAL", "AUTHORIZED",
                "VERIFYING", "CAPTURED", "COMPLETED", "BLOCKED", "VOIDED", "FAILED", "CANCELLED"].map((s) => (
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
                  setQuickFilter("");
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

        <div style={{ height: 640, width: "100%" }}>
          {mounted && (
            <AgGridReact
              ref={gridRef}
              rowData={filteredRows}
              // Required for AG Grid's immutable-data diffing: with a stable
              // row id, passing a new `rowData` array (as the ledger page
              // does whenever a real backend event arrives over SSE) only
              // touches the rows that actually changed - existing rows keep
              // their selection/scroll state, and `enableCellChangeFlash`
              // above can highlight exactly which cells a live update
              // changed, instead of the grid looking like it silently
              // re-rendered from scratch every few seconds.
              getRowId={(p) => p.data.id}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              autoGroupColumnDef={autoGroupColumnDef}
              // Enterprise row grouping: the dropdown above sets one column's
              // `rowGroup: true`, but this panel also lets a viewer drag any
              // other groupable column header in directly, or stack a second
              // grouping level on top of the first, without touching code.
              rowGroupPanelShow="always"
              groupDefaultExpanded={1}
              // Enterprise range selection + the status bar below: drag
              // across a block of (e.g.) Amount cells to see a live
              // sum/avg/count computed at the bottom, on top of each group
              // row's own aggregated total.
              cellSelection
              // AG Grid's own clipboard support (cell range copy/paste)
              // always tries the real navigator.clipboard API first. In
              // this app's embedded preview iframe (sandbox="allow-scripts",
              // no clipboard-write grant), that call is blocked by the
              // browser's Permissions-Policy, which throws, which AG Grid
              // logs via console.error - and Next's dev overlay counts every
              // console.error as a blocking error, so clicking/copying cells
              // a handful of times inflates the "N errors" badge with
              // nothing actually broken. This flag tells AG Grid to assume
              // the Clipboard API is unavailable and go straight to its
              // execCommand-based fallback instead of ever calling (and
              // failing) navigator.clipboard - copy/paste still works
              // everywhere, including this preview, this just stops it from
              // probing an API it already can't use.
              suppressClipboardApi
              statusBar={statusBar}
              // Simple, reliable native tooltips for the decision_reason /
              // error tooltipValueGetters above - no custom tooltip
              // component needed for plain text.
              enableBrowserTooltips
              theme={resolvedTheme === "dark" ? darkTheme : lightTheme}
              pagination
              paginationPageSize={20}
              paginationPageSizeSelector={[10, 20, 50, 100]}
              quickFilterText={quickFilter}
              animateRows
              onRowClicked={(e) => e.data && setSelected(e.data)}
              rowStyle={{ cursor: "pointer" }}
              noRowsOverlayComponent={NoRowsOverlay}
              noRowsOverlayComponentParams={{ filtered: hasActiveFilters, loading }}
            />
          )}
        </div>
        <p className="px-1 text-xs text-[var(--color-text-muted)]">
          Click any row to see its evidence chain. Every value above comes straight from the real backend.
          Nothing here is sample data.
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
