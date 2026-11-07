'use client';

import { useMemo, useState } from 'react';

import { FilterBar } from '@/components/dashboard/filter-bar';
import { HistorySyncCard } from '@/components/dashboard/history-sync-card';
import { KpiCards } from '@/components/dashboard/kpi-cards';
import { PrFeed } from '@/components/dashboard/pr-feed';
import { StateTabs } from '@/components/dashboard/state-tabs';
import { EmptyState, ErrorState } from '@/components/ui/feedback';
import { Skeleton } from '@/components/ui/skeleton';
import {
  DEFAULT_DASHBOARD_FILTERS,
  toReportFilters,
  type DashboardFilters,
} from '@/features/reports/filters';
import { useReportSummary } from '@/features/reports/queries';
import { useTenant } from '@/features/tenant/tenant-context';
import { errorMessage } from '@/lib/api/error-message';

export default function DashboardPage() {
  const { activeTenant, isLoading } = useTenant();

  if (isLoading) {
    return (
      <div className="space-y-6" aria-busy="true">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32" />
      </div>
    );
  }

  if (!activeTenant) {
    return (
      <EmptyState
        title="Você ainda não tem empresas"
        description="Peça ao administrador da sua organização para instalar o GitHub App. Depois disso, a empresa aparece aqui."
      />
    );
  }

  // Remontar ao trocar de empresa zera os filtros, que são específicos de cada uma.
  return <DashboardContent key={activeTenant.slug} tenantSlug={activeTenant.slug} />;
}

function DashboardContent({ tenantSlug }: { tenantSlug: string }) {
  const [filters, setFilters] = useState<DashboardFilters>(DEFAULT_DASHBOARD_FILTERS);
  const reportFilters = useMemo(() => toReportFilters(tenantSlug, filters), [tenantSlug, filters]);
  const summary = useReportSummary(reportFilters);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Pull Requests</h1>
        <p className="text-sm text-muted-foreground">
          PRs mergeados nas branches principais, com análise de IA e métricas de engenharia.
        </p>
      </header>

      {summary.isError ? (
        <ErrorState message={errorMessage(summary.error)} onRetry={() => void summary.refetch()} />
      ) : (
        <KpiCards summary={summary.data} isPending={summary.isPending} />
      )}

      <HistorySyncCard tenantSlug={tenantSlug} />

      <FilterBar
        value={filters}
        onChange={setFilters}
        repositories={summary.data?.available_repositories ?? []}
        authors={summary.data?.available_authors ?? []}
      />

      <div className="space-y-4">
        <StateTabs
          value={filters.state}
          onChange={(state) => setFilters((current) => ({ ...current, state }))}
        />
        <PrFeed filters={reportFilters} />
      </div>
    </div>
  );
}
