"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// The sidebar (desktop) and the mobile nav drawer are both mounted at all
// times regardless of viewport - only CSS (`md:hidden` / `hidden md:flex`)
// decides which one is visible. If each read the same live status with its
// own useEffect+setInterval, every page would quietly fire the dashboard
// summary request twice, forever, for no reason a reader of either
// component could see in isolation. A single module-level poll shared by
// however many nav instances are mounted - started on first subscriber,
// stopped on last - gets the same live data to both without that doubled
// cost.
export type LiveSidebarStatus = {
  // Transactions genuinely waiting on a human decision right now - a real
  // action count, not a vanity metric, so it's worth a badge in the nav
  // itself rather than something you only discover by opening the ledger.
  awaitingApproval: number;
};

const POLL_INTERVAL_MS = 20_000;

let current: LiveSidebarStatus = { awaitingApproval: 0 };
let timer: ReturnType<typeof setInterval> | null = null;
const subscribers = new Set<(status: LiveSidebarStatus) => void>();

function notify() {
  subscribers.forEach((fn) => fn(current));
}

async function poll() {
  try {
    const summary = await api.dashboardSummary();
    current = { awaitingApproval: summary.awaiting_approval };
    notify();
  } catch {
    // A failed poll just leaves the last-known count in place rather than
    // zeroing it out - a transient blip shouldn't make a real pending
    // approval disappear from the nav.
  }
}

function ensureStarted() {
  if (timer) return;
  poll();
  timer = setInterval(poll, POLL_INTERVAL_MS);
}

function stopIfUnwatched() {
  if (subscribers.size === 0 && timer) {
    clearInterval(timer);
    timer = null;
  }
}

export function useLiveSidebarStatus(): LiveSidebarStatus {
  const [status, setStatus] = useState(current);

  useEffect(() => {
    subscribers.add(setStatus);
    ensureStarted();
    return () => {
      subscribers.delete(setStatus);
      stopIfUnwatched();
    };
  }, []);

  return status;
}
