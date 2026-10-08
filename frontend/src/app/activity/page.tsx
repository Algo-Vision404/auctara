"use client";

import { TopBar } from "@/components/nav/TopBar";
import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { Terminal } from "@/components/terminal/Terminal";

export default function ActivityPage() {
  return (
    <div className="flex flex-1 flex-col">
      <TopBar title="Activity" subtitle="Human-readable operational activity across every agent, live." />
      <main className="flex-1 space-y-6 px-5 py-6 md:px-8">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <ActivityFeed limit={100} />
          <Terminal />
        </div>
      </main>
    </div>
  );
}
