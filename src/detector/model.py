"""A configurable Chat Completions adapter for OpenAI-compatible endpoints."""

import httpx



class ModelError(RuntimeError):
    """A sanitized provider failure suitable for inclusion in a result report."""


class ChatModel:
    """Use an injected HTTP client so connections and test transports stay explicit."""

    def __init__(
        self, client: httpx.AsyncClient, *, base_url: str, model: str, api_key: str = "",
        json_mode: bool = False,
    ) -> None:
        """Configure an API base URL, model ID, and optional authentication."""
        url = httpx.URL(base_url)
        if url.scheme not in ("https", "http") or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError("base_url must be an HTTP(S) API root without credentials, query, or fragment")
        if not model.strip():
            raise ValueError("a model ID is required")
        self.client, self.model = client, model
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.api_key, self.json_mode = api_key, json_mode

    async def complete(self, *, system: str, user: str) -> str:
        """Make one request without retries; reject refused or incomplete output."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {"model": self.model, "messages": messages}
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            response = await self.client.post(self.endpoint, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise ModelError("Model request timed out") from None
        except httpx.HTTPError:
            raise ModelError("Model transport failed") from None
        if response.status_code != 200:
            # Provider response bodies may contain submitted code or credentials.
            raise ModelError(f"Model endpoint returned HTTP {response.status_code}")
        try:
            choice = response.json()["choices"][0]
            message = choice["message"]
            reason = choice["finish_reason"]
            if reason != "stop" or message.get("refusal"):
                raise ModelError("Model response was refused or incomplete")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ModelError("Model response requires non-empty text")
            return content
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ModelError("Invalid Chat Completions response") from None
