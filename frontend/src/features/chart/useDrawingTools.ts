'use client';

/**
 * Drawing-tools state (§F-draw): the currently-selected tool, the
 * anchor-collection workflow that turns clicks into a finished `IDrawing`,
 * the drawings-list panel's mirror state, active-color selection, and the
 * two drawing-specific popovers (`DrawingContextMenu`/`DrawingEditPopover`)
 * plus the outside-click effect that closes them. That outside-click effect
 * completes phase 5's TODO — see `useOrderPopovers.ts`'s module doc, which
 * left this exact half of the old combined outside-click effect in
 * ChartPanel.tsx specifically for this hook to absorb once it existed.
 *
 * Ownership split — and why this hook doesn't own *every* piece of this
 * concern's state: most of it (`drawingTool`/`drawingsList`/`activeColor`/
 * `drawingContextMenu`/`drawingEditPopover`, plus `originalStylesRef`/
 * `saveAndSyncRef`/`isSwitchingSymbolRef`) is also read or written directly
 * inside `useChartEngine`'s one-time `[]` chart-creation effect —
 * highlight/select/save-and-sync, the drag-to-move-a-drawing handler, and
 * the right-click router between drawing/order popovers (see
 * `useChartEngine.ts`'s module doc, which deliberately keeps that wiring in
 * one effect to avoid a setup/teardown gap — a real risk, not a style
 * preference). `useChartEngine` runs *before* this hook (it produces
 * `chartController`, which this hook needs as an input), so those specific
 * pieces of state must already exist as real `useState`/`useRef` values by
 * the time `useChartEngine(...)` is called — a hook invoked afterward can't
 * retroactively supply them. ChartPanel.tsx therefore still creates exactly
 * those primitives (unchanged from before this phase) and passes them in
 * here as controlled inputs; this hook creates and owns everything that has
 * no such ordering constraint — `showDrawingsList`, `pendingAnchorCount`,
 * `activeColorRef` (a pure internal cache, nothing outside this hook's own
 * effect ever read it), and — per the "prefer owning refs nothing else
 * needs directly" call — `drawingContextMenuRef`/`drawingEditPopoverRef`,
 * previously created in ChartPanel.tsx but only ever consumed by this
 * hook's outside-click effect and the JSX `ref=` props this hook's return
 * value now feeds directly.
 *
 * Not owned here (left in ChartPanel.tsx, drawing-manager-adjacent but a
 * different concern): the live trade-markers poll and the backtest-report
 * trade-drawing effect both add/remove drawings via
 * `chartController.getDrawingManager()`, but what they draw
 * (`LIVE_TRADE_DRAWING_PREFIX`/`BACKTEST_DRAWING_PREFIX` zone/SL/TP/exit
 * lines) is trade-history rendering, not user-drawn shapes — same
 * "not this concern" call `useIndicators.ts` already made for the
 * strategy-derived price-level drawings it adds. They're `useBacktestData`/
 * `chartMarkers.ts` territory for a later phase, not this one. Likewise the
 * right-click routing between `ChartContextMenu`/`DrawingContextMenu` stays
 * in `useChartEngine`'s init effect (see its module doc) — this hook's
 * pieces just need to keep calling the setters that routing already uses.
 */

import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react';
import { type MouseEventParams, type UTCTimestamp } from 'lightweight-charts';
import { type IDrawing } from 'lightweight-charts-drawing';
import { createDrawingInstance } from './chartMarkers';
import { hexToRgba, REQUIRED_ANCHORS } from './chartFormat';
import { clearUserDrawings, loadDrawingsFromStorage } from './chartStorage';
import type { ChartEngineController, DrawingToolType } from './types';

/** Shared shape of the drawing-tools' own context-menu/edit-popover state —
 * populated by `useChartEngine`'s right-click router (its `setXxx` calls),
 * consumed here for the outside-click effect and passed through to JSX. */
export interface DrawingMenuState {
  x: number;
  y: number;
  drawingId: string;
  drawingType: string;
  containerWidth: number;
  containerHeight: number;
}

export interface UseDrawingToolsParams {
  chartController: ChartEngineController;
  symbol: string;
  /** See the module doc: created in ChartPanel.tsx (not here) because
   * `useChartEngine`'s init effect needs `setDrawingTool` before this hook
   * can exist. */
  drawingTool: DrawingToolType | null;
  setDrawingTool: Dispatch<SetStateAction<DrawingToolType | null>>;
  drawingsList: IDrawing[];
  setDrawingsList: Dispatch<SetStateAction<IDrawing[]>>;
  activeColor: string;
  setActiveColor: Dispatch<SetStateAction<string>>;
  drawingContextMenu: DrawingMenuState | null;
  setDrawingContextMenu: Dispatch<SetStateAction<DrawingMenuState | null>>;
  drawingEditPopover: DrawingMenuState | null;
  setDrawingEditPopover: Dispatch<SetStateAction<DrawingMenuState | null>>;
  originalStylesRef: RefObject<Record<string, any>>;
  saveAndSyncRef: RefObject<() => void>;
  /** Set true/false around the symbol-switch clear+reload below so
   * `useChartEngine`'s `saveAndSync` skips persisting to localStorage mid-
   * switch (see that hook's module doc / this hook's symbol-switch effect).
   * Created in ChartPanel.tsx for the same ordering reason as the state
   * above. */
  isSwitchingSymbolRef: RefObject<boolean>;
}

export function useDrawingTools(params: UseDrawingToolsParams) {
  const {
    chartController,
    symbol,
    drawingTool,
    setDrawingTool,
    drawingsList,
    setDrawingsList,
    activeColor,
    setActiveColor,
    drawingContextMenu,
    setDrawingContextMenu,
    drawingEditPopover,
    setDrawingEditPopover,
    originalStylesRef,
    saveAndSyncRef,
    isSwitchingSymbolRef,
  } = params;

  // DrawingsList panel toggle + how many more clicks the in-progress drawing
  // needs — both purely local UI state, no ordering conflict with
  // useChartEngine, so owned outright here.
  const [showDrawingsList, setShowDrawingsList] = useState(false);
  const [pendingAnchorCount, setPendingAnchorCount] = useState(0);

  // Root-element refs for this hook's two popover/menu components, scoped
  // per instance rather than a fixed global DOM id — the outside-click
  // effect below checks these instead of `document.getElementById(...)`, so
  // multiple ChartPanel instances on the same page (planned) won't collide.
  // The order-popover pair's own refs live in useOrderPopovers.
  const drawingContextMenuRef = useRef<HTMLDivElement>(null);
  const drawingEditPopoverRef = useRef<HTMLDivElement>(null);

  // Fresh-read cache for the chosen color inside the anchor-collection
  // effect below (mousemove fires far more often than a re-render should
  // need to happen) — nothing outside this hook ever reads it, so unlike
  // the other pieces in the module doc it's created fresh here instead of
  // received from ChartPanel.tsx.
  const activeColorRef = useRef(activeColor);
  activeColorRef.current = activeColor;

  // When the symbol changes, save the current symbol's drawings and load the
  // new symbol's drawings. The chart-creation effect (useChartEngine) only
  // handles the initial symbol; this effect keeps things in sync on
  // subsequent symbol switches.
  useEffect(() => {
    const manager = chartController.getDrawingManager();
    if (!manager) return;
    isSwitchingSymbolRef.current = true;
    clearUserDrawings(manager);
    loadDrawingsFromStorage(manager, symbol);
    isSwitchingSymbolRef.current = false;
    // chartController/isSwitchingSymbolRef are stable ref-bearing objects —
    // omitted deliberately, same as every other effect in this file (and
    // ChartPanel.tsx) that reads them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  // Interactive drawing placement.
  //
  // DrawingManager.setActiveTool() is a stub in v0.1.1 — its handleClick
  // does nothing when a tool is active. We implement the anchor-collection
  // workflow ourselves:
  //   1. Disable chart panning so mouse events reach our handler.
  //   2. Subscribe to chart.subscribeClick to collect price+time anchors.
  //   3. Once the required number of anchors is placed, instantiate the
  //      concrete Drawing subclass and hand it to the manager.
  //
  // Required anchor counts per tool:
  //   1 anchor : horizontal-line, vertical-line
  //   2 anchors: trend-line, extended-line, rectangle, fib-retracement, circle
  //   3 anchors: parallel-channel
  useEffect(() => {
    const manager = chartController.getDrawingManager();
    const chart = chartController.getChart();
    const container = chartController.containerRef.current;
    if (!chart) return;

    if (!drawingTool) {
      chart.applyOptions({ handleScroll: true, handleScale: true });
      if (container) container.style.cursor = '';
      setPendingAnchorCount(0);
      return;
    }

    // Freeze chart interaction so clicks are not consumed as pans.
    chart.applyOptions({ handleScroll: false, handleScale: false });
    if (container) container.style.cursor = 'crosshair';

    const REQUIRED: Record<DrawingToolType, number> = REQUIRED_ANCHORS;

    const required = REQUIRED[drawingTool];
    // Mutable accumulator — not React state because we don't need a re-render
    // for each click, only when the drawing is complete.
    const pendingAnchors: Array<{ price: number; time: UTCTimestamp }> = [];

    const handleClick = (param: MouseEventParams) => {
      if (!param.point) return;
      const candleSeries = chartController.getCandleSeries();
      if (!candleSeries || !manager) return;

      const time = chart.timeScale().coordinateToTime(param.point.x);
      const price = candleSeries.coordinateToPrice(param.point.y);
      if (time === null || price === null) return;

      pendingAnchors.push({ price, time: time as UTCTimestamp });
      setPendingAnchorCount(pendingAnchors.length);

      if (pendingAnchors.length < required) {
        // Update the preview anchors immediately so it uses the newly clicked point
        const filledAnchors = [...pendingAnchors];
        while (filledAnchors.length < required) {
          filledAnchors.push({ price, time: time as UTCTimestamp });
        }
        try {
          const existing = manager.getDrawing('drawing-preview');
          if (existing) {
            existing.setAnchors(filledAnchors);
            existing.requestUpdate();
          }
        } catch (err) {
          console.warn('Failed to update preview on click:', err);
        }
        return; // wait for more clicks
      }

      // All anchors collected — remove preview first
      if (manager.getDrawing('drawing-preview')) {
        try {
          manager.removeDrawing('drawing-preview');
        } catch (e) {
          console.warn(e);
        }
      }

      // All anchors collected — create and register the drawing.
      const id = `d-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const chosenColor = activeColorRef.current;
      const style = {
        lineColor: chosenColor,
        lineWidth: 2,
        showLabels: true,
        labelColor: chosenColor,
        fillColor: hexToRgba(chosenColor, 0.15),
      };

      const drawing = createDrawingInstance(drawingTool, id, pendingAnchors, style);
      if (drawing) manager.addDrawing(drawing);

      // Reset — the drawing:added listener (in useChartEngine's
      // chart-creation effect) handles saving + updating the list panel.
      setDrawingTool(null);
      setPendingAnchorCount(0);
    };

    const handleMouseMove = (param: MouseEventParams) => {
      if (!manager) return;
      const candleSeries = chartController.getCandleSeries();
      if (!candleSeries) return;

      if (!param.point) return;

      const time = chart.timeScale().coordinateToTime(param.point.x);
      const price = candleSeries.coordinateToPrice(param.point.y);
      if (time === null || price === null) return;

      const hoverAnchor = { price, time: time as UTCTimestamp };

      // For tools requiring more than 1 anchor: we only start showing drawing progress
      // AFTER the first anchor has been placed.
      if (pendingAnchors.length === 0 && required > 1) {
        if (manager.getDrawing('drawing-preview')) {
          try {
            manager.removeDrawing('drawing-preview');
          } catch (e) {
            console.warn(e);
          }
        }
        return;
      }

      const filledAnchors = [...pendingAnchors];
      while (filledAnchors.length < required) {
        filledAnchors.push(hoverAnchor);
      }

      const chosenColor = activeColorRef.current;
      const previewStyle = {
        lineColor: chosenColor,
        lineWidth: 2,
        lineDash: [4, 4], // dotted line for preview
        showLabels: false, // hide labels for cleaner preview
        labelColor: chosenColor,
        fillColor: hexToRgba(chosenColor, 0.1),
      };

      try {
        const existing = manager.getDrawing('drawing-preview');
        if (existing) {
          existing.setAnchors(filledAnchors);
          existing.requestUpdate();
        } else {
          const previewDrawing = createDrawingInstance(
            drawingTool,
            'drawing-preview',
            filledAnchors,
            previewStyle,
          );
          if (previewDrawing) {
            manager.addDrawing(previewDrawing);
          }
        }
      } catch (err) {
        console.warn('Failed to update/create preview drawing:', err);
      }
    };

    chart.subscribeClick(handleClick);
    chart.subscribeCrosshairMove(handleMouseMove);

    return () => {
      chart.unsubscribeClick(handleClick);
      chart.unsubscribeCrosshairMove(handleMouseMove);
      chart.applyOptions({ handleScroll: true, handleScale: true });
      if (container) container.style.cursor = '';
      setPendingAnchorCount(0);
      if (manager && manager.getDrawing('drawing-preview')) {
        try {
          manager.removeDrawing('drawing-preview');
        } catch (e) {
          console.warn(e);
        }
      }
    };
    // chartController is a stable object returned from useChartEngine —
    // omitted deliberately, same as every other effect in this file that
    // reads it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingTool]);

  // Close the drawing-tools context menu / edit popover on click outside.
  // The matching effect for `contextMenu`/`orderPopover` lives in
  // useOrderPopovers — the two pairs are opened mutually exclusively by
  // useChartEngine's `contextmenu` handler, so splitting the single
  // combined effect this way (each half only checking its own two refs) is
  // behaviorally identical to the original pre-split effect.
  useEffect(() => {
    if (!drawingContextMenu && !drawingEditPopover) return;
    const handleMouseDownOutside = (e: MouseEvent) => {
      const drawingMenuEl = drawingContextMenuRef.current;
      const drawingPopoverEl = drawingEditPopoverRef.current;
      if (
        (drawingMenuEl && drawingMenuEl.contains(e.target as Node)) ||
        (drawingPopoverEl && drawingPopoverEl.contains(e.target as Node))
      ) {
        return;
      }
      setDrawingContextMenu(null);
      setDrawingEditPopover(null);
    };
    window.addEventListener('mousedown', handleMouseDownOutside);
    return () =>
      window.removeEventListener('mousedown', handleMouseDownOutside);
  }, [drawingContextMenu, drawingEditPopover, setDrawingContextMenu, setDrawingEditPopover]);

  function handleColorChange(newColor: string) {
    setActiveColor(newColor);

    // If a drawing is currently selected, update its style immediately
    const manager = chartController.getDrawingManager();
    if (manager) {
      const selected = manager.getSelectedDrawing();
      if (selected) {
        if (originalStylesRef.current[selected.id]) {
          originalStylesRef.current[selected.id].lineColor = newColor;
          originalStylesRef.current[selected.id].labelColor = newColor;
          originalStylesRef.current[selected.id].fillColor = hexToRgba(
            newColor,
            0.15,
          );
        }

        selected.updateStyle({
          lineColor: newColor,
          labelColor: newColor,
          fillColor: hexToRgba(newColor, 0.25),
          lineWidth: 4,
        });

        saveAndSyncRef.current();
      }
    }
  }

  function handleModifyDrawingColor(id: string, newColor: string) {
    const manager = chartController.getDrawingManager();
    if (manager) {
      const d = manager.getDrawing(id);
      if (d) {
        if (originalStylesRef.current[id]) {
          originalStylesRef.current[id].lineColor = newColor;
          originalStylesRef.current[id].labelColor = newColor;
          originalStylesRef.current[id].fillColor = hexToRgba(newColor, 0.15);

          d.updateStyle({
            lineColor: newColor,
            labelColor: newColor,
            fillColor: hexToRgba(newColor, 0.25),
            lineWidth: 4,
          });
        } else {
          d.updateStyle({
            lineColor: newColor,
            labelColor: newColor,
            fillColor: hexToRgba(newColor, 0.15),
          });
        }

        // If the modified drawing is the currently selected one, sync activeColor
        const selected = manager.getSelectedDrawing();
        if (selected && selected.id === id) {
          setActiveColor(newColor);
        }

        saveAndSyncRef.current();
      }
    }
  }

  function removeDrawing(id: string) {
    chartController.getDrawingManager()?.removeDrawing(id);
  }

  function toggleDrawingVisible(id: string) {
    const manager = chartController.getDrawingManager();
    const d = manager?.getDrawing(id);
    if (!manager || !d) return;
    d.updateOptions({ visible: !d.options.visible });
    try {
      const data = manager.exportDrawings();
      localStorage.setItem(`chart-drawings:${symbol}`, JSON.stringify(data));
    } catch {
      // localStorage quota or serialisation errors are non-fatal.
    }
    setDrawingsList(manager.getAllDrawings());
  }

  function clearAllDrawings() {
    const manager = chartController.getDrawingManager();
    if (manager) clearUserDrawings(manager);
  }

  return {
    // Passed through from ChartPanel.tsx (see module doc for why these are
    // received rather than created here) — re-exported so JSX has a single
    // `drawingTools.*` surface for everything this concern owns.
    drawingTool,
    setDrawingTool,
    drawingsList,
    activeColor,
    drawingContextMenu,
    setDrawingContextMenu,
    drawingEditPopover,
    setDrawingEditPopover,
    originalStylesRef,
    saveAndSyncRef,

    // Owned here.
    showDrawingsList,
    setShowDrawingsList,
    pendingAnchorCount,
    drawingContextMenuRef,
    drawingEditPopoverRef,

    // Handlers.
    handleColorChange,
    handleModifyDrawingColor,
    removeDrawing,
    toggleDrawingVisible,
    clearAllDrawings,
  };
}

export type DrawingTools = ReturnType<typeof useDrawingTools>;
