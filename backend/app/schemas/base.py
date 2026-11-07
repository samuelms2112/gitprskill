"""Tipos e configurações base compartilhados pelos schemas.

``InputSchema`` rejeita campos desconhecidos (``extra="forbid"``), evitando que
payloads inesperados, como campos do GitHub não mapeados, sejam aceitos em silêncio.
``ReadSchema`` habilita a leitura direta de atributos ORM.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

PositiveInt = Annotated[int, Field(gt=0)]
GitHubId = Annotated[int, Field(gt=0, description="Identificador numérico do GitHub")]


class InputSchema(BaseModel):
    """Base para payloads de entrada: estrito e com espaços removidos das bordas."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReadSchema(BaseModel):
    """Base para respostas: converte objetos ORM em schemas."""

    model_config = ConfigDict(from_attributes=True)
