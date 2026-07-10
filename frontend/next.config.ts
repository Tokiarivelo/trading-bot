import type { NextConfig } from "next";

// Backend REST is proxied under /api so the frontend never hardcodes the
// backend URL. WebSockets are NOT proxied by Next rewrites — see
// src/shared/api/ws.ts, which connects to the backend directly.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
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
