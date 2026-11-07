import { cn } from '@/lib/utils';
import { formatNumber } from '@/lib/format';
import type { PRSizeCategory, SizeDistribution as Distribution } from '@/lib/api/types';

interface SizeDistributionProps {
  distribution: Distribution | undefined;
  total: number;
  sizes: readonly { value: PRSizeCategory; range: string }[];
}

const SEGMENT_COLORS: Record<PRSizeCategory, string> = {
  XS: 'bg-emerald-400',
  S: 'bg-lime-400',
  M: 'bg-amber-400',
  L: 'bg-orange-400',
  XL: 'bg-red-400',
};

/** Barra empilhada com a proporção de cada faixa de tamanho, e legenda com contagens. */
export function SizeDistribution({ distribution, total, sizes }: SizeDistributionProps) {
  const counts = distribution ?? { XS: 0, S: 0, M: 0, L: 0, XL: 0 };

  return (
    <div className="space-y-3">
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted"
        role="img"
        aria-label={sizes.map(({ value }) => `${value}: ${counts[value]}`).join(', ')}
      >
        {total > 0 &&
          sizes.map(({ value }) => {
            const share = (counts[value] / total) * 100;
            return share > 0 ? (
              <div key={value} className={cn('h-full', SEGMENT_COLORS[value])} style={{ width: `${share}%` }} />
            ) : null;
          })}
      </div>
      <ul className="grid grid-cols-5 gap-2 text-xs">
        {sizes.map(({ value, range }) => (
          <li key={value} className="space-y-0.5">
            <span className="flex items-center gap-1.5 font-mono font-medium text-foreground">
              <span className={cn('size-2 rounded-full', SEGMENT_COLORS[value])} aria-hidden />
              {value}
            </span>
            <span className="block tabular-nums text-muted-foreground">{formatNumber(counts[value])}</span>
            <span className="hidden text-[10px] text-muted-foreground/70 xl:block">{range}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
