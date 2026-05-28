from __future__ import annotations

import json
import os
from urllib.error import URLError
import urllib.parse
import urllib.request
from dataclasses import dataclass


TELEGRAM_MESSAGE_LIMIT = 4096


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


def load_telegram_config_from_env() -> TelegramConfig | None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return None
    return TelegramConfig(bot_token=bot_token, chat_id=chat_id)


def chunk_text(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            split_at = text.rfind("\n", start, end)
            if split_at <= start:
                split_at = text.rfind(" ", start, end)
            if split_at > start:
                end = split_at + 1
        chunks.append(text[start:end].rstrip())
        start = end
    return [chunk for chunk in chunks if chunk]


def send_telegram_message(config: TelegramConfig, text: str) -> list[dict[str, object]]:
    url = f"https://api.telegram.org/bot{config.bot_token}/sendMessage"
    responses: list[dict[str, object]] = []
    for chunk in chunk_text(text):
        payload = urllib.parse.urlencode(
            {
                "chat_id": config.chat_id,
                "text": chunk,
                "link_preview_options": json.dumps({"is_disabled": True}),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                if not parsed.get("ok"):
                    raise RuntimeError(f"Telegram API error: {body}")
                responses.append(parsed)
        except (OSError, TimeoutError, URLError) as exc:
            raise RuntimeError(f"Telegram delivery failed: {exc}") from exc
    return responses
