import { AI_CATEGORIES, type PeriodValue } from '@/lib/constants';
import type { AICategory, PRStateFilter, ReportFilters } from '@/lib/api/types';

import { periodToDates } from './period';

/** Estado dos filtros da tela. Strings vazias significam "sem filtro". */
export interface DashboardFilters {
  period: PeriodValue;
  repository: string;
  author: string;
  aiCategory: AICategory | '';
  /** Aba do feed: todos, em aberto ou mergeados. Não conta como filtro extra. */
  state: PRStateFilter;
}

export const DEFAULT_DASHBOARD_FILTERS: DashboardFilters = {
  period: '30d',
  repository: '',
  author: '',
  aiCategory: '',
  state: 'merged',
};

const VALID_CATEGORIES = new Set<string>(AI_CATEGORIES.map((item) => item.value));

/** Converte o estado da tela no filtro enviado à API. */
export function toReportFilters(tenantSlug: string, filters: DashboardFilters, today?: Date): ReportFilters {
  return {
    tenantSlug,
    ...periodToDates(filters.period, today),
    repository: filters.repository || undefined,
    author: filters.author || undefined,
    aiCategory: isAICategory(filters.aiCategory) ? filters.aiCategory : undefined,
    state: filters.state,
  };
}

export function isAICategory(value: string): value is AICategory {
  return VALID_CATEGORIES.has(value);
}

export function hasActiveFilters(filters: DashboardFilters): boolean {
  return filters.repository !== '' || filters.author !== '' || filters.aiCategory !== '';
}
