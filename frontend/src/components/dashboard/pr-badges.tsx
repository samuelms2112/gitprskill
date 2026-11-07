import { Badge } from '@/components/ui/badge';
import { AI_RISK_LEVELS } from '@/lib/constants';
import type { AICategory, AIRiskLevel, PRSizeCategory } from '@/lib/api/types';
import { cn } from '@/lib/utils';

/** Cores dedicadas por categoria de IA. Pares fundo/texto com contraste suficiente no tema escuro. */
const CATEGORY_STYLES: Record<AICategory, { label: string; className: string }> = {
  FEATURE: { label: 'Feature', className: 'border-sky-500/30 bg-sky-500/10 text-sky-300' },
  BUGFIX: { label: 'Bugfix', className: 'border-rose-500/30 bg-rose-500/10 text-rose-300' },
  REFACTOR: { label: 'Refatoração', className: 'border-teal-500/30 bg-teal-500/10 text-teal-300' },
  SECURITY: { label: 'Segurança', className: 'border-violet-500/30 bg-violet-500/10 text-violet-300' },
  CHORE: { label: 'Manutenção', className: 'border-zinc-500/40 bg-zinc-500/10 text-zinc-300' },
};

const RISK_STYLES: Record<AIRiskLevel, string> = {
  LOW: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  MEDIUM: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  HIGH: 'border-red-500/40 bg-red-500/15 text-red-300',
};

const SIZE_STYLES: Record<PRSizeCategory, string> = {
  XS: 'border-emerald-500/30 text-emerald-300',
  S: 'border-lime-500/30 text-lime-300',
  M: 'border-amber-500/30 text-amber-300',
  L: 'border-orange-500/30 text-orange-300',
  XL: 'border-red-500/40 text-red-300',
};

export function CategoryBadge({ category }: { category: AICategory }) {
  const style = CATEGORY_STYLES[category];
  return <Badge className={cn(style.className)}>{style.label}</Badge>;
}

export function RiskBadge({ risk }: { risk: AIRiskLevel }) {
  return (
    <Badge className={RISK_STYLES[risk]} title="Avaliação de impacto feita pela IA">
      {AI_RISK_LEVELS[risk].label}
    </Badge>
  );
}

export function SizeBadge({ size }: { size: PRSizeCategory }) {
  return (
    <Badge className={cn('font-mono', SIZE_STYLES[size])} title="Tamanho do PR (linhas alteradas)">
      {size}
    </Badge>
  );
}

/** Estado do PR: verde para abertos, roxo para mergeados. */
export function PullRequestStateBadge({ isMerged }: { isMerged: boolean }) {
  return isMerged ? (
    <Badge className="border-violet-500/30 bg-violet-500/10 text-violet-300">Mergeado</Badge>
  ) : (
    <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-300">Aberto</Badge>
  );
}
