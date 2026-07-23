"use client";

import { useCallback, useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  ApiError,
  connectAccount,
  disconnectAccount,
  getAccountStatus,
  type AccountStatus,
} from "@/shared/api/client";

const STATUS_POLL_MS = 5000;

/** MT5 account connection (F11): login form, live status, disconnect — for
 * whichever account is currently selected in the top-nav switcher. */
export function AccountPanel() {
  const accountId = useActiveAccount();
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!accountId) return;
    getAccountStatus(accountId)
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [accountId]);

  useEffect(() => {
    setStatus(null);
    refresh();
    const timer = setInterval(refresh, STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  async function onConnect(form: FormData) {
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      await connectAccount(accountId, {
        login: Number(form.get("login")),
        password: String(form.get("password")),
        server: String(form.get("server")),
        remember: form.get("remember") === "on",
      });
      refresh();
    } catch (e) {
      setError(connectErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function onDisconnect() {
    if (!accountId) return;
    setBusy(true);
    setError(null);
    try {
      await disconnectAccount(accountId);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "disconnect failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-md border border-line bg-panel p-3 text-sm">
      <header className="mb-2 flex items-center justify-between">
        <strong>MT5 Account</strong>
        <StatusDot status={status} />
      </header>

      {status?.connected && status.account ? (
        <div className="flex flex-col gap-1">
          <Row label="Account" value={`${status.account.login} · ${status.account.server}`} />
          <Row label="Name" value={status.account.name} />
          <Row
            label="Balance"
            value={`${status.account.balance.toFixed(2)} ${status.account.currency}`}
          />
          <Row
            label="Equity"
            value={`${status.account.equity.toFixed(2)} ${status.account.currency}`}
          />
          <button
            className="mt-2 cursor-pointer rounded border border-line px-3 py-1 hover:border-err hover:text-err disabled:opacity-50"
            disabled={busy}
            onClick={onDisconnect}
          >
            Disconnect
          </button>
        </div>
      ) : (
        <form action={onConnect} className="flex flex-col gap-2">
          <input className={inputCls} name="login" type="number" placeholder="Login" required />
          <input
            className={inputCls}
            name="password"
            type="password"
            placeholder="Password"
            required
          />
          <input
            className={inputCls}
            name="server"
            type="text"
            placeholder="Server (e.g. MetaQuotes-Demo)"
            required
          />
          <label className="flex items-center gap-2 text-ink-muted">
            <input name="remember" type="checkbox" defaultChecked />
            Remember (encrypted, key in OS keyring)
          </label>
          <button
            className="cursor-pointer rounded border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-bg disabled:opacity-50"
            disabled={busy || !accountId || status?.gateway_up === false}
            type="submit"
          >
            {busy ? "Connecting…" : "Connect"}
          </button>
          {status?.gateway_up === false && (
            <p className="text-ink-muted">Gateway offline — start it first (gateway/README.md).</p>
          )}
        </form>
      )}

      {error && <p className="mt-2 text-err">{error}</p>}
    </section>
  );
}

function connectErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return "MT5 rejected the credentials — check login/password/server.";
    if (e.status === 503) return "Gateway unreachable — is the MT5 terminal running?";
  }
  return e instanceof Error ? e.message : "connect failed";
}

function StatusDot({ status }: { status: AccountStatus | null }) {
  const [color, label] =
    status === null
      ? (["bg-ink-muted", "backend offline"] as const)
      : status.connected
        ? (["bg-ok", "connected"] as const)
        : status.gateway_up
          ? (["bg-err", "not connected"] as const)
          : (["bg-ink-muted", "gateway offline"] as const);
  return (
    <span className="flex items-center gap-1.5 text-xs text-ink-muted">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-ink-muted">{label}</span>
      <span className="truncate">{value}</span>
    </div>
  );
}

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";
