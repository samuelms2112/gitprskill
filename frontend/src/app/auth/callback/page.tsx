'use client';

import { Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useRef } from 'react';

import { useAuth } from '@/features/auth/auth-context';

/**
 * Recebe o token do backend pelo fragmento da URL (``#access_token=...``) e inicia a sessão.
 * O fragmento nunca é enviado ao servidor; ele é removido da barra de endereços logo após a leitura.
 *
 * Sem token, o usuário volta ao login com ``?error=`` (a mensagem é exibida lá).
 */
export default function AuthCallbackPage() {
  const { signIn } = useAuth();
  const router = useRouter();
  // O React em modo estrito executa efeitos duas vezes; a primeira já apaga o fragmento.
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const token = new URLSearchParams(window.location.hash.slice(1)).get('access_token');
    window.history.replaceState(null, '', window.location.pathname);

    if (token) {
      signIn(token);
      router.replace('/dashboard');
    } else {
      router.replace('/login?error=callback');
    }
  }, [signIn, router]);

  return (
    <main className="flex min-h-screen items-center justify-center gap-3 p-4 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      Entrando…
    </main>
  );
}
