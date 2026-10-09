import { Transaction } from "@/lib/types";
import { money } from "@/lib/format";
import { PackageSearch, CheckCircle2 } from "lucide-react";

// Channel3's real-time catalog search (channel3.py / CHANNEL3_SEARCH_COMPLETED)
// already returns a rich, structured list of candidate products - title,
// brand, live price, retailer, image, availability - straight from its
// 100M+ product index. Until now that list only ever reached the user as a
// one-line activity message ("Found 5 real product candidate(s)."); the
// actual candidates were captured in the audit trail but never shown. This
// surfaces them as real cards, sourced from the same tamper-evident audit
// payload the rest of this page already trusts (tx.timeline), so a viewer
// can see exactly what Channel3 returned and which of those real listings
// the agent picked - not just take the final choice on faith.
interface Channel3Product {
  channel3_product_id: string | null;
  title: string | null;
  brand: string | null;
  key_features?: string[];
  image_url: string | null;
  price: number | null;
  compare_at_price: number | null;
  currency: string | null;
  availability: string | null;
  retailer: string | null;
  buy_url: string | null;
}

export function Channel3Candidates({ tx }: { tx: Transaction }) {
  const timeline = tx.timeline || [];
  const searches = timeline.filter((r) => r.event_type === "CHANNEL3_SEARCH_COMPLETED");
  const failed = timeline.some((r) => r.event_type === "CHANNEL3_SEARCH_FAILED");

  if (searches.length === 0 && !failed) return null;

  // If the agent searched more than once (e.g. a refined follow-up query),
  // only the most recent set of candidates is what actually fed the
  // eventual proposal - earlier searches are still in the full Terminal/
  // audit log below for anyone who wants that detail.
  const latest = searches[searches.length - 1];
  const products = (latest?.payload?.products as Channel3Product[] | undefined) || [];
  const query = latest?.payload?.query as string | undefined;

  return (
    <div className="card-surface space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          <PackageSearch size={14} /> Channel3 Product Research
        </p>
        {query && <span className="text-xs italic text-[var(--color-text-muted)]">&ldquo;{query}&rdquo;</span>}
      </div>

      {products.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {products.map((p, i) => {
            const chosen = Boolean(tx.channel3_product_id) && p.channel3_product_id === tx.channel3_product_id;
            const cardClass = `relative flex gap-3 rounded-xl border p-3 transition ${
              chosen
                ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                : "border-[var(--color-border)] hover:border-[var(--color-accent)]"
            }`;
            const content = (
              <>
                {p.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={p.image_url}
                    alt=""
                    className="h-14 w-14 flex-shrink-0 rounded-lg border border-[var(--color-border)] object-contain bg-[var(--color-surface-2)]"
                  />
                ) : (
                  <div className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--color-surface-2)] text-[var(--color-text-muted)]">
                    <PackageSearch size={18} />
                  </div>
                )}
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="truncate text-sm font-medium text-[var(--color-text)]">
                    {p.title || "Untitled product"}
                  </p>
                  <p className="truncate text-xs text-[var(--color-text-muted)]">
                    {p.retailer || "Unknown retailer"}
                    {p.brand ? ` · ${p.brand}` : ""}
                  </p>
                  <div className="flex items-center gap-2 pt-0.5">
                    <span className="font-mono-ui text-sm font-semibold text-[var(--color-text)]">
                      {p.price != null ? money(p.price, p.currency || "USD") : "N/A"}
                    </span>
                    {p.compare_at_price != null && p.price != null && p.compare_at_price > p.price && (
                      <span className="font-mono-ui text-xs text-[var(--color-text-muted)] line-through">
                        {money(p.compare_at_price, p.currency || "USD")}
                      </span>
                    )}
                  </div>
                </div>
                {chosen && (
                  <span className="absolute -top-2 -right-2 flex items-center gap-1 rounded-full bg-[var(--color-accent)] px-2 py-0.5 text-[10px] font-semibold text-white shadow-sm">
                    <CheckCircle2 size={11} /> Chosen
                  </span>
                )}
              </>
            );
            const key = p.channel3_product_id || `${p.title}-${i}`;
            return p.buy_url ? (
              <a key={key} href={p.buy_url} target="_blank" rel="noreferrer" className={cardClass}>
                {content}
              </a>
            ) : (
              <div key={key} className={cardClass}>
                {content}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-[var(--color-text-muted)]">
          Channel3&apos;s catalog search failed for this task; the agent fell back to a general web
          search instead (see the proposal&apos;s source listing and the Terminal log below).
        </p>
      )}

      {products.length > 0 && (
        <p className="text-xs text-[var(--color-text-muted)]">
          Live structured data straight from Channel3&apos;s product catalog — real prices, real
          retailers, real availability. {products.length} candidate{products.length === 1 ? "" : "s"}{" "}
          considered before the policy engine evaluated the agent&apos;s final pick.
        </p>
      )}
    </div>
  );
}
