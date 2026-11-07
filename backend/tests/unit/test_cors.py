"""Testes unitários da política de CORS: só as origens configuradas podem chamar a API pelo navegador."""

import httpx

from app.main import app

HEALTH = "/api/v1/health"


async def _preflight(origin: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.options(
            HEALTH,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )


async def test_configured_frontend_origin_is_allowed() -> None:
    """A origem do frontend recebe permissão para chamar a API com o cabeçalho Authorization."""
    response = await _preflight("http://localhost:3000")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


async def test_unknown_origin_gets_no_cors_permission() -> None:
    """Origens não configuradas não recebem cabeçalho de permissão."""
    response = await _preflight("https://site-malicioso.example")

    assert "access-control-allow-origin" not in response.headers
