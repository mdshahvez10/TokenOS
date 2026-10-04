from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tokenos.domain.models import Rates
from tokenos.runtime.contracts import Policy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOKENOS_", env_file=".env", extra="ignore")
    runtime_provider: Literal["sandbox", "gemini"] = "sandbox"
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    policy_file: Path = Path("config/policy.json")
    sandbox_fixture: Path = Path("config/sandbox.json")
    concurrency: int = Field(default=4, ge=1)
    mcp_servers: dict[str, str] = {}
    model_rates: Rates | None = None

    def runtime_policy(self) -> Policy:
        return Policy.model_validate_json(self.policy_file.read_text())

    backend: Literal["memory", "postgres"] = "postgres"
    api_key: SecretStr = Field(min_length=32)
    database_url: SecretStr | None = None
    pool_min: int = Field(default=1, ge=1)
    pool_max: int = Field(default=10, ge=1)
    db_timeout_seconds: float = Field(default=10, gt=0)
    provider_timeout_seconds: float = Field(default=30, gt=0)
    shutdown_timeout_seconds: float = Field(default=10, gt=0)
    safety_tokens: int = Field(default=32, ge=0)
    max_prompt_characters: int = Field(default=16_000, gt=0)
    max_output_tokens: int = Field(default=2_000, gt=0)
    max_task_budget: int = Field(default=1_000_000, gt=0)
    demo_enabled: bool = False
    demo_model_id: str = "tokenos-simulator-v1"
    demo_response: str = "Simulated response: accounting works."
    demo_overhead_tokens: int = Field(default=8, ge=0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    otel_service_name: str = "tokenos-ledger"
    otel_export: bool = False

    @model_validator(mode="after")
    def validate_backend(self) -> "Settings":
        if self.backend == "postgres" and self.database_url is None:
            raise ValueError("TOKENOS_DATABASE_URL is required for the postgres backend")
        if self.runtime_provider == "gemini" and (not self.gemini_api_key or not self.gemini_model):
            raise ValueError("Gemini requires model and API key")
        if self.pool_min > self.pool_max:
            raise ValueError("pool_min cannot exceed pool_max")
        return self
