"""Central settings object — the only place that reads process environment.

Every other module imports ``settings`` from here rather than touching
``os.environ`` directly, so behavior is deterministic and fully overridable
from tests via monkeypatching.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── LLM provider ──
    llm_provider: str = "openai"  # openai | groq | gemini | nvidia | anthropic | ollama
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    temperature: float = 0.2

    openai_api_key: str = ""
    groq_api_key: str = ""
    google_api_key: str = ""
    nvidia_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434/v1"

    # ── LangSmith tracing ──
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "ticketwarden"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # ── Agent behavior ──
    max_review_iterations: int = 2
    max_tool_rounds: int = 3

    # ── Storage (self-contained: no external commerce API) ──
    sqlite_path: str = "./ticketwarden.db"

    # ── Service ──
    api_host: str = "0.0.0.0"  # nosec B104 - Cloud Run requires binding all interfaces
    api_port: int = 8080
    log_level: str = "INFO"

    # ── UI ──
    api_url: str = "http://localhost:8080"

    @property
    def active_llm_api_key(self) -> str:
        keys = {
            "openai": self.openai_api_key,
            "groq": self.groq_api_key,
            "gemini": self.google_api_key,
            "nvidia": self.nvidia_api_key,
            "anthropic": self.anthropic_api_key,
            "ollama": "local",
        }
        key = keys.get(self.llm_provider.lower(), "")
        # .env.example ships obvious placeholders — never treat those as real.
        return "" if key in {"sk-...", "gsk_...", "nvapi-...", "sk-ant-..."} else key

    @property
    def has_llm_credentials(self) -> bool:
        return bool(self.active_llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
