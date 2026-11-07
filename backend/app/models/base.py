"""Base declarativa do ORM, convenções de nomes e mixins compartilhados."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Convenção de nomes fixa: constraints ganham nomes previsíveis, o que facilita
# migrações do Alembic (ex.: remoção de constraints por nome).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Classe base de todos os modelos ORM."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adiciona ``created_at`` e ``updated_at`` gerenciados pelo banco.

    Usado em entidades cujo ciclo de vida é controlado pela plataforma. Entidades
    que espelham o GitHub (ex.: ``PullRequest``) usam as datas do próprio GitHub.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def str_enum(enum_cls: type[StrEnum], *, name: str, length: int) -> SAEnum:
    """Cria uma coluna de enum armazenada como VARCHAR com CHECK constraint.

    Armazenar como texto (``native_enum=False``) evita ``ALTER TYPE`` nas
    migrações ao adicionar novos valores, e o CHECK mantém a integridade no banco.

    Args:
        enum_cls: Enumeração Python de origem.
        name: Nome lógico do enum, usado no nome da constraint.
        length: Tamanho máximo do VARCHAR; deve cobrir o maior valor.

    Returns:
        Tipo SQLAlchemy configurado para persistir os ``value`` do enum.
    """
    return SAEnum(
        enum_cls,
        name=name,
        length=length,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
