from __future__ import annotations

from agent.llm_client import LLMClient


def test_llm_client_reuses_cached_instance_for_same_effective_config(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    LLMClient.clear_cache()

    config = {
        "llm": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "temperature_hcl": 0.0,
            "temperature_report": 0.2,
        }
    }

    first = LLMClient(config=config)
    second = LLMClient(config=config)

    assert first is second


def test_llm_client_creates_distinct_instances_for_distinct_configs(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    LLMClient.clear_cache()

    config = {
        "llm": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
        }
    }

    first = LLMClient(config=config)
    second = LLMClient(config=config, model_override="claude-3-5-sonnet-latest")

    assert first is not second


class _FakeUsage:
    input_tokens = 1200
    output_tokens = 300
    cache_read_input_tokens = 900
    cache_creation_input_tokens = 0
    iterations = []


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason
        self.stop_details = None
        self.model = "claude-opus-5"
        self.usage = _FakeUsage()


class _RecordingAnthropic:
    """Stands in for anthropic.Anthropic; records the request the client builds."""

    def __init__(self, response: _FakeResponse) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._response = response

        outer = self

        class _Messages:
            def create(self, **kwargs: object) -> _FakeResponse:
                outer.calls.append(("messages.create", kwargs))
                return outer._response

        class _Beta:
            class messages:  # noqa: N801 - mirrors the SDK attribute path
                @staticmethod
                def create(**kwargs: object) -> _FakeResponse:
                    outer.calls.append(("beta.messages.create", kwargs))
                    return outer._response

        self.messages = _Messages()
        self.beta = _Beta()


def _client(monkeypatch, fake: _RecordingAnthropic, **llm_cfg: object) -> LLMClient:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    LLMClient.clear_cache()
    client = LLMClient(config={"llm": {"provider": "anthropic", "model": "claude-opus-5", **llm_cfg}})
    monkeypatch.setattr(client, "_get_anthropic_client", lambda: fake)
    return client


def test_anthropic_structured_request_uses_schema_fallbacks_and_cache(monkeypatch) -> None:
    fake = _RecordingAnthropic(_FakeResponse('{"files": []}'))
    client = _client(monkeypatch, fake)

    result = client.generate_structured(
        prompt="volatile part",
        json_schema={"type": "object", "properties": {}, "additionalProperties": False},
        system_prompt="system",
        stable_prefix="stable part",
    )

    assert result == {"files": []}
    method, request = fake.calls[0]
    assert method == "beta.messages.create"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["fallbacks"] == "default"
    assert request["output_config"]["format"] == {
        "type": "json_schema",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    assert "temperature" not in request
    user_content = request["messages"][0]["content"]
    assert user_content[0]["text"] == "stable part" and user_content[0]["cache_control"] == {"type": "ephemeral"}
    assert user_content[1]["text"] == "volatile part"
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert client.last_usage.input_tokens == 1200 and client.total_usage.cache_read_input_tokens == 900


def test_anthropic_fallbacks_can_be_disabled(monkeypatch) -> None:
    fake = _RecordingAnthropic(_FakeResponse("notes"))
    client = _client(monkeypatch, fake, enable_fallbacks=False)

    assert client.generate_review_notes(prompt="p", system_prompt="s") == "notes"
    method, request = fake.calls[0]
    assert method == "messages.create"
    assert "fallbacks" not in request and "betas" not in request


def test_anthropic_refusal_and_truncation_raise_typed_errors(monkeypatch) -> None:
    import pytest

    from agent.llm_client import LLMRefusalError, LLMTruncatedError

    client = _client(monkeypatch, _RecordingAnthropic(_FakeResponse("", stop_reason="refusal")))
    with pytest.raises(LLMRefusalError):
        client.generate_hcl(prompt="p")

    client = _client(monkeypatch, _RecordingAnthropic(_FakeResponse("partial", stop_reason="max_tokens")), retry_attempts=1)
    with pytest.raises(LLMTruncatedError):
        client.generate_hcl(prompt="p")


def test_transient_errors_are_retried_with_backoff(monkeypatch) -> None:
    import anthropic

    from agent import llm_client as llm_module

    monkeypatch.setattr(llm_module.time, "sleep", lambda seconds: None)
    fake = _RecordingAnthropic(_FakeResponse("ok"))
    client = _client(monkeypatch, fake, retry_attempts=3)

    attempts = {"n": 0}

    def _flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
        return "ok"

    assert client._with_retries(_flaky) == "ok"
    assert attempts["n"] == 3
