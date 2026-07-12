"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  activateStrategyVersion,
  getStrategyVersion,
  type StrategyVersionDetail as VersionDetail,
} from "@/shared/api/client";
import { DuplicateVersionForm } from "./DuplicateVersionForm";
import { RenameVersionInline } from "./RenameVersionInline";
import { StatusBadge } from "./StatusBadge";

/** Full version detail: spec snapshot, source code, and the activate button
 * — which doubles as rollback when applied to an older version (§6.5). */
export function StrategyVersionDetail({ versionId }: { versionId: string }) {
  const [version, setVersion] = useState<VersionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    getStrategyVersion(versionId)
      .then(setVersion)
      .catch(() => setError("version not found"));
  }

  useEffect(load, [versionId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onActivate() {
    setBusy(true);
    setError(null);
    try {
      await activateStrategyVersion(versionId);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "activation failed");
    } finally {
      setBusy(false);
    }
  }

  if (error && version === null) return <p className="p-4 text-sm text-err">{error}</p>;
  if (version === null) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <Link href="/strategies" className="text-xs text-ink-muted hover:text-accent">
          ← All strategies
        </Link>
        <div className="mt-1 flex items-center gap-2">
          <h2 className="text-lg font-semibold">
            {version.name} · v{version.version}
          </h2>
          <RenameVersionInline versionId={version.id} name={version.name} onRenamed={load} />
          <StatusBadge status={version.status} />
        </div>
        <p className="text-sm text-ink-muted">
          {version.source === "ai_generated" ? "AI generated" : "Manual"} · {version.file_path}
        </p>
        <p className="text-xs text-ink-muted">
          Symbols are independent from configs/app.yaml — duplicating or retargeting a bot
          here never makes the engine trade it live; that's a separate, human-confirmed step.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <button
          className="cursor-pointer rounded border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50"
          disabled={busy || version.status === "active"}
          onClick={onActivate}
          type="button"
        >
          {version.status === "active" ? "Active" : busy ? "Activating…" : "Activate"}
        </button>
        <DuplicateVersionForm
          versionId={version.id}
          sourceSymbols={version.spec?.symbols ?? []}
        />
        {version.parent_version_id && (
          <Link
            href={`/strategies/versions/${version.parent_version_id}`}
            className="text-accent hover:underline"
          >
            ← parent version
          </Link>
        )}
        {version.backtest_report_id && (
          <Link
            href={`/backtest/${version.backtest_report_id}`}
            className="text-accent hover:underline"
          >
            Backtest report →
          </Link>
        )}
        {error && <span className="text-err">{error}</span>}
      </div>

      {version.spec && (
        <section className="rounded-md border border-line bg-panel p-3 text-sm">
          <header className="mb-2 text-ink-muted">Spec snapshot</header>
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
            <Row label="Symbols" value={version.spec.symbols.join(", ")} />
            <Row label="Entry timeframe" value={version.spec.entry_timeframe} />
            <Row
              label="Confirmation timeframes"
              value={version.spec.confirmation_timeframes.join(", ")}
            />
            <Row
              label="Indicators"
              value={
                version.spec.indicators.map((i) => i.label).join(", ") || "—"
              }
            />
            {version.spec.unrecognized_indicators.length > 0 && (
              <Row
                label="Other indicators (not charted)"
                value={version.spec.unrecognized_indicators.join(", ")}
              />
            )}
            {version.spec.price_levels.length > 0 && (
              <Row
                label="Price levels"
                value={version.spec.price_levels
                  .map((l) => `${l.type} @ ${l.price}`)
                  .join(", ")}
              />
            )}
            {version.spec.chart_notes.length > 0 && (
              <Row label="Chart notes" value={version.spec.chart_notes.join(", ")} />
            )}
          </dl>
          <p className="mt-2 whitespace-pre-wrap text-ink-muted">
            <strong className="text-ink">Entry:</strong> {version.spec.entry_rules}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-ink-muted">
            <strong className="text-ink">Exit:</strong> {version.spec.exit_rules}
          </p>
        </section>
      )}

      <section className="rounded-md border border-line bg-panel">
        <header className="border-b border-line px-3 py-2 text-sm text-ink-muted">
          Source code
        </header>
        <pre className="max-h-[32rem] overflow-auto p-3 text-xs">{version.code}</pre>
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 sm:block">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  );
}
