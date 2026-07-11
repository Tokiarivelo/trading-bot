"use client";

import { useEffect, useState } from "react";
import { getAuthStatus, getToken, login, UNAUTHORIZED_EVENT } from "@/shared/api/client";
import { refreshWsAuth } from "@/shared/api/ws";

/** Wraps the whole app (see app/layout.tsx): shows a password form until the
 * backend confirms a session, since the bot can start live trading (§11).
 * Skips the form entirely when `TB_APP_PASSWORD` is unset (bare local dev). */
export function LoginGate({ children }: { children: React.ReactNode }) {
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);
  const [unlocked, setUnlocked] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getAuthStatus()
      .then((status) => {
        setAuthRequired(status.auth_required);
        setUnlocked(!status.auth_required || !!getToken());
      })
      .catch(() => {
        // Backend unreachable — let the rest of the UI's own "offline" state
        // handle it rather than blocking on a login screen that can't work.
        setAuthRequired(false);
        setUnlocked(true);
      });

    const onUnauthorized = () => setUnlocked(false);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(password);
      refreshWsAuth();
      setPassword("");
      setUnlocked(true);
    } catch {
      setError("Wrong password");
    } finally {
      setSubmitting(false);
    }
  }

  if (authRequired === null) return null;
  if (unlocked) return <>{children}</>;

  return (
    <div className="flex h-screen items-center justify-center bg-bg">
      <form
        onSubmit={handleSubmit}
        className="flex w-72 flex-col gap-3 rounded-md border border-line bg-panel p-6"
      >
        <h1 className="text-base font-bold text-ink">AI Trading Bot</h1>
        <p className="text-sm text-ink-muted">Enter the app password to continue.</p>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          placeholder="Password"
        />
        {error && <p className="text-sm text-err">{error}</p>}
        <button
          type="submit"
          disabled={submitting || !password}
          className="cursor-pointer rounded bg-accent px-3 py-2 text-sm font-bold text-white disabled:opacity-50"
        >
          {submitting ? "Checking…" : "Log in"}
        </button>
      </form>
    </div>
  );
}
