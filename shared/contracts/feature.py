from typing import Any, Protocol


class FeatureProvider(Protocol):
    """Contract for extensible feature computation providers."""

    def feature_id(self) -> str:
        ...

    def feature_version(self) -> str:
        ...

    def depends_on(self) -> list[str]:
        ...

    def compute(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        ...
