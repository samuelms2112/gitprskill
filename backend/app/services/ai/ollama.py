"""Cliente do Ollama (IA local). Usa a API compatível com OpenAI em ``/v1/chat/completions``
e a API nativa de embeddings em ``/api/embeddings``.

Diferente da nuvem, o Ollama não tem cota por dia nem limite de requisições: não existe 429.
Falhas reais (serviço fora do ar, modelo não instalado, timeout) viram ``AIUnavailableError``.
"""

from __future__ import annotations

import re
from types import TracebackType
from typing import Any, Self

import httpx

from app.core.exceptions import AIResponseError, AIUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Modelos de raciocínio (ex.: deepseek-r1) escrevem o raciocínio entre <think> antes da resposta.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

# Orçamento de saída por chamada. Precisa cobrir o raciocínio dos modelos de "pensar" antes do JSON.
DEFAULT_MAX_TOKENS = 1536


def strip_reasoning(text: str) -> str:
    """Remove o raciocínio do modelo, mantendo só a resposta final.

    Se o bloco de raciocínio nunca fecha, o que vem depois dele não é resposta: é descartado.
    """
    cleaned = _THINK_BLOCK.sub("", text)
    return cleaned.split("<think>", 1)[0].strip()


class OllamaTextModel:
    """Um modelo local fixo para texto livre (ex.: o modelo do agente PM/PO)."""

    def __init__(self, client: OllamaClient, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def generate_text(self, prompt: str) -> str:
        return await self._client.chat(self._model, prompt, max_tokens=DEFAULT_MAX_TOKENS)


class OllamaClient:
    """Cliente HTTP assíncrono do Ollama. Implementa ``TextEmbedder`` e chamadas de chat."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        embedding_model: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._embedding_model = embedding_model
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def chat(
        self,
        model: str,
        prompt: str,
        *,
        json_output: bool = False,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Pede uma resposta de chat a um modelo local.

        ``max_tokens`` é obrigatório na prática: sem ele, o modelo pode gerar indefinidamente, e
        o Ollama não cancela a geração quando o cliente desiste. Isso trava o único slot de
        execução e todas as chamadas seguintes ficam na fila.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_output:
            body["response_format"] = {"type": "json_object"}

        data = await self._post("/v1/chat/completions", body)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIResponseError(f"Resposta do modelo local {model} fora do formato esperado.") from exc
        if not isinstance(content, str):
            raise AIResponseError(f"Resposta do modelo local {model} sem texto.")
        text = strip_reasoning(content)
        if not text:
            raise AIResponseError(f"O modelo local {model} respondeu vazio.")
        return text

    async def embed(self, text: str) -> list[float]:
        """Vetor de embedding do texto, com o modelo de embeddings configurado."""
        data = await self._post("/api/embeddings", {"model": self._embedding_model, "prompt": text})
        vector = data.get("embedding")
        if not isinstance(vector, list) or not vector or not all(isinstance(v, (int, float)) for v in vector):
            raise AIResponseError("Embedding retornado pelo Ollama fora do formato esperado.")
        return [float(v) for v in vector]

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        model = str(body.get("model", ""))
        try:
            response = await self._http.post(f"{self._base_url}{path}", json=body)
        except httpx.TransportError as exc:
            logger.error("Ollama inacessível", extra={"path": path})
            raise AIUnavailableError("O serviço de IA local (Ollama) não está acessível.") from exc

        if response.status_code == 404:
            raise AIUnavailableError(f"Modelo '{model}' não instalado no Ollama. Instale com: ollama pull {model}")
        if response.status_code >= 500:
            raise AIUnavailableError(f"Ollama retornou HTTP {response.status_code}.")
        if not response.is_success:
            raise AIResponseError(f"Ollama retornou HTTP {response.status_code}.")

        try:
            data = response.json()
        except ValueError as exc:
            raise AIResponseError("Resposta do Ollama não é JSON válido.") from exc
        if not isinstance(data, dict):
            raise AIResponseError("Resposta do Ollama fora do formato esperado.")
        return data
