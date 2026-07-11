/** Thin fetch wrapper for the backend REST API (proxied via /api, see next.config.ts). */

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

// ── Account (MT5 login, F11) ────────────────────────────────────────────────

export interface AccountInfo {
  login: number;
  server: string;
  name: string;
  currency: string;
  balance: number;
  equity: number;
  leverage: number;
}

export interface AccountStatus {
  gateway_up: boolean;
  connected: boolean;
  account: AccountInfo | null;
  has_saved_credentials: boolean;
}

export const getAccountStatus = () => api.get<AccountStatus>("/account/status");
export const connectAccount = (body: {
  login: number;
  password: string;
  server: string;
  remember: boolean;
}) => api.post<{ connected: boolean; account: AccountInfo }>("/account/connect", body);
export const disconnectAccount = (forget = false) =>
  api.post<{ connected: boolean }>("/account/disconnect", { forget });

// ── Market data ─────────────────────────────────────────────────────────────

export interface Candle {
  symbol: string;
  timeframe: "M5" | "H1" | "H4" | "D1";
  time: number; // bar open, epoch seconds UTC (lightweight-charts native)
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
  spread_points: number;
}

export const getCandles = (symbol: string, timeframe: Candle["timeframe"], count = 300) =>
  api.get<Candle[]>(
    `/market-data/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&count=${count}`,
  );

export interface SymbolInfo {
  symbol: string;
  bid: number;
  ask: number;
  spread_points: number;
  point: number;
  digits: number;
  stops_level: number;
  contract_size: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
}

export const getSymbolInfo = (symbol: string) =>
  api.get<SymbolInfo>(`/market-data/symbol-info?symbol=${encodeURIComponent(symbol)}`);

// ── Journal (trade markers, F7) ─────────────────────────────────────────────

export interface TradeMarker {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  volume: number;
  open_price: number;
  open_time: number; // epoch seconds UTC
  sl: number | null;
  tp: number | null;
  close_price: number | null;
  close_time: number | null; // epoch seconds UTC, null while open
  profit: number | null;
  comment: string;
}

export const getTradeMarkers = (symbol: string) =>
  api.get<TradeMarker[]>(`/journal/markers?symbol=${encodeURIComponent(symbol)}`);

// ── Backtest (Phase 5 reports) ──────────────────────────────────────────────

export interface BacktestTrade {
  side: "buy" | "sell";
  volume: number;
  open_time: number; // epoch seconds UTC
  open_price: number;
  sl: number | null;
  tp: number | null;
  close_time: number; // epoch seconds UTC
  close_price: number;
  profit: number;
  r_multiple: number | null;
}

export interface EquityPoint {
  time: number; // epoch seconds UTC
  balance: number;
}

export interface BacktestReportSummary {
  id: string;
  strategy: string;
  symbol: string;
  period: string;
  trade_count: number;
  win_rate: number;
  profit_factor: number | null; // null means no losing trades (infinite)
  max_drawdown_pct: number;
  avg_r: number;
  worst_losing_streak: number;
  starting_balance: number;
  ending_balance: number;
}

export interface BacktestReportDetail extends BacktestReportSummary {
  trades: BacktestTrade[];
  equity_curve: EquityPoint[];
}

export const getBacktestReports = () => api.get<BacktestReportSummary[]>("/backtest/reports");
export const getBacktestReport = (id: string) =>
  api.get<BacktestReportDetail>(`/backtest/reports/${encodeURIComponent(id)}`);
