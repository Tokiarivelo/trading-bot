"use client";

/**
 * Active-account selection (MULTI_ACCOUNT_PLAN.md Phase 8): loads the
 * account list from `GET /accounts`, persists the user's choice in
 * localStorage, and hands every other feature its `accountId` via
 * `useActiveAccount()` — so a hook or component never has to be passed one
 * as a prop, it just reads the context directly.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getAccounts, type AccountSummary } from "@/shared/api/client";

const ACTIVE_ACCOUNT_KEY = "tb.activeAccountId";
const POLL_MS = 30000; // accounts.yaml rarely changes; just catch a backend restart with a new roster

interface AccountContextValue {
  accounts: AccountSummary[];
  /** Null until `GET /accounts` first resolves (or if it returns nothing —
   * e.g. every account disabled). Every per-account hook/component treats
   * null as "not ready yet" and skips fetching, the same way they already
   * skip on an empty `symbol`. */
  activeAccountId: string | null;
  setActiveAccountId: (id: string) => void;
  loading: boolean;
}

const AccountContext = createContext<AccountContextValue | null>(null);

function readStoredAccountId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_ACCOUNT_KEY);
  } catch {
    return null;
  }
}

function writeStoredAccountId(id: string): void {
  try {
    localStorage.setItem(ACTIVE_ACCOUNT_KEY, id);
  } catch {
    // Ignore blocked/full localStorage — selection just won't persist across reloads.
  }
}

export function AccountProvider({ children }: { children: React.ReactNode }) {
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [activeAccountId, setActiveAccountIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    getAccounts()
      .then((list) => {
        setAccounts(list);
        setActiveAccountIdState((prev) => {
          if (prev && list.some((a) => a.id === prev)) return prev;
          const stored = readStoredAccountId();
          if (stored && list.some((a) => a.id === stored)) return stored;
          return list[0]?.id ?? null;
        });
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const setActiveAccountId = useCallback((id: string) => {
    setActiveAccountIdState(id);
    writeStoredAccountId(id);
  }, []);

  return (
    <AccountContext.Provider value={{ accounts, activeAccountId, setActiveAccountId, loading }}>
      {children}
    </AccountContext.Provider>
  );
}

/** Full account-switcher state: the list, the current selection, and a
 * setter — for the switcher UI itself (see NavigationDrawer). Most other
 * call sites just want the id — use `useActiveAccount()` instead. */
export function useAccounts(): AccountContextValue {
  const ctx = useContext(AccountContext);
  if (!ctx) throw new Error("useAccounts must be used within an AccountProvider");
  return ctx;
}

/** The currently-selected account's id, or null before `GET /accounts` has
 * resolved for the first time. Every per-account API call and WS room
 * subscription should gate on this the same way existing hooks gate on an
 * empty `symbol` — never fall back to a guessed id, since that could point
 * a fetch/mutation at the wrong account. */
export function useActiveAccount(): string | null {
  return useAccounts().activeAccountId;
}
