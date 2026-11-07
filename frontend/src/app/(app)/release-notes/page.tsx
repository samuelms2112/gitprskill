'use client';

import { ReleaseNotesForm } from '@/components/release-notes/release-notes-form';
import { ReleaseNotesOutput } from '@/components/release-notes/release-notes-output';
import { EmptyState, ErrorState } from '@/components/ui/feedback';
import { Skeleton } from '@/components/ui/skeleton';
import { useReleaseNotes } from '@/features/reports/queries';
import { useTenant } from '@/features/tenant/tenant-context';
import { errorMessage } from '@/lib/api/error-message';

export default function ReleaseNotesPage() {
  const { activeTenant, isLoading } = useTenant();

  if (isLoading) {
    return <Skeleton className="h-64" />;
  }

  if (!activeTenant) {
    return (
      <EmptyState
        title="Nenhuma empresa disponível"
        description="Você precisa ser membro de uma empresa para gerar release notes."
      />
    );
  }

  // Remontar ao trocar de empresa descarta um resultado gerado para outra empresa.
  return <ReleaseNotesContent key={activeTenant.slug} tenantSlug={activeTenant.slug} />;
}

function ReleaseNotesContent({ tenantSlug }: { tenantSlug: string }) {
  const generate = useReleaseNotes();

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Release notes</h1>
        <p className="text-sm text-muted-foreground">
          Gere um resumo de versão a partir dos PRs mergeados, pronto para colar no changelog.
        </p>
      </header>

      <ReleaseNotesForm
        pending={generate.isPending}
        onSubmit={(request) => generate.mutate({ ...request, tenant_slug: tenantSlug })}
      />

      {generate.isError && <ErrorState message={errorMessage(generate.error)} />}
      {generate.data && <ReleaseNotesOutput result={generate.data} />}
    </div>
  );
}
