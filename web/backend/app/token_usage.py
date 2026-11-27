"""Capture provider token counts without changing the framework ChatModel."""

from __future__ import annotations

from typing import Any


def _count(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


class TokenUsage:
    """Accumulate OpenAI-style or input/output-style usage from one task."""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.calls = 0

    def observe(self, response: Any) -> None:
        try:
            if getattr(response, "status_code", 200) != 200:
                return
            payload = response.json()
        except Exception:  # noqa: BLE001 - usage telemetry is best effort
            return
        if not isinstance(payload, dict):
            return
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        self.calls += 1
        prompt = _count(usage.get("prompt_tokens") or usage.get("input_tokens"))
        completion = _count(
            usage.get("completion_tokens") or usage.get("output_tokens")
        )
        total = _count(usage.get("total_tokens")) or (prompt + completion)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total

    def as_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "token_calls": self.calls,
        }


class UsageTrackingClient:
    """Proxy the one method ChatModel uses and read token usage from responses."""

    def __init__(self, client: Any, usage: TokenUsage) -> None:
        self._client = client
        self._usage = usage

    async def post(self, *args, **kwargs):
        response = await self._client.post(*args, **kwargs)
        self._usage.observe(response)
        return response

    def __getattr__(self, name):
        return getattr(self._client, name)
