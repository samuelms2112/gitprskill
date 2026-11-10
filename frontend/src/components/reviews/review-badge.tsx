'use client';

import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import Link from 'next/link';

import type { AIReview } from '@/lib/api/reviews';

/** Estado da revisão automática no card do PR: revisando, com apontamentos, sem apontamentos ou falhou. */
export function ReviewBadge({ review }: { review: AIReview | undefined }) {
  if (!review) return null;

  if (review.status === 'PENDING' || review.status === 'RUNNING') {
    return (
      <span role="status" className="inline-flex items-center gap-1.5 text-xs text-sky-300">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        Revisando…
      </span>
    );
  }

  if (review.status === 'FAILED') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-red-300" title={review.error_message ?? undefined}>
        <XCircle className="size-3.5" aria-hidden />
        Revisão falhou
      </span>
    );
  }

  if (review.findings_count === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-emerald-300">
        <CheckCircle2 className="size-3.5" aria-hidden />
        Revisado: sem apontamentos
      </span>
    );
  }

  return (
    <Link href="/revisoes" className="text-xs text-amber-300 underline-offset-4 hover:underline">
      Revisão: {review.findings_count} apontamento(s)
    </Link>
  );
}
