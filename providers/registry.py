import logging
from .base import BaseProvider
from config import config

logger = logging.getLogger(__name__)

# lazy imports — only load providers that are enabled
_PROVIDER_MAP = {
    "azure_openai": "providers.azure_openai.AzureOpenAIProvider",
    "aws_bedrock":  "providers.aws_bedrock.AWSBedrockProvider",
    "google":       "providers.google.GoogleProvider",
    "openai":       "providers.openai.OpenAIProvider",
    "ollama":       "providers.ollama.OllamaProvider",
    "local":        "providers.local.LocalProvider",
}


def _load_provider(name: str) -> BaseProvider:
    """Dynamically import and instantiate a provider class."""
    module_path, class_name = _PROVIDER_MAP[name].rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


class ProviderRegistry:
    """
    Resolves the best available LLM provider.

    Selection rules:
    1. Walk config.providers.priority list
    2. Skip providers with enabled=false
    3. Return first provider that passes is_healthy()
    4. Raise if none are reachable
    """

    async def auto_select(self) -> BaseProvider:
        """Return the highest-priority healthy provider."""
        for name in config.providers.priority:
            if not config.providers.is_enabled(name):
                logger.debug(f"provider '{name}' is disabled — skipping")
                continue
            try:
                provider = _load_provider(name)
                if await provider.is_healthy():
                    logger.info(f"provider selected: {name}")
                    return provider
                else:
                    logger.debug(f"provider '{name}' is not healthy — trying next")
            except Exception as e:
                logger.debug(f"provider '{name}' failed to load: {e}")
                continue

        raise RuntimeError(
            "No LLM providers are reachable. "
            "Check your config.json and ensure at least one provider is enabled and accessible."
        )

    def get(self, name: str, model: str | None = None) -> BaseProvider:
        """Get a specific provider by name (bypasses health check)."""
        if name not in _PROVIDER_MAP:
            raise ValueError(f"Unknown provider: '{name}'. Available: {list(_PROVIDER_MAP.keys())}")
        provider = _load_provider(name)
        return provider

    async def get_all_statuses(self) -> dict[str, bool]:
        """Return health status of all configured providers."""
        statuses = {}
        for name in _PROVIDER_MAP:
            if not config.providers.is_enabled(name):
                statuses[name] = False
                continue
            try:
                provider = _load_provider(name)
                statuses[name] = await provider.is_healthy()
            except Exception:
                statuses[name] = False
        return statuses


# singleton
provider_registry = ProviderRegistry()
