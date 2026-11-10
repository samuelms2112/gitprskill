'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { candidatesApi, membersApi, type MemberRoleValue } from '@/lib/api/members';

import { useAuth } from '../auth/auth-context';

function requireToken(token: string | null): string {
  if (token === null) throw new Error('Sessão expirada. Entre novamente.');
  return token;
}

export function useMembers(tenantSlug: string, enabled: boolean) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['members', tenantSlug],
    queryFn: ({ signal }) => membersApi.list(requireToken(token), tenantSlug, signal),
    enabled: enabled && token !== null,
  });
}

export function useUpdateMemberRole(tenantSlug: string) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: MemberRoleValue }) =>
      membersApi.updateRole(requireToken(token), tenantSlug, userId, role),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['members', tenantSlug] }),
  });
}

export function useRemoveMember(tenantSlug: string) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) => membersApi.remove(requireToken(token), tenantSlug, userId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['members', tenantSlug] }),
  });
}

export function useCandidates(tenantSlug: string, enabled: boolean) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['member-candidates', tenantSlug],
    queryFn: ({ signal }) => candidatesApi.list(requireToken(token), tenantSlug, signal),
    enabled: enabled && token !== null,
  });
}

export function useAddMember(tenantSlug: string) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: MemberRoleValue }) =>
      candidatesApi.add(requireToken(token), tenantSlug, userId, role),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['members', tenantSlug] });
      void queryClient.invalidateQueries({ queryKey: ['member-candidates', tenantSlug] });
    },
  });
}
