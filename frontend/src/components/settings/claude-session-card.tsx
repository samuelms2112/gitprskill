'use client';

import { CheckCircle2, KeyRound, Loader2, RefreshCw, XCircle } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ErrorState } from '@/components/ui/feedback';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useClaudeStatus,
  useCompleteClaudeReauth,
  useRefreshClaudeStatus,
  useStartClaudeReauth,
} from '@/features/system/queries';
import { errorMessage } from '@/lib/api/error-message';
import type { ClaudeReauthStart, ClaudeStatus } from '@/lib/api/system';
import { formatDateTime, formatRelative } from '@/lib/format';

/** Sessão do Claude Code CLI: badge de estado, teste manual e renovação do login. */
export function ClaudeSessionCard() {
  const status = useClaudeStatus();
  const refresh = useRefreshClaudeStatus();
  const [renewOpen, setRenewOpen] = useState(false);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <CardTitle>Sessão do Claude (análise de PRs)</CardTitle>
            <CardDescription>
              A análise dos PRs usa o login do Claude Code no servidor. Quando a sessão expira, a fila pausa
              e nenhum PR é descartado.
            </CardDescription>
          </div>
          {status.data && <SessionBadge status={status.data} />}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {status.isPending && <Skeleton className="h-16" />}

        {status.isError && !status.data && (
          <ErrorState
            message={errorMessage(status.error)}
            onRetry={() => void status.refetch()}
          />
        )}

        {status.data && <StatusDetails status={status.data} />}

        {refresh.isError && (
          <p role="alert" className="text-sm text-red-300">
            {errorMessage(refresh.error)}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
            Verificar agora
          </Button>
          <Button size="sm" onClick={() => setRenewOpen(true)}>
            <KeyRound aria-hidden />
            Renovar sessão
          </Button>
        </div>
      </CardContent>

      <RenewSessionDialog open={renewOpen} onOpenChange={setRenewOpen} />
    </Card>
  );
}

function SessionBadge({ status }: { status: ClaudeStatus }) {
  if (status.authenticated) {
    return (
      <Badge variant="default" className="text-emerald-300" aria-label="Status: conectado">
        <span aria-hidden>🟢</span> Conectado
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-destructive/50 text-red-300" aria-label="Status: sessão expirada">
      <span aria-hidden>🔴</span> Sessão Expirada
    </Badge>
  );
}

function StatusDetails({ status }: { status: ClaudeStatus }) {
  return (
    <div className="space-y-2 text-sm">
      <p className="text-muted-foreground">
        Último teste:{' '}
        <time dateTime={status.last_checked} title={formatDateTime(status.last_checked)}>
          {formatRelative(status.last_checked)}
        </time>
      </p>
      {status.error_message && (
        <p role="status" className="flex items-start gap-2 text-muted-foreground">
          {status.authenticated ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-400" aria-hidden />
          ) : (
            <XCircle className="mt-0.5 size-4 shrink-0 text-red-400" aria-hidden />
          )}
          {status.error_message}
        </p>
      )}
    </div>
  );
}

type RenewStep = 'idle' | 'awaiting-code';

function RenewSessionDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const start = useStartClaudeReauth();
  const complete = useCompleteClaudeReauth();
  const [login, setLogin] = useState<ClaudeReauthStart | null>(null);
  const [code, setCode] = useState('');
  const [confirmed, setConfirmed] = useState<boolean | null>(null);

  const reset = () => {
    setLogin(null);
    setCode('');
    setConfirmed(null);
    start.reset();
    complete.reset();
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const step: RenewStep = login ? 'awaiting-code' : 'idle';

  const handleStart = () => {
    start.mutate(undefined, {
      onSuccess: (result) => setLogin(result),
    });
  };

  const handleConfirm = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!login) return;
    complete.mutate(
      { loginId: login.login_id, code: code.trim() },
      { onSuccess: (result) => setConfirmed(result.authenticated) },
    );
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Renovar sessão do Claude</DialogTitle>
          <DialogDescription>
            Gere o link de autorização, abra-o, autorize o acesso e copie o código que o Claude mostrar.
          </DialogDescription>
        </DialogHeader>

        {step === 'idle' && (
          <div className="space-y-3">
            {start.isError && (
              <p role="alert" className="text-sm text-red-300">
                {errorMessage(start.error)}
              </p>
            )}
            <Button onClick={handleStart} disabled={start.isPending} className="w-full">
              {start.isPending && <Loader2 className="animate-spin" aria-hidden />}
              Gerar link de autorização
            </Button>
          </div>
        )}

        {step === 'awaiting-code' && login && confirmed !== true && (
          <form onSubmit={handleConfirm} className="space-y-4">
            <div className="space-y-2 text-sm">
              <p className="font-medium">1. Abra o link e autorize</p>
              <a
                href={login.login_url}
                target="_blank"
                rel="noopener noreferrer"
                className="block break-all text-primary underline-offset-4 hover:underline"
              >
                {login.login_url}
              </a>
            </div>

            <div className="space-y-2 text-sm">
              <label htmlFor="claude-code" className="font-medium">
                2. Cole o código de autorização
              </label>
              <Input
                id="claude-code"
                autoComplete="off"
                spellCheck={false}
                value={code}
                onChange={(event) => setCode(event.target.value)}
                maxLength={512}
                required
              />
            </div>

            {confirmed === false && complete.data?.error_message && (
              <p role="alert" className="text-sm text-red-300">
                {complete.data.error_message}
              </p>
            )}
            {complete.isError && (
              <p role="alert" className="text-sm text-red-300">
                {errorMessage(complete.error)}
              </p>
            )}

            <DialogFooter>
              <Button type="submit" disabled={complete.isPending || code.trim() === ''}>
                {complete.isPending && <Loader2 className="animate-spin" aria-hidden />}
                Confirmar login
              </Button>
            </DialogFooter>
          </form>
        )}

        {confirmed === true && (
          <div role="status" className="flex items-center gap-2 text-sm text-emerald-300">
            <CheckCircle2 className="size-4" aria-hidden />
            Sessão renovada. A fila foi retomada.
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
