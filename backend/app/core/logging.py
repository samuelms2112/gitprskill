"""Logs estruturados em JSON.

Cada registro é emitido como um objeto JSON em uma linha, facilitando a
ingestão por ferramentas de observabilidade. Campos passados via ``extra=``
são incluídos automaticamente no payload.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Atributos padrão de LogRecord que não devem ser repetidos no payload.
_RESERVED_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    """Formata registros de log como JSON de uma única linha."""

    def format(self, record: logging.LogRecord) -> str:
        """Converte o ``LogRecord`` em string JSON.

        Args:
            record: Registro de log a ser formatado.

        Returns:
            Representação JSON do registro, incluindo campos ``extra``.
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Configura o logger raiz para emitir JSON no stdout.

    Args:
        level: Nível mínimo de log (ex.: ``"INFO"``).
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger nomeado para o módulo informado."""
    return logging.getLogger(name)
