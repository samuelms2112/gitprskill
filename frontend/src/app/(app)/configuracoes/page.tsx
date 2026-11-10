'use client';

import { ClaudeSessionCard } from '@/components/settings/claude-session-card';
import { MembersCard } from '@/components/settings/members-card';
import { ReviewSkillCard } from '@/components/settings/review-skill-card';
import { EmptyState } from '@/components/ui/feedback';
import { Skeleton } from '@/components/ui/skeleton';
import { useTenant } from '@/features/tenant/tenant-context';

/**
 * Configurações por papel: a sessão do Claude é do sistema (qualquer dono de empresa);
 * usuários e regras de revisão são da empresa ativa (somente o dono dela).
 */
export default function SettingsPage() {
  const { tenants, activeTenant, isLoading } = useTenant();

  if (isLoading) {
    return <Skeleton className="h-64" />;
  }

  const ownsSomeTenant = tenants.some((tenant) => tenant.role === 'OWNER');
  const ownsActiveTenant = activeTenant?.role === 'OWNER';

  if (!ownsSomeTenant) {
    return (
      <EmptyState
        title="Área restrita a donos"
        description="Configurações do sistema e de usuários ficam disponíveis apenas para o dono de uma empresa."
      />
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Configurações</h1>
        <p className="text-sm text-muted-foreground">Gerenciamento do sistema e das pessoas da empresa.</p>
      </header>

      <section aria-labelledby="sistema-titulo" className="space-y-4">
        <h2 id="sistema-titulo" className="text-lg font-semibold">
          Sistema
        </h2>
        <ClaudeSessionCard />
      </section>

      {ownsActiveTenant && activeTenant && (
        <>
          <section aria-labelledby="usuarios-titulo" className="space-y-4">
            <h2 id="usuarios-titulo" className="text-lg font-semibold">
              Usuários
            </h2>
            <MembersCard tenantSlug={activeTenant.slug} tenantName={activeTenant.name} />
          </section>

          <section aria-labelledby="revisao-titulo" className="space-y-4">
            <h2 id="revisao-titulo" className="text-lg font-semibold">
              Revisão de PRs
            </h2>
            <ReviewSkillCard tenantSlug={activeTenant.slug} tenantName={activeTenant.name} />
          </section>
        </>
      )}
    </div>
  );
}
