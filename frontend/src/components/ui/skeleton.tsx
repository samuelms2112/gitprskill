import type { HTMLAttributes } from 'react';

import { cn } from '@/lib/utils';

/** Placeholder de carregamento. Mantém o layout estável enquanto os dados chegam. */
function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />;
}

export { Skeleton };
