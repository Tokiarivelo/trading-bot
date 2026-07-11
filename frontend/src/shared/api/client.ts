/** Thin fetch wrapper for the backend REST API (proxied via /api, see next.config.ts). */

const BASE = "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function errorMessage(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Not JSON (or no `detail` field) — fall through to the raw text below.
  }
  return text;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return res.json() as Promise<T>;
}

async function requestForm<T>(path: string, method: string, form: FormData): Promise<T> {
  // No Content-Type header here on purpose — the browser sets the multipart
  // boundary itself when the body is a FormData.
  const res = await fetch(`${BASE}${path}`, { method, body: form });
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  postForm: <T>(path: string, form: FormData) => requestForm<T>(path, "POST", form),
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
  timeframe: "M1" | "M5" | "H1" | "H4" | "D1";
  time: number; // bar open, epoch seconds UTC (lightweight-charts native)
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
  spread_points: number;
}

/** `before` (epoch seconds) pages further back than the most recent `count`
 * bars — pass the oldest loaded candle's `time` to fetch older history. */
export const getCandles = (
  symbol: string,
  timeframe: Candle["timeframe"],
  count = 300,
  before?: number,
) => {
  const params = new URLSearchParams({ symbol, timeframe, count: String(count) });
  if (before !== undefined) params.set("before", String(before));
  return api.get<Candle[]>(`/market-data/candles?${params}`);
};

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

export interface BrokerSymbol {
  name: string;
  description: string;
  path: string; // broker's Market Watch group, e.g. "Forex\\Majors"
  visible: boolean;
}

export interface BrokerSymbolPage {
  items: BrokerSymbol[];
  total: number; // count matching `search` (or full catalog), before limit/offset
}

/** Browse the connected broker's full symbol catalog (chart/watchlist only —
 * does not configure the engine; see configs/app.yaml: symbols for that).
 * Pass `offset` to page through the full catalog when `search` is omitted. */
export const getBrokerSymbols = (search?: string, limit = 50, offset = 0) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (search) params.set("search", search);
  return api.get<BrokerSymbolPage>(`/market-data/broker-symbols?${params}`);
};

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

// ── AI: PDF -> StrategySpec pipeline (Phase 6, F4) ──────────────────────────

export interface ExtractedStrategySpec {
  name: string;
  symbols: string[];
  entry_timeframe: string;
  confirmation_timeframes: string[];
  indicators: string[];
  entry_rules: string;
  exit_rules: string;
  risk_notes: string;
  params: Record<string, unknown>;
}

export type DraftStatus = "pending_review" | "approved" | "rejected" | "code_generated";

export interface StrategyDraft {
  id: string;
  source_filename: string;
  created_at: number; // epoch seconds UTC
  status: DraftStatus;
  extracted_spec: ExtractedStrategySpec;
  edited_spec: ExtractedStrategySpec | null;
  effective_spec: ExtractedStrategySpec;
}

export interface GeneratedCode {
  draft_id: string;
  code: string;
  is_valid: boolean;
  sandbox_errors: string[];
  version_id: string | null;
  backtest_report_id: string | null;
}

export const uploadStrategyPdf = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.postForm<StrategyDraft>("/ai/pdf-strategy/upload", form);
};

export const getStrategyDrafts = () => api.get<StrategyDraft[]>("/ai/pdf-strategy/drafts");
export const getStrategyDraft = (id: string) =>
  api.get<StrategyDraft>(`/ai/pdf-strategy/drafts/${encodeURIComponent(id)}`);
export const updateStrategyDraftSpec = (id: string, editedSpec: ExtractedStrategySpec) =>
  api.patch<StrategyDraft>(`/ai/pdf-strategy/drafts/${encodeURIComponent(id)}`, {
    edited_spec: editedSpec,
  });
export const approveStrategyDraft = (id: string) =>
  api.post<StrategyDraft>(`/ai/pdf-strategy/drafts/${encodeURIComponent(id)}/approve`);
export const rejectStrategyDraft = (id: string) =>
  api.post<StrategyDraft>(`/ai/pdf-strategy/drafts/${encodeURIComponent(id)}/reject`);
export const generateStrategyCode = (id: string) =>
  api.post<GeneratedCode>(`/ai/pdf-strategy/drafts/${encodeURIComponent(id)}/generate-code`);

// ── Strategy versions & activation (Phase 6, §6.5) ──────────────────────────

export type StrategyVersionStatus = "validated" | "active" | "archived";
export type StrategySource = "ai_generated" | "ai_refined" | "manual";

export interface StrategyVersionSummary {
  id: string;
  name: string;
  version: number;
  file_path: string;
  code_hash: string;
  source: StrategySource;
  status: StrategyVersionStatus;
  created_at: number; // epoch seconds UTC
  parent_version_id: string | null;
  draft_id: string | null;
  spec: ExtractedStrategySpec | null;
  backtest_report_id: string | null;
}

export interface StrategyVersionDetail extends StrategyVersionSummary {
  code: string;
}

export const getStrategyVersions = (name?: string) =>
  api.get<StrategyVersionSummary[]>(
    `/strategies/versions${name ? `?name=${encodeURIComponent(name)}` : ""}`,
  );
export const getStrategyVersion = (id: string) =>
  api.get<StrategyVersionDetail>(`/strategies/versions/${encodeURIComponent(id)}`);
export const activateStrategyVersion = (id: string) =>
  api.post<StrategyVersionSummary>(`/strategies/versions/${encodeURIComponent(id)}/activate`);

// ── AI: 10-trade self-refinement loop (Phase 7, F5) ─────────────────────────

export type ReportVerdict = "no_action" | "refinement_proposed";

export interface AnalysisReport {
  id: string;
  symbol: string;
  strategy_name: string;
  base_version_id: string;
  trade_ids: string[];
  created_at: number; // epoch seconds UTC
  win_rate: number;
  avg_r: number;
  common_failure_pattern: string;
  session_or_news_correlation: string;
  verdict: ReportVerdict;
  raw_llm_response: string;
  proposal_id: string | null;
}

export type ProposalStatus = "pending" | "backtested" | "applied" | "rejected";

export interface RefinementProposalDetail {
  id: string;
  report_id: string;
  strategy_name: string;
  base_version_id: string;
  rationale: string;
  proposed_code: string;
  status: ProposalStatus;
  created_at: number; // epoch seconds UTC
  sandbox_errors: string[];
  new_version_id: string | null;
  improvement_pct: number | null; // candidate avg_r % improvement over baseline
  applied_mode: "suggest" | "auto" | null;
  diff: string[]; // unified diff lines, computed fresh server-side on every read
  baseline_backtest: BacktestReportSummary | null;
  candidate_backtest: BacktestReportSummary | null;
}

export const getAnalysisReports = (symbol?: string) =>
  api.get<AnalysisReport[]>(
    `/ai/refinement/reports${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`,
  );
export const getAnalysisReport = (id: string) =>
  api.get<AnalysisReport>(`/ai/refinement/reports/${encodeURIComponent(id)}`);
export const getRefinementProposal = (id: string) =>
  api.get<RefinementProposalDetail>(`/ai/refinement/proposals/${encodeURIComponent(id)}`);
export const rejectRefinementProposal = (id: string) =>
  api.post<RefinementProposalDetail>(`/ai/refinement/proposals/${encodeURIComponent(id)}/reject`);

// ── News: economic calendar & active windows (Phase 8, F8) ─────────────────

export type ImpactLevel = "low" | "medium" | "high";

export interface NewsEvent {
  name: string;
  time: number; // epoch seconds UTC
  impact: ImpactLevel;
  currency: string;
  skill: string | null; // matched news skill, or null if this event never activates one
}

export interface NewsWindow {
  event: NewsEvent;
  skill: string;
  window_start: number; // epoch seconds UTC
  window_end: number; // epoch seconds UTC
  phase: "pre" | "post";
  symbols: string[]; // symbols this window affects
}

export const getUpcomingNews = (daysAhead = 7) =>
  api.get<NewsEvent[]>(`/news/upcoming?days_ahead=${daysAhead}`);
export const getActiveNewsWindows = () => api.get<NewsWindow[]>("/news/active-windows");
