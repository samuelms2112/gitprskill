'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { systemApi, type ClaudeStatus } from '@/lib/api/system';

import { useAuth } from '../auth/auth-context';

const CLAUDE_STATUS_KEY = ['system', 'claude', 'status'] as const;

/** Estado da sessão do Claude. Não é reconsultado sozinho: cada consulta gasta uma chamada ao Claude. */
export function useClaudeStatus() {
  const { token } = useAuth();
  return useQuery({
    queryKey: CLAUDE_STATUS_KEY,
    queryFn: ({ signal }) => systemApi.claudeStatus(token ?? '', signal),
    enabled: token !== null,
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

function requireToken(token: string | null): string {
  if (token === null) throw new Error('Sessão expirada. Entre novamente.');
  return token;
}

export function useStartClaudeReauth() {
  const { token } = useAuth();
  return useMutation({
    mutationFn: () => systemApi.startClaudeReauth(requireToken(token)),
  });
}

export function useCompleteClaudeReauth() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ loginId, code }: { loginId: string; code: string }) =>
      systemApi.completeClaudeReauth(requireToken(token), loginId, code),
    onSuccess: (status: ClaudeStatus) => {
      queryClient.setQueryData(CLAUDE_STATUS_KEY, status);
    },
  });
}

export function useRefreshClaudeStatus() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => systemApi.claudeStatus(requireToken(token)),
    onSuccess: (status: ClaudeStatus) => {
      queryClient.setQueryData(CLAUDE_STATUS_KEY, status);
    },
  });
}
