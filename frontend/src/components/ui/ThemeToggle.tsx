"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import clsx from "clsx";

const options = [
  { id: "system", icon: Monitor, label: "System" },
  { id: "light", icon: Sun, label: "Light" },
  { id: "dark", icon: Moon, label: "Dark" },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <div className="flex items-center gap-0.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-2)] p-1">
      {options.map((opt) => {
        const Icon = opt.icon;
        const active = mounted && theme === opt.id;
        return (
          <button
            key={opt.id}
            aria-label={opt.label}
            onClick={() => setTheme(opt.id)}
            className={clsx(
              "flex h-7 w-7 items-center justify-center rounded-full transition-all duration-150",
              active
                ? "bg-[var(--color-surface)] text-[var(--color-accent)] shadow-sm"
                : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            )}
          >
            <Icon size={14} />
          </button>
        );
      })}
    </div>
  );
}
