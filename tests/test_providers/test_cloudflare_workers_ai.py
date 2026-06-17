"""Tests for the Cloudflare Workers AI provider."""

import pytest

from providers.base import ChatMessage
from providers.cloudflare_workers_ai import (
    CloudflareCredentialError,
    CloudflareWorkersAIProvider,
    _parse_cloudflare_credentials,
    normalize_cloudflare_credentials,
)


ACCOUNT_ID = "0123456789abcdef0123456789abcdef"


def test_normalize_credentials_accepts_colon_format():
    value = normalize_cloudflare_credentials(f"{ACCOUNT_ID}:token-value")

    assert value == f"{ACCOUNT_ID}:token-value"


def test_normalize_credentials_accepts_two_line_format():
    value = normalize_cloudflare_credentials(f"{ACCOUNT_ID}\ntoken-value")

    assert value == f"{ACCOUNT_ID}:token-value"


def test_normalize_credentials_accepts_token_only():
    value = normalize_cloudflare_credentials("token-value")

    assert value == "token-value"


def test_normalize_credentials_rejects_empty_value():
    with pytest.raises(CloudflareCredentialError):
        normalize_cloudflare_credentials("  ")


def test_parse_credentials_uses_env_account_id(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)

    account_id, token = _parse_cloudflare_credentials("token-value")

    assert account_id == ACCOUNT_ID
    assert token == "token-value"


def test_build_messages_prepends_system_instruction():
    messages = [
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="assistant", content="hi"),
    ]

    result = CloudflareWorkersAIProvider._build_messages(messages, "be terse")

    assert result == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_parse_response_supports_workers_ai_response_shape():
    payload = {
        "success": True,
        "result": {
            "response": "hello",
            "usage": {"input_tokens": 3, "output_tokens": 5},
        },
    }

    response = CloudflareWorkersAIProvider._parse_response(payload)

    assert response.text == "hello"
    assert response.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 5,
        "total_tokens": 8,
    }


def test_parse_response_supports_openai_style_shape():
    payload = {
        "result": {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6},
        }
    }

    response = CloudflareWorkersAIProvider._parse_response(payload)

    assert response.text == "hello"
    assert response.usage["total_tokens"] == 6


def test_parse_stream_event_supports_delta_shape():
    text, usage = CloudflareWorkersAIProvider._parse_stream_event(
        '{"choices":[{"delta":{"content":"hel"}}],"usage":{"prompt_tokens":1}}'
    )

    assert text == "hel"
    assert usage["prompt_tokens"] == 1


def test_extract_models_filters_text_generation_models():
    payload = {
        "result": [
            {
                "id": "@cf/zai-org/glm-4.7-flash",
                "name": "glm-4.7-flash",
                "task": {"name": "Text Generation"},
                "context_window": 131072,
            },
            {
                "id": "@cf/baai/bge-base-en-v1.5",
                "name": "bge-base-en-v1.5",
                "task": {"name": "Text Embeddings"},
            },
        ]
    }

    models = CloudflareWorkersAIProvider._extract_models(payload)

    assert [model.id for model in models] == ["@cf/zai-org/glm-4.7-flash"]
    assert models[0].context_window == 131072


@pytest.mark.asyncio
async def test_chat_uses_native_run_endpoint(monkeypatch):
    provider = CloudflareWorkersAIProvider()
    calls = []

    async def fake_request_json(api_key, method, path, json_payload=None):
        calls.append((api_key, method, path, json_payload))
        return {"result": {"response": "pong"}}

    monkeypatch.setattr(provider, "_request_json", fake_request_json)

    response = await provider.chat(
        f"{ACCOUNT_ID}:token-value",
        "@cf/zai-org/glm-4.7-flash",
        [ChatMessage(role="user", content="ping")],
        "system",
    )

    assert response.text == "pong"
    assert calls == [
        (
            f"{ACCOUNT_ID}:token-value",
            "POST",
            "ai/run/@cf/zai-org/glm-4.7-flash",
            {
                "messages": [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "ping"},
                ],
            },
        )
    ]
