'use client';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { ExternalLink, FilePlus2, Timer } from 'lucide-react';
import { useState } from 'react';

import { formatDateTime, formatDuration, formatNumber, formatRelative } from '@/lib/format';
import type { PullRequestReportItem } from '@/lib/api/types';
import { cn } from '@/lib/utils';

import { CategoryBadge, PullRequestStateBadge, RiskBadge, SizeBadge } from './pr-badges';

/** URL pública do avatar do autor. O relatório da API não traz o avatar, só o login. */
function avatarUrl(login: string): string {
  return `https://github.com/${encodeURIComponent(login)}.png?size=72`;
}

function summaryParagraphs(summary: string | null): string[] {
  if (!summary) return [];
  return summary
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph.length > 0);
}

interface PrCardProps {
  item: PullRequestReportItem;
}

/** Card de um PR mergeado com a análise da IA, expansível para ler o resumo completo. */
export function PrCard({ item }: PrCardProps) {
  const [expanded, setExpanded] = useState(false);
  const paragraphs = summaryParagraphs(item.ai_summary);
  const hasLongSummary = paragraphs.join(' ').length > 180 || paragraphs.length > 1;

  return (
    <article className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-muted-foreground/30">
      <div className="flex gap-3">
        <Avatar className="mt-0.5 size-9">
          <AvatarImage src={avatarUrl(item.author)} alt="" />
          <AvatarFallback>{item.author.slice(0, 2)}</AvatarFallback>
        </Avatar>

        <div className="min-w-0 flex-1 space-y-3">
          <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <a
                href={item.html_url}
                target="_blank"
                rel="noopener noreferrer"
                className="group inline-flex max-w-full items-center gap-1.5 font-medium text-foreground hover:underline"
              >
                <span className="truncate">{item.title}</span>
                <ExternalLink className="size-3.5 shrink-0 opacity-50 transition-opacity group-hover:opacity-100" aria-hidden />
                <span className="sr-only">(abre no GitHub)</span>
              </a>
              <p className="mt-0.5 text-xs text-muted-foreground">
                <span className="font-mono">
                  {item.repository}#{item.number}
                </span>
                {' · '}@{item.author}
                {' · '}
                {item.is_merged && item.merged_at ? (
                  <time dateTime={item.merged_at} title={formatDateTime(item.merged_at)}>
                    mergeado {formatRelative(item.merged_at)}
                  </time>
                ) : (
                  <time dateTime={item.created_at} title={formatDateTime(item.created_at)}>
                    aberto {formatRelative(item.created_at)}
                  </time>
                )}
              </p>
            </div>

            <div className="flex shrink-0 flex-wrap gap-1.5">
              <PullRequestStateBadge isMerged={item.is_merged} />
              {item.ai_category && <CategoryBadge category={item.ai_category} />}
              {item.ai_risk_level && <RiskBadge risk={item.ai_risk_level} />}
              {item.pr_size_category && <SizeBadge size={item.pr_size_category} />}
            </div>
          </header>

          {paragraphs.length > 0 ? (
            <div className="space-y-2 text-sm leading-relaxed text-muted-foreground">
              {paragraphs.map((paragraph, index) => (
                <p key={index} className={cn(!expanded && index > 0 && 'hidden', !expanded && 'line-clamp-2')}>
                  {paragraph}
                </p>
              ))}
            </div>
          ) : (
            <p className="text-xs italic text-muted-foreground">
              {item.is_merged
                ? 'Análise de IA pendente para este PR.'
                : 'A análise de IA é feita depois do merge.'}
            </p>
          )}

          <footer className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
            <div className="flex flex-wrap items-center gap-4">
              <span className="flex items-center gap-1.5 font-mono tabular-nums" title="Linhas adicionadas e removidas">
                <span className="text-emerald-400">+{formatNumber(item.additions)}</span>
                <span className="text-red-400">-{formatNumber(item.deletions)}</span>
              </span>
              <span className="flex items-center gap-1.5 tabular-nums" title="Arquivos alterados">
                <FilePlus2 className="size-3.5" aria-hidden />
                {formatNumber(item.changed_files)} arquivos
              </span>
              <span className="flex items-center gap-1.5 tabular-nums" title="Tempo até o merge">
                <Timer className="size-3.5" aria-hidden />
                {formatDuration(item.time_to_merge_seconds)}
              </span>
            </div>

            {hasLongSummary && (
              <Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
                {expanded ? 'Ver menos' : 'Ver resumo completo'}
              </Button>
            )}
          </footer>
        </div>
      </div>
    </article>
  );
}
