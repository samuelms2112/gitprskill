'use client';

import { useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useEffect } from 'react';

import { repositoriesApi, syncApi } from '@/lib/api/endpoints';
import type { SyncState, SyncStatus } from '@/lib/api/types';

import { useAuth } from '../auth/auth-context';

const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATES: readonly SyncState[] = ['completed', 'failed'];

export function isTerminal(state: SyncState | undefined): boolean {
  return state !== undefined && TERMINAL_STATES.includes(state);
}

export function useTenantRepositories(tenantSlug: string) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['repositories', tenantSlug],
    queryFn: ({ signal }) => repositoriesApi.list(token ?? '', tenantSlug, signal),
    enabled: token !== null,
  });
}

export function useStartSync(tenantSlug: string) {
  const { token } = useAuth();
  return useMutation({
    mutationFn: ({ repositoryId, daysBack }: { repositoryId: number; daysBack?: number }) => {
      if (token === null) throw new Error('Sessão expirada. Entre novamente.');
      return syncApi.start(token, tenantSlug, repositoryId, daysBack);
    },
  });
}

export function useStartSyncAll(tenantSlug: string) {
  const { token } = useAuth();
  return useMutation({
    mutationFn: () => {
      if (token === null) throw new Error('Sessão expirada. Entre novamente.');
      return syncApi.startAll(token, tenantSlug);
    },
  });
}

/**
 * Acompanha um job até o estado final: consulta a cada 2s enquanto ele está em andamento
 * e para ao chegar em ``completed`` ou ``failed``. Ao concluir, atualiza os relatórios e a lista
 * de repositórios, para os PRs importados aparecerem sem recarregar a página.
 */
function usePollingSync(
  queryKey: QueryKey,
  tenantSlug: string,
  fetchStatus: (signal: AbortSignal) => Promise<SyncStatus>,
  enabled: boolean,
) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchStatus(signal),
    enabled,
    refetchInterval: (current) => (isTerminal(current.state.data?.state) ? false : POLL_INTERVAL_MS),
  });

  const state = query.data?.state;
  useEffect(() => {
    if (state === 'completed') {
      void queryClient.invalidateQueries({ queryKey: ['reports'] });
      void queryClient.invalidateQueries({ queryKey: ['repositories', tenantSlug] });
    }
  }, [state, queryClient, tenantSlug]);

  return query;
}

/** Progresso de um repositório. ``taskId`` nulo significa que nenhum job foi iniciado. */
export function useSyncStatus(tenantSlug: string, repositoryId: number, taskId: string | null) {
  const { token } = useAuth();
  return usePollingSync(
    ['sync', tenantSlug, repositoryId, taskId],
    tenantSlug,
    (signal) => syncApi.status(token ?? '', tenantSlug, repositoryId, taskId ?? '', signal),
    token !== null && taskId !== null,
  );
}

/** Progresso agregado de todos os repositórios do tenant. */
export function useSyncAllStatus(tenantSlug: string, taskId: string | null) {
  const { token } = useAuth();
  return usePollingSync(
    ['sync-all', tenantSlug, taskId],
    tenantSlug,
    (signal) => syncApi.statusAll(token ?? '', tenantSlug, taskId ?? '', signal),
    token !== null && taskId !== null,
  );
}

/** Atualiza a lista de repositórios consultando a instalação do App (resolve instalações antigas). */
export function useSyncFromGitHubApp(tenantSlug: string) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => {
      if (token === null) throw new Error('Sessão expirada. Entre novamente.');
      return syncApi.syncFromGitHubApp(token, tenantSlug);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repositories', tenantSlug] });
    },
  });
}
