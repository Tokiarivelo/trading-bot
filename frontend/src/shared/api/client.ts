/** Thin fetch wrapper for the backend REST API (proxied via /api, see vite.config.ts). */

const BASE = "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
};

export interface AppConfig {
  mode: "paper" | "live";
  symbols: string[];
  engine: { enabled: boolean; entry_timeframe: string; confirmation_timeframes: string[] };
}

export const getHealth = () => api.get<{ status: string }>("/health");
export const getAppConfig = () => api.get<AppConfig>("/config/app");
