"use client";

import { ThemeProvider } from "next-themes";
import { ReactNode } from "react";
import { ConfirmProvider } from "@/components/ui/ConfirmDialog";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <ConfirmProvider>{children}</ConfirmProvider>
    </ThemeProvider>
  );
}
