/**
 * Tipos espelhando os schemas Pydantic do backend (app/schemas).
 * Mantenha sincronizados ao alterar a API.
 */

export type MemberRole = 'OWNER' | 'DEVELOPER' | 'VIEWER';
export type AICategory = 'FEATURE' | 'BUGFIX' | 'REFACTOR' | 'SECURITY' | 'CHORE';
export type AIRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';
export type PRSizeCategory = 'XS' | 'S' | 'M' | 'L' | 'XL';
export type ReleaseBranch = 'main' | 'master' | 'master-tip';

export interface User {
  id: number;
  github_id: number;
  login: string;
  email: string | null;
  avatar_url: string | null;
}

export interface TenantMembership {
  slug: string;
  name: string;
  role: MemberRole;
}

export type PRStateFilter = 'all' | 'open' | 'merged';

export interface PullRequestReportItem {
  id: number;
  number: number;
  title: string;
  repository: string;
  author: string;
  base_branch: string;
  state: 'open' | 'closed';
  is_merged: boolean;
  created_at: string;
  merged_at: string | null;
  additions: number;
  deletions: number;
  changed_files: number;
  pr_size_category: PRSizeCategory | null;
  time_to_merge_seconds: number | null;
  ai_category: AICategory | null;
  ai_risk_level: AIRiskLevel | null;
  ai_summary: string | null;
  html_url: string;
}

export interface PullRequestReportPage {
  items: PullRequestReportItem[];
  total: number;
  limit: number;
  offset: number;
}

export type SizeDistribution = Record<PRSizeCategory, number>;

export interface ReportSummary {
  total: number;
  average_time_to_merge_seconds: number | null;
  size_distribution: SizeDistribution;
  available_authors: string[];
  available_repositories: string[];
}

export interface ReleaseNotesRequest {
  tenant_slug: string;
  start_date: string;
  end_date: string;
  base_branch?: ReleaseBranch | null;
  limit?: number;
}

export interface ReleaseNotesResponse {
  tenant_slug: string;
  start_date: string;
  end_date: string;
  base_branch: string | null;
  pr_count: number;
  markdown: string;
}

/** Filtros compartilhados pelo resumo e pela listagem de PRs. */
export interface ReportFilters {
  tenantSlug: string;
  startDate?: string;
  endDate?: string;
  repository?: string;
  author?: string;
  aiCategory?: AICategory;
  state?: PRStateFilter;
}

export interface TenantRepository {
  id: number;
  tenant_id: number;
  github_id: number;
  name: string;
  full_name: string;
  owner_login: string;
  html_url: string;
  default_branch: string;
  is_private: boolean;
}

export type SyncState = 'queued' | 'running' | 'completed' | 'failed';

export interface SyncAccepted {
  task_id: string;
  state: SyncState;
}

export interface SyncStatus {
  task_id: string;
  tenant_id: number;
  repository_id: number;
  state: SyncState;
  examined: number;
  stored: number;
  new: number;
  skipped: number;
  error: string | null;
  updated_at: string;
}
