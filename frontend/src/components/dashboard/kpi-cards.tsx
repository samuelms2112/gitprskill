import { Clock, GitMerge } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { SIZE_CATEGORIES } from '@/lib/constants';
import { formatDuration, formatNumber } from '@/lib/format';
import type { ReportSummary } from '@/lib/api/types';

import { SizeDistribution } from './size-distribution';

interface KpiCardsProps {
  summary: ReportSummary | undefined;
  isPending: boolean;
}

/** Os três indicadores principais do painel. Mostra esqueletos enquanto os dados chegam. */
export function KpiCards({ summary, isPending }: KpiCardsProps) {
  if (isPending && !summary) {
    return (
      <div className="grid gap-4 md:grid-cols-3" aria-busy="true">
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} className="h-32" />
        ))}
      </div>
    );
  }

  const total = summary?.total ?? 0;

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card>
        <CardHeader>
          <CardDescription className="flex items-center gap-2">
            <GitMerge className="size-4" aria-hidden />
            Pull Requests mergeados
          </CardDescription>
          <CardTitle className="text-3xl font-semibold tabular-nums text-foreground">
            {formatNumber(total)}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground">No período e filtros selecionados</CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription className="flex items-center gap-2">
            <Clock className="size-4" aria-hidden />
            Tempo médio até o merge
          </CardDescription>
          <CardTitle className="text-3xl font-semibold tabular-nums text-foreground">
            {formatDuration(summary?.average_time_to_merge_seconds ?? null)}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground">Da abertura do PR ao merge</CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardDescription>Distribuição por tamanho</CardDescription>
        </CardHeader>
        <CardContent>
          <SizeDistribution
            distribution={summary?.size_distribution}
            total={total}
            sizes={SIZE_CATEGORIES}
          />
        </CardContent>
      </Card>
    </div>
  );
}
