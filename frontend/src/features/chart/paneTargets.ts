/**
 * Pane-target resolution for manually-added indicators (IndicatorsDock).
 *
 * Every `ManualIndicator` carries an optional `paneTarget` saying which
 * "screen" (lightweight-charts pane) it should render on:
 *   - `'main'`         — the price pane (pane 0). Valid for every indicator
 *                        type, including oscillators (RSI/MACD/ATR/
 *                        Volatility) forced onto the main pane with their
 *                        own `priceScaleId` so they don't distort the
 *                        candle scale — the old overlay/scaleMargins trick,
 *                        now opt-in instead of automatic.
 *   - `{ paneKey }`    — a bottom pane, identified by a stable logical key
 *                        the caller manages (NOT a raw pane index, which
 *                        shifts as panes are added/removed). Two indicators
 *                        sharing the same `paneKey` render stacked in the
 *                        SAME real chart pane ("combine in same screen").
 *   - `undefined`      — legacy/default: overlay types (ema/sma/vwap/
 *                        bollinger/...) go to main, oscillator types each
 *                        get their own bottom pane keyed by their type name
 *                        (`legacy:<type>`) — matches the pre-existing
 *                        behavior so already-persisted indicators (saved
 *                        before this field existed) don't change position.
 *
 * `useIndicators.ts` resolves `paneKeyOf()` to a real `paneIndex` at render
 * time via a `paneKey -> paneIndex` map rebuilt every recompute (panes are
 * torn down and recreated wholesale each pass, same convention as
 * `indicatorSeriesRef`) — see `getOscillatorPane`/`getPaneForKey` there.
 * `IndicatorsDock.tsx` uses `listBottomPanes()` to offer existing panes as
 * reuse targets in its pane picker instead of only ever offering "new pane".
 *
 * Extension point: any future indicator type reads/writes `paneTarget`
 * through these helpers rather than hardcoding a new scaleMargins band or
 * an unconditional `chart.addPane()` call.
 */

import type { ManualIndicator, ManualIndicatorType } from './types';

export const OSCILLATOR_TYPES: ManualIndicatorType[] = ['rsi', 'macd', 'atr', 'volatility'];

export function isOscillatorType(type: ManualIndicatorType): boolean {
  return OSCILLATOR_TYPES.includes(type);
}

/** Resolves an indicator's `paneTarget` to a stable logical key: `'main'`
 * for the price pane, or a string key identifying a bottom pane. */
export function paneKeyOf(indicator: ManualIndicator): 'main' | string {
  if (indicator.paneTarget === 'main') return 'main';
  if (indicator.paneTarget && typeof indicator.paneTarget === 'object') {
    return indicator.paneTarget.paneKey;
  }
  return isOscillatorType(indicator.type) ? `legacy:${indicator.type}` : 'main';
}

export interface BottomPaneOption {
  key: string;
  label: string;
}

/** Every bottom-pane key currently occupied by at least one indicator in
 * `indicators`, first-seen order, labeled with the indicator(s) already
 * there — used by the pane picker to offer "combine into an existing
 * screen" targets instead of only "new split pane". */
export function listBottomPanes(indicators: ManualIndicator[]): BottomPaneOption[] {
  const panes = new Map<string, string[]>();
  for (const ind of indicators) {
    const key = paneKeyOf(ind);
    if (key === 'main') continue;
    const labels = panes.get(key) ?? [];
    labels.push(ind.label);
    panes.set(key, labels);
  }
  return Array.from(panes.entries()).map(([key, labels]) => ({
    key,
    label: labels.join(' + '),
  }));
}

/** Sentinel used by the pane picker for "create a brand-new split pane" —
 * resolved to a fresh `paneKey` (a `crypto.randomUUID()`) at add time so the
 * choice is fixed and persisted from then on, not re-resolved every render. */
export const NEW_PANE_OPTION = '__new_pane__';
export const MAIN_PANE_OPTION = 'main';
