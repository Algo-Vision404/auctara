"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { TopBar } from "@/components/nav/TopBar";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { api, ApiError } from "@/lib/api";
import { Task } from "@/lib/types";
import { Loader2 } from "lucide-react";

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  const redirected = useRef(false);

  useEffect(() => {
    let mounted = true;
    const poll = () => {
      api
        .getTask(id)
        .then((t) => {
          if (!mounted) return;
          setTask(t);
          setError(null);
          const tx = (t.transactions || [])[0];
          if (tx && !redirected.current) {
            redirected.current = true;
            router.replace(`/transactions/${tx.id}`);
          }
        })
        .catch((e) => mounted && setError(e instanceof ApiError ? e.message : "Failed to load task"));
    };
    poll();
    const i = setInterval(poll, 1500);
    return () => {
      mounted = false;
      clearInterval(i);
    };
  }, [id, router]);

  return (
    <div className="flex flex-1 flex-col">
      <TopBar
        title="Task Execution"
        subtitle="Live, backend-driven agent activity."
        backHref={task ? `/agents/${task.agent_id}` : "/agents"}
        backLabel="Back to agent"
      />
      <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-5 py-6 md:px-8">
        {error && (
          <div className="card-surface border-l-4 border-l-[var(--color-danger)] p-4 text-sm text-[var(--color-danger)]">
            {error}
          </div>
        )}
        {task && (
          <div className="card-surface space-y-2 p-5">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">
              Task prompt
            </p>
            <p className="text-sm">{task.prompt}</p>
            <div className="flex items-center gap-2 pt-2 text-sm text-[var(--color-text-secondary)]">
              <Loader2 size={14} className="animate-spin" />
              Status: {task.status}
            </div>
          </div>
        )}
        <ActivityFeed taskId={id} />
      </main>
    </div>
  );
}
