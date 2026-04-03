import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Environment variables that signal a provider is configured
_PROVIDER_ENV_SIGNALS: dict[str, list[str]] = {
    "openai":       ["OPENAI_API_KEY"],
    "azure_openai": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
    "google":       ["GOOGLE_API_KEY"],
    "aws_bedrock":  ["AWS_ACCESS_KEY_ID"],
    "ollama":       ["OLLAMA_BASE_URL"],
}

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"


def _load() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH) as f:
        return json.load(f)


# ── raw config dict ─────────────────────────────────────────────────────────
_cfg: dict = _load()


# ── typed accessors ──────────────────────────────────────────────────────────
class ProvidersConfig:
    def __init__(self, data: dict):
        self._data = data

    @property
    def priority(self) -> list[str]:
        return self._data.get("priority", [])

    def get(self, name: str) -> dict:
        return self._data.get(name, {})

    def is_enabled(self, name: str) -> bool:
        # Explicit override in config.json takes precedence
        cfg = self._data.get(name, {})
        if "enabled" in cfg:
            return bool(cfg["enabled"])
        # Auto-enable if ALL required env vars for this provider are present
        signals = _PROVIDER_ENV_SIGNALS.get(name, [])
        if signals and all(os.environ.get(v) for v in signals):
            return True
        return False


class AgentModelConfig:
    def __init__(self, data: dict):
        self.provider: str = data.get("provider", "auto")
        self.model: str = data.get("model", "auto")


class SubagentConfig(AgentModelConfig):
    def __init__(self, data: dict):
        super().__init__(data)
        self.max_concurrent: int = data.get("max_concurrent", 8)


class AgentsConfig:
    def __init__(self, data: dict):
        self.orchestrator = AgentModelConfig(data.get("orchestrator", {}))
        self.subagents = SubagentConfig(data.get("subagents", {}))


class ContextConfig:
    def __init__(self, data: dict):
        self.max_tokens: int = data.get("max_tokens", 180000)
        self.recent_messages_always_include: int = data.get("recent_messages_always_include", 20)
        self.compact_threshold: float = data.get("compact_threshold", 0.85)


class WorkspaceConfig:
    def __init__(self, data: dict):
        self.path: Path = BASE_DIR / data.get("path", "storage/workspace")
        self.allowed_extensions: list[str] = data.get(
            "allowed_extensions",
            [
                ".md", ".txt", ".py", ".js", ".ts", ".json",
                ".yaml", ".yml", ".toml", ".sh", ".html", ".css",
                ".sql", ".env.example", ".gitignore",
            ],
        )


class ServerConfig:
    def __init__(self, data: dict):
        self.host: str = data.get("host", "0.0.0.0")
        self.port: int = data.get("port", 8000)
        self.reload: bool = data.get("reload", False)


# ── main config object ───────────────────────────────────────────────────────
class Config:
    def __init__(self, data: dict):
        self.providers = ProvidersConfig(data.get("providers", {}))
        self.agents = AgentsConfig(data.get("agents", {}))
        self.context = ContextConfig(data.get("context", {}))
        self.workspace = WorkspaceConfig(data.get("workspace", {}))
        self.server = ServerConfig(data.get("server", {}))

    # ── path helpers ─────────────────────────────────────────────────────────
    @property
    def security_path(self) -> Path:
        return BASE_DIR / "storage" / "security" / "Security.md"

    @property
    def security_hash_path(self) -> Path:
        return BASE_DIR / "storage" / "security" / "Security.md.sha256"

    @property
    def soul_path(self) -> Path:
        return BASE_DIR / "storage" / "soul" / "boot.md"

    @property
    def memory_dir(self) -> Path:
        return BASE_DIR / "storage" / "memory"

    @property
    def sessions_dir(self) -> Path:
        return BASE_DIR / "storage" / "sessions"

    @property
    def core_skills_dir(self) -> Path:
        return BASE_DIR / "skills" / "definitions"

    @property
    def custom_skills_dir(self) -> Path:
        return BASE_DIR / "skills" / "custom"

    @property
    def plans_dir(self) -> Path:
        return BASE_DIR / "storage" / "plans"

    @property
    def bus_dir(self) -> Path:
        return BASE_DIR / "storage" / "bus"

    @property
    def research_dir(self) -> Path:
        return BASE_DIR / "storage" / "research"

    @property
    def human_review_dir(self) -> Path:
        return BASE_DIR / "storage" / "human_review"


config = Config(_cfg)
