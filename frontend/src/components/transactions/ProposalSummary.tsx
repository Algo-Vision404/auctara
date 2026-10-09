import { useState } from "react";
import { Transaction } from "@/lib/types";
import { money, titleCase } from "@/lib/format";
import { ArrowUpRight, Store, Tag, FileText, PackageSearch, ImageOff } from "lucide-react";

export function ProposalSummary({ tx }: { tx: Transaction }) {
  const [imageFailed, setImageFailed] = useState(false);
  if (!tx.merchant) return null;
  return (
    <div className="card-surface space-y-4 p-6">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          Purchase Proposal
        </p>
        {tx.channel3_product_id && (
          <span className="flex items-center gap-1.5 rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-text-secondary)]">
            <PackageSearch size={12} /> Verified live listing
          </span>
        )}
      </div>
      <div className="flex gap-4">
        {tx.image_url && !imageFailed ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={tx.image_url}
            alt={tx.merchant}
            onError={() => setImageFailed(true)}
            className="h-20 w-20 flex-shrink-0 rounded-lg border border-[var(--color-border)] object-contain bg-[var(--color-surface-2)]"
          />
        ) : tx.image_url ? (
          <div className="flex h-20 w-20 flex-shrink-0 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] text-[var(--color-text-muted)]">
            <ImageOff size={20} />
          </div>
        ) : null}
        <div className="min-w-0 space-y-1">
          <h3 className="truncate font-sans text-lg font-semibold">{tx.merchant}</h3>
          <p className="font-mono-ui text-3xl font-semibold tracking-tight">
            {money(tx.amount, tx.currency || "USD")}
          </p>
        </div>
      </div>
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
