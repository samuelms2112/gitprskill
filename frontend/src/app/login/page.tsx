'use client';

import { AlertTriangle, GitPullRequest, ShieldCheck } from 'lucide-react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Suspense, useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/features/auth/auth-context';
import { API_BASE_URL } from '@/lib/api/client';

const LOGIN_ERRORS: Record<string, string> = {
  callback: 'Não foi possível concluir o login com o GitHub. Tente novamente.',
};

export default function LoginPage() {
  // useSearchParams exige um limite de Suspense no App Router para a renderização estática.
  return (
    <Suspense fallback={null}>
      <LoginContent />
    </Suspense>
  );
}

function LoginContent() {
  const { status } = useAuth();
  const router = useRouter();
  const errorCode = useSearchParams().get('error');

  useEffect(() => {
    if (status === 'authenticated') router.replace('/dashboard');
  }, [status, router]);

  // Navegação de página inteira: o backend redireciona para o GitHub e, depois, de volta ao frontend.
  const loginUrl = `${API_BASE_URL}/api/v1/auth/github/login`;
  const errorMessage = errorCode ? (LOGIN_ERRORS[errorCode] ?? 'Erro ao entrar. Tente novamente.') : null;

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="flex size-12 items-center justify-center rounded-xl border border-border bg-card">
            <GitPullRequest className="size-6" aria-hidden />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">Gestão de Pull Requests</h1>
          <p className="text-sm text-muted-foreground">Métricas de engenharia e resumos com IA para seu time.</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-foreground">Entrar</CardTitle>
            <CardDescription>Use sua conta do GitHub. Só vemos as empresas em que você é membro.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {errorMessage && (
              <p role="alert" className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-red-300">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                {errorMessage}
              </p>
            )}
            <Button asChild size="lg" className="w-full">
              <a href={loginUrl}>
                <GitPullRequest aria-hidden />
                Entrar com GitHub
              </a>
            </Button>
            <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
              <ShieldCheck className="size-3.5" aria-hidden />
              Não armazenamos seu token do GitHub.
            </p>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
