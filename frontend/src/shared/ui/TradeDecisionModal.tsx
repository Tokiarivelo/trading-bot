"use client";

/**
 * "Why did the bot take this trade" detail — the full decision context
 * behind one journaled trade (reason, confidence, S&D zone, pattern,
 * swing structure), shown as a click-through modal from a table cell.
 * Shared by the Active Orders table (`AllOrdersPanel`) and the Trade
 * History table (`TradeHistoryTable`) so both read the same journal fields
 * the same way. Modeled on `EventDetailModal` in
 * `features/news/UpcomingEventsPanel.tsx`.
 */

import type { TradeHistoryItem } from "@/shared/api/client";

function formatFullTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

export function TradeDecisionModal({
  trade,
  onClose,
}: {
  trade: TradeHistoryItem;
  onClose: () => void;
}) {
  const hasDecisionContext =
    trade.reason !== "" ||
    trade.confidence !== null ||
    trade.zone !== null ||
    trade.pattern !== null ||
    trade.structure.length > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-md border border-line bg-panel p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <h3 className="text-sm font-bold">
            Why #{trade.id} — {trade.symbol}{" "}
            <span className={trade.side === "buy" ? "text-ok" : "text-err"}>{trade.side}</span>
          </h3>
          <button
            type="button"
            className="cursor-pointer text-ink-muted hover:text-ink"
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {!hasDecisionContext ? (
          <p className="text-sm text-ink-muted">
            Placed manually or via the API — no bot decision to explain.
          </p>
        ) : (
          <dl className="flex flex-col gap-2 text-sm">
            {trade.reason !== "" && (
              <Row label="Reason">
                <span className="whitespace-pre-wrap">{trade.reason}</span>
              </Row>
            )}
            {trade.confidence !== null && (
              <Row label="Confidence">{(trade.confidence * 100).toFixed(0)}%</Row>
            )}
            <Row label="Strategy">{trade.strategy_version ?? "—"}</Row>
            <Row label="Bot / skill">{trade.skill ?? "Manual"}</Row>
            {trade.pattern !== null && (
              <Row label="Confirming pattern">{trade.pattern.replace(/_/g, " ")}</Row>
            )}
            {trade.zone !== null && (
              <Row label="Supply/demand zone">
                <span className={trade.zone.kind === "demand" ? "text-ok" : "text-err"}>
                  {trade.zone.kind}
                </span>{" "}
                {trade.zone.price_low.toFixed(5)} – {trade.zone.price_high.toFixed(5)}
                <br />
                <span className="text-xs text-ink-muted">
                  {formatFullTime(trade.zone.time_start)} → {formatFullTime(trade.zone.time_end)}
                </span>
              </Row>
            )}
            {trade.structure.length > 0 && (
              <Row label="Swing structure">
                <ul className="flex flex-col gap-0.5">
                  {trade.structure.map((p, i) => (
                    <li key={i} className="text-xs">
                      <span className="font-medium">{p.label}</span> @ {p.price.toFixed(5)}{" "}
                      <span className="text-ink-muted">({formatFullTime(p.time)})</span>
                    </li>
                  ))}
                </ul>
              </Row>
            )}
          </dl>
        )}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-line pb-2 last:border-0 last:pb-0">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
