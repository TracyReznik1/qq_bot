from dataclasses import dataclass, field
from typing import Any

import requests

from src.config import Config


@dataclass(frozen=True)
class ChatResponse:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class DeepSeekClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        if not self.cfg.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": self.cfg.deepseek_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

        response = requests.post(
            self.cfg.deepseek_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.cfg.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            proxies=self.cfg.proxies,
            timeout=self.cfg.request_timeout,
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            tool_calls = []
        return ChatResponse(content=(message.get("content") or "").strip(), tool_calls=tool_calls)
