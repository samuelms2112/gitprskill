'use client';

import { useQuery } from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

import { tenantsApi } from '@/lib/api/endpoints';
import type { TenantMembership } from '@/lib/api/types';
import { createStringStore } from '@/lib/browser-store';

import { useAuth } from '../auth/auth-context';

/** Última empresa escolhida. Preferência de visualização, não dado sensível: fica no localStorage. */
export const tenantSlugStore = createStringStore('ghm.tenant.slug', 'local');

export interface TenantContextValue {
  tenants: TenantMembership[];
  activeTenant: TenantMembership | null;
  isLoading: boolean;
  selectTenant: (slug: string) => void;
}

const TenantContext = createContext<TenantContextValue | null>(null);

export function TenantProvider({ children }: { children: ReactNode }) {
  const { status, token } = useAuth();
  const selectedSlug = useSyncExternalStore(tenantSlugStore.subscribe, tenantSlugStore.read, () => null);

  const memberships = useQuery({
    queryKey: ['tenants'],
    queryFn: ({ signal }) => tenantsApi.list(token ?? '', signal),
    enabled: status === 'authenticated' && token !== null,
  });

  const tenants = useMemo(() => memberships.data ?? [], [memberships.data]);

  // Se a empresa salva não pertence mais ao usuário, usa a primeira disponível.
  const activeTenant = useMemo(
    () => tenants.find((tenant) => tenant.slug === selectedSlug) ?? tenants[0] ?? null,
    [tenants, selectedSlug],
  );

  const selectTenant = useCallback((slug: string) => {
    tenantSlugStore.write(slug);
  }, []);

  const value = useMemo<TenantContextValue>(
    () => ({
      tenants,
      activeTenant,
      isLoading: status === 'loading' || memberships.isPending,
      selectTenant,
    }),
    [tenants, activeTenant, status, memberships.isPending, selectTenant],
  );

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant(): TenantContextValue {
  const context = useContext(TenantContext);
  if (context === null) {
    throw new Error('useTenant deve ser usado dentro de <TenantProvider>.');
  }
  return context;
}
