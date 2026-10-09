"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Transaction } from "@/lib/types";
import { MessageCircleQuestion, Send } from "lucide-react";

export function NeedsInputCard({
  tx,
  onReply,
}: {
  tx: Transaction;
  onReply: (message: string) => Promise<void>;
}) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSend() {
    const trimmed = message.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      await onReply(trimmed);
      setMessage("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send reply");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card-elevated animate-enter overflow-hidden">
      <div className="border-b border-[var(--color-border)] bg-[var(--color-warning-soft)] px-6 py-5">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-[var(--color-warning)]">
          <MessageCircleQuestion size={14} /> Agent needs your input
        </p>
        <p className="mt-2 text-sm leading-relaxed text-[var(--color-text)]">{tx.pending_question}</p>
      </div>

      <div className="space-y-3 px-6 py-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
          Your reply
        </p>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder="e.g. Yes, go ahead with that one. Or: keep searching, raise the budget to $50."
          rows={3}
          disabled={busy}
          className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--color-accent)] disabled:opacity-60"
        />
        {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
        <div className="flex justify-end">
          <Button variant="primary" onClick={handleSend} loading={busy} disabled={busy || !message.trim()}>
            <Send size={16} /> Send reply
          </Button>
        </div>
        <p className="text-xs text-[var(--color-text-muted)]">
          The agent paused here instead of guessing or giving up. Your reply is added to its conversation and it
          continues from exactly where it left off.
        </p>
      </div>
    </div>
  );
}
