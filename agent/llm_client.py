from __future__ import annotations

import hashlib
import importlib
import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, ClassVar, Mapping

import anthropic
import openai
from anthropic import Anthropic
from dotenv import load_dotenv
from loguru import logger
from openai import OpenAI

# Server-side refusal fallbacks ("default" routes by refusal category; no model list to maintain).
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"
ALLOWED_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


class LLMRefusalError(ValueError):
    """The model (or its safety classifier) declined the request; not retryable as-is."""


class LLMTruncatedError(ValueError):
    """The response hit max_tokens; the caller should shrink the request or raise the limit."""


@dataclass(frozen=True)
class LLMSettings:
    provider: LLMProvider
    model: str
    temperature_hcl: float
    temperature_report: float
    max_tokens: int
    timeout_seconds: int
    api_key: str
    base_url: str | None
    effort: str | None = None
    retry_attempts: int = 3
    retry_backoff_seconds: float = 2.0
    sdk_max_retries: int = 2
    enable_fallbacks: bool = True


@dataclass
class LLMUsage:
    """Token accounting for one call (last_usage) or the whole client lifetime (total_usage)."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    model: str = ""
    stop_reason: str = ""
    served_by_fallback: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def add(self, other: "LLMUsage") -> None:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.model = other.model or self.model
        self.stop_reason = other.stop_reason or self.stop_reason
        self.served_by_fallback = self.served_by_fallback or other.served_by_fallback

    def summary(self) -> str:
        return (
            f"calls={self.calls} input_tokens={self.input_tokens} output_tokens={self.output_tokens} "
            f"cache_read={self.cache_read_input_tokens} cache_write={self.cache_creation_input_tokens} "
            f"model={self.model or 'n/a'}"
        )


class LLMClient:
    """Provider-agnostic LLM client used by graph nodes.

    Text generation (`generate_hcl`, `generate_review_notes`) and schema-constrained JSON
    (`generate_structured`) share one path with transient-error retries, refusal handling,
    truncation detection and token accounting.
    """

    _cache_lock: ClassVar[threading.Lock] = threading.Lock()
    _instance_cache: ClassVar[dict[str, "LLMClient"]] = {}

    def __new__(
        cls,
        config: Mapping[str, object],
        provider_override: str | None = None,
        model_override: str | None = None,
        base_url_override: str | None = None,
        api_key_override: str | None = None,
    ) -> "LLMClient":
        load_dotenv()

        cache_key = _build_client_cache_key(
            config=config,
            provider_override=provider_override,
            model_override=model_override,
            base_url_override=base_url_override,
            api_key_override=api_key_override,
        )

        with cls._cache_lock:
            cached = cls._instance_cache.get(cache_key)
            if cached is not None:
                return cached

            instance = super().__new__(cls)
            instance._cache_key = cache_key
            instance._initialized = False
            cls._instance_cache[cache_key] = instance
            return instance

    def __init__(
        self,
        config: Mapping[str, object],
        provider_override: str | None = None,
        model_override: str | None = None,
        base_url_override: str | None = None,
        api_key_override: str | None = None,
    ) -> None:
        with self.__class__._cache_lock:
            if getattr(self, "_initialized", False):
                return

            try:
                load_dotenv()
                self.settings = self._build_settings(
                    config=config,
                    provider_override=provider_override,
                    model_override=model_override,
                    base_url_override=base_url_override,
                    api_key_override=api_key_override,
                )

                self._anthropic_client: Anthropic | None = None
                self._openai_client: OpenAI | None = None
                self._google_client: Any | None = None
                self._google_legacy_model: Any | None = None
                self.last_usage: LLMUsage = LLMUsage()
                self.total_usage: LLMUsage = LLMUsage()

                self._initialized = True
            except Exception:
                cache_key = getattr(self, "_cache_key", "")
                if cache_key and self.__class__._instance_cache.get(cache_key) is self:
                    del self.__class__._instance_cache[cache_key]
                raise

        logger.info(
            "Initialized LLMClient with provider={} model={}",
            self.settings.provider.value,
            self.settings.model,
        )

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            cls._instance_cache.clear()

    # ── public API ────────────────────────────────────────────────────────────

    def generate_hcl(self, prompt: str, system_prompt: str | None = None) -> str:
        return self._generate(prompt=prompt, system_prompt=system_prompt, temperature=self.settings.temperature_hcl)

    def generate_review_notes(self, prompt: str, system_prompt: str | None = None) -> str:
        return self._generate(prompt=prompt, system_prompt=system_prompt, temperature=self.settings.temperature_report)

    def generate_structured(
        self,
        prompt: str,
        json_schema: dict[str, Any],
        system_prompt: str | None = None,
        stable_prefix: str | None = None,
        schema_name: str = "response",
    ) -> Any:
        """Return JSON parsed from a schema-constrained response.

        `stable_prefix` is content that repeats across calls (documentation, the CIM); it is
        placed first and marked cacheable so retries and batches hit the prompt cache.
        """
        text = self._generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=self.settings.temperature_hcl,
            json_schema=json_schema,
            stable_prefix=stable_prefix,
            schema_name=schema_name,
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM structured response is not valid JSON: {exc}") from exc

    def usage_summary(self) -> str:
        return self.total_usage.summary()

    # ── dispatch, retries ─────────────────────────────────────────────────────

    def _generate(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        json_schema: dict[str, Any] | None = None,
        stable_prefix: str | None = None,
        schema_name: str = "response",
    ) -> str:
        provider = self.settings.provider
        if provider == LLMProvider.ANTHROPIC:
            call: Callable[[], str] = lambda: self._generate_anthropic(prompt, system_prompt, json_schema, stable_prefix)
        elif provider == LLMProvider.OPENAI:
            call = lambda: self._generate_openai(prompt, system_prompt, temperature, json_schema, stable_prefix, schema_name)
        elif provider == LLMProvider.GOOGLE:
            call = lambda: self._generate_google(prompt, system_prompt, temperature, json_schema, stable_prefix)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        return self._with_retries(call)

    def _with_retries(self, call: Callable[[], str]) -> str:
        """Retry transient failures (rate limits, 5xx, network, timeouts) with jittered backoff.

        The SDKs already retry a couple of times internally; this outer loop covers longer
        outages. Refusals, truncation and 4xx errors are never retried here.
        """
        attempts = max(1, self.settings.retry_attempts)
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                return call()
            except (LLMRefusalError, LLMTruncatedError):
                raise
            except Exception as exc:  # classified below
                if not _is_transient(exc) or attempt == attempts - 1:
                    raise
                last_exc = exc
                delay = min(self.settings.retry_backoff_seconds * (2**attempt) + random.uniform(0, 1), 60.0)
                logger.warning(
                    "LLM call failed with transient error ({}); retry {}/{} in {:.1f}s",
                    exc.__class__.__name__,
                    attempt + 1,
                    attempts - 1,
                    delay,
                )
                time.sleep(delay)

        assert last_exc is not None
        raise last_exc

    # ── Anthropic ─────────────────────────────────────────────────────────────

    def _generate_anthropic(
        self,
        prompt: str,
        system_prompt: str | None,
        json_schema: dict[str, Any] | None,
        stable_prefix: str | None,
    ) -> str:
        client = self._get_anthropic_client()

        # Stable content first and cacheable; the volatile part (feedback, scope) last.
        content: list[dict[str, Any]] = []
        if stable_prefix and stable_prefix.strip():
            content.append({"type": "text", "text": stable_prefix, "cache_control": {"type": "ephemeral"}})
        content.append({"type": "text", "text": prompt})

        request: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "messages": [{"role": "user", "content": content}],
            "timeout": self.settings.timeout_seconds,
        }
        if system_prompt and system_prompt.strip():
            request["system"] = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

        # Claude 5-family models reject sampling parameters; determinism comes from the schema
        # and the deterministic validation loop, and effort controls thinking depth instead.
        output_config: dict[str, Any] = {}
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if self.settings.effort:
            output_config["effort"] = self.settings.effort
        if output_config:
            request["output_config"] = output_config

        if self.settings.enable_fallbacks:
            response = client.beta.messages.create(
                betas=[ANTHROPIC_FALLBACK_BETA],
                fallbacks="default",
                **request,
            )
        else:
            response = client.messages.create(**request)

        self._record_anthropic_usage(response)

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details is not None else None
            explanation = getattr(details, "explanation", None) if details is not None else None
            raise LLMRefusalError(
                f"Anthropic declined the request (category={category or 'unknown'}): {explanation or 'no explanation'}"
            )

        text = "\n".join(
            block.text for block in response.content if getattr(block, "type", None) == "text" and getattr(block, "text", "")
        ).strip()

        if stop_reason == "max_tokens":
            raise LLMTruncatedError(
                f"Anthropic response hit max_tokens={self.settings.max_tokens}; reduce the batch or raise llm.max_tokens"
            )
        if not text:
            raise ValueError("Anthropic response did not contain text content")
        return text

    def _record_anthropic_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        iterations = getattr(usage, "iterations", None) or []
        served_by_fallback = any(getattr(entry, "type", None) == "fallback_message" for entry in iterations)
        self._record_usage(
            LLMUsage(
                calls=1,
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                cache_read_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                cache_creation_input_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
                model=str(getattr(response, "model", "") or self.settings.model),
                stop_reason=str(getattr(response, "stop_reason", "") or ""),
                served_by_fallback=served_by_fallback,
            )
        )
        if served_by_fallback:
            logger.warning("Anthropic request was served by fallback model {}", getattr(response, "model", "?"))

    # ── OpenAI ────────────────────────────────────────────────────────────────

    def _generate_openai(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        json_schema: dict[str, Any] | None,
        stable_prefix: str | None,
        schema_name: str,
    ) -> str:
        client = self._get_openai_client()
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        user_text = f"{stable_prefix}\n\n{prompt}" if stable_prefix else prompt
        messages.append({"role": "user", "content": user_text})

        request: dict[str, Any] = {
            "model": self.settings.model,
            "temperature": temperature,
            "max_completion_tokens": self.settings.max_tokens,
            "messages": messages,
        }
        if json_schema is not None:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": json_schema, "strict": True},
            }

        response = client.chat.completions.create(**request)
        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        self._record_usage(
            LLMUsage(
                calls=1,
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                model=str(getattr(response, "model", "") or self.settings.model),
                stop_reason=str(getattr(choice, "finish_reason", "") or ""),
            )
        )

        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "content_filter":
            raise LLMRefusalError("OpenAI declined the request (content_filter)")
        if finish_reason == "length":
            raise LLMTruncatedError(f"OpenAI response hit max_completion_tokens={self.settings.max_tokens}")

        content = choice.message.content
        result = content.strip() if content else ""
        if not result:
            raise ValueError("OpenAI response did not contain text content")
        return result

    # ── Google ────────────────────────────────────────────────────────────────

    def _generate_google(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        json_schema: dict[str, Any] | None,
        stable_prefix: str | None,
    ) -> str:
        sdk = _load_google_sdk()
        body = f"{stable_prefix}\n\n{prompt}" if stable_prefix else prompt
        combined_prompt = body if not system_prompt else f"{system_prompt}\n\n{body}"

        if sdk["legacy"]:
            model = self._get_google_legacy_model(sdk["genai_module"])
            response = model.generate_content(
                combined_prompt,
                generation_config=sdk["genai_module"].GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=self.settings.max_tokens,
                ),
            )
        else:
            client = self._get_google_client(sdk["genai_module"])
            response = client.models.generate_content(
                model=self.settings.model,
                contents=combined_prompt,
                config=_build_google_generate_config(
                    types_module=sdk["types_module"],
                    temperature=temperature,
                    max_output_tokens=self.settings.max_tokens,
                    json_schema=json_schema,
                ),
            )

        usage = getattr(response, "usage_metadata", None)
        self._record_usage(
            LLMUsage(
                calls=1,
                input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
                output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
                model=self.settings.model,
            )
        )

        result = _extract_google_response_text(response)
        if not result:
            raise ValueError("Google response did not contain text content")
        return result

    # ── clients, settings, accounting ─────────────────────────────────────────

    def _record_usage(self, usage: LLMUsage) -> None:
        self.last_usage = usage
        self.total_usage.add(usage)
        logger.info("LLM usage: {}", usage.summary())

    def _get_anthropic_client(self) -> Anthropic:
        if self._anthropic_client is None:
            self._anthropic_client = Anthropic(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_seconds,
                max_retries=self.settings.sdk_max_retries,
            )
        return self._anthropic_client

    def _get_openai_client(self) -> OpenAI:
        if self._openai_client is None:
            self._openai_client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout_seconds,
                max_retries=self.settings.sdk_max_retries,
            )
        return self._openai_client

    def _get_google_client(self, genai_module: Any) -> Any:
        if self._google_client is None:
            self._google_client = genai_module.Client(api_key=self.settings.api_key)
        return self._google_client

    def _get_google_legacy_model(self, genai_module: Any) -> Any:
        if self._google_legacy_model is None:
            genai_module.configure(api_key=self.settings.api_key)
            self._google_legacy_model = genai_module.GenerativeModel(model_name=self.settings.model)
        return self._google_legacy_model

    def _build_settings(
        self,
        config: Mapping[str, object],
        provider_override: str | None,
        model_override: str | None,
        base_url_override: str | None,
        api_key_override: str | None,
    ) -> LLMSettings:
        llm_section = _get_mapping(config, "llm")

        env_provider = os.getenv("LLM_PROVIDER", "").strip().lower()
        provider_str = (provider_override or env_provider or _get_str(llm_section, "provider", "anthropic")).strip().lower()
        provider = LLMProvider(provider_str)

        models_map = _get_mapping(llm_section, "models")
        env_model = os.getenv("LLM_MODEL", "").strip()
        if model_override:
            model = model_override
        elif env_model:
            model = env_model
        elif _get_optional_str(llm_section, "model"):
            model = _get_str(llm_section, "model", _default_model(provider))
        elif models_map:
            model = _get_str(models_map, provider.value, _default_model(provider))
        else:
            model = _default_model(provider)

        effort = _get_optional_str(llm_section, "effort")
        if effort is not None:
            effort = effort.lower()
            if effort not in ALLOWED_EFFORT_LEVELS:
                raise ValueError(f"llm.effort must be one of {', '.join(ALLOWED_EFFORT_LEVELS)}")

        base_url: str | None
        if provider == LLMProvider.OPENAI:
            base_url = base_url_override or _resolve_openai_base_url() or _get_optional_str(llm_section, "base_url")
        else:
            base_url = None
        api_key = api_key_override or _resolve_api_key(provider)

        return LLMSettings(
            provider=provider,
            model=model,
            temperature_hcl=_get_float(llm_section, "temperature_hcl", 0.0),
            temperature_report=_get_float(llm_section, "temperature_report", 0.2),
            max_tokens=_get_int(llm_section, "max_tokens", 16000),
            timeout_seconds=_get_int(llm_section, "timeout_seconds", 300),
            api_key=api_key,
            base_url=base_url,
            effort=effort,
            retry_attempts=_get_int(llm_section, "retry_attempts", 3),
            retry_backoff_seconds=_get_float(llm_section, "retry_backoff_seconds", 2.0),
            sdk_max_retries=_get_int(llm_section, "sdk_max_retries", 2),
            enable_fallbacks=_get_bool(llm_section, "enable_fallbacks", True),
        )


def _is_transient(exc: Exception) -> bool:
    """Rate limits, server errors, network failures and timeouts are worth retrying; nothing else is."""
    for sdk in (anthropic, openai):
        if isinstance(exc, (sdk.RateLimitError, sdk.APIConnectionError, sdk.APITimeoutError)):
            return True
        if isinstance(exc, sdk.APIStatusError) and int(getattr(exc, "status_code", 0) or 0) >= 500:
            return True

    # google-genai raises ClientError/ServerError carrying a numeric code
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and (code == 429 or code >= 500):
        return True
    return False


def _resolve_api_key(provider: LLMProvider) -> str:
    env_var = {
        LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
        LLMProvider.OPENAI: "OPENAI_API_KEY",
        LLMProvider.GOOGLE: "GOOGLE_API_KEY",
    }[provider]

    value = os.getenv(env_var, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {env_var}")
    return value


def _load_google_sdk() -> dict[str, Any]:
    try:
        genai_module = importlib.import_module("google.genai")
        try:
            types_module = importlib.import_module("google.genai.types")
        except ModuleNotFoundError:
            types_module = None

        return {"legacy": False, "genai_module": genai_module, "types_module": types_module}
    except ModuleNotFoundError:
        try:
            legacy_module = importlib.import_module("google.generativeai")
            return {"legacy": True, "genai_module": legacy_module, "types_module": None}
        except ModuleNotFoundError as exc:
            raise ValueError("Google provider requires google-genai (preferred) or google-generativeai") from exc


def _build_google_generate_config(
    types_module: Any,
    temperature: float,
    max_output_tokens: int,
    json_schema: dict[str, Any] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_output_tokens}
    if json_schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_json_schema"] = json_schema

    if types_module is not None and hasattr(types_module, "GenerateContentConfig"):
        return types_module.GenerateContentConfig(**kwargs)
    return kwargs


def _extract_google_response_text(response: Any) -> str:
    direct_text = getattr(response, "text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    candidates = getattr(response, "candidates", None)
    if not isinstance(candidates, list):
        return ""

    chunks: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None)
        if not isinstance(parts, list):
            continue
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())

    return "\n".join(chunks).strip()


def _resolve_openai_base_url() -> str | None:
    for env_var in ("OPENAI_BASE_URL", "LLM_BASE_URL"):
        value = os.getenv(env_var, "").strip()
        if value:
            return value
    return None


def _default_model(provider: LLMProvider) -> str:
    return {
        LLMProvider.ANTHROPIC: "claude-opus-5",
        LLMProvider.OPENAI: "gpt-4o",
        LLMProvider.GOOGLE: "gemini-2.0-flash",
    }[provider]


def _build_client_cache_key(
    config: Mapping[str, object],
    provider_override: str | None,
    model_override: str | None,
    base_url_override: str | None,
    api_key_override: str | None,
) -> str:
    payload = {
        "llm_config": _normalize_cache_value(_get_mapping(config, "llm")),
        "provider_override": provider_override or "",
        "model_override": model_override or "",
        "base_url_override": base_url_override or "",
        "api_key_override_sha256": _hash_secret(api_key_override),
        "env": {
            "LLM_PROVIDER": os.getenv("LLM_PROVIDER", "").strip(),
            "LLM_MODEL": os.getenv("LLM_MODEL", "").strip(),
            "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "").strip(),
            "LLM_BASE_URL": os.getenv("LLM_BASE_URL", "").strip(),
            "ANTHROPIC_API_KEY_SHA256": _hash_secret(os.getenv("ANTHROPIC_API_KEY", "").strip()),
            "OPENAI_API_KEY_SHA256": _hash_secret(os.getenv("OPENAI_API_KEY", "").strip()),
            "GOOGLE_API_KEY_SHA256": _hash_secret(os.getenv("GOOGLE_API_KEY", "").strip()),
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_cache_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize_cache_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, set):
        return [_normalize_cache_value(item) for item in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [_normalize_cache_value(item) for item in value]
    return repr(value)


def _hash_secret(value: str | None) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _get_mapping(source: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = source.get(key)
    if isinstance(value, Mapping):
        return value
    return {}


def _get_str(source: Mapping[str, object], key: str, default: str) -> str:
    value = source.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _get_optional_str(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _get_int(source: Mapping[str, object], key: str, default: int) -> int:
    value = source.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return default


def _get_float(source: Mapping[str, object], key: str, default: float) -> float:
    value = source.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _get_bool(source: Mapping[str, object], key: str, default: bool) -> bool:
    value = source.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default
