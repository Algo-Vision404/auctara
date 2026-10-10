import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["*.e2b.app"],
  devIndicators: false,
  // The heaviest two routes (the AG Grid-powered ledger and the Bryntum-
  // powered schedule) each push the dev server's own memory well past a
  // gigabyte while compiling. By default Next.js dev keeps several recently
  // visited pages' compiled modules resident at once (pagesBufferLength),
  // so navigating between those two specifically compounds rather than
  // replaces the memory cost - the exact pattern that twice crashed the dev
  // server in this sandbox's tight RAM ceiling. Keeping only the single
  // most recently visited page's compiled output in memory, and disposing
  // it quickly once it's not the active page, trades a little recompile
  // time when flipping back and forth for not running the dev server out
  // of memory. Dev-only: production (`next build`) precompiles every route
  // once and this setting has no effect there.
  onDemandEntries: {
    maxInactiveAge: 10 * 1000,
    pagesBufferLength: 1,
  },
  // Next's built-in gzip compression buffers proxied/rewritten responses,
  // which silently breaks real-time Server-Sent Events streamed through the
  // /api/* rewrite below. Disable it so SSE chunks flush immediately.
  compress: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
