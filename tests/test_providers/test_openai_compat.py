"""Tests for pre-configured OpenAI-compatible providers."""

from providers.openai_compat import KNOWN_ENDPOINTS, OpenAICompatProvider


def test_zenmux_endpoint_configuration():
    assert KNOWN_ENDPOINTS["zenmux"] == {
        "base_url": "https://zenmux.ai/api/v1",
        "display_name": "ZenMux",
    }


def test_zenmux_provider_uses_known_endpoint_defaults():
    provider = OpenAICompatProvider(provider_name="zenmux")

    assert provider.provider_name == "zenmux"
    assert provider.base_url == "https://zenmux.ai/api/v1"
    assert provider.display_name == "ZenMux"
