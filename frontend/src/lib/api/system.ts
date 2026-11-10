import { apiRequest } from './client';

/** Espelha ``ClaudeStatusResponse`` do backend. */
export interface ClaudeStatus {
  authenticated: boolean;
  last_checked: string;
  error_message: string | null;
}

/** Espelha ``ClaudeReauthResponse``: o link abre a página de autorização do Claude. */
export interface ClaudeReauthStart {
  login_id: string;
  login_url: string;
}

/** Diagnóstico e reautenticação da sessão do Claude Code CLI (restrito a donos de tenant). */
export const systemApi = {
  claudeStatus: (token: string, signal?: AbortSignal) =>
    apiRequest<ClaudeStatus>('/system/claude/status', { token, signal }),

  startClaudeReauth: (token: string) =>
    apiRequest<ClaudeReauthStart>('/system/claude/reauth', { method: 'POST', token }),

  completeClaudeReauth: (token: string, loginId: string, code: string) =>
    apiRequest<ClaudeStatus>('/system/claude/reauth/complete', {
      method: 'POST',
      token,
      body: { login_id: loginId, code },
    }),
};
