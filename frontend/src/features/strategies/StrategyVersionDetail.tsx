"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  ApiError,
  activateStrategyVersion,
  getStrategyVersion,
  type StrategyVersionDetail as VersionDetail,
} from "@/shared/api/client";
import { downloadJson } from "@/shared/utils/download";
import { CodeEditorPanel } from "./CodeEditorPanel";
import { DuplicateVersionForm } from "./DuplicateVersionForm";
import { RenameVersionInline } from "./RenameVersionInline";
import { SpecSnapshotPanel } from "./SpecSnapshotPanel";
import { StatusBadge } from "./StatusBadge";
import { VersionLifecycleActions } from "./VersionLifecycleActions";

/** Full version detail: spec snapshot, source code, and the activate button
 * — which doubles as rollback when applied to an older version (§6.5). */
export function StrategyVersionDetail({ versionId }: { versionId: string }) {
  const router = useRouter();
  const accountId = useActiveAccount();
  const [version, setVersion] = useState<VersionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    if (!accountId) return;
    getStrategyVersion(accountId, versionId)
      .then(setVersion)
      .catch(() => setError("version not found"));
  }

  useEffect(load, [versionId, accountId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onActivate() {
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      await activateStrategyVersion(accountId, versionId);
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
        <Link href="/bots" className="text-xs text-ink-muted hover:text-accent">
          ← All bots
        </Link>
        <div className="mt-1 flex items-center gap-2">
          <h2 className="text-lg font-semibold">
            {version.name} · v{version.version}
          </h2>
          <RenameVersionInline versionId={version.id} name={version.name} onRenamed={load} />
          <StatusBadge status={version.status} />
          {version.status === "active" && version.paused && <StatusBadge status="paused" />}
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
        <VersionLifecycleActions
          version={version}
          onChanged={load}
          onDeleted={() => router.push("/strategies")}
        />
        <button
          type="button"
          onClick={() => downloadJson(version, `${version.name}_v${version.version}_${version.id}.json`)}
          className="cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent transition-colors"
        >
          Export JSON
        </button>
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
        <SpecSnapshotPanel versionId={version.id} spec={version.spec} onSaved={load} />
      )}

      <CodeEditorPanel
        versionId={version.id}
        name={version.name}
        code={version.code}
        spec={version.spec}
      />
    </div>
  );
}
