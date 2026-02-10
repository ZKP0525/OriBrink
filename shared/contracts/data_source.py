from typing import Any, Protocol


class SourceAdapter(Protocol):
    """Contract for heterogeneous data source adapters."""

    def source_id(self) -> str:
        ...

    def capabilities(self) -> dict[str, Any]:
        ...

    async def fetch(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        ...

    async def health_check(self) -> bool:
        ...
