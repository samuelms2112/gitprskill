import { PERIOD_OPTIONS, type PeriodValue } from '@/lib/constants';
import { toIsoDate } from '@/lib/format';

const DAY_MS = 86_400_000;

/** Converte um período predefinido em datas inclusivas (``YYYY-MM-DD``). ``all`` não limita datas. */
export function periodToDates(period: PeriodValue, today: Date = new Date()): { startDate?: string; endDate?: string } {
  const option = PERIOD_OPTIONS.find((item) => item.value === period);
  if (!option || option.days === null) return {};
  const start = new Date(today.getTime() - (option.days - 1) * DAY_MS);
  return { startDate: toIsoDate(start), endDate: toIsoDate(today) };
}

/** Quantidade de dias de um intervalo inclusivo, usada para validar as release notes. */
export function inclusiveDayCount(startDate: string, endDate: string): number {
  const start = Date.parse(`${startDate}T00:00:00Z`);
  const end = Date.parse(`${endDate}T00:00:00Z`);
  return Math.round((end - start) / DAY_MS) + 1;
}
