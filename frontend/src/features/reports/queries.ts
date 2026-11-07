'use client';

import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query';

import { reportsApi } from '@/lib/api/endpoints';
import type { ReleaseNotesRequest, ReportFilters } from '@/lib/api/types';

import { useAuth } from '../auth/auth-context';

export const PAGE_SIZE = 20;

/** Chave de cache estável: só depende dos filtros (nunca do token). */
export const reportKeys = {
  summary: (filters: ReportFilters) => ['reports', 'summary', filters] as const,
  list: (filters: ReportFilters) => ['reports', 'prs', filters] as const,
};

export function useReportSummary(filters: ReportFilters) {
  const { token } = useAuth();
  return useQuery({
    queryKey: reportKeys.summary(filters),
    queryFn: ({ signal }) => reportsApi.summary(token ?? '', filters, signal),
    enabled: token !== null,
    placeholderData: (previous) => previous,
  });
}

export function usePullRequestFeed(filters: ReportFilters) {
  const { token } = useAuth();
  return useInfiniteQuery({
    queryKey: reportKeys.list(filters),
    queryFn: ({ pageParam, signal }) =>
      reportsApi.list(token ?? '', filters, { limit: PAGE_SIZE, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const nextOffset = lastPage.offset + lastPage.items.length;
      return nextOffset < lastPage.total ? nextOffset : undefined;
    },
    enabled: token !== null,
    placeholderData: (previous) => previous,
  });
}

export function useReleaseNotes() {
  const { token } = useAuth();
  return useMutation({
    mutationFn: (body: ReleaseNotesRequest) => {
      if (token === null) throw new Error('Sessão expirada. Entre novamente.');
      return reportsApi.releaseNotes(token, body);
    },
  });
}
