'use client';

import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState, ErrorState } from '@/components/ui/feedback';
import { Skeleton } from '@/components/ui/skeleton';
import { usePullRequestFeed } from '@/features/reports/queries';
import { errorMessage } from '@/lib/api/error-message';
import type { ReportFilters } from '@/lib/api/types';
import { formatNumber } from '@/lib/format';

import { PrCard } from './pr-card';

interface PrFeedProps {
  filters: ReportFilters;
}

/** Feed paginado (infinito por botão) dos PRs enriquecidos. */
export function PrFeed({ filters }: PrFeedProps) {
  const feed = usePullRequestFeed(filters);

  if (feed.isPending) {
    return (
      <div className="space-y-3" aria-busy="true">
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} className="h-32" />
        ))}
      </div>
    );
  }

  if (feed.isError) {
    return <ErrorState message={errorMessage(feed.error)} onRetry={() => void feed.refetch()} />;
  }

  const items = feed.data.pages.flatMap((page) => page.items);
  const total = feed.data.pages[0]?.total ?? 0;

  if (items.length === 0) {
    return (
      <EmptyState
        title="Nenhum Pull Request neste recorte"
        description="Ajuste o período ou os filtros para ver PRs mergeados nas branches principais."
      />
    );
  }

  return (
    <section aria-label="Pull Requests" className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Mostrando {formatNumber(items.length)} de {formatNumber(total)} PRs
      </p>
      {items.map((item) => (
        <PrCard key={item.id} item={item} />
      ))}
      {feed.hasNextPage && (
        <Button
          variant="outline"
          className="w-full"
          onClick={() => void feed.fetchNextPage()}
          disabled={feed.isFetchingNextPage}
        >
          {feed.isFetchingNextPage && <Loader2 className="animate-spin" aria-hidden />}
          Carregar mais
        </Button>
      )}
    </section>
  );
}
