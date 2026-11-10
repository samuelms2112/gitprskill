'use client';

import { ExternalLink, Loader2, RefreshCw } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/feedback';
import { Skeleton } from '@/components/ui/skeleton';
import { useRequestReview, useReviews } from '@/features/reviews/queries';
import { useTenant } from '@/features/tenant/tenant-context';
import { errorMessage } from '@/lib/api/error-message';
import type { AIReview, ReviewFinding, ReviewSeverity } from '@/lib/api/reviews';
import { formatRelative } from '@/lib/format';

const SEVERITY: Record<ReviewSeverity, { label: string; className: string }> = {
  BLOCKER: { label: 'Bloqueante', className: 'border-red-500/50 text-red-300' },
  IMPORTANT: { label: 'Importante', className: 'border-amber-500/50 text-amber-300' },
  SUGGESTION: { label: 'Sugestão', className: 'border-sky-500/50 text-sky-300' },
  QUESTION: { label: 'Dúvida', className: 'border-violet-500/50 text-violet-300' },
};

export default function ReviewsPage() {
  const { activeTenant, isLoading } = useTenant();
  const reviews = useReviews(activeTenant?.slug ?? null);

  if (isLoading || (reviews.isPending && reviews.fetchStatus !== 'idle')) {
    return <Skeleton className="h-64" />;
  }
  if (!activeTenant) {
    return <EmptyState title="Nenhuma empresa disponível" description="Você precisa ser membro de uma empresa." />;
  }
  if (reviews.isError) {
    return <ErrorState message={errorMessage(reviews.error)} onRetry={() => void reviews.refetch()} />;
  }
  if (!reviews.data || reviews.data.length === 0) {
    return (
      <EmptyState
        title="Nenhuma revisão ainda"
        description="Quando um PR é aberto, a revisão automática roda com as regras da empresa e aparece aqui."
      />
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Revisões</h1>
        <p className="text-sm text-muted-foreground">
          Apontamentos da revisão automática com as regras da empresa. Nada é publicado sem que a revisão termine.
        </p>
      </header>
      <ul className="space-y-4">
        {reviews.data.map((review) => (
          <ReviewCard key={review.id} review={review} tenantSlug={activeTenant.slug} />
        ))}
      </ul>
    </div>
  );
}

function ReviewCard({ review, tenantSlug }: { review: AIReview; tenantSlug: string }) {
  const request = useRequestReview(tenantSlug);
  const busy = review.status === 'PENDING' || review.status === 'RUNNING';

  return (
    <li>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base text-foreground">
              <a href={review.pr_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 hover:underline">
                <span className="font-mono text-xs text-muted-foreground">
                  {review.repository}#{review.pr_number}
                </span>
                {review.pr_title}
                <ExternalLink className="size-3.5 opacity-60" aria-hidden />
              </a>
            </CardTitle>
            <div className="flex items-center gap-2">
              <StatusLabel review={review} />
              <Button
                size="sm"
                variant="outline"
                disabled={busy || request.isPending}
                onClick={() => request.mutate(review.pull_request_id)}
              >
                {request.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
                Revisar de novo
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">Revisado {formatRelative(review.created_at)}</p>
        </CardHeader>

        <CardContent className="space-y-3">
          {request.isError && (
            <p role="alert" className="text-sm text-red-300">
              {errorMessage(request.error)}
            </p>
          )}
          {review.status === 'FAILED' && (
            <p className="text-sm text-red-300">Não foi possível revisar: {review.error_message ?? 'erro desconhecido'}</p>
          )}
          {review.publish_error && (
            <p className="text-sm text-amber-300">Os apontamentos não foram publicados no GitHub: {review.publish_error}</p>
          )}
          {review.github_review_url && (
            <a href={review.github_review_url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline">
              Ver a revisão publicada no GitHub
            </a>
          )}
          {review.findings?.map((finding, index) => (
            <FindingRow key={`${review.id}-${index}`} finding={finding} />
          ))}
        </CardContent>
      </Card>
    </li>
  );
}

function StatusLabel({ review }: { review: AIReview }) {
  if (review.status === 'PENDING' || review.status === 'RUNNING') {
    return (
      <Badge variant="outline" className="border-sky-500/50 text-sky-300">
        Revisando…
      </Badge>
    );
  }
  if (review.status === 'FAILED') {
    return (
      <Badge variant="outline" className="border-red-500/50 text-red-300">
        Falhou
      </Badge>
    );
  }
  return (
    <Badge variant="outline">
      {review.findings_count === 0 ? 'Sem apontamentos' : `${review.findings_count} apontamento(s)`}
    </Badge>
  );
}

function FindingRow({ finding }: { finding: ReviewFinding }) {
  const severity = SEVERITY[finding.severity];
  return (
    <div className="space-y-1 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="outline" className={severity.className}>
          {severity.label}
        </Badge>
        <code className="text-muted-foreground">
          {finding.file}
          {finding.line ? `:${finding.line}` : ''}
        </code>
      </div>
      <p className="text-sm">{finding.comment}</p>
    </div>
  );
}
