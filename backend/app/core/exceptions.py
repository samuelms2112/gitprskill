"""Hierarquia de exceções da aplicação.

Cada exceção define um ``status_code`` HTTP e um ``code`` estável, que o
handler global em ``app.api.errors`` converte em resposta JSON padronizada.
"""

from datetime import datetime
from typing import Any


class AppError(Exception):
    """Exceção base. Subclasses definem o status HTTP e o código de erro."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str = "Erro interno do servidor.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Inicializa a exceção com mensagem segura para o cliente.

        Args:
            message: Mensagem exibida ao cliente. Não deve conter segredos.
            details: Dados estruturados opcionais para diagnóstico do cliente.
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
        # Cabeçalhos extras da resposta HTTP (ex.: Retry-After em limites de taxa).
        self.headers: dict[str, str] = {}


class NotFoundError(AppError):
    """O recurso solicitado não existe."""

    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """O recurso já existe ou conflita com o estado atual."""

    status_code = 409
    code = "conflict"


class InvalidSignatureError(AppError):
    """Assinatura HMAC de um webhook ausente ou inválida."""

    status_code = 401
    code = "invalid_signature"


class DatabaseError(AppError):
    """Falha de comunicação ou de execução no banco de dados."""

    status_code = 503
    code = "database_unavailable"


class InvalidPayloadError(AppError):
    """Corpo de requisição malformado ou fora do schema esperado."""

    status_code = 400
    code = "invalid_payload"


class PayloadTooLargeError(AppError):
    """Corpo de requisição acima do limite permitido."""

    status_code = 413
    code = "payload_too_large"


class AuthenticationError(AppError):
    """Credencial ausente, inválida ou expirada (HTTP 401)."""

    status_code = 401
    code = "unauthenticated"


class AuthorizationError(AppError):
    """Usuário autenticado sem permissão para a operação (HTTP 403)."""

    status_code = 403
    code = "forbidden"


class OAuthStateError(AppError):
    """Parâmetro ``state`` do OAuth ausente, expirado ou adulterado."""

    status_code = 400
    code = "invalid_oauth_state"


class OAuthError(AppError):
    """Falha na troca de código ou na obtenção do perfil com o GitHub."""

    status_code = 502
    code = "github_oauth_failed"


class OAuthNotConfiguredError(AppError):
    """Credenciais do GitHub OAuth não configuradas."""

    status_code = 503
    code = "github_oauth_not_configured"


class CeleryDispatchError(AppError):
    """Não foi possível enfileirar a tarefa de processamento (broker indisponível)."""

    status_code = 503
    code = "task_queue_unavailable"


class AIError(AppError):
    """Base das falhas na integração com o modelo de IA (Gemini)."""

    status_code = 502
    code = "ai_error"


class AIRateLimitError(AIError):
    """Limite de requisições do modelo atingido. ``retry_after`` indica quando tentar de novo."""

    status_code = 429
    code = "ai_rate_limited"

    def __init__(self, *, retry_after: int) -> None:
        """Registra o tempo de espera sugerido, exposto também no cabeçalho ``Retry-After``.

        Args:
            retry_after: Segundos a aguardar antes de uma nova tentativa.
        """
        super().__init__(
            "Limite de requisições da IA atingido. Tente novamente mais tarde.",
            details={"retry_after_seconds": retry_after},
        )
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(retry_after)}


class AIUnavailableError(AIError):
    """Modelo indisponível (timeouts ou erros 5xx persistentes)."""

    status_code = 503
    code = "ai_unavailable"


class AIResponseError(AIError):
    """Resposta do modelo vazia, bloqueada por segurança ou fora do formato esperado."""

    code = "ai_invalid_response"


class AINotConfiguredError(AppError):
    """Chave da API de IA não configurada no servidor."""

    status_code = 503
    code = "ai_not_configured"


class WebhookSecretNotConfiguredError(AppError):
    """O segredo do webhook não foi configurado; nenhuma requisição é aceita (fail closed)."""

    status_code = 500
    code = "webhook_secret_not_configured"


# --- Erros da integração com o GitHub -------------------------------------------------


class GitHubError(AppError):
    """Base das falhas ao comunicar com a API do GitHub."""

    status_code = 502
    code = "github_error"


class GitHubRequestError(GitHubError):
    """Falha de rede, DNS ou timeout ao acessar o GitHub após as tentativas."""

    code = "github_unreachable"


class GitHubAuthenticationError(GitHubError):
    """Token ausente, inválido ou expirado (HTTP 401)."""

    code = "github_authentication_failed"


class GitHubNotFoundError(GitHubError):
    """Repositório ou recurso inexistente, ou sem permissão de visualização (HTTP 404)."""

    status_code = 404
    code = "github_resource_not_found"


class GitHubRateLimitError(GitHubError):
    """Cota de requisições esgotada e o tempo de espera excede o limite configurado."""

    status_code = 503
    code = "github_rate_limited"

    def __init__(self, *, reset_at: datetime | None) -> None:
        """Registra o instante em que a cota será renovada, quando conhecido.

        Args:
            reset_at: Momento de renovação informado pelo cabeçalho ``X-RateLimit-Reset``.
        """
        super().__init__(
            "Limite de requisições do GitHub atingido.",
            details={"reset_at": reset_at.isoformat() if reset_at else None},
        )
        self.reset_at = reset_at


class GitHubApiError(GitHubError):
    """Resposta de erro inesperada da API do GitHub."""

    code = "github_api_error"

    def __init__(self, upstream_status: int, message: str) -> None:
        """Encapsula o status original do GitHub sem expor credenciais.

        Args:
            upstream_status: Código HTTP devolvido pelo GitHub.
            message: Mensagem resumida retornada pelo GitHub.
        """
        super().__init__(message, details={"upstream_status": upstream_status})
        self.upstream_status = upstream_status


class GitHubAppNotConfiguredError(GitHubError):
    """Credenciais do GitHub App ausentes ou inválidas (ID ou chave privada)."""

    status_code = 503
    code = "github_app_not_configured"


class GitHubResponseError(GitHubError):
    """Resposta do GitHub com formato diferente do esperado."""

    code = "github_invalid_response"
