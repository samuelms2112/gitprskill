'use client';

import { CheckCircle2, History, Layers, Loader2, RefreshCw, TriangleAlert } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select } from '@/components/ui/select';
import { errorMessage } from '@/lib/api/error-message';
import type { SyncState } from '@/lib/api/types';
import { formatNumber } from '@/lib/format';
import {
  isTerminal,
  useStartSync,
  useStartSyncAll,
  useSyncAllStatus,
  useSyncFromGitHubApp,
  useSyncStatus,
  useTenantRepositories,
} from '@/features/sync/queries';

const HISTORY_OPTIONS = [
  { value: '30', label: 'Últimos 30 dias' },
  { value: '90', label: 'Últimos 90 dias' },
  { value: '365', label: 'Último ano' },
  { value: 'all', label: 'Todo o histórico' },
] as const;

type PeriodValue = (typeof HISTORY_OPTIONS)[number]['value'];

interface HistorySyncCardProps {
  tenantSlug: string;
}

/**
 * Importa o histórico de PRs: de um repositório, ou de todos de uma vez. O total é desconhecido
 * de antemão (o GitHub pagina sem informar a quantidade), então o progresso mostra contagens.
 */
export function HistorySyncCard({ tenantSlug }: HistorySyncCardProps) {
  const repositories = useTenantRepositories(tenantSlug);
  const [chosenRepositoryId, setChosenRepositoryId] = useState<number | null>(null);
  const [period, setPeriod] = useState<PeriodValue>('30');
  const [taskId, setTaskId] = useState<string | null>(null);
  const [allTaskId, setAllTaskId] = useState<string | null>(null);

  const repositoryId = chosenRepositoryId ?? repositories.data?.[0]?.id ?? null;
  const start = useStartSync(tenantSlug);
  const startAll = useStartSyncAll(tenantSlug);
  const refreshRepositories = useSyncFromGitHubApp(tenantSlug);
  const status = useSyncStatus(tenantSlug, repositoryId ?? 0, taskId);
  const allStatus = useSyncAllStatus(tenantSlug, allTaskId);

  const singleRunning = taskId !== null && !isTerminal(status.data?.state);
  const allRunning = allTaskId !== null && !isTerminal(allStatus.data?.state);
  const busy = singleRunning || allRunning || start.isPending || startAll.isPending;
  const noRepositories = !repositories.data?.length;

  const startSingle = () => {
    if (repositoryId === null) return;
    start.mutate(
      { repositoryId, daysBack: period === 'all' ? undefined : Number(period) },
      { onSuccess: (accepted) => setTaskId(accepted.task_id) },
    );
  };

  const startEverything = () => {
    startAll.mutate(undefined, { onSuccess: (accepted) => setAllTaskId(accepted.task_id) });
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-foreground">
            <History className="size-4" aria-hidden />
            Histórico de PRs
          </CardTitle>
          <CardDescription>
            Importa PRs do GitHub, abertos e fechados. Os mergeados passam pela análise de IA automaticamente.
          </CardDescription>
        </div>
        {busy && (
          <Badge className="border-sky-500/30 bg-sky-500/10 text-sky-300">
            <Loader2 className="size-3 animate-spin" aria-hidden />
            Sincronizando
          </Badge>
        )}
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Não vê um repositório? Atualize a lista direto da instalação do GitHub App.
          </p>
          <Button variant="ghost" size="sm" onClick={() => refreshRepositories.mutate()} disabled={refreshRepositories.isPending}>
            {refreshRepositories.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
            Atualizar lista de repositórios
          </Button>
        </div>
        {refreshRepositories.isSuccess && (
          <p role="status" className="text-xs text-emerald-300">
            {refreshRepositories.data.synced} {refreshRepositories.data.synced === 1 ? 'repositório' : 'repositórios'} na instalação.
          </p>
        )}
        {refreshRepositories.isError && (
          <p role="alert" className="text-xs text-red-300">{errorMessage(refreshRepositories.error)}</p>
        )}

        <div className="space-y-3">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Um repositório</p>
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">Repositório</span>
              <Select
                value={repositoryId ?? ''}
                disabled={noRepositories}
                onChange={(event) => setChosenRepositoryId(Number(event.target.value))}
              >
                {(repositories.data ?? []).map((repository) => (
                  <option key={repository.id} value={repository.id}>
                    {repository.full_name}
                  </option>
                ))}
              </Select>
            </label>

            <label className="space-y-1.5">
              <span className="text-xs font-medium text-muted-foreground">Período</span>
              <Select value={period} onChange={(event) => setPeriod(event.target.value as PeriodValue)}>
                {HISTORY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </label>

            <Button onClick={startSingle} disabled={repositoryId === null || busy}>
              <History aria-hidden />
              Sincronizar histórico
            </Button>
          </div>
        </div>

        <div className="space-y-3 border-t border-border pt-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Todos os repositórios</p>
            <Button variant="outline" onClick={startEverything} disabled={noRepositories || busy}>
              <Layers aria-hidden />
              Sincronizar todos os repositórios
            </Button>
          </div>
          {allTaskId && allStatus.data && (
            <SyncProgress state={allStatus.data.state} counts={allStatus.data} error={allStatus.data.error} label="Todos os repositórios" />
          )}
        </div>

        {!repositories.isPending && noRepositories && (
          <p className="text-sm text-muted-foreground">
            Nenhum repositório conectado ainda. Eles aparecem aqui assim que o GitHub App é instalado na organização.
          </p>
        )}

        {(start.isError || startAll.isError) && (
          <p role="alert" className="text-sm text-red-300">
            {errorMessage(start.error ?? startAll.error)}
          </p>
        )}

        {taskId && status.data && (
          <SyncProgress state={status.data.state} counts={status.data} error={status.data.error} label="Repositório" />
        )}
      </CardContent>
    </Card>
  );
}

interface SyncProgressProps {
  state: SyncState;
  counts: { examined: number; stored: number; new: number; skipped: number };
  error: string | null;
  label: string;
}

function SyncProgress({ state, counts, error, label }: SyncProgressProps) {
  if (state === 'completed') {
    return (
      <p className="flex items-center gap-2 text-sm text-emerald-300" role="status">
        <CheckCircle2 className="size-4" aria-hidden />
        {label}: concluído, {formatNumber(counts.new)} {counts.new === 1 ? 'PR novo importado' : 'PRs novos importados'}.
      </p>
    );
  }

  if (state === 'failed') {
    return (
      <p role="alert" className="flex items-center gap-2 text-sm text-red-300">
        <TriangleAlert className="size-4" aria-hidden />
        {label}: não foi possível concluir. {error ?? ''}
      </p>
    );
  }

  return (
    <div className="space-y-2" role="status" aria-live="polite">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full w-1/3 animate-pulse rounded-full bg-sky-400" />
      </div>
      <p className="text-xs text-muted-foreground">
        {label}: {state === 'queued' ? 'na fila, aguardando o worker…' : 'processando…'} {formatNumber(counts.examined)} PRs analisados ·{' '}
        {formatNumber(counts.stored)} importados · {formatNumber(counts.new)} novos · {formatNumber(counts.skipped)} ignorados
      </p>
    </div>
  );
}
