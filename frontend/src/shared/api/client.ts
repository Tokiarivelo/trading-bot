/** Thin fetch wrapper for the backend REST API (proxied via /api, see next.config.ts). */

const BASE = "/api";
const TOKEN_KEY = "tb.session";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// ── Session token (§11) ─────────────────────────────────────────────────────
// Token-based (not cookie-based) so the same token works whether a request
// goes through the Next.js /api rewrite or hits the backend directly (Socket.IO
// — see ws.ts), with no cross-origin cookie handling to worry about.

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** Dispatched on any 401 from a non-/auth/ request, so the UI can re-lock
 * after a session expires mid-use. See features/auth/LoginGate.tsx. */
export const UNAUTHORIZED_EVENT = "tb:unauthorized";

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
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

function handleUnauthorized(path: string, status: number): void {
  if (status !== 401 || path.startsWith("/auth/") || path === "/account/connect") return;
  clearToken();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...init,
  });
  if (!res.ok) {
    handleUnauthorized(path, res.status);
    throw new ApiError(res.status, await errorMessage(res));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function requestForm<T>(path: string, method: string, form: FormData): Promise<T> {
  // No Content-Type header here on purpose — the browser sets the multipart
  // boundary itself when the body is a FormData.
  const res = await fetch(`${BASE}${path}`, { method, body: form, headers: authHeaders() });
  if (!res.ok) {
    handleUnauthorized(path, res.status);
    throw new ApiError(res.status, await errorMessage(res));
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  postForm: <T>(path: string, form: FormData) => requestForm<T>(path, "POST", form),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// ── Auth (§11) ───────────────────────────────────────────────────────────────

export interface AuthStatus {
  auth_required: boolean;
}

export const getAuthStatus = () => api.get<AuthStatus>("/auth/status");
export const login = async (password: string) => {
  const res = await api.post<{ token: string; expires_in_seconds: number }>("/auth/login", {
    password,
  });
  setToken(res.token);
  return res;
};
export const logout = async () => {
  clearToken();
  try {
    await api.post("/auth/logout");
  } catch {
    // Logout is best-effort client-side (token already cleared above).
  }
};

export interface AppConfig {
  mode: "paper" | "live";
  symbols: string[];
  engine: { enabled: boolean; entry_timeframe: string };
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
  timeframe: "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN";
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

/** `skill` (a bot's full id from `getSkillAssignments`, e.g.
 * 'normal/xauusd/breakout_v1'), when given, scopes markers to just that
 * bot's own trades instead of every trade (any bot, or manual) on the
 * symbol — used by the chart's per-bot "eye" overlay. */
export const getTradeMarkers = (symbol: string, skill?: string) => {
  const params = new URLSearchParams({ symbol });
  if (skill) params.set("skill", skill);
  return api.get<TradeMarker[]>(`/journal/markers?${params}`);
};

// ── Journal (trade history, filterable/paginated) ───────────────────────────

export interface TradeHistoryItem {
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
  strategy_version: string | null;
  skill: string | null;
}

export interface TradeHistoryPage {
  items: TradeHistoryItem[];
  total: number; // count matching the filters, before limit/offset
}

export type TradeOutcome = "win" | "loss" | "breakeven" | "open";
export type TradeHistoryOrderBy = "open_time" | "close_time" | "profit";
export type SortDir = "asc" | "desc";

export interface TradeHistoryFilters {
  symbol?: string;
  side?: OrderSide;
  strategy_version?: string;
  skill?: string;
  outcome?: TradeOutcome;
  open_from?: number; // epoch seconds UTC
  open_to?: number;
  close_from?: number;
  close_to?: number;
  order_by?: TradeHistoryOrderBy;
  order_dir?: SortDir;
  limit?: number;
  offset?: number;
}

/** Filtered, paginated trade history across any symbol — backs the trade
 * history page's filter and group-by controls. Unlike `getTradeMarkers`
 * (single symbol, chart overlay only), this supports the full filter set. */
export const getTradeHistory = (filters: TradeHistoryFilters = {}) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return api.get<TradeHistoryPage>(`/journal/history${qs ? `?${qs}` : ""}`);
};

// ── Activity log (persisted "what is the bot doing and why") ───────────────

export interface LogEntry {
  id: number;
  created_at: number; // epoch seconds UTC
  level: string; // "INFO" | "WARNING" | "ERROR" | ...
  logger: string; // e.g. "src.engine.application.trade_loop"
  message: string;
}

export interface LogHistoryPage {
  items: LogEntry[];
  total: number; // count matching the filters, before limit/offset
}

export interface LogHistoryFilters {
  level?: string;
  logger_contains?: string;
  q?: string;
  created_from?: number; // epoch seconds UTC
  created_to?: number;
  limit?: number;
  offset?: number;
}

/** Filtered, paginated activity log across every backend module — the
 * durable record of signals, vetoes, fills, and circuit breakers, beyond
 * what scrolls past in stdout. */
export const getActivityLog = (filters: LogHistoryFilters = {}) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return api.get<LogHistoryPage>(`/activity/history${qs ? `?${qs}` : ""}`);
};

export interface LogDeleteResult {
  deleted: number;
}

/** Deletes specific activity log rows by id — backs single-row delete and
 * multi-select bulk delete in the activity log UI. */
export const deleteActivityLogByIds = (ids: number[]) =>
  api.post<LogDeleteResult>("/activity/history/delete-by-ids", { ids });

/** Deletes every activity log row matching the given filters — backs
 * "delete all matching" in the activity log UI. Mirrors `LogHistoryFilters`
 * (minus pagination); omitting all fields deletes every row. */
export const deleteActivityLogByFilter = (
  filters: Omit<LogHistoryFilters, "limit" | "offset"> = {}
) => api.post<LogDeleteResult>("/activity/history/delete-by-filter", filters);

// ── Backtest (Phase 5 reports) ──────────────────────────────────────────────

export interface Zone {
  kind: "demand" | "supply";
  price_low: number;
  price_high: number;
  time_start: number; // epoch seconds UTC
  time_end: number; // epoch seconds UTC
}

export interface StructurePoint {
  label: "HH" | "HL" | "LH" | "LL";
  price: number;
  time: number; // epoch seconds UTC
}

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
  zone: Zone | null;
  pattern: string | null;
  structure: StructurePoint[];
}

export interface EquityPoint {
  time: number; // epoch seconds UTC
  balance: number;
}

export interface ActivityLogEntry {
  time: number; // epoch seconds UTC — simulated bot clock, not wall-clock
  level: string; // "INFO" | "WARNING" | "ERROR"
  logger: string; // e.g. "src.engine.application.trade_loop"
  message: string;
}

/** One strategy signal emitted during the replay — including signals that
 * never became trades (vetoed or rejected by the engine), so the report
 * page and chart can show every valid setup the strategy saw. Also reused
 * as-is for a *live* bot's signal trail (`getLiveBotSignals` below,
 * `GET /activity/signals`) — same shape, same chart rendering, just sourced
 * from the live decision-trail log instead of a backtest replay. */
export interface BacktestSignal {
  time: number; // epoch seconds UTC — simulated bot clock (bar close time), or live wall clock
  direction: "buy" | "sell";
  /** 'opened' (became a trade), 'htf_veto' (higher-TF trend opposed it),
   * 'risk_rejected' (sizing failed the risk caps), 'spread_veto'
   * (spread/RR gate), 'broker_rejected' (the broker/MT5 itself refused the
   * order — live only), or 'skipped'. */
  outcome: "opened" | "htf_veto" | "risk_rejected" | "spread_veto" | "broker_rejected" | "skipped";
  /** The strategy's own reason string — pattern, zone rect, entry/SL/TP. */
  reason: string;
}

/** Reconstructs one live bot's own signal→outcome trail — every setup its
 * strategy saw, whether it became a trade or was vetoed/rejected — for the
 * chart's per-bot "eye" overlay. `skill` is a bot's full id from
 * `getSkillAssignments` (e.g. 'normal/xauusd/breakout_v1') and already
 * fully identifies the symbol, so no separate `symbol` param is needed.
 * Defaults to the last 14 days server-side if `from` is omitted. */
export const getLiveBotSignals = (skill: string, from?: number, to?: number) => {
  const params = new URLSearchParams({ skill });
  if (from !== undefined) params.set("from", String(from));
  if (to !== undefined) params.set("to", String(to));
  return api.get<BacktestSignal[]>(`/activity/signals?${params}`);
};

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
  /** Spread-adjusted minimum reward:risk ratio SpreadGate enforced for this
   * run — a run parameter like starting_balance, not a fixed strategy
   * property. */
  min_rr: number;
  // The full RiskCaps actually enforced for this run (configs/risk.yaml's
  // values, or this run's own overrides) — see RiskManager.size_position /
  // record_trade_closed. daily_loss_limit_pct and consecutive_loss_pause
  // are circuit breakers that pause the engine and never auto-resume, so a
  // low trade_count relative to the period often means one of these
  // tripped early, not that no more setups occurred.
  risk_per_trade_pct: number;
  daily_loss_limit_pct: number;
  max_open_positions: number;
  max_trades_per_day: number;
  consecutive_loss_pause: number;
  min_lot_fallback_enabled: boolean;
  max_risk_per_trade_pct: number | null;
}

export interface BacktestReportDetail extends BacktestReportSummary {
  trades: BacktestTrade[];
  equity_curve: EquityPoint[];
  activity_log: ActivityLogEntry[];
  /** Every signal the strategy emitted (taken or vetoed), oldest first —
   * empty for report files predating this field. */
  signals: BacktestSignal[];
}

export interface BacktestReportPage {
  items: BacktestReportSummary[];
  total: number;
  limit: number;
  offset: number;
}

export const getBacktestReports = (limit: number, offset: number) =>
  api.get<BacktestReportPage>(
    `/backtest/reports?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`,
  );
export const getBacktestReport = (id: string) =>
  api.get<BacktestReportDetail>(`/backtest/reports/${encodeURIComponent(id)}`);
/** Hard-deletes this report's file. This cannot be undone. */
export const deleteBacktestReport = (id: string) =>
  api.delete<void>(`/backtest/reports/${encodeURIComponent(id)}`);
/** Saves a new report from JSON shaped exactly like getBacktestReport()'s
 * response — download an existing report to get a valid example. A fresh
 * id is always assigned (any `id` in `body` is ignored), so this never
 * overwrites an existing report. */
export const importBacktestReport = (body: BacktestReportDetail) =>
  api.post<BacktestReportSummary>("/backtest/reports/import", body);

// ── Backtest bots + on-demand run ─────────────────────────────────────────────

export interface BacktestBot {
  /** Stable identifier — pass this to `startBacktest`, never `name`. The
   * literal string "breakout_v1" for the hardcoded baseline, or a strategy
   * version id (UUID) for everything else. */
  id: string;
  /** Display label only — human-typed, not guaranteed unique or stable
   * (a family can be renamed, or its generated code can hardcode the same
   * internal name as an unrelated family). Never use this to look anything
   * up; use `id`. */
  name: string;
  symbols: string[];
}

export interface BacktestJobStatus {
  job_id: string;
  status: "pending" | "running" | "done" | "error";
  report_id: string | null;
  error: string | null;
}

export const getBacktestBots = () => api.get<BacktestBot[]>("/backtest/bots");
export const startBacktest = (
  strategyId: string,
  symbol: string,
  period: string,
  startingBalance?: number,
  /** Override configs/risk.yaml's min-lot fallback for this run only — null/omitted
   * uses whatever's currently configured (file default, or the live engine override
   * from putMinLotFallback). See RunBacktestPanel's "small balance" section. */
  minLotFallbackEnabled?: boolean,
  maxRiskPerTradePct?: number,
  /** Override configs/symbols/<symbol>.yaml's min_rr for this run only — null/omitted
   * uses whatever's currently configured (file default, or the live override from
   * putSymbolMinRr). A tighter-stop strategy can fail the RR floor a swing-trading
   * min_rr was tuned for. */
  minRr?: number,
) =>
  api.post<BacktestJobStatus>("/backtest/run", {
    strategy_id: strategyId,
    symbol,
    period,
    ...(startingBalance != null ? { starting_balance: startingBalance } : {}),
    ...(minLotFallbackEnabled != null
      ? { min_lot_fallback_enabled: minLotFallbackEnabled }
      : {}),
    ...(maxRiskPerTradePct != null ? { max_risk_per_trade_pct: maxRiskPerTradePct } : {}),
    ...(minRr != null ? { min_rr: minRr } : {}),
  });
export const getBacktestJobStatus = (jobId: string) =>
  api.get<BacktestJobStatus>(`/backtest/run/${encodeURIComponent(jobId)}`);

// ── AI: PDF -> StrategySpec pipeline (Phase 6, F4) ──────────────────────────

export type IndicatorType = "ema" | "sma" | "rsi" | "macd" | "bollinger";

export interface IndicatorSpec {
  type: IndicatorType;
  period: number;
  label: string;
  source: string;
  params: Record<string, number>;
}

export type PriceLevelAnnotationType = "support" | "resistance" | "level";

export interface PriceLevelAnnotation {
  type: PriceLevelAnnotationType;
  price: number;
  label: string;
}

export interface ExtractedStrategySpec {
  name: string;
  symbols: string[];
  entry_timeframe: string;
  confirmation_timeframes: string[];
  indicators: IndicatorSpec[];
  entry_rules: string;
  exit_rules: string;
  risk_notes: string;
  params: Record<string, unknown>;
  unrecognized_indicators: string[];
  price_levels: PriceLevelAnnotation[];
  chart_notes: string[];
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

export const uploadStrategyPdf = (file: File, symbol?: string) => {
  const form = new FormData();
  form.append("file", file);
  if (symbol) form.append("symbol", symbol);
  return api.postForm<StrategyDraft>("/ai/pdf-strategy/upload", form);
};

/** Same draft pipeline as uploadStrategyPdf, but from a typed description —
 * no PDF required. Lands on the same review/approve/generate-code flow. */
export const createStrategyDraftFromText = (description: string, symbol?: string) =>
  api.post<StrategyDraft>("/ai/pdf-strategy/from-prompt", { description, symbol });

/** Same draft pipeline, but `spec` is already structured JSON (e.g. a file
 * upload) — skips LLM extraction entirely, `spec` becomes the draft's
 * extracted_spec as-is. Lands on the same review/approve/generate flow. */
export const createStrategyDraftFromJson = (spec: ExtractedStrategySpec, symbol?: string) =>
  api.post<StrategyDraft>("/ai/pdf-strategy/from-spec", { spec, symbol });

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
  /** Only meaningful while status is "active": true if suspended from live
   * evaluation via pauseStrategyVersion without being deactivated. */
  paused: boolean;
  created_at: number; // epoch seconds UTC
  parent_version_id: string | null;
  draft_id: string | null;
  spec: ExtractedStrategySpec | null;
  backtest_report_id: string | null;
}

export interface StrategyVersionDetail extends StrategyVersionSummary {
  code: string;
}

export const getStrategyVersions = (name?: string, status?: StrategyVersionStatus) => {
  const params = new URLSearchParams();
  if (name) params.set("name", name);
  if (status) params.set("status", status);
  const query = params.toString();
  return api.get<StrategyVersionSummary[]>(`/strategies/versions${query ? `?${query}` : ""}`);
};
export const getStrategyVersion = (id: string) =>
  api.get<StrategyVersionDetail>(`/strategies/versions/${encodeURIComponent(id)}`);
export const activateStrategyVersion = (id: string) =>
  api.post<StrategyVersionSummary>(`/strategies/versions/${encodeURIComponent(id)}/activate`);
/** Clones a version's code into a new, independent strategy family (fork,
 * not a new version of the same family). Pass `symbols` to also retarget
 * the clone — rewrites the generated code's `StrategySpec(symbols=...)` and
 * re-validates it in the sandbox; omit to keep the source's symbols. */
export const duplicateStrategyVersion = (id: string, body: { name: string; symbols?: string[] }) =>
  api.post<StrategyVersionSummary>(
    `/strategies/versions/${encodeURIComponent(id)}/duplicate`,
    body,
  );
/** Renames the display name shared by every version of this strategy
 * family, not just this one. */
export const renameStrategyVersion = (id: string, name: string) =>
  api.patch<StrategyVersionSummary>(`/strategies/versions/${encodeURIComponent(id)}/rename`, {
    name,
  });
/** Retires this version: marks it archived and, if it was the live version,
 * stops the engine from evaluating it. No replacement version is required —
 * the strategy family can end up with nothing active. */
export const archiveStrategyVersion = (id: string) =>
  api.post<StrategyVersionSummary>(`/strategies/versions/${encodeURIComponent(id)}/archive`);
/** Hard-deletes this version's record and generated file. Rejected with a
 * 409 if the version is currently active — archive it first. */
export const deleteStrategyVersion = (id: string) =>
  api.delete<void>(`/strategies/versions/${encodeURIComponent(id)}`);
/** Suspends live trading for this active version without deactivating it —
 * distinct from the engine-wide kill switch, which pauses every strategy. */
export const pauseStrategyVersion = (id: string) =>
  api.post<StrategyVersionSummary>(`/strategies/versions/${encodeURIComponent(id)}/pause`);
/** Reverses pauseStrategyVersion. */
export const resumeStrategyVersion = (id: string) =>
  api.post<StrategyVersionSummary>(`/strategies/versions/${encodeURIComponent(id)}/resume`);
/** Saves a hand-edited source. Leave `newName` unset to save as the next
 * version of this version's own strategy family, parented on `id` itself
 * (not necessarily the active version). Pass `newName` to fork the edit
 * into a brand-new strategy family at version 1 instead — throws
 * ApiError(409) if that name is already in use by another family.
 * Re-validated in the sandbox either way — throws ApiError(422) if that
 * fails. The new version's status is "validated", never "active". */
export const editStrategyVersionCode = (id: string, code: string, newName?: string) =>
  api.post<StrategyVersionDetail>(`/strategies/versions/${encodeURIComponent(id)}/edit`, {
    code,
    new_name: newName,
  });
/** Overwrites this version's spec snapshot in place — annotation only, never
 * touches the generated code or creates a new version (the same way
 * renameStrategyVersion mutates in place rather than forking). */
export const updateStrategyVersionSpec = (id: string, spec: ExtractedStrategySpec) =>
  api.patch<StrategyVersionSummary>(`/strategies/versions/${encodeURIComponent(id)}/spec`, spec);

// ── AI: user-triggered code regeneration (§6.5 code editor) ────────────────

export interface RegeneratedCode {
  version_id: string;
  instructions: string;
  code: string;
  is_valid: boolean;
  sandbox_errors: string[];
  new_version_id: string | null;
}

/** Runs the trader's free-form instructions through the `code_generation`
 * task's configured LLM (the same provider setting as the PDF-to-code
 * pipeline — see the Settings page) against this version's current code
 * and spec — or,
 * if `spec` is given, that edited spec instead, letting the trader tweak
 * symbols/timeframes/entry-exit rules before regenerating — then
 * sandbox-validates the result. Leave `newName` unset to save as the next
 * version of this version's own family; pass it to fork into a brand-new
 * family at version 1 instead (throws ApiError(409) if already in use). On
 * success `new_version_id` points at the new "validated" StrategyVersion;
 * on sandbox rejection `sandbox_errors` explains why and no version is
 * created — the caller can still show `code` for manual fixup via
 * `editStrategyVersionCode`. */
export const regenerateStrategyVersionCode = (
  id: string,
  instructions: string,
  spec?: ExtractedStrategySpec,
  newName?: string,
) =>
  api.post<RegeneratedCode>(`/ai/strategies/versions/${encodeURIComponent(id)}/regenerate`, {
    instructions,
    spec,
    new_name: newName,
  });

export interface CustomSignal {
  time: number;
  direction: "buy" | "sell";
  sl_points: number;
  tp_points: number;
  confidence: number;
  reason: string;
}

export interface EvaluateCustomCodeResponse {
  signals: CustomSignal[];
  indicators: Record<string, (number | null)[]>;
  candles: {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
    tick_volume: number;
  }[];
  error: string | null;
}

export const evaluateCustomCode = (body: {
  code: string;
  symbol: string;
  timeframe: string;
  period: string;
}) => api.post<EvaluateCustomCodeResponse>("/strategies/evaluate-custom", body);

// ── Custom indicators (sandboxed Python, independent of the chart's ────────
// ── built-in client-side indicators) ────────────────────────────────────────

export interface IndicatorSummary {
  id: string;
  name: string;
  code_hash: string;
  default_params: Record<string, number>;
  created_at: number; // epoch seconds UTC
  updated_at: number; // epoch seconds UTC
}

export interface IndicatorDetail extends IndicatorSummary {
  code: string;
}

export interface ComputeIndicatorResponse {
  times: number[];
  series: Record<string, (number | null)[]>;
  error: string | null;
}

export const listIndicators = () => api.get<IndicatorSummary[]>("/indicators");
export const getIndicator = (id: string) =>
  api.get<IndicatorDetail>(`/indicators/${encodeURIComponent(id)}`);
/** Sandbox-validates `code` and, if it passes, saves a new indicator that
 * immediately shows up in the chart's indicator picker. Throws
 * ApiError(409) if `name` is already in use, ApiError(422) on sandbox
 * rejection. */
export const createIndicator = (body: {
  name: string;
  code: string;
  default_params?: Record<string, number>;
}) => api.post<IndicatorDetail>("/indicators", body);
/** Re-validates `code` and, if it passes, updates this indicator's row in
 * place — no version history, since indicators never trade live. Every
 * chart currently using it picks up the new code on its next compute. */
export const editIndicatorCode = (
  id: string,
  code: string,
  defaultParams?: Record<string, number>,
) =>
  api.post<IndicatorDetail>(`/indicators/${encodeURIComponent(id)}/edit`, {
    code,
    default_params: defaultParams,
  });
/** Clones this indicator's code and default params into a brand-new row.
 * Throws ApiError(409) if `name` is already in use. */
export const duplicateIndicator = (id: string, name: string) =>
  api.post<IndicatorDetail>(`/indicators/${encodeURIComponent(id)}/duplicate`, { name });
export const deleteIndicator = (id: string) =>
  api.delete<void>(`/indicators/${encodeURIComponent(id)}`);
/** Computes a saved indicator against real candle history for the chart.
 * `period` is "YYYY-MM:YYYY-MM". Sandbox/history/runtime failures come back
 * as `error` in the response body, not an HTTP error. */
export const computeIndicator = (
  id: string,
  body: { symbol: string; timeframe: string; period: string; params?: Record<string, number> },
) => api.post<ComputeIndicatorResponse>(`/indicators/${encodeURIComponent(id)}/compute`, body);
/** Same as computeIndicator, but for ad-hoc code that hasn't been saved yet
 * — nothing is persisted. Used by the create/edit UI's Preview button. */
export const previewIndicatorCode = (body: {
  code: string;
  params?: Record<string, number>;
  symbol: string;
  timeframe: string;
  period: string;
}) => api.post<ComputeIndicatorResponse>("/indicators/preview", body);

// ── Symbol -> strategy routing (§6.6) ───────────────────────────────────────

export interface SessionWindowWire {
  start: string; // HH:MM
  end: string; // HH:MM
}

/** JSON-scalar value a strategy param can hold — mirrors the backend's
 * `dict[str, float | int | str | bool]`. */
export type ParamValue = number | string | boolean;

export interface NormalSkillAssignment {
  name: string;
  /** This bot's short id on its symbol (the last segment of `name`) — the
   * path segment used by updateBotAssignment/removeBotFromSymbol. */
  bot_name: string;
  symbol: string;
  strategy: string;
  risk_multiplier: number;
  sessions: SessionWindowWire[];
  /** Per-bot overrides of this strategy's tunable params, keyed by param
   * name — only explicitly overridden keys appear here; every other param
   * runs at its `strategy_default_params` value. Set via updateBotConfig. */
  param_overrides: Record<string, ParamValue>;
  /** Per-bot override of the engine's HTF veto. `null` means this bot
   * inherits `strategy_default_htf_veto`. */
  htf_veto_override: boolean | null;
  /** This bot's strategy's own declared param defaults (its registered
   * StrategySpec.params) — the base every key in `param_overrides` layers
   * on top of. Empty if the strategy isn't currently registered (paused). */
  strategy_default_params: Record<string, ParamValue>;
  /** This bot's strategy's own declared StrategySpec.htf_veto — the base
   * `htf_veto_override` layers on top of. */
  strategy_default_htf_veto: boolean;
  /** True only on the addBotToSymbol response when that call just
   * activated a previously-inactive symbol for live automated trading
   * (persisted to configs/app.yaml, hot-added to candle streaming and the
   * spread gate). Always false in getSkillAssignments()'s list — a listing
   * isn't an action outcome. */
  newly_activated: boolean;
}

/** Every bot currently routed for live trading, on every symbol — the real
 * "which bots trade this symbol live" state (`TradeEngine._try_enter` reads
 * this via `SkillSelector`), distinct from a version's `spec.symbols`
 * membership. A symbol may appear multiple times, once per active bot.
 * Includes any bot activated at runtime via `addBotToSymbol`, not just bots
 * configured at backend startup. */
export const getSkillAssignments = () => api.get<NormalSkillAssignment[]>("/skills/normal");

/** Activates a new bot on `symbol`, alongside any bots already routed there
 * — never replaces one (see `updateBotAssignment` to reassign an existing
 * bot instead). Writes skills/normal/<symbol>/<bot_name>.yaml and hot-swaps
 * the live SkillSelector, no restart needed. If `symbol` isn't yet
 * live-traded, this is also the action that activates it: persists it into
 * configs/app.yaml and hot-adds it to candle streaming/the spread gate (see
 * the response's `newly_activated`). `strategyName` must currently have an
 * active, non-paused StrategyVersion (422 otherwise); 404 if `symbol` has no
 * configs/symbols/<symbol>.yaml; 409 if `botName` is already taken on this
 * symbol. */
export const addBotToSymbol = (symbol: string, strategyName: string, botName?: string) =>
  api.post<NormalSkillAssignment>(`/skills/normal/${encodeURIComponent(symbol)}/bots`, {
    strategy_name: strategyName,
    bot_name: botName,
  });

/** Reassigns `botName`'s strategy on `symbol` in place, keeping its
 * sessions/risk_multiplier and leaving every other bot on the symbol
 * untouched — hot-swaps the live SkillSelector, no restart needed. */
export const updateBotAssignment = (symbol: string, botName: string, strategyName: string) =>
  api.put<NormalSkillAssignment>(
    `/skills/normal/${encodeURIComponent(symbol)}/bots/${encodeURIComponent(botName)}`,
    { strategy_name: strategyName },
  );

/** Replaces `botName`'s risk_multiplier, sessions, and per-bot strategy
 * param/htf_veto overrides in one call — every field is a full replacement,
 * not a partial patch. Doesn't change which strategy family the bot trades
 * (see `updateBotAssignment`) — reassigning strategy resets overrides
 * server-side, since they may not apply to the new strategy's params. */
export const updateBotConfig = (
  symbol: string,
  botName: string,
  config: {
    risk_multiplier: number;
    sessions: SessionWindowWire[];
    param_overrides: Record<string, ParamValue>;
    htf_veto_override: boolean | null;
  },
) =>
  api.put<NormalSkillAssignment>(
    `/skills/normal/${encodeURIComponent(symbol)}/bots/${encodeURIComponent(botName)}/config`,
    config,
  );

/** Stops `botName` from trading `symbol` — every other bot on the symbol
 * keeps trading unaffected. */
export const removeBotFromSymbol = (symbol: string, botName: string) =>
  api.delete<void>(
    `/skills/normal/${encodeURIComponent(symbol)}/bots/${encodeURIComponent(botName)}`,
  );

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
  forecast: string | null; // consensus estimate, formatted as the source publishes it
  previous: string | null; // prior period's reading
  actual: string | null; // released value, once the event has happened (source-dependent)
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

// ── Engine: status + kill switch (Phase 9, §11) ─────────────────────────────

export interface EngineStatus {
  enabled: boolean;
  paused: boolean;
  pause_reason: string;
  consecutive_losses: number;
  trades_today: number;
  daily_pnl: number;
}

export const getEngineStatus = () => api.get<EngineStatus>("/engine/status");
export const killSwitch = () => api.post<EngineStatus>("/engine/kill");
export const resumeEngine = () => api.post<EngineStatus>("/engine/resume");

export interface RiskCaps {
  risk_per_trade_pct: number;
  daily_loss_limit_pct: number;
  max_open_positions: number;
  max_trades_per_day: number;
  consecutive_loss_pause: number;
  /** When true, a balance too small for risk_per_trade_pct to reach the broker's
   * minimum lot trades that minimum lot anyway, capped by max_risk_per_trade_pct. */
  min_lot_fallback_enabled: boolean;
  max_risk_per_trade_pct: number | null;
}

export const getRiskCaps = () => api.get<RiskCaps>("/engine/risk-caps");
/** Live-updates the min-lot fallback on the running engine. Not persisted —
 * a backend restart reverts to configs/risk.yaml. */
export const putMinLotFallback = (enabled: boolean, maxRiskPerTradePct: number | null) =>
  api.put<RiskCaps>("/engine/risk-caps/min-lot-fallback", {
    enabled,
    max_risk_per_trade_pct: maxRiskPerTradePct,
  });

// ── Broker: manual trading (chart buttons, click-to-trade, draggable SL/TP) ─

export type OrderSide = "buy" | "sell";
export type PendingOrderType = "limit" | "stop";

export interface OpenOrderRequest {
  symbol: string;
  side: OrderSide;
  volume: number;
  sl?: number | null;
  tp?: number | null;
  comment?: string;
}

export interface ExecutionResultOut {
  ticket: number;
  symbol: string;
  side: OrderSide;
  volume: number;
  price: number;
  sl: number | null;
  tp: number | null;
  time: string;
  spread_points: number;
  comment: string;
  profit: number | null;
}

export interface PositionOut {
  ticket: number;
  symbol: string;
  side: OrderSide;
  volume: number;
  open_price: number;
  sl: number | null;
  tp: number | null;
  open_time: string;
  profit: number;
  comment: string;
}

export interface PlacePendingOrderRequest {
  symbol: string;
  side: OrderSide;
  order_type: PendingOrderType;
  volume: number;
  price: number;
  sl?: number | null;
  tp?: number | null;
  comment?: string;
}

export interface PendingOrderOut {
  ticket: number;
  symbol: string;
  side: OrderSide;
  order_type: PendingOrderType;
  volume: number;
  price: number;
  sl: number | null;
  tp: number | null;
  placed_time: string;
  comment: string;
}

export const openOrder = (body: OpenOrderRequest) =>
  api.post<ExecutionResultOut>("/broker/orders", body);
export const closePosition = (ticket: number, volume?: number) =>
  api.post<ExecutionResultOut>(`/broker/positions/${ticket}/close`, volume ? { volume } : undefined);
export const closeAllPositions = (symbol: string) =>
  api.post<ExecutionResultOut[]>(
    `/broker/positions/close-all?symbol=${encodeURIComponent(symbol)}`,
    undefined,
  );
export const modifyPosition = (ticket: number, sl: number | null, tp: number | null) =>
  api.post<{ status: string }>(`/broker/positions/${ticket}/modify`, { sl, tp });
export const getPositions = (symbol?: string) =>
  api.get<PositionOut[]>(`/broker/positions${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`);

export const placePendingOrder = (body: PlacePendingOrderRequest) =>
  api.post<PendingOrderOut>("/broker/orders/pending", body);
export const getPendingOrders = (symbol?: string) =>
  api.get<PendingOrderOut[]>(
    `/broker/orders/pending${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""}`,
  );
export const modifyPendingOrder = (
  ticket: number,
  price: number | null,
  sl: number | null,
  tp: number | null,
) => api.post<{ status: string }>(`/broker/orders/pending/${ticket}/modify`, { price, sl, tp });
export const cancelPendingOrder = (ticket: number) =>
  api.delete<{ status: string }>(`/broker/orders/pending/${ticket}`);

export interface SymbolSpreadConfig {
  symbol: string;
  max_spread_points: number;
  /** Minimum spread-adjusted reward:risk ratio required to open —
   * tp_distance >= min_rr * (sl_distance + spread_value). */
  min_rr: number;
}

export const getSymbolSpreadConfig = (symbol: string) =>
  api.get<SymbolSpreadConfig>(`/broker/symbols/${encodeURIComponent(symbol)}/spread-config`);
/** Live-updates min_rr on the running engine. Not persisted — a backend
 * restart reverts to configs/symbols/<symbol>.yaml. */
export const putSymbolMinRr = (symbol: string, minRr: number) =>
  api.put<SymbolSpreadConfig>(`/broker/symbols/${encodeURIComponent(symbol)}/min-rr`, {
    min_rr: minRr,
  });

// ── AI: provider settings (per-task LLM selection, Phase 10.4) ─────────────
export interface TaskProviderStatus {
  task: string;
  provider: string;
  model: string;
  source: "override" | "default";
  configured: boolean;
}

export interface ProviderPresetModel {
  label: string;
  model: string;
}

export interface ProviderInfo {
  id: string;
  label: string;
  description: string;
  needsSecret: boolean;
  configured: boolean;
  presetModels?: ProviderPresetModel[];
}

export interface ProviderTestResult {
  provider: string;
  ok: boolean;
  message: string | null;
  reply: string | null;
}

export const listTaskProviders = () => api.get<TaskProviderStatus[]>("/ai/settings/tasks");
export const setTaskProvider = (task: string, provider: string, model: string) =>
  api.put<TaskProviderStatus>(`/ai/settings/tasks/${task}`, { provider, model });
export const clearTaskProvider = (task: string) =>
  api.delete<TaskProviderStatus>(`/ai/settings/tasks/${task}`);
export const testProvider = (provider: string, message?: string) =>
  api.post<ProviderTestResult>(
    `/ai/settings/providers/${provider}/test`,
    message ? { message } : undefined,
  );
interface ProviderInfoRaw {
  id: string;
  label: string;
  description: string;
  needs_secret: boolean;
  configured: boolean;
  preset_models: ProviderPresetModel[] | null;
}

function fromRawProviderInfo(p: ProviderInfoRaw): ProviderInfo {
  return {
    id: p.id,
    label: p.label,
    description: p.description,
    needsSecret: p.needs_secret,
    configured: p.configured,
    presetModels: p.preset_models ?? undefined,
  };
}

export const listProviders = () =>
  api.get<ProviderInfoRaw[]>("/ai/settings/providers").then((raw) => raw.map(fromRawProviderInfo));

/** Saves `provider`'s API key, encrypted at rest — takes effect immediately,
 * no backend restart. The key is never returned by this or any other call. */
export const setProviderKey = (provider: string, apiKey: string) =>
  api
    .put<ProviderInfoRaw>(`/ai/settings/providers/${provider}/key`, { api_key: apiKey })
    .then(fromRawProviderInfo);

export const clearProviderKey = (provider: string) =>
  api.delete<ProviderInfoRaw>(`/ai/settings/providers/${provider}/key`).then(fromRawProviderInfo);
