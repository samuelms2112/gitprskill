/**
 * Store de texto sobre ``sessionStorage`` ou ``localStorage``, compatível com ``useSyncExternalStore``.
 *
 * Escritas na mesma aba não disparam o evento ``storage`` nativo, então notificamos os
 * ouvintes manualmente. Cada acesso é protegido: o storage pode estar bloqueado pelo navegador
 * (modo privado, políticas corporativas) e a aplicação deve continuar funcionando sem ele.
 */

type StorageKind = 'session' | 'local';

export interface StringStore {
  read: () => string | null;
  write: (value: string) => void;
  clear: () => void;
  subscribe: (listener: () => void) => () => void;
}

export function createStringStore(key: string, kind: StorageKind): StringStore {
  const listeners = new Set<() => void>();

  const storage = (): Storage | null => {
    try {
      return kind === 'session' ? window.sessionStorage : window.localStorage;
    } catch {
      return null;
    }
  };

  const notify = () => listeners.forEach((listener) => listener());

  return {
    read() {
      try {
        return storage()?.getItem(key) ?? null;
      } catch {
        return null;
      }
    },
    write(value) {
      try {
        storage()?.setItem(key, value);
      } catch {
        // Sem storage, o valor vale só em memória, até a próxima recarga.
      }
      notify();
    },
    clear() {
      try {
        storage()?.removeItem(key);
      } catch {
        // Nada a remover se o storage não está disponível.
      }
      notify();
    },
    subscribe(listener) {
      listeners.add(listener);
      // Outras abas (localStorage) e outras janelas recebem mudanças pelo evento nativo.
      const onStorage = (event: StorageEvent) => {
        if (event.key === key || event.key === null) listener();
      };
      window.addEventListener('storage', onStorage);
      return () => {
        listeners.delete(listener);
        window.removeEventListener('storage', onStorage);
      };
    },
  };
}
