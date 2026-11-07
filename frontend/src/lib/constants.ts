import type { AICategory, AIRiskLevel, PRSizeCategory, ReleaseBranch } from './api/types';

export const AI_CATEGORIES: readonly { value: AICategory; label: string }[] = [
  { value: 'FEATURE', label: 'Feature' },
  { value: 'BUGFIX', label: 'Bugfix' },
  { value: 'REFACTOR', label: 'Refatoração' },
  { value: 'SECURITY', label: 'Segurança' },
  { value: 'CHORE', label: 'Manutenção' },
];

export const AI_RISK_LEVELS: Record<AIRiskLevel, { label: string }> = {
  LOW: { label: 'Risco baixo' },
  MEDIUM: { label: 'Risco médio' },
  HIGH: { label: 'Risco alto' },
};

export const SIZE_CATEGORIES: readonly { value: PRSizeCategory; range: string }[] = [
  { value: 'XS', range: '< 10 linhas' },
  { value: 'S', range: '10–49 linhas' },
  { value: 'M', range: '50–249 linhas' },
  { value: 'L', range: '250–999 linhas' },
  { value: 'XL', range: '≥ 1000 linhas' },
];

export const RELEASE_BRANCHES: readonly { value: ReleaseBranch; label: string }[] = [
  { value: 'main', label: 'main' },
  { value: 'master', label: 'master' },
  { value: 'master-tip', label: 'master-tip' },
];

export const PERIOD_OPTIONS = [
  { value: '7d', label: 'Últimos 7 dias', days: 7 },
  { value: '30d', label: 'Últimos 30 dias', days: 30 },
  { value: '90d', label: 'Últimos 90 dias', days: 90 },
  { value: 'all', label: 'Todo o período', days: null },
] as const;

export type PeriodValue = (typeof PERIOD_OPTIONS)[number]['value'];

/** Limite da API para o intervalo de release notes (ver ReleaseNotesRequest no backend). */
export const MAX_RELEASE_NOTES_RANGE_DAYS = 366;
