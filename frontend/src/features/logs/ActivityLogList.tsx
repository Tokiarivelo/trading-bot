"use client";

import { useEffect, useMemo, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import { ActivityLogFilters, EMPTY_FILTERS, type ActivityLogFilterState } from "./ActivityLogFilters";
import { ActivityLogTable } from "./ActivityLogTable";
import { PAGE_SIZE, useActivityLog } from "./useActivityLog";
import {
  ApiError,
  deleteActivityLogByFilter,
  deleteActivityLogByIds,
  type LogHistoryFilters,
} from "@/shared/api/client";

function toApiFilters(f: ActivityLogFilterState): Omit<LogHistoryFilters, "limit" | "offset"> {
  return {
    level: f.level || undefined,
    logger_contains: f.loggerContains || undefined,
    q: f.q || undefined,
  };
}

/** Activity log page: every backend module's persisted INFO+ log line —
 * signals, HTF vetoes, risk gate blocks, spread vetoes, fills, circuit
 * breakers — filterable by level/module/text and optionally live-polling
 * for a "what is the bot doing right now" view. */
export function ActivityLogList() {
  const accountId = useActiveAccount();
  const [filters, setFilters] = useState<ActivityLogFilterState>(EMPTY_FILTERS);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const apiFilters = useMemo(() => toApiFilters(filters), [filters]);
  const { items, total, error, page, setPage, refresh } = useActivityLog(apiFilters, autoRefresh);

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // The visible rows change under a fixed selection whenever filters, page,
  // or a delete refetch swap `items` out — stale ids in the selection would
  // silently apply to rows no longer on screen, so clear it whenever that happens.
  useEffect(() => {
    setSelectedIds(new Set());
  }, [items]);

  const hasNextPage = (page + 1) * PAGE_SIZE < total;

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll(checked: boolean) {
    setSelectedIds(checked ? new Set((items ?? []).map((e) => e.id)) : new Set());
  }

  async function runDelete(action: () => Promise<{ deleted: number }>) {
    setDeleteError(null);
    setIsDeleting(true);
    try {
      await action();
      refresh();
    } catch (e) {
      setDeleteError(e instanceof ApiError ? e.message : "failed to delete log entries");
    } finally {
      setIsDeleting(false);
    }
  }

  function handleDeleteOne(id: number) {
    if (!accountId) return;
    if (!window.confirm("Delete this log entry? This cannot be undone.")) return;
    void runDelete(() => deleteActivityLogByIds(accountId, [id]));
  }

  function handleDeleteSelected() {
    if (!accountId) return;
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    if (!window.confirm(`Delete ${ids.length} selected log entries? This cannot be undone.`)) return;
    void runDelete(() => deleteActivityLogByIds(accountId, ids));
  }

  function handleDeleteAllMatching() {
    if (!accountId) return;
    if (
      !window.confirm(
        `Delete all ${total} log entries matching the current filters? This cannot be undone.`
      )
    )
      return;
    void runDelete(() => deleteActivityLogByFilter(accountId, apiFilters));
  }

  return (
    <div className="flex flex-col">
      <ActivityLogFilters
        filters={filters}
        onChange={setFilters}
        autoRefresh={autoRefresh}
        onAutoRefreshChange={setAutoRefresh}
      />
      {!error && total > 0 && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2 text-xs text-ink-muted">
          {selectedIds.size > 0 && (
            <>
              <span>{selectedIds.size} selected</span>
              <button
                type="button"
                className="cursor-pointer rounded border border-line px-2 py-1 text-err hover:border-err disabled:cursor-not-allowed disabled:opacity-40"
                onClick={handleDeleteSelected}
                disabled={isDeleting}
              >
                Delete selected
              </button>
            </>
          )}
          <button
            type="button"
            className="cursor-pointer rounded border border-line px-2 py-1 text-err hover:border-err disabled:cursor-not-allowed disabled:opacity-40"
            onClick={handleDeleteAllMatching}
            disabled={isDeleting}
          >
            Delete all {total} matching
          </button>
        </div>
      )}
      {deleteError && <p className="px-4 pt-2 text-sm text-err">{deleteError}</p>}
      {error && <p className="p-4 text-sm text-err">{error}</p>}
      {!error && items === null && <p className="p-4 text-sm text-ink-muted">Loading…</p>}
      {!error && items !== null && items.length === 0 && (
        <p className="p-4 text-sm text-ink-muted">No log entries match these filters.</p>
      )}
      {!error && items !== null && items.length > 0 && (
        <ActivityLogTable
          entries={items}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelect}
          onToggleSelectAll={toggleSelectAll}
          onDeleteOne={handleDeleteOne}
        />
      )}
      {!error && total > 0 && (
        <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-ink-muted">
          <button
            type="button"
            className="cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            ← Prev
          </button>
          <span>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </span>
          <button
            type="button"
            className="cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => setPage((p) => (hasNextPage ? p + 1 : p))}
            disabled={!hasNextPage}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
