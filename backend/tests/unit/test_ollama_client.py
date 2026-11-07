"""Testes unitários do cliente Ollama: formato da requisição, limpeza do raciocínio e erros."""

import json
from typing import Any

import httpx
import pytest

from app.core.exceptions import AIResponseError, AIUnavailableError
from app.services.ai.ollama import DEFAULT_MAX_TOKENS, OllamaClient, strip_reasoning

BASE = "http://ollama:11434"


def _client(handler: Any) -> OllamaClient:
    return OllamaClient(
        base_url=BASE,
        timeout=30,
        embedding_model="nomic-embed-text",
        http_client=httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(handler)),
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<think>pensando...</think>{\"a\": 1}", '{"a": 1}'),
        ("<think>a</think>x<think>b</think>y", "xy"),
        ("resposta direta", "resposta direta"),
        ("texto antes<think>nunca fecha", "texto antes"),
    ],
    ids=["bloco_unico", "dois_blocos", "sem_raciocinio", "raciocinio_sem_fecho"],
)
def test_reasoning_blocks_are_removed(raw: str, expected: str) -> None:
    """Modelos de raciocínio (deepseek-r1) não podem contaminar o JSON da análise."""
    assert strip_reasoning(raw) == expected


async def test_chat_sends_openai_compatible_request_and_returns_clean_text() -> None:
    """A requisição usa ``/v1/chat/completions`` e, em modo JSON, pede ``response_format``."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path, "body": json.loads(request.content)})
        return _chat_response("<think>hmm</think>{\"ok\": true}")

    async with _client(handler) as client:
        text = await client.chat("qwen2.5-coder:7b", "prompt", json_output=True)

    assert text == '{"ok": true}'
    assert seen[0]["path"] == "/v1/chat/completions"
    assert seen[0]["body"]["model"] == "qwen2.5-coder:7b"
    assert seen[0]["body"]["response_format"] == {"type": "json_object"}
    assert seen[0]["body"]["stream"] is False
    # Sem limite de saída, a geração pode nunca terminar e travar o servidor local.
    assert seen[0]["body"]["max_tokens"] == DEFAULT_MAX_TOKENS


async def test_text_mode_does_not_request_json() -> None:
    """Texto livre não força formato JSON."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _chat_response("ok")

    async with _client(handler) as client:
        await client.chat("llama3.1:8b", "prompt")

    assert "response_format" not in seen[0]


async def test_missing_model_gives_actionable_error() -> None:
    """Modelo não instalado vira erro com o comando exato para instalar."""
    async with _client(lambda r: httpx.Response(404, json={"error": "model not found"})) as client:
        with pytest.raises(AIUnavailableError, match="ollama pull deepseek-r1:8b"):
            await client.chat("deepseek-r1:8b", "prompt")


async def test_server_error_is_unavailable() -> None:
    """Falha do serviço local é indisponibilidade, não resposta inválida."""
    async with _client(lambda r: httpx.Response(500)) as client:
        with pytest.raises(AIUnavailableError):
            await client.chat("llama3.1:8b", "prompt")


async def test_unreachable_service_is_unavailable() -> None:
    """Ollama fora do ar (rede) vira indisponibilidade com mensagem clara."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rota", request=request)

    async with _client(handler) as client:
        with pytest.raises(AIUnavailableError, match="não está acessível"):
            await client.chat("llama3.1:8b", "prompt")


async def test_empty_content_is_an_invalid_response() -> None:
    """Resposta vazia (depois de limpar o raciocínio) não é aceita."""
    async with _client(lambda r: _chat_response("<think>só raciocínio</think>")) as client:
        with pytest.raises(AIResponseError):
            await client.chat("qwen2.5-coder:7b", "prompt")


async def test_embedding_returns_floats_from_the_configured_model() -> None:
    """O embedding usa o modelo de embeddings configurado e devolve uma lista de floats."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    async with _client(handler) as client:
        vector = await client.embed("resumo do PR")

    assert vector == [0.1, 0.2, 0.3]
    assert seen[0]["model"] == "nomic-embed-text"


async def test_malformed_embedding_is_rejected() -> None:
    """Embedding fora do formato (vazio ou com texto) não entra na memória."""
    async with _client(lambda r: httpx.Response(200, json={"embedding": ["x"]})) as client:
        with pytest.raises(AIResponseError):
            await client.embed("texto")
