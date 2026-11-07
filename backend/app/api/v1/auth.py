"""Rotas de autenticação com GitHub OAuth e sessão JWT."""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_github_oauth_service, get_token_service
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.exceptions import OAuthStateError
from app.core.security import TokenService, TokenValidationError
from app.schemas.user import UserRead
from app.services.github_oauth import GitHubOAuthService
from app.services.users import upsert_user

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.get(
    "/github/login",
    status_code=302,
    summary="Redireciona para a autorização do GitHub",
    response_class=RedirectResponse,
)
async def github_login(
    oauth: Annotated[GitHubOAuthService, Depends(get_github_oauth_service)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> RedirectResponse:
    """Inicia o fluxo OAuth com um ``state`` assinado para proteção contra CSRF."""
    state = tokens.create_oauth_state()
    return RedirectResponse(oauth.build_authorize_url(state), status_code=302)


@router.get(
    "/github/callback",
    status_code=302,
    response_class=RedirectResponse,
    summary="Conclui o login e redireciona ao frontend com o token de sessão",
)
async def github_callback(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    oauth: Annotated[GitHubOAuthService, Depends(get_github_oauth_service)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str, Query(min_length=1, max_length=512)],
    state: Annotated[str, Query(min_length=1, max_length=2048)],
) -> RedirectResponse:
    """Valida o ``state``, troca o ``code``, cria ou atualiza o usuário e emite o JWT.

    O token vai no **fragmento** da URL de retorno (``#access_token=...``): fragmentos não são
    enviados ao servidor nem aparecem em logs ou cabeçalho ``Referer``.

    Raises:
        OAuthStateError: Quando o ``state`` é inválido, expirado ou adulterado.
    """
    try:
        tokens.validate_oauth_state(state)
    except TokenValidationError as exc:
        raise OAuthStateError("Parâmetro state inválido ou expirado.") from exc

    profile = await oauth.complete_login(code)
    user = await upsert_user(
        session,
        github_id=profile.id,
        login=profile.login,
        email=profile.email,
        avatar_url=profile.avatar_url,
    )
    access_token, expires_in = tokens.create_access_token(user.id)
    fragment = urlencode({"access_token": access_token, "expires_in": expires_in})
    return RedirectResponse(
        f"{settings.frontend_url.rstrip('/')}/auth/callback#{fragment}",
        status_code=302,
    )


@router.get("/me", response_model=UserRead, summary="Dados do usuário autenticado")
async def read_current_user(user: CurrentUser) -> UserRead:
    """Retorna o usuário dono do token enviado."""
    return UserRead.model_validate(user)
