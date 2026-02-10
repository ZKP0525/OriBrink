from typing import Any

from services.data_service.adapters import SourceAdapterRegistry
from services.feature_service.registry import FeatureRegistry


class DummyAdapter:
    def source_id(self) -> str:
        return "dummy"

    def capabilities(self) -> dict[str, Any]:
        return {"types": ["daily"]}

    async def fetch(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    async def health_check(self) -> bool:
        return True


class DummyFeatureProvider:
    def feature_id(self) -> str:
        return "f_dummy"

    def feature_version(self) -> str:
        return "v1"

    def depends_on(self) -> list[str]:
        return ["close"]

    def compute(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        return []


def test_source_registry_register_and_get() -> None:
    registry = SourceAdapterRegistry()
    adapter = DummyAdapter()

    registry.register(adapter)

    assert registry.get("dummy") is adapter
    assert registry.list_sources() == ["dummy"]


def test_feature_registry_register_and_get() -> None:
    registry = FeatureRegistry()
    provider = DummyFeatureProvider()

    registry.register(provider)

    assert registry.get("f_dummy") is provider
    assert registry.list_features() == ["f_dummy"]
