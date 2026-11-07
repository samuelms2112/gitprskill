'use client';

import { X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/select';
import { AI_CATEGORIES, PERIOD_OPTIONS, type PeriodValue } from '@/lib/constants';
import type { AICategory } from '@/lib/api/types';
import {
  DEFAULT_DASHBOARD_FILTERS,
  hasActiveFilters,
  isAICategory,
  type DashboardFilters,
} from '@/features/reports/filters';

interface FilterBarProps {
  value: DashboardFilters;
  onChange: (next: DashboardFilters) => void;
  repositories: string[];
  authors: string[];
}

const FIELD_LABEL = 'text-xs font-medium text-muted-foreground';

/** Barra de filtros do painel: período, repositório, autor e categoria de IA. */
export function FilterBar({ value, onChange, repositories, authors }: FilterBarProps) {
  const update = <K extends keyof DashboardFilters>(key: K, fieldValue: DashboardFilters[K]) =>
    onChange({ ...value, [key]: fieldValue });

  return (
    <div className="grid gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-2 xl:grid-cols-[1fr_1.4fr_1fr_1fr_auto] xl:items-end">
      <label className="space-y-1.5">
        <span className={FIELD_LABEL}>Período</span>
        <Select
          value={value.period}
          onChange={(event) => update('period', event.target.value as PeriodValue)}
        >
          {PERIOD_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </label>

      <label className="space-y-1.5">
        <span className={FIELD_LABEL}>Repositório</span>
        <Select value={value.repository} onChange={(event) => update('repository', event.target.value)}>
          <option value="">Todos os repositórios</option>
          {repositories.map((repository) => (
            <option key={repository} value={repository}>
              {repository}
            </option>
          ))}
        </Select>
      </label>

      <label className="space-y-1.5">
        <span className={FIELD_LABEL}>Autor</span>
        <Select value={value.author} onChange={(event) => update('author', event.target.value)}>
          <option value="">Todos os autores</option>
          {authors.map((author) => (
            <option key={author} value={author}>
              @{author}
            </option>
          ))}
        </Select>
      </label>

      <label className="space-y-1.5">
        <span className={FIELD_LABEL}>Categoria (IA)</span>
        <Select
          value={value.aiCategory}
          onChange={(event) => {
            const selected = event.target.value;
            update('aiCategory', isAICategory(selected) ? (selected as AICategory) : '');
          }}
        >
          <option value="">Todas as categorias</option>
          {AI_CATEGORIES.map((category) => (
            <option key={category.value} value={category.value}>
              {category.label}
            </option>
          ))}
        </Select>
      </label>

      <Button
        variant="ghost"
        size="default"
        disabled={!hasActiveFilters(value)}
        onClick={() => onChange({ ...DEFAULT_DASHBOARD_FILTERS, period: value.period, state: value.state })}
        className="justify-self-start xl:justify-self-end"
      >
        <X aria-hidden />
        Limpar filtros
      </Button>
    </div>
  );
}
