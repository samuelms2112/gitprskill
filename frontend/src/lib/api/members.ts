import { apiRequest } from './client';

export type MemberRoleValue = 'VIEWER' | 'DEVELOPER' | 'OWNER';

/** Espelha ``MemberRead`` do backend. */
export interface Member {
  user_id: number;
  login: string;
  avatar_url: string | null;
  role: MemberRoleValue;
  joined_at: string;
}

/** Gestão de membros de um tenant. Restrita a OWNER do tenant. */
export const membersApi = {
  list: (token: string, tenantSlug: string, signal?: AbortSignal) =>
    apiRequest<Member[]>(`/tenants/${encodeURIComponent(tenantSlug)}/members`, { token, signal }),

  updateRole: (token: string, tenantSlug: string, userId: number, role: MemberRoleValue) =>
    apiRequest<Member>(`/tenants/${encodeURIComponent(tenantSlug)}/members/${userId}`, {
      method: 'PATCH',
      token,
      body: { role },
    }),

  remove: (token: string, tenantSlug: string, userId: number) =>
    apiRequest<void>(`/tenants/${encodeURIComponent(tenantSlug)}/members/${userId}`, {
      method: 'DELETE',
      token,
    }),
};

/** Usuário da plataforma que ainda não pertence à empresa. Espelha ``CandidateRead``. */
export interface Candidate {
  user_id: number;
  login: string;
  avatar_url: string | null;
}

export const candidatesApi = {
  list: (token: string, tenantSlug: string, signal?: AbortSignal) =>
    apiRequest<Candidate[]>(`/tenants/${encodeURIComponent(tenantSlug)}/members/candidates`, {
      token,
      signal,
    }),

  add: (token: string, tenantSlug: string, userId: number, role: MemberRoleValue) =>
    apiRequest<Member>(`/tenants/${encodeURIComponent(tenantSlug)}/members`, {
      method: 'POST',
      token,
      body: { user_id: userId, role },
    }),
};
