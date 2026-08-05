"use client";

/**
 * The volatility guard's live on/off switch and read-only config, shared
 * between two independent consumers — `VolatilityGuardPanel.tsx` (settings
 * page) and the chart toolbar toggle — so toggling in either place is
 * reflected in the other immediately. Backed by TanStack Query: both
 * consumers read the same `queryKeys.engine.volatilityConfig(accountId)`
 * cache entry, and the mutation writes its response straight into that
 * entry (`setQueryData`) rather than waiting on a refetch, so the other
 * mounted consumer re-renders on the next tick with no extra network call.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useActiveAccount } from "@/shared/api/account-context";
import { queryKeys } from "@/shared/api/queryKeys";
import { getVolatilityConfig, putVolatilityGuardEnabled } from "@/shared/api/client";

export function useVolatilityGuard() {
  const accountId = useActiveAccount();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: queryKeys.engine.volatilityConfig(accountId),
    queryFn: () => getVolatilityConfig(accountId as string),
    enabled: accountId !== null,
  });

  const mutation = useMutation({
    mutationFn: (enabled: boolean) => putVolatilityGuardEnabled(accountId as string, enabled),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.engine.volatilityConfig(accountId), updated);
    },
  });

  return {
    config: query.data ?? null,
    isPending: query.isPending,
    isError: query.isError,
    setEnabled: mutation.mutate,
    isSaving: mutation.isPending,
    saveError: mutation.isError,
  };
}

export type UseVolatilityGuardReturn = ReturnType<typeof useVolatilityGuard>;
