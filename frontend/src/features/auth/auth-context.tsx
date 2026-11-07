'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

import { ApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';
import type { User } from '@/lib/api/types';

import { sessionTokenStore } from './token-storage';

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

export interface AuthContextValue {
  status: AuthStatus;
  token: string | null;
  user: User | null;
  signIn: (token: string) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Snapshot do servidor: o storage não existe fora do navegador, então a sessão é "desconhecida". */
const UNKNOWN_SESSION = undefined;

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  // A sessão é derivada do storage, não copiada para um estado local: qualquer limpeza
  // (expiração, logout, outra aba) reflete em todo o app sem sincronização manual.
  const storedToken = useSyncExternalStore(
    sessionTokenStore.subscribe,
    sessionTokenStore.read,
    () => UNKNOWN_SESSION,
  );

  const token = storedToken ?? null;

  // Valida o token no backend: um token expirado ou revogado vira sessão anônima.
  const me = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: ({ signal }) => authApi.me(token ?? '', signal),
    enabled: token !== null,
    retry: false,
    staleTime: 5 * 60_000,
  });

  const rejectedToken = me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (!rejectedToken) return;
    sessionTokenStore.clear();
    queryClient.clear();
  }, [rejectedToken, queryClient]);

  const signIn = useCallback((newToken: string) => {
    sessionTokenStore.write(newToken);
  }, []);

  const signOut = useCallback(() => {
    sessionTokenStore.clear();
    // Remove todo o cache: dados de um usuário nunca podem aparecer para o próximo.
    queryClient.clear();
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(() => {
    let status: AuthStatus = 'loading';
    if (storedToken === null) status = 'anonymous';
    else if (me.isSuccess) status = 'authenticated';
    else if (me.isError) status = 'anonymous';

    return {
      status,
      token: status === 'authenticated' ? token : null,
      user: me.data ?? null,
      signIn,
      signOut,
    };
  }, [storedToken, me.isSuccess, me.isError, me.data, token, signIn, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error('useAuth deve ser usado dentro de <AuthProvider>.');
  }
  return context;
}
