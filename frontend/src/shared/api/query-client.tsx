"use client";

/**
 * Mounts one TanStack Query `QueryClient` for the whole app — the same
 * "client component wrapping {children}" pattern `AccountProvider` already
 * uses (see account-context.tsx), so it can sit directly in the (server)
 * root layout with no extra "providers" indirection.
 *
 * The client is created in `useState`'s lazy initializer rather than at
 * module scope, per TanStack's own App Router guidance — a module-level
 * singleton would leak cached data across requests/users on the server and
 * (worse) across browser sessions if this module were ever reused; `useState`
 * still keeps one stable instance for the lifetime of this client tree.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Polled queries set their own `refetchInterval` to reproduce
            // each hook's prior `setInterval` cadence — no need for an
            // implicit window-focus refetch on top of that for live
            // positions/orders data.
            refetchOnWindowFocus: false,
            staleTime: 1000,
          },
        },
      }),
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
