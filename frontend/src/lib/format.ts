/** Formatação de valores para exibição, sempre em pt-BR. */

const DATE_TIME = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium', timeStyle: 'short' });
const NUMBER = new Intl.NumberFormat('pt-BR');
const RELATIVE = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' });

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86_400;

/** Duração em formato compacto: ``45s``, ``12min``, ``3h 20min``, ``2d 4h``. ``null`` vira travessão. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < MINUTE) return `${Math.round(seconds)}s`;
  if (seconds < HOUR) return `${Math.round(seconds / MINUTE)}min`;
  if (seconds < DAY) {
    const hours = Math.floor(seconds / HOUR);
    const minutes = Math.round((seconds % HOUR) / MINUTE);
    return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}min`;
  }
  const days = Math.floor(seconds / DAY);
  const hours = Math.round((seconds % DAY) / HOUR);
  return hours === 0 ? `${days}d` : `${days}d ${hours}h`;
}

/** Data e hora absolutas, para tooltips e metadados. */
export function formatDateTime(iso: string): string {
  return DATE_TIME.format(new Date(iso));
}

/** Tempo relativo ("há 3 dias", "ontem"), com fallback para data absoluta em períodos longos. */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const diffSeconds = (new Date(iso).getTime() - now.getTime()) / 1000;
  const absSeconds = Math.abs(diffSeconds);
  if (absSeconds < MINUTE) return 'agora';
  if (absSeconds < HOUR) return RELATIVE.format(Math.round(diffSeconds / MINUTE), 'minute');
  if (absSeconds < DAY) return RELATIVE.format(Math.round(diffSeconds / HOUR), 'hour');
  if (absSeconds < 30 * DAY) return RELATIVE.format(Math.round(diffSeconds / DAY), 'day');
  return formatDateTime(iso);
}

export function formatNumber(value: number): string {
  return NUMBER.format(value);
}

/** Linhas adicionadas e removidas no formato ``+45 / -12``. */
export function formatLineChanges(additions: number, deletions: number): string {
  return `+${formatNumber(additions)} / -${formatNumber(deletions)}`;
}

/** Converte uma data local em ``YYYY-MM-DD`` (formato aceito pela API). */
export function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
