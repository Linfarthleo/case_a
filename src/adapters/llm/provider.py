"""Selects the LLM adapter from configuration (``LLM_PROVIDER``)."""

from adapters.llm.mock_llm import MockLLMAdapter
from adapters.llm.openai_compatible import OpenAICompatibleAdapter
from core.config import Settings
from ports.llm import LLMPort


def build_llm_provider(settings: Settings) -> LLMPort:
    if settings.llm_provider == "openai":
        assert settings.llm_api_key is not None  # enforced by Settings validation
        return OpenAICompatibleAdapter(settings.llm_base_url, settings.llm_api_key)
    return MockLLMAdapter()
