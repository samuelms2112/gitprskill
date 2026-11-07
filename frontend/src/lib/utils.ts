import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Combina classes condicionais e resolve conflitos do Tailwind (ex.: ``p-2`` vs ``p-4``). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
