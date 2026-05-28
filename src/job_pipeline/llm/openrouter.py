from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable


OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    base_url: str = OPENROUTER_CHAT_COMPLETIONS_URL
    app_name: str = "Job Application Pipeline"
    site_url: str | None = None
    timeout_seconds: int = 90
    max_retries: int = 2


@dataclass(frozen=True)
class OpenRouterMessage:
    role: str
    content: str


@dataclass(frozen=True)
class OpenRouterResponse:
    model: str
    content: str
    raw: dict[str, Any]
    prompt_hash: str
    usage: dict[str, Any] | None = None


def load_openrouter_config_from_env() -> OpenRouterConfig | None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None
    return OpenRouterConfig(
        api_key=api_key,
        app_name=os.environ.get("OPENROUTER_APP_NAME", "Job Application Pipeline").strip()
        or "Job Application Pipeline",
        site_url=os.environ.get("OPENROUTER_SITE_URL", "").strip() or None,
    )


def prompt_hash(messages: Iterable[OpenRouterMessage]) -> str:
    payload = [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in messages
    ]
    return sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


def _extract_json_object(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    first_object = stripped.find("{")
    first_array = stripped.find("[")
    starts = [index for index in (first_object, first_array) if index >= 0]
    if not starts:
        raise ValueError("Model response did not contain JSON")
    start = min(starts)
    opener = stripped[start]
    closer = "}" if opener == "{" else "]"
    end = stripped.rfind(closer)
    if end < start:
        raise ValueError("Model response contained incomplete JSON")
    return json.loads(stripped[start : end + 1])


class OpenRouterClient:
    def __init__(self, config: OpenRouterConfig) -> None:
        self.config = config

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[OpenRouterMessage],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> OpenRouterResponse:
        body: dict[str, Any] = {
            "model": model,
            "messages": [message.__dict__ for message in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = response_format
        if extra_body:
            body.update(extra_body)

        encoded_body = json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "X-Title": self.config.app_name,
        }
        if self.config.site_url:
            headers["HTTP-Referer"] = self.config.site_url

        request = urllib.request.Request(
            self.config.base_url,
            data=encoded_body,
            headers=headers,
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                content = raw["choices"][0]["message"]["content"]
                return OpenRouterResponse(
                    model=str(raw.get("model") or model),
                    content=content,
                    raw=raw,
                    prompt_hash=prompt_hash(messages),
                    usage=raw.get("usage"),
                )
            except (OSError, TimeoutError, urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                time.sleep(2**attempt)
        raise RuntimeError(f"OpenRouter request failed: {last_error}") from last_error

    def complete_json(
        self,
        *,
        model: str,
        messages: list[OpenRouterMessage],
        temperature: float = 0.1,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> tuple[Any, OpenRouterResponse]:
        response = self.chat_completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            extra_body=extra_body,
        )
        return _extract_json_object(response.content), response
