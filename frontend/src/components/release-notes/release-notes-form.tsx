'use client';

import { Loader2, Sparkles } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { inclusiveDayCount, periodToDates } from '@/features/reports/period';
import { RELEASE_BRANCHES, MAX_RELEASE_NOTES_RANGE_DAYS } from '@/lib/constants';
import type { ReleaseBranch, ReleaseNotesRequest } from '@/lib/api/types';

export interface ReleaseNotesFormValues {
  startDate: string;
  endDate: string;
  branch: ReleaseBranch | '';
}

interface ReleaseNotesFormProps {
  pending: boolean;
  onSubmit: (request: Omit<ReleaseNotesRequest, 'tenant_slug'>) => void;
}

/** Valores iniciais: últimos 30 dias, em todas as branches principais. */
function initialValues(): ReleaseNotesFormValues {
  const { startDate = '', endDate = '' } = periodToDates('30d');
  return { startDate, endDate, branch: '' };
}

/** Validação local: evita uma ida à API (e uma chamada à IA) para pedidos inválidos. */
export function validateReleaseNotes(values: ReleaseNotesFormValues): string | null {
  if (!values.startDate || !values.endDate) return 'Informe o início e o fim do período.';
  if (values.startDate > values.endDate) return 'A data inicial não pode ser posterior à final.';
  if (inclusiveDayCount(values.startDate, values.endDate) > MAX_RELEASE_NOTES_RANGE_DAYS) {
    return `O período máximo é de ${MAX_RELEASE_NOTES_RANGE_DAYS} dias.`;
  }
  return null;
}

export function ReleaseNotesForm({ pending, onSubmit }: ReleaseNotesFormProps) {
  const [values, setValues] = useState<ReleaseNotesFormValues>(initialValues);
  const [validation, setValidation] = useState<string | null>(null);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const problem = validateReleaseNotes(values);
    setValidation(problem);
    if (problem) return;
    onSubmit({
      start_date: values.startDate,
      end_date: values.endDate,
      base_branch: values.branch === '' ? null : values.branch,
    });
  };

  const update = <K extends keyof ReleaseNotesFormValues>(key: K, value: ReleaseNotesFormValues[K]) => {
    setValues((current) => ({ ...current, [key]: value }));
    setValidation(null);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-foreground">Gerar release notes</CardTitle>
        <CardDescription>
          A IA resume os PRs mergeados no período e na branch escolhidos, agrupados por tipo de mudança.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid gap-4 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end" noValidate>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">Início</span>
            <Input type="date" value={values.startDate} onChange={(event) => update('startDate', event.target.value)} required />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">Fim</span>
            <Input type="date" value={values.endDate} onChange={(event) => update('endDate', event.target.value)} required />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">Branch</span>
            <Select value={values.branch} onChange={(event) => update('branch', event.target.value as ReleaseBranch | '')}>
              <option value="">Todas as principais</option>
              {RELEASE_BRANCHES.map((branch) => (
                <option key={branch.value} value={branch.value}>
                  {branch.label}
                </option>
              ))}
            </Select>
          </label>
          <Button type="submit" disabled={pending} size="default">
            {pending ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
            {pending ? 'Gerando…' : 'Gerar com IA'}
          </Button>
        </form>
        {validation && (
          <p role="alert" className="mt-3 text-sm text-red-300">
            {validation}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
