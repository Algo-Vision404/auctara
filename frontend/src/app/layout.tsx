import type { Metadata } from "next";
import { Sora, DM_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Sidebar, MobileNav } from "@/components/nav/Sidebar";

const sora = Sora({
  variable: "--font-sora",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});

const dmMono = DM_Mono({
  variable: "--font-dm-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "AgentAuth: Delegated Spending Authority for AI Agents",
  description:
    "Let AI agents act. Keep financial authority under your control. AgentAuth lets users delegate spending authority to AI agents behind a deterministic policy engine and real PayPal Sandbox execution.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${sora.variable} ${dmMono.variable} antialiased`}>
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex min-h-screen min-w-0 flex-1 flex-col pb-16 md:pb-0">{children}</div>
          </div>
          <MobileNav />
        </Providers>
      </body>
    </html>
  );
}
