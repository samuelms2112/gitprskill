"""Cliente do Google Gemini (REST ``generateContent``) para análise de PRs e release notes.

Tratamento de falhas:
    * HTTP 429 (limite de taxa) -> ``AIRateLimitError`` com ``retry_after``. Não há espera
      interna: quem chama decide (a API responde 429; o worker reagenda a tarefa).
    * Timeouts, erros de rede e HTTP 5xx -> novas tentativas com backoff; esgotadas, ``AIUnavailableError``.
    * Resposta bloqueada por segurança, vazia ou fora do schema -> ``AIResponseError``.

A chave de API vai no cabeçalho ``x-goog-api-key`` e nunca aparece em URLs, logs ou mensagens de erro.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from types import TracebackType
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.core.exceptions import (
    AIRateLimitError,
    AIResponseError,
    AIUnavailableError,
)
from app.core.logging import get_logger
from app.models.enums import AICategory, AIRiskLevel
from app.models.pull_request import PullRequest
from app.services.ai_prompts import build_analysis_prompt, build_release_notes_prompt

logger = get_logger(__name__)

DEFAULT_RETRY_AFTER_SECONDS = 60
MAX_TRANSIENT_RETRIES = 2
BACKOFF_BASE_SECONDS = 1.0
BLOCKED_FINISH_REASONS = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)

# Schema da resposta estruturada: o modelo é obrigado a devolver este formato.
ANALYSIS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "category": {"type": "STRING", "enum": [c.value for c in AICategory]},
        "risk_level": {"type": "STRING", "enum": [r.value for r in AIRiskLevel]},
    },
    "required": ["summary", "category", "risk_level"],
}

SleepFn = Callable[[float], Awaitable[None]]


class PullRequestAnalysis(BaseModel):
    """Resultado validado da análise de um PR pelo modelo."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, frozen=True)

    summary: str = Field(min_length=20, max_length=4000)
    category: AICategory
    risk_level: AIRiskLevel


class AIService:
    """Cliente assíncrono do Gemini. Use com ``async with`` para fechar o cliente interno."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        base_url: str,
        max_diff_chars: int,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        """Configura o cliente.

        Args:
            api_key: Chave do Google AI Studio (``GEMINI_API_KEY``).
            model: Nome do modelo, ex.: ``gemini-2.5-flash``.
            base_url: URL base da API do Gemini.
            max_diff_chars: Limite de caracteres do diff enviado ao modelo.
            http_client: Cliente httpx externo (usado nos testes com ``MockTransport``).
            timeout: Timeout de cada requisição, em segundos.
            sleep: Função de espera assíncrona (injetável nos testes).
        """
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_diff_chars = max_diff_chars
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._sleep = sleep

    async def __aenter__(self) -> Self:
        """Permite uso em ``async with``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Fecha o cliente HTTP interno, se ele foi criado por esta instância."""
        if self._owns_client:
            await self._http.aclose()

    async def generate_text(self, prompt: str) -> str:
        """Texto livre do modelo (usado pelo agente PM/PO e pelos componentes de texto)."""
        text = (await self._generate(prompt)).strip()
        if not text:
            raise AIResponseError("O modelo retornou um texto vazio.")
        return text

    async def analyze_pull_request(
        self,
        title: str,
        description: str,
        diff_text: str,
        *,
        product_context: str | None = None,
    ) -> PullRequestAnalysis:
        """Gera resumo executivo, categoria e nível de risco de um PR.

        Raises:
            AIRateLimitError: Limite de taxa atingido.
            AIUnavailableError: Modelo indisponível após as tentativas.
            AIResponseError: Resposta bloqueada, vazia ou fora do schema.
        """
        prompt = build_analysis_prompt(
            title, description, diff_text, self._max_diff_chars, product_context=product_context
        )
        text = await self._generate(
            prompt,
            response_mime_type="application/json",
            response_schema=ANALYSIS_RESPONSE_SCHEMA,
        )
        return parse_analysis(text)

    async def generate_release_notes(self, prs: Sequence[PullRequest]) -> str:
        """Sintetiza uma lista de PRs em release notes em Markdown.

        Raises:
            AIRateLimitError: Limite de taxa atingido.
            AIUnavailableError: Modelo indisponível após as tentativas.
            AIResponseError: Resposta vazia ou bloqueada.
        """
        text = await self._generate(build_release_notes_prompt(prs))
        notes = text.strip()
        if not notes:
            raise AIResponseError("O modelo retornou release notes vazias.")
        return notes

    async def _generate(
        self,
        prompt: str,
        *,
        response_mime_type: Literal["text/plain", "application/json"] = "text/plain",
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        generation_config: dict[str, Any] = {"temperature": 0.2, "responseMimeType": response_mime_type}
        if response_schema is not None:
            generation_config["responseSchema"] = response_schema
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        url = f"{self._base_url}/v1beta/models/{self._model}:generateContent"
        headers = {
            "x-goog-api-key": self._api_key.get_secret_value(),
            "Content-Type": "application/json",
        }

        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._http.post(url, json=body, headers=headers)
            except httpx.TransportError as exc:
                if attempt > MAX_TRANSIENT_RETRIES:
                    logger.error("Falha de rede ao acessar o Gemini", extra={"attempts": attempt})
                    raise AIUnavailableError("Falha de comunicação com o modelo de IA.") from exc
                await self._sleep(_backoff(attempt))
                continue

            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                logger.warning("Limite de taxa do Gemini atingido", extra={"retry_after": retry_after})
                raise AIRateLimitError(retry_after=retry_after)

            if response.status_code >= 500:
                if attempt > MAX_TRANSIENT_RETRIES:
                    raise AIUnavailableError(
                        f"Modelo de IA indisponível (HTTP {response.status_code})."
                    )
                await self._sleep(_backoff(attempt))
                continue

            if not response.is_success:
                raise AIResponseError(f"Modelo de IA retornou HTTP {response.status_code}.")

            return _extract_text(response.json())


def parse_analysis(text: str) -> PullRequestAnalysis:
    """Converte o JSON do modelo em ``PullRequestAnalysis`` validado.

    Raises:
        AIResponseError: Quando o texto não é JSON ou não respeita o schema.
    """
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AIResponseError("A análise do modelo não é JSON válido.") from exc
    try:
        return PullRequestAnalysis.model_validate(data)
    except ValidationError as exc:
        raise AIResponseError("A análise do modelo não respeita o schema esperado.") from exc


def _extract_text(data: Any) -> str:
    """Extrai o texto do primeiro candidato, tratando bloqueios e respostas vazias."""
    if not isinstance(data, dict):
        raise AIResponseError("Resposta inesperada do modelo de IA.")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise AIResponseError("O modelo de IA não retornou candidatos.")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise AIResponseError("Resposta inesperada do modelo de IA.")

    finish_reason = candidate.get("finishReason")
    if isinstance(finish_reason, str) and finish_reason in BLOCKED_FINISH_REASONS:
        raise AIResponseError(f"Resposta do modelo bloqueada ({finish_reason}).")

    content = candidate.get("content")
    parts = content.get("parts", []) if isinstance(content, dict) else []
    text = "".join(
        part["text"] for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)
    )
    if not text.strip():
        raise AIResponseError("O modelo de IA retornou uma resposta vazia.")
    return text


def _parse_retry_after(header: str | None) -> int:
    """Lê ``Retry-After`` em segundos; usa um padrão quando ausente ou inválido."""
    if header is None:
        return DEFAULT_RETRY_AFTER_SECONDS
    try:
        return max(int(float(header)), 1)
    except ValueError:
        return DEFAULT_RETRY_AFTER_SECONDS


def _backoff(attempt: int) -> float:
    return BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
