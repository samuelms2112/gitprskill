"""Validação de dados derivados do GitHub contra os schemas de domínio."""

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.exceptions import InvalidPayloadError

_T = TypeVar("_T", bound=BaseModel)


def validate_domain(model: type[_T], **data: Any) -> _T:
    """Instancia ``model`` e converte falhas em erro de aplicação sem ecoar valores de entrada.

    Raises:
        InvalidPayloadError: Quando as regras de consistência do domínio são violadas.
    """
    try:
        return model(**data)
    except ValidationError as exc:
        raise InvalidPayloadError(
            "Dados do GitHub inconsistentes para persistência.",
            details={"errors": safe_error_details(exc)},
        ) from exc


def safe_error_details(exc: ValidationError) -> list[dict[str, Any]]:
    """Lista de erros apenas com localização e mensagem, sem valores de entrada."""
    return [
        {"loc": [str(part) for part in error["loc"]], "msg": error["msg"]}
        for error in exc.errors(include_input=False, include_url=False)
    ]
