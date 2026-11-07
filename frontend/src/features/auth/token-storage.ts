import { createStringStore } from '@/lib/browser-store';

/**
 * Token de sessão no ``sessionStorage``: vale apenas para a aba atual e some ao fechá-la.
 * Não usamos ``localStorage`` para não deixar o token disponível por tempo indeterminado.
 *
 * Trade-off conhecido: um script injetado (XSS) ainda lê o token enquanto a aba estiver
 * aberta. A correção definitiva é um cookie ``HttpOnly`` emitido pelo backend.
 */
export const sessionTokenStore = createStringStore('ghm.session.token', 'session');
