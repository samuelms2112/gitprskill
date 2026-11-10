'use client';

import { ClaudeSessionCard } from '@/components/settings/claude-session-card';

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Configurações</h1>
        <p className="text-sm text-muted-foreground">Gerenciamento do sistema.</p>
      </header>

      <section aria-labelledby="sistema-titulo" className="space-y-4">
        <h2 id="sistema-titulo" className="text-lg font-semibold">
          Sistema
        </h2>
        <ClaudeSessionCard />
      </section>
    </div>
  );
}
