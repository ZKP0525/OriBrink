from typing import Any, Protocol


class Normalizer(Protocol):
    """Contract for converting raw batches into canonical records."""

    def schema_version(self) -> str:
        ...

    def normalize(self, raw_batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...
