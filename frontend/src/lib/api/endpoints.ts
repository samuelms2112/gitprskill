import { apiRequest } from './client';
import type {
  PullRequestReportPage,
  ReleaseNotesRequest,
  ReleaseNotesResponse,
  ReportFilters,
  ReportSummary,
  SyncAccepted,
  SyncStatus,
  TenantMembership,
  TenantRepository,
  User,
} from './types';

/** Endpoints agrupados por recurso. Cada função recebe o token de sessão explicitamente. */

export const authApi = {
  me: (token: string, signal?: AbortSignal) => apiRequest<User>('/auth/me', { token, signal }),
};

export const tenantsApi = {
  list: (token: string, signal?: AbortSignal) =>
    apiRequest<TenantMembership[]>('/tenants', { token, signal }),
};

export const repositoriesApi = {
  list: (token: string, tenantSlug: string, signal?: AbortSignal) =>
    apiRequest<TenantRepository[]>(`/tenants/${encodeURIComponent(tenantSlug)}/repositories`, { token, signal }),
};

/** Sincronização histórica: o POST responde 202 com o task_id; o progresso vem pelo GET. */
export const syncApi = {
  start: (token: string, tenantSlug: string, repositoryId: number, daysBack?: number) =>
    apiRequest<SyncAccepted>(
      `/tenants/${encodeURIComponent(tenantSlug)}/repositories/${repositoryId}/sync`,
      { method: 'POST', token, body: daysBack === undefined ? {} : { days_back: daysBack } },
    ),

  status: (token: string, tenantSlug: string, repositoryId: number, taskId: string, signal?: AbortSignal) =>
    apiRequest<SyncStatus>(
      `/tenants/${encodeURIComponent(tenantSlug)}/repositories/${repositoryId}/sync/status/${encodeURIComponent(taskId)}`,
      { token, signal },
    ),

  /** Atualiza a lista de repositórios consultando a própria instalação do GitHub App. */
  syncFromGitHubApp: (token: string, tenantSlug: string) =>
    apiRequest<{ synced: number }>(
      `/tenants/${encodeURIComponent(tenantSlug)}/repositories/sync-from-github-app`,
      { method: 'POST', token },
    ),

  /** Sincroniza todos os repositórios do tenant; responde 202 com um ``task_id`` agregado. */
  startAll: (token: string, tenantSlug: string) =>
    apiRequest<SyncAccepted>(`/tenants/${encodeURIComponent(tenantSlug)}/repositories/sync-all`, {
      method: 'POST',
      token,
    }),

  statusAll: (token: string, tenantSlug: string, taskId: string, signal?: AbortSignal) =>
    apiRequest<SyncStatus>(
      `/tenants/${encodeURIComponent(tenantSlug)}/repositories/sync-all/status/${encodeURIComponent(taskId)}`,
      { token, signal },
    ),
};

/** Converte os filtros da interface em query string, omitindo os vazios. */
export function buildReportQuery(filters: ReportFilters, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams({ tenant_slug: filters.tenantSlug, ...extra });
  if (filters.startDate) params.set('start_date', filters.startDate);
  if (filters.endDate) params.set('end_date', filters.endDate);
  if (filters.repository) params.set('repository', filters.repository);
  if (filters.author) params.set('author', filters.author);
  if (filters.aiCategory) params.set('ai_category', filters.aiCategory);
  if (filters.state) params.set('state', filters.state);
  return params.toString();
}

export const reportsApi = {
  summary: (token: string, filters: ReportFilters, signal?: AbortSignal) =>
    apiRequest<ReportSummary>(`/reports/summary?${buildReportQuery(filters)}`, { token, signal }),

  list: (token: string, filters: ReportFilters, page: { limit: number; offset: number }, signal?: AbortSignal) =>
    apiRequest<PullRequestReportPage>(
      `/reports/prs?${buildReportQuery(filters, { limit: String(page.limit), offset: String(page.offset) })}`,
      { token, signal },
    ),

  releaseNotes: (token: string, body: ReleaseNotesRequest) =>
    apiRequest<ReleaseNotesResponse>('/reports/release-notes', { method: 'POST', token, body }),
};
