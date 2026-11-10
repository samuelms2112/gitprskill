import { createStringStore, type StringStore } from '@/lib/browser-store';

const SESSION_KEY = 'ghm.session.token';
const rawStore = createStringStore(SESSION_KEY, 'local');

/**
 * Lê o claim ``exp`` do JWT sem validar a assinatura (quem valida é o backend).
 * Um token malformado ou sem ``exp`` conta como expirado.
 */
export function isTokenExpired(token: string, now: number = Date.now()): boolean {
  try {
    const payload = token.split('.')[1];
    if (!payload) return true;
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const claims = JSON.parse(atob(base64)) as { exp?: unknown };
    return typeof claims.exp !== 'number' || claims.exp * 1000 <= now;
  } catch {
    return true;
  }
}

/**
 * Token de sessão no ``localStorage``: a sessão continua ao reabrir o navegador, até o ``exp``
 * do token. Um token vencido é ignorado na leitura e o usuário volta ao login.
 *
 * Trade-off: diferente do ``sessionStorage``, um script injetado (XSS) consegue ler o token
 * enquanto ele for válido. A correção definitiva é um cookie ``HttpOnly`` emitido pelo backend.
 */
export const sessionTokenStore: StringStore = {
  read() {
    const token = rawStore.read();
    if (token === null || isTokenExpired(token)) return null;
    return token;
  },
  write: rawStore.write,
  clear: rawStore.clear,
  subscribe: rawStore.subscribe,
};
