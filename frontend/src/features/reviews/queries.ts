'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { reviewsApi, type AIReview } from '@/lib/api/reviews';

import { useAuth } from '../auth/auth-context';

const ACTIVE_POLL_MS = 4000;

function requireToken(token: string | null): string {
  if (token === null) throw new Error('Sessão expirada. Entre novamente.');
  return token;
}

const isActive = (review: AIReview) => review.status === 'PENDING' || review.status === 'RUNNING';

/** Revisões recentes. Enquanto alguma estiver pendente ou rodando, atualiza a cada 4 s. */
export function useReviews(tenantSlug: string | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['reviews', tenantSlug],
    queryFn: ({ signal }) => reviewsApi.list(requireToken(token), tenantSlug ?? '', signal),
    enabled: token !== null && tenantSlug !== null,
    refetchInterval: (query) => (query.state.data?.some(isActive) ? ACTIVE_POLL_MS : false),
  });
}

/** Última revisão de cada PR, pelo id interno do PR. */
export function latestReviewByPullRequest(reviews: AIReview[] | undefined): Map<number, AIReview> {
  const map = new Map<number, AIReview>();
  for (const review of reviews ?? []) {
    if (!map.has(review.pull_request_id)) map.set(review.pull_request_id, review);
  }
  return map;
}

export function useRequestReview(tenantSlug: string) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pullRequestId: number) => reviewsApi.request(requireToken(token), tenantSlug, pullRequestId),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['reviews', tenantSlug] }),
  });
}

export function useReviewSkill(tenantSlug: string | null, enabled: boolean) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['review-skill', tenantSlug],
    queryFn: ({ signal }) => reviewsApi.skill(requireToken(token), tenantSlug ?? '', signal),
    enabled: enabled && token !== null && tenantSlug !== null,
  });
}

export function useUpdateSkillRule(tenantSlug: string) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ filename, content }: { filename: string; content: string }) =>
      reviewsApi.updateRule(requireToken(token), tenantSlug, filename, content),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['review-skill', tenantSlug] }),
  });
}
