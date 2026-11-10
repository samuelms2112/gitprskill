'use client';

import { Loader2 } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorState } from '@/components/ui/feedback';
import { Skeleton } from '@/components/ui/skeleton';
import { useReviewSkill, useUpdateSkillRule } from '@/features/reviews/queries';
import { errorMessage } from '@/lib/api/error-message';
import type { SkillRule } from '@/lib/api/reviews';

/** Regras da skill de revisão da empresa. Editáveis pelo dono; a próxima revisão já usa o texto novo. */
export function ReviewSkillCard({ tenantSlug, tenantName }: { tenantSlug: string; tenantName: string }) {
  const skill = useReviewSkill(tenantSlug, true);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Regras de revisão de {tenantName}</CardTitle>
        <CardDescription>
          Cada PR aberto é revisado com estas regras. Edite o texto para ajustar o que a revisão aponta.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {skill.isPending && <Skeleton className="h-40" />}
        {skill.isError && <ErrorState message={errorMessage(skill.error)} onRetry={() => void skill.refetch()} />}
        {skill.data?.rules.map((rule) => (
          // A chave muda a cada versão salva: o editor volta a mostrar o texto do servidor.
          <RuleEditor
            key={`${rule.filename}-${rule.updated_at}`}
            tenantSlug={tenantSlug}
            rule={rule}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function RuleEditor({ tenantSlug, rule }: { tenantSlug: string; rule: SkillRule }) {
  const [draft, setDraft] = useState(rule.content);
  const update = useUpdateSkillRule(tenantSlug);

  const dirty = draft !== rule.content;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={`rule-${rule.filename}`} className="font-mono text-sm">
          {rule.filename}
        </label>
      </div>
      <textarea
        id={`rule-${rule.filename}`}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        rows={8}
        maxLength={20000}
        spellCheck={false}
        className="w-full rounded-md border border-input bg-transparent p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
      {update.isError && (
        <p role="alert" className="text-sm text-red-300">
          {errorMessage(update.error)}
        </p>
      )}
      <div className="flex justify-end">
        <Button
          size="sm"
          disabled={!dirty || draft.trim() === '' || update.isPending}
          onClick={() => update.mutate({ filename: rule.filename, content: draft })}
        >
          {update.isPending && <Loader2 className="animate-spin" aria-hidden />}
          Salvar regra
        </Button>
      </div>
    </div>
  );
}
