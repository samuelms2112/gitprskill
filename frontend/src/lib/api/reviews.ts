import { apiRequest } from './client';

export type AIReviewStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
export type ReviewSeverity = 'BLOCKER' | 'IMPORTANT' | 'SUGGESTION' | 'QUESTION';

/** Espelha ``ReviewFinding`` do backend. */
export interface ReviewFinding {
  severity: ReviewSeverity;
  file: string;
  line: number | null;
  comment: string;
}

/** Espelha ``AIReviewRead`` do backend. */
export interface AIReview {
  id: number;
  pull_request_id: number;
  pr_number: number;
  pr_title: string;
  repository: string;
  pr_url: string;
  status: AIReviewStatus;
  findings: ReviewFinding[] | null;
  findings_count: number;
  error_message: string | null;
  publish_error: string | null;
  github_review_url: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface SkillRule {
  filename: string;
  content: string;
  updated_at: string;
}

export interface ReviewSkill {
  slug: string;
  name: string;
  rules: SkillRule[];
}

export const reviewsApi = {
  list: (token: string, tenantSlug: string, signal?: AbortSignal) =>
    apiRequest<AIReview[]>(`/tenants/${encodeURIComponent(tenantSlug)}/reviews?limit=200`, { token, signal }),

  request: (token: string, tenantSlug: string, pullRequestId: number) =>
    apiRequest<{ id: number; pull_request_id: number; status: AIReviewStatus }>(
      `/tenants/${encodeURIComponent(tenantSlug)}/pull-requests/${pullRequestId}/review`,
      { method: 'POST', token },
    ),

  skill: (token: string, tenantSlug: string, signal?: AbortSignal) =>
    apiRequest<ReviewSkill>(`/tenants/${encodeURIComponent(tenantSlug)}/review-skill`, { token, signal }),

  updateRule: (token: string, tenantSlug: string, filename: string, content: string) =>
    apiRequest<SkillRule>(
      `/tenants/${encodeURIComponent(tenantSlug)}/review-skill/rules/${encodeURIComponent(filename)}`,
      { method: 'PUT', token, body: { content } },
    ),
};
