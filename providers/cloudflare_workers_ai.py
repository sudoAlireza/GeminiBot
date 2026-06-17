"""Cloudflare Workers AI provider using the native REST API."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable

import httpx

from monitoring.metrics import metrics
from providers.base import (
    AuthenticationError,
    Capability,
    ChatMessage,
    ChatResponse,
    ContentFilterError,
    InsufficientQuotaError,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.cloudflare.com/client/v4"
ACCOUNT_ID_RE = re.compile(r"^[a-fA-F0-9]{32}$")


DEFAULT_TEXT_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        id="@cf/zai-org/glm-4.7-flash",
        display_name="glm-4.7-flash",
        provider="cloudflare",
        capabilities=Capability.TEXT_CHAT | Capability.STREAMING | Capability.TOOL_USE,
        context_window=131072,
        input_price_per_mtok=0.06,
        output_price_per_mtok=0.40,
    ),
    ModelInfo(
        id="@cf/openai/gpt-oss-120b",
        display_name="gpt-oss-120b",
        provider="cloudflare",
        capabilities=Capability.TEXT_CHAT | Capability.STREAMING | Capability.TOOL_USE,
        context_window=128000,
        input_price_per_mtok=0.35,
        output_price_per_mtok=0.75,
    ),
    ModelInfo(
        id="@cf/openai/gpt-oss-20b",
        display_name="gpt-oss-20b",
        provider="cloudflare",
        capabilities=Capability.TEXT_CHAT | Capability.STREAMING | Capability.TOOL_USE,
    ),
    ModelInfo(
        id="@cf/meta/llama-4-scout-17b-16e-instruct",
        display_name="llama-4-scout-17b-16e-instruct",
        provider="cloudflare",
        capabilities=Capability.TEXT_CHAT | Capability.STREAMING | Capability.VISION | Capability.TOOL_USE,
    ),
    ModelInfo(
        id="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        display_name="llama-3.3-70b-instruct-fp8-fast",
        provider="cloudflare",
        capabilities=Capability.TEXT_CHAT | Capability.STREAMING | Capability.TOOL_USE,
    ),
    ModelInfo(
        id="@cf/qwen/qwen3-30b-a3b-fp8",
        display_name="qwen3-30b-a3b-fp8",
        provider="cloudflare",
        capabilities=Capability.TEXT_CHAT | Capability.STREAMING | Capability.TOOL_USE,
    ),
    ModelInfo(
        id="@cf/meta/llama-3.1-8b-instruct",
        display_name="llama-3.1-8b-instruct",
        provider="cloudflare",
        capabilities=Capability.TEXT_CHAT | Capability.STREAMING,
        context_window=7968,
        input_price_per_mtok=0.28,
        output_price_per_mtok=0.83,
    ),
)


class CloudflareCredentialError(ValueError):
    """Raised when Cloudflare credential input is missing required parts."""


def normalize_cloudflare_credentials(value: str) -> str:
    """Normalize user-entered credentials to ACCOUNT_ID:API_TOKEN or API_TOKEN.

    A token-only value is accepted when CLOUDFLARE_ACCOUNT_ID is configured in
    the deployment environment.
    """
    raw = value.strip()
    if not raw:
        raise CloudflareCredentialError("Cloudflare credentials are empty.")

    account_id: str | None = None
    token: str | None = None

    if ":" in raw:
        first, rest = raw.split(":", 1)
        if ACCOUNT_ID_RE.match(first.strip()) and rest.strip():
            account_id = first.strip()
            token = rest.strip()

    if not token:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) >= 2 and ACCOUNT_ID_RE.match(lines[0]):
            account_id = lines[0]
            token = lines[1]

    if not token:
        parts = raw.split()
        if len(parts) == 2 and ACCOUNT_ID_RE.match(parts[0]):
            account_id, token = parts

    if token:
        token = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", token).strip()
        if not token:
            raise CloudflareCredentialError("Cloudflare API token is empty.")
        return f"{account_id}:{token}" if account_id else token

    sanitized = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", raw).strip()
    if not sanitized:
        raise CloudflareCredentialError("Cloudflare API token is empty.")
    return sanitized


def _parse_cloudflare_credentials(api_key: str) -> tuple[str, str]:
    """Return (account_id, api_token) from stored credentials or env config."""
    raw = normalize_cloudflare_credentials(api_key)
    env_account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()

    if ":" in raw:
        account_id, token = raw.split(":", 1)
    else:
        account_id, token = env_account_id, raw

    account_id = account_id.strip()
    token = token.strip()
    if not ACCOUNT_ID_RE.match(account_id):
        raise AuthenticationError(
            "Cloudflare credentials must include a valid Account ID. "
            "Use ACCOUNT_ID:API_TOKEN or set CLOUDFLARE_ACCOUNT_ID.",
            provider="cloudflare",
        )
    if not token:
        raise AuthenticationError("Cloudflare API token is empty.", provider="cloudflare")
    return account_id, token


def _cloudflare_error_message(payload: Any, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback

    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        messages = []
        for error in errors:
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message") or error.get("detail")
                messages.append(f"{code}: {message}" if code and message else str(error))
            else:
                messages.append(str(error))
        return "; ".join(messages)

    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        return "; ".join(str(message) for message in messages)

    return str(payload.get("message") or fallback)


def _map_cloudflare_error(exc: Exception) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc

    msg = str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        try:
            payload = exc.response.json()
        except ValueError:
            payload = None
        msg = _cloudflare_error_message(payload, msg)

        if status_code in (401, 403):
            return AuthenticationError(msg, provider="cloudflare", original=exc)
        if status_code == 404:
            return ModelNotFoundError(msg, provider="cloudflare", original=exc)
        if status_code == 429:
            return RateLimitError(msg, provider="cloudflare", original=exc)
        if status_code == 402 or "quota" in msg.lower() or "insufficient" in msg.lower():
            return InsufficientQuotaError(msg, provider="cloudflare", original=exc)
        if status_code >= 500:
            return ServiceUnavailableError(msg, provider="cloudflare", original=exc)

    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return ServiceUnavailableError(msg, provider="cloudflare", original=exc)

    if "content filter" in msg.lower() or "safety" in msg.lower():
        return ContentFilterError(msg, provider="cloudflare", original=exc)

    return ProviderError(msg, provider="cloudflare", original=exc)


class CloudflareWorkersAIProvider:
    """Cloudflare Workers AI provider for text generation models."""

    provider_name: str = "cloudflare"
    display_name: str = "Cloudflare Workers AI"
    default_model: str = "@cf/zai-org/glm-4.7-flash"
    capabilities: Capability = Capability.TEXT_CHAT | Capability.STREAMING | Capability.STRUCTURED_OUTPUT

    async def validate_key(self, api_key: str) -> bool:
        try:
            await self.list_models(api_key)
            return True
        except Exception:
            return False

    async def list_models(self, api_key: str) -> list[ModelInfo]:
        try:
            payload = await self._request_json(api_key, "GET", "ai/models/search")
            models = self._extract_models(payload)
            return models or list(DEFAULT_TEXT_MODELS)
        except Exception as exc:
            logger.error(f"Failed to list Cloudflare Workers AI models: {exc}")
            raise _map_cloudflare_error(exc) from exc

    async def chat(
        self,
        api_key: str,
        model: str,
        messages: list[ChatMessage],
        system_instruction: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        model = model or self.default_model
        payload = {
            "messages": self._build_messages(messages, system_instruction),
        }
        self._apply_generation_kwargs(payload, kwargs)

        try:
            response = await self._request_json(api_key, "POST", f"ai/run/{model}", json_payload=payload)
            metrics.increment("cloudflare_messages_sent")
            return self._parse_response(response)
        except Exception as exc:
            metrics.increment("cloudflare_errors")
            raise _map_cloudflare_error(exc) from exc

    async def chat_stream(
        self,
        api_key: str,
        model: str,
        messages: list[ChatMessage],
        system_instruction: str | None = None,
        on_update: Callable[[str], Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        model = model or self.default_model
        payload = {
            "messages": self._build_messages(messages, system_instruction),
            "stream": True,
        }
        self._apply_generation_kwargs(payload, kwargs)

        start_time = time.monotonic()
        full_text = ""
        last_update_time = 0.0
        usage: dict[str, int] = {}

        try:
            async for event in self._stream_events(api_key, model, payload):
                event_text, event_usage = self._parse_stream_event(event)
                if event_usage:
                    usage = event_usage
                if not event_text:
                    continue
                full_text += event_text
                now = time.monotonic()
                if on_update and now - last_update_time >= 1.5:
                    try:
                        await on_update(full_text)
                    except Exception:
                        pass
                    last_update_time = now

            metrics.increment("cloudflare_messages_sent")
            metrics.record_latency("cloudflare_streaming", time.monotonic() - start_time)
            return ChatResponse(text=full_text, usage=usage)
        except Exception as exc:
            metrics.increment("cloudflare_errors")
            raise _map_cloudflare_error(exc) from exc

    async def chat_structured(
        self,
        api_key: str,
        model: str,
        messages: list[ChatMessage],
        schema: dict,
        system_instruction: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        schema_instruction = f"Respond with valid JSON matching this schema: {json.dumps(schema)}"
        combined_instruction = (
            f"{system_instruction}\n\n{schema_instruction}" if system_instruction else schema_instruction
        )
        response = await self.chat(
            api_key,
            model or self.default_model,
            messages,
            combined_instruction,
            response_format={"type": "json_object"},
            **kwargs,
        )
        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError:
            parsed = None
        response.metadata["parsed"] = parsed
        return response

    async def one_shot(
        self,
        api_key: str,
        model: str,
        prompt: str,
        system_instruction: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        return await self.chat(
            api_key,
            model or self.default_model,
            [ChatMessage(role="user", content=prompt)],
            system_instruction,
            **kwargs,
        )

    async def _request_json(
        self,
        api_key: str,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        account_id, token = _parse_cloudflare_credentials(api_key)
        url = f"{API_BASE_URL}/accounts/{account_id}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(method, url, headers=headers, json=json_payload)
            response.raise_for_status()
            payload = response.json()

        if isinstance(payload, dict) and payload.get("success") is False:
            raise ProviderError(_cloudflare_error_message(payload, "Cloudflare request failed"), provider="cloudflare")
        return payload

    async def _stream_events(self, api_key: str, model: str, payload: dict[str, Any]):
        account_id, token = _parse_cloudflare_credentials(api_key)
        url = f"{API_BASE_URL}/accounts/{account_id}/ai/run/{model}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        data = line.removeprefix("data:").strip()
                        if data == "[DONE]":
                            break
                        yield data

    @staticmethod
    def _build_messages(messages: list[ChatMessage], system_instruction: str | None = None) -> list[dict[str, str]]:
        cf_messages: list[dict[str, str]] = []
        if system_instruction:
            cf_messages.append({"role": "system", "content": system_instruction})

        for msg in messages:
            role = msg.role if msg.role in ("system", "assistant", "user") else "user"
            if msg.images:
                logger.warning("Cloudflare Workers AI image inputs are not supported by this provider yet")
            cf_messages.append({"role": role, "content": msg.content or ""})

        return cf_messages

    @staticmethod
    def _apply_generation_kwargs(payload: dict[str, Any], kwargs: dict[str, Any]) -> None:
        allowed_keys = {
            "max_tokens",
            "max_completion_tokens",
            "temperature",
            "top_p",
            "top_k",
            "seed",
            "repetition_penalty",
            "frequency_penalty",
            "presence_penalty",
            "response_format",
        }
        for key in allowed_keys:
            value = kwargs.get(key)
            if value is not None:
                payload[key] = value

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> ChatResponse:
        body = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        if not isinstance(body, dict):
            return ChatResponse(text=str(body or ""))

        text = ""
        if isinstance(body.get("response"), str):
            text = body["response"]
        elif isinstance(body.get("text"), str):
            text = body["text"]
        elif isinstance(body.get("output_text"), str):
            text = body["output_text"]
        elif isinstance(body.get("choices"), list) and body["choices"]:
            choice = body["choices"][0]
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    text = content if isinstance(content, str) else ""
                if not text and isinstance(choice.get("text"), str):
                    text = choice["text"]

        usage = CloudflareWorkersAIProvider._normalize_usage(body.get("usage") or payload.get("usage"))
        return ChatResponse(text=text or "", usage=usage, metadata={"raw": body})

    @staticmethod
    def _parse_stream_event(event: str) -> tuple[str, dict[str, int]]:
        try:
            payload = json.loads(event)
        except json.JSONDecodeError:
            return event, {}

        body = payload.get("result") if isinstance(payload, dict) and isinstance(payload.get("result"), dict) else payload
        if not isinstance(body, dict):
            return "", {}

        usage = CloudflareWorkersAIProvider._normalize_usage(body.get("usage") or payload.get("usage"))

        if isinstance(body.get("response"), str):
            return body["response"], usage

        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                delta = choice.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    return delta["content"], usage
                message = choice.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"], usage
                if isinstance(choice.get("text"), str):
                    return choice["text"], usage

        return "", usage

    @staticmethod
    def _normalize_usage(usage: Any) -> dict[str, int]:
        if not isinstance(usage, dict):
            return {}
        prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
        completion_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens) or 0
        return {
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "total_tokens": int(total_tokens),
        }

    @staticmethod
    def _extract_models(payload: dict[str, Any]) -> list[ModelInfo]:
        result = payload.get("result", payload)
        if isinstance(result, dict):
            candidates = (
                result.get("models")
                or result.get("items")
                or result.get("data")
                or result.get("result")
                or []
            )
        else:
            candidates = result

        if not isinstance(candidates, list):
            return []

        models: list[ModelInfo] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            model_id = (
                item.get("id")
                or item.get("name")
                or item.get("model")
                or item.get("source")
                or item.get("model_id")
            )
            if not isinstance(model_id, str) or not model_id.startswith("@cf/"):
                continue
            if not CloudflareWorkersAIProvider._is_text_generation_model(item):
                continue

            display_name = item.get("display_name") or item.get("name") or model_id.rsplit("/", 1)[-1]
            models.append(ModelInfo(
                id=model_id,
                display_name=str(display_name),
                provider="cloudflare",
                capabilities=CloudflareWorkersAIProvider._model_capabilities(item),
                context_window=CloudflareWorkersAIProvider._extract_context_window(item),
            ))

        models.sort(key=lambda model: model.id)
        return models

    @staticmethod
    def _is_text_generation_model(item: dict[str, Any]) -> bool:
        task = item.get("task")
        if isinstance(task, dict):
            task_text = " ".join(str(task.get(key, "")) for key in ("id", "name", "type")).lower()
            if task_text and "text generation" not in task_text and "text-generation" not in task_text:
                return False
        elif isinstance(task, str):
            task_text = task.lower()
            if "text generation" not in task_text and "text-generation" not in task_text:
                return False

        searchable = json.dumps(item, default=str).lower()
        non_chat_tasks = (
            "text embeddings",
            "text-embeddings",
            "text classification",
            "text-classification",
            "text-to-image",
            "text to image",
            "text-to-speech",
            "text to speech",
            "automatic speech recognition",
            "translation",
            "object detection",
            "image classification",
            "image-to-text",
        )
        if any(task_name in searchable for task_name in non_chat_tasks):
            return False

        taskish = ("text generation", "text-generation", "chat completion", "chat-completion")
        if any(task in searchable for task in taskish):
            deprecated_only = "deprecated" in searchable and "planned deprecation" not in searchable
            return not deprecated_only
        return True

    @staticmethod
    def _model_capabilities(item: dict[str, Any]) -> Capability:
        searchable = json.dumps(item, default=str).lower()
        capabilities = Capability.TEXT_CHAT | Capability.STREAMING
        if "vision" in searchable or "image" in searchable:
            capabilities |= Capability.VISION
        if "function" in searchable or "tool" in searchable:
            capabilities |= Capability.TOOL_USE
        return capabilities

    @staticmethod
    def _extract_context_window(item: dict[str, Any]) -> int:
        for key in ("context_window", "contextWindow", "context_length", "contextLength"):
            value = item.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return 0
