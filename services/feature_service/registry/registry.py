from shared.contracts import FeatureProvider


class FeatureRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, FeatureProvider] = {}

    def register(self, provider: FeatureProvider) -> None:
        key = provider.feature_id()
        if key in self._providers:
            raise ValueError(f"feature provider already registered: {key}")
        self._providers[key] = provider

    def get(self, feature_id: str) -> FeatureProvider:
        try:
            return self._providers[feature_id]
        except KeyError as exc:
            raise KeyError(f"unknown feature provider: {feature_id}") from exc

    def list_features(self) -> list[str]:
        return sorted(self._providers.keys())
