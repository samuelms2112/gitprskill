/**
 * Cliente HTTP da API FastAPI.
 *
 * Erros do backend chegam em dois formatos e são normalizados aqui:
 *   - ``{"error": {"code", "message", "details"}}`` (erros de aplicação);
 *   - ``{"detail": [{"msg", "loc"}]}`` (validação de entrada do FastAPI).
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryAfterSeconds: number | null;

  constructor(message: string, status: number, code: string | null, retryAfterSeconds: number | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');
const API_PREFIX = '/api/v1';

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${API_PREFIX}${path}`;
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  token?: string | null;
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', token, body, signal } = options;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError('Não foi possível conectar à API. Verifique sua conexão.', 0, 'network_error', null);
  }

  if (!response.ok) throw await toApiError(response);
  // 204 No Content (ex.: remoção de membro) não tem corpo.
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => null);
  const { code, message } = describeError(body, response.status);
  return new ApiError(message, response.status, code, parseRetryAfter(response.headers.get('Retry-After')));
}

interface ApplicationErrorBody {
  error: { code: string; message: string };
}

interface ValidationErrorBody {
  detail: Array<{ msg: string }>;
}

function describeError(body: unknown, status: number): { code: string | null; message: string } {
  if (isApplicationError(body)) return { code: body.error.code, message: body.error.message };
  if (isValidationError(body)) {
    return { code: 'validation_error', message: body.detail.map((item) => item.msg).join('; ') };
  }
  return { code: null, message: `Erro ${status} ao comunicar com o servidor.` };
}

function isApplicationError(body: unknown): body is ApplicationErrorBody {
  return typeof body === 'object' && body !== null && 'error' in body && typeof (body as ApplicationErrorBody).error?.message === 'string';
}

function isValidationError(body: unknown): body is ValidationErrorBody {
  return typeof body === 'object' && body !== null && Array.isArray((body as ValidationErrorBody).detail);
}

function parseRetryAfter(header: string | null): number | null {
  if (header === null) return null;
  const seconds = Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? Math.round(seconds) : null;
}
