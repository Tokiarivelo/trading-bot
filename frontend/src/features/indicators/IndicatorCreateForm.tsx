"use client";

/** "+ New indicator" button + form: name, default params (JSON), and a code
 * editor pre-filled with a minimal working template. Sandbox-validated
 * server-side on submit (POST /indicators) — a rejection surfaces the
 * sandbox's error list inline instead of routing away. */

import { python } from "@codemirror/lang-python";
import { githubDarkInit } from "@uiw/codemirror-theme-github";
import CodeMirror from "@uiw/react-codemirror";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, createIndicator } from "@/shared/api/client";

const cmTheme = githubDarkInit({
  settings: {
    background: "var(--color-bg)",
    gutterBackground: "var(--color-bg)",
    lineHighlight: "var(--color-panel)",
    foreground: "var(--color-ink)",
    caret: "var(--color-accent)",
    selection: "color-mix(in srgb, var(--color-accent) 30%, transparent)",
  },
});

const DEFAULT_TEMPLATE = `import pandas as pd


class CustomIndicator:
    def compute(self, candles: pd.DataFrame, params: dict) -> dict:
        period = int(params.get("period", 20))
        sma = candles["close"].rolling(period).mean()
        return {"value": sma.tolist()}
`;

export function IndicatorCreateForm() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState(DEFAULT_TEMPLATE);
  const [paramsJson, setParamsJson] = useState('{\n  "period": 20\n}');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("name is required");
      return;
    }
    let defaultParams: Record<string, number>;
    try {
      defaultParams = JSON.parse(paramsJson || "{}");
    } catch {
      setError("default params must be valid JSON");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createIndicator({ name: trimmed, code, default_params: defaultParams });
      router.push(`/indicators/${created.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "create failed");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className={btnAccentCls} onClick={() => setOpen(true)}>
        + New indicator
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border border-line bg-panel p-3 text-sm">
      <div className="flex gap-3">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-ink-muted">Name</span>
          <input
            autoFocus
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. custom_sma"
          />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-ink-muted">Default params (JSON)</span>
          <input
            className={`${inputCls} font-mono`}
            value={paramsJson}
            onChange={(e) => setParamsJson(e.target.value)}
          />
        </label>
      </div>
      <div>
        <span className="mb-1 block text-xs text-ink-muted">
          Code — a class with a compute(candles, params) -&gt; dict[str, list] method
        </span>
        <CodeMirror value={code} height="20rem" theme={cmTheme} extensions={[python()]} onChange={setCode} />
      </div>
      {error && <p className="text-xs text-err">{error}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={busy} className={btnAccentCls} onClick={onSubmit}>
          {busy ? "Creating…" : "Create"}
        </button>
        <button
          type="button"
          className={btnCls}
          onClick={() => {
            setOpen(false);
            setError(null);
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";
const btnCls =
  "cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent";
const btnAccentCls =
  "cursor-pointer rounded border border-accent px-3 py-1 text-xs text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50";
