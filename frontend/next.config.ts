import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["*.e2b.app"],
  devIndicators: false,
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
