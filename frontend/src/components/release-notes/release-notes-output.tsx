'use client';

import { Check, Copy } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { ReleaseNotesResponse } from '@/lib/api/types';

const COPIED_FEEDBACK_MS = 2000;

/**
 * Renderiza as release notes em Markdown. ``react-markdown`` não interpreta HTML bruto
 * por padrão, então conteúdo malicioso gerado pela IA não vira marcação ativa na página.
 */
export function ReleaseNotesOutput({ result }: { result: ReleaseNotesResponse }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(result.markdown);
      setCopied(true);
    } catch {
      // Sem permissão de área de transferência: o usuário ainda pode selecionar o texto.
      setCopied(false);
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1">
          <CardTitle className="text-foreground">Release notes</CardTitle>
          <CardDescription>
            {result.pr_count} {result.pr_count === 1 ? 'PR' : 'PRs'} de {result.start_date} a {result.end_date}
            {result.base_branch ? ` · branch ${result.base_branch}` : ' · todas as branches principais'}
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={copy} aria-live="polite">
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? 'Copiado' : 'Copiar Release Notes'}
        </Button>
      </CardHeader>
      <CardContent>
        <article
          className="space-y-3 text-sm leading-relaxed text-foreground/90 [&_a]:text-sky-300 [&_a]:underline-offset-4 [&_a:hover]:underline [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:font-mono [&_code]:text-xs [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mt-6 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:font-medium [&_li]:ml-5 [&_li]:list-disc [&_li]:marker:text-muted-foreground [&_ol>li]:list-decimal [&_p]:text-muted-foreground"
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.markdown}</ReactMarkdown>
        </article>
      </CardContent>
    </Card>
  );
}
