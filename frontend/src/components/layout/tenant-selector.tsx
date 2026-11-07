'use client';

import { Building2, ChevronDown } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useTenant } from '@/features/tenant/tenant-context';
import type { MemberRole } from '@/lib/api/types';

const ROLE_LABELS: Record<MemberRole, string> = {
  OWNER: 'Proprietário',
  DEVELOPER: 'Desenvolvedor',
  VIEWER: 'Leitor',
};

/** Seletor da empresa ativa. Troca os dados de todo o painel ao escolher outra. */
export function TenantSelector() {
  const { tenants, activeTenant, selectTenant, isLoading } = useTenant();

  if (isLoading) {
    return <div className="h-8 w-40 animate-pulse rounded-md bg-muted" aria-label="Carregando empresas" />;
  }

  if (!activeTenant) {
    return <span className="text-sm text-muted-foreground">Sem empresa</span>;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-2 px-2" aria-label="Trocar de empresa">
          <Building2 aria-hidden />
          <span className="max-w-[12rem] truncate font-medium">{activeTenant.name}</span>
          <ChevronDown className="text-muted-foreground" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Empresas</DropdownMenuLabel>
        {tenants.map((tenant) => (
          <DropdownMenuCheckboxItem
            key={tenant.slug}
            checked={tenant.slug === activeTenant.slug}
            onCheckedChange={() => selectTenant(tenant.slug)}
            className="justify-between"
          >
            <span className="truncate">{tenant.name}</span>
            <Badge variant="outline" className="ml-2 shrink-0">
              {ROLE_LABELS[tenant.role]}
            </Badge>
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator />
        <p className="px-2 py-1.5 text-xs text-muted-foreground">
          Para adicionar uma empresa, instale o GitHub App na organização.
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
