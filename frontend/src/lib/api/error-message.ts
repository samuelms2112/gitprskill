import { ApiError } from './client';

const FALLBACK_MESSAGE = 'Ocorreu um erro inesperado. Tente novamente.';

/** Mensagem legível para exibir ao usuário, qualquer que seja o tipo de erro. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429 && error.retryAfterSeconds !== null) {
      return `Limite de uso da IA atingido. Tente novamente em ${formatWait(error.retryAfterSeconds)}.`;
    }
    return error.message;
  }
  if (error instanceof Error && error.message) return error.message;
  return FALLBACK_MESSAGE;
}

function formatWait(seconds: number): string {
  if (seconds < 90) return `${seconds} segundos`;
  return `${Math.ceil(seconds / 60)} minutos`;
}
