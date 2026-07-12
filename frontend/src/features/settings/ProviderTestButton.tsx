"use client";

import { useState } from "react";
import { testProvider } from "@/shared/api/client";

/** Runs POST /ai/settings/providers/{provider}/test and shows pass/fail inline.
 * Never throws for a connectivity failure — the backend always returns 200
 * with `ok: false` for that case, so this only catches genuine request errors.
 * An optional message input lets the user send a real prompt (e.g. "hello")
 * instead of the default one-token connectivity probe, showing the
 * provider's actual reply on success. */
export function ProviderTestButton({ provider }: { provider: string }) {
  const [state, setState] = useState<"idle" | "testing" | "ok" | "fail">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [input, setInput] = useState("");

  async function run() {
    setState("testing");
    setMessage(null);
    setReply(null);
    try {
      const result = await testProvider(provider, input.trim() || undefined);
      setState(result.ok ? "ok" : "fail");
      setMessage(result.message);
      setReply(result.reply);
    } catch {
      setState("fail");
      setMessage("request failed");
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="hello"
        className="w-20 rounded border border-line bg-transparent px-1.5 py-1 text-xs text-ink placeholder:text-ink-muted/60"
      />
      <button
        type="button"
        onClick={run}
        disabled={state === "testing"}
        className="rounded border border-line px-2 py-1 text-xs text-ink-muted hover:text-ink disabled:opacity-40"
      >
        {state === "testing" ? "Testing…" : "Test"}
      </button>
      {state === "ok" && (
        <span className="text-xs text-ok" title={reply ?? undefined}>
          ✓ {reply ? reply.slice(0, 60) : "ok"}
        </span>
      )}
      {state === "fail" && (
        <span className="text-xs text-err" title={message ?? undefined}>
          ✗ {message ? message.slice(0, 60) : "failed"}
        </span>
      )}
    </span>
  );
}
