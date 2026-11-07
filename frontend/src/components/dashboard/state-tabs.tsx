'use client';

import { cn } from '@/lib/utils';
import type { PRStateFilter } from '@/lib/api/types';

const TABS: readonly { value: PRStateFilter; label: string }[] = [
  { value: 'all', label: 'Todos' },
  { value: 'open', label: 'Em aberto' },
  { value: 'merged', label: 'Mergeados' },
];

interface StateTabsProps {
  value: PRStateFilter;
  onChange: (next: PRStateFilter) => void;
}

/**
 * Abas do feed por estado do PR. Acessíveis pelo teclado: as setas trocam de aba,
 * como no padrão WAI-ARIA para ``tablist``.
 */
export function StateTabs({ value, onChange }: StateTabsProps) {
  const focusTab = (index: number) => {
    const next = TABS[(index + TABS.length) % TABS.length];
    if (next) onChange(next.value);
    document.getElementById(`state-tab-${next?.value}`)?.focus();
  };

  return (
    <div role="tablist" aria-label="Estado dos Pull Requests" className="inline-flex rounded-lg border border-border bg-card p-1">
      {TABS.map((tab, index) => {
        const selected = tab.value === value;
        return (
          <button
            key={tab.value}
            id={`state-tab-${tab.value}`}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.value)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowRight') focusTab(index + 1);
              if (event.key === 'ArrowLeft') focusTab(index - 1);
            }}
            className={cn(
              'rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              selected ? 'bg-accent text-accent-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
