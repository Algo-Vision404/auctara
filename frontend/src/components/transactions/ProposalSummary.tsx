import { Transaction } from "@/lib/types";
import { money, titleCase } from "@/lib/format";
import { ArrowUpRight, Store, Tag, FileText } from "lucide-react";

export function ProposalSummary({ tx }: { tx: Transaction }) {
  if (!tx.merchant) return null;
  return (
    <div className="card-surface space-y-4 p-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
        Purchase Proposal
      </p>
      <h3 className="font-sans text-lg font-semibold">{tx.merchant}</h3>
      <p className="font-mono-ui text-3xl font-semibold tracking-tight">
        {money(tx.amount, tx.currency || "USD")}
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <InfoRow icon={Store} label="Merchant" value={tx.merchant} />
        <InfoRow icon={Tag} label="Category" value={titleCase(tx.category)} />
      </div>
      {tx.reason && <InfoRow icon={FileText} label="Reason" value={tx.reason} />}
      {tx.source_url && (
        <a
          href={tx.source_url}
          target="_blank"
          rel="noreferrer"
          className="flex w-fit items-center gap-1 text-sm font-medium text-[var(--color-accent)]"
        >
          View listing <ArrowUpRight size={14} />
        </a>
      )}
    </div>
  );
}

function InfoRow({ icon: Icon, label, value }: { icon: typeof Store; label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <Icon size={15} className="mt-0.5 text-[var(--color-text-muted)]" />
      <div>
        <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{label}</p>
        <p className="text-sm">{value}</p>
      </div>
    </div>
  );
}
