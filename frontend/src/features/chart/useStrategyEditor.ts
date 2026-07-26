"use client";

/**
 * UI/editor-drawer state for the two slide-in code drawers ChartPanel
 * renders while in backtest view: the "Edit Strategy Code" drawer
 * (`showStrategyEditor`, shared `drawerPosition`) and the "Run Custom Code"
 * drawer (`showCustomCodeEditor`, the draft/result/busy/error/copied state
 * around it), plus the collapsed-by-default strategy info pills
 * (`strategyInfoExpanded`). Pure UI state — no chart-engine coupling; the
 * actual custom-code execution (`runCustomCode`/`clearCustomCode` in
 * ChartPanel.tsx) needs `recomputeIndicatorsRef`/`candlesRef` and stays
 * there.
 */

import { useEffect, useRef, useState } from "react";
import type { EvaluateCustomCodeResponse } from "@/shared/api/client";

export type DrawerPosition = "right" | "left" | "bottom" | "top";

const DEFAULT_CUSTOM_CODE_TEMPLATE = `import pandas as pd
from src.strategies.domain.models import Direction, MarketContext, Signal, StrategySpec

class CustomScriptStrategy:
    def __init__(self) -> None:
        self.spec = StrategySpec(
            name="custom_script",
            version=1,
            symbols=("XAUUSD", "Volatility 75 Index"),
            entry_timeframe="M5",
            confirmation_timeframes=(),
            params={}
        )

    def indicators(self, candles: dict[str, pd.DataFrame]) -> dict[str, list]:
        df = candles[self.spec.entry_timeframe]
        # Example: Calculate a 20-period Simple Moving Average (SMA)
        sma_20 = df["close"].rolling(20).mean()
        return {
            "SMA 20": sma_20.tolist()
        }

    def evaluate(self, ctx: MarketContext) -> Signal | None:
        df = ctx.candles[self.spec.entry_timeframe]
        if len(df) < 21:
            return None

        # Example logic: Close crosses above SMA 20
        close_prev = df["close"].iloc[-2]
        close_curr = df["close"].iloc[-1]

        # Calculate SMA 20 for previous and current bar
        sma_20 = df["close"].rolling(20).mean()
        sma_prev = sma_20.iloc[-2]
        sma_curr = sma_20.iloc[-1]

        if close_prev <= sma_prev and close_curr > sma_curr:
            return Signal(direction=Direction.BUY, sl_points=200, tp_points=400, reason="Cross above SMA 20")
        elif close_prev >= sma_prev and close_curr < sma_curr:
            return Signal(direction=Direction.SELL, sl_points=200, tp_points=400, reason="Cross below SMA 20")

        return None
`;

export function useStrategyEditor() {
  const [showStrategyEditor, setShowStrategyEditor] = useState(false);
  // Drawer position, shared by both the strategy-code and custom-code drawers.
  const [drawerPosition, setDrawerPosition] = useState<DrawerPosition>("right");
  // Whether the strategy info pills are expanded.
  const [strategyInfoExpanded, setStrategyInfoExpanded] = useState(false);

  const [showCustomCodeEditor, setShowCustomCodeEditor] = useState(false);
  const [customCodeDraft, setCustomCodeDraft] = useState(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("chart-custom-script-code");
      if (saved) return saved;
    }
    return DEFAULT_CUSTOM_CODE_TEMPLATE;
  });
  const [customCodeResult, setCustomCodeResult] =
    useState<EvaluateCustomCodeResponse | null>(null);
  // Imperative mirror of customCodeResult, read fresh inside ChartPanel's
  // recomputeIndicators closure (created once per data-load, not re-created
  // on every state update) the same way other *Ref mirrors there work.
  const customCodeResultRef = useRef<EvaluateCustomCodeResponse | null>(null);
  customCodeResultRef.current = customCodeResult;
  const [customCodeBusy, setCustomCodeBusy] = useState(false);
  const [customCodeError, setCustomCodeError] = useState<string | null>(null);
  const [customCodeCopied, setCustomCodeCopied] = useState(false);

  const handleCopyCustomCode = () => {
    navigator.clipboard.writeText(customCodeDraft);
    setCustomCodeCopied(true);
    setTimeout(() => setCustomCodeCopied(false), 2000);
  };

  useEffect(() => {
    try {
      localStorage.setItem("chart-custom-script-code", customCodeDraft);
    } catch {}
  }, [customCodeDraft]);

  return {
    showStrategyEditor,
    setShowStrategyEditor,
    drawerPosition,
    setDrawerPosition,
    strategyInfoExpanded,
    setStrategyInfoExpanded,
    showCustomCodeEditor,
    setShowCustomCodeEditor,
    customCodeDraft,
    setCustomCodeDraft,
    customCodeResult,
    setCustomCodeResult,
    customCodeResultRef,
    customCodeBusy,
    setCustomCodeBusy,
    customCodeError,
    setCustomCodeError,
    customCodeCopied,
    setCustomCodeCopied,
    handleCopyCustomCode,
  };
}

export type StrategyEditor = ReturnType<typeof useStrategyEditor>;
