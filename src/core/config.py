"""Application configuration.

Every operational value (models, prompts, timeouts, retries, budgets, guardrails,
logging) is read from environment variables so it can change without code changes.
Secrets are typed as ``SecretStr`` so they are never printed by accident.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: Literal["dev", "test", "staging", "prod"] = "dev"
    app_name: str = "secure-rag-agent"

    # --- Authentication ---------------------------------------------------
    auth_mode: Literal["mock"] = "mock"

    # --- LLM ----------------------------------------------------------------
    llm_provider: Literal["mock", "openai"] = "mock"
    llm_model: str = "mock-model-v1"
    llm_fallback_model: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_timeout_ms: int = Field(10_000, gt=0)
    llm_max_retries: int = Field(1, ge=0)
    llm_temperature: float = Field(0.0, ge=0.0, le=2.0)
    llm_max_output_tokens_per_call: int = Field(600, gt=0)
    llm_input_cost_per_1k_tokens: float = Field(0.00015, ge=0)
    llm_output_cost_per_1k_tokens: float = Field(0.0006, ge=0)

    # --- MCP ----------------------------------------------------------------
    mcp_timeout_ms: int = Field(3_000, gt=0)
    mcp_max_retries: int = Field(2, ge=0)
    mcp_top_k: int = Field(3, gt=0)

    # --- Permissions service ------------------------------------------------
    permissions_timeout_ms: int = Field(2_000, gt=0)

    # --- Retry backoff (exponential + full jitter) --------------------------
    retry_base_delay_ms: int = Field(200, ge=0)
    retry_max_delay_ms: int = Field(2_000, ge=0)

    # --- Circuit breaker ----------------------------------------------------
    circuit_breaker_failure_threshold: int = Field(5, gt=0)
    circuit_breaker_reset_timeout_s: float = Field(30.0, gt=0)

    # --- Per-request execution budget ---------------------------------------
    max_llm_calls_per_request: int = Field(3, gt=0)
    max_llm_retries_per_request: int = Field(1, ge=0)
    max_tool_calls_per_request: int = Field(3, gt=0)
    max_input_tokens: int = Field(12_000, gt=0)
    max_output_tokens: int = Field(1_200, gt=0)
    max_estimated_cost_usd: float = Field(0.10, gt=0)
    request_deadline_ms: int = Field(20_000, gt=0)

    # --- Guardrails ---------------------------------------------------------
    guardrail_mode: Literal["rules"] = "rules"
    injection_threshold: float = Field(0.5, gt=0, le=1)
    max_query_chars: int = Field(2_000, gt=0)
    max_answer_chars: int = Field(4_000, gt=0)
    output_require_citations: bool = True
    insufficient_info_answer: str = (
        "No encuentro información suficiente en los documentos autorizados para responder."
    )

    # --- Prompts ------------------------------------------------------------
    prompt_version: str = Field("system_v1", pattern=r"^[a-z0-9_]+$")

    # --- Observability ------------------------------------------------------
    log_level: str = "INFO"
    log_prompt_content: bool = False
    log_document_content: bool = False
    otel_enabled: bool = True
    otel_exporter: Literal["none", "console"] = "none"
    metrics_endpoint_enabled: bool = True

    @model_validator(mode="after")
    def _validate_provider(self) -> "Settings":
        if self.llm_provider != "mock" and self.llm_api_key is None:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER is not 'mock'")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
