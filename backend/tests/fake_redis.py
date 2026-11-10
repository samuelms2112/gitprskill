"""Dublê em memória do subconjunto de ``redis.Redis`` usado pelo estado da sessão do Claude."""


class FakeRedis:
    """Armazena chaves em um dicionário. Só implementa ``get``, ``set``, ``delete`` e ``close``."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def delete(self, key: str) -> int:
        return int(self.data.pop(key, None) is not None)

    def close(self) -> None:
        return None
