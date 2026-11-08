"""AGT LLM Client and JSON extraction utilities."""
from __future__ import annotations

import json
import os
from typing import Any

import httpx


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Scan text for balanced {...} substrings and parse with json.loads.

    Handles strings and escapes, returning the first valid dict found (or None).
    """
    if not isinstance(text, str):
        return None

    n = len(text)
    for start_idx in range(n):
        if text[start_idx] != "{":
            continue

        depth = 0
        in_string = False
        escape = False
        for i in range(start_idx, n):
            char = text[i]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start_idx : i + 1]
                        try:
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass
                        break
    return None


class AGTClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        if base_url is None:
            base_url = os.getenv("AGT_BASE_URL", "http://127.0.0.1:4000/v1")
        if api_key is None:
            api_key = os.getenv("AGT_API_KEY", "")
        if model is None:
            model = os.getenv("AGT_MODEL", "gemini-3.8-flash")
        if timeout is None:
            raw_timeout = os.getenv("AGT_TIMEOUT_SECONDS", "20.0")
            try:
                timeout = float(raw_timeout)
            except (ValueError, TypeError):
                timeout = 20.0

        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "AGTClient":
        return cls()

    def is_configured(self) -> bool:
        return bool(self.api_key) and os.getenv("RING_OFFLINE_MODE") != "1"

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "dsh/1.0",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = httpx.post(url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
