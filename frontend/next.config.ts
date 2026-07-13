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
  experimental: {
    // Default is 10MB; strategy-spec PDFs (with embedded images/diagrams)
    // routinely exceed that. Applies to requests proxied through the /api
    // rewrite above, e.g. POST /api/ai/pdf-strategy/upload.
    proxyClientMaxBodySize: "50mb",
    // Next's dev proxy kills any /api rewrite after 30s by default. PDF
    // extraction runs a real LLM call over the extracted text and routinely
    // takes longer than that on a big PDF, so the proxy was resetting the
    // socket (ECONNRESET) while the backend kept working in the background —
    // the draft would show up on refresh even though the upload request
    // itself errored client-side. 3 minutes covers slow LLM extraction.
    proxyTimeout: 180_000,
  },
};

export default nextConfig;
