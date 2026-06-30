from __future__ import annotations

import requests


class DiscordWebhookSender:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send_message(self, content: str) -> None:
        if not self.webhook_url:
            raise RuntimeError("DISCORD_WEBHOOK_URL saknas.")
        if len(content) > 2000:
            for chunk in _split_message(content, 2000):
                self._post(chunk)
            return
        self._post(content)

    def _post(self, content: str) -> None:
        response = requests.post(
            self.webhook_url,
            json={"content": content},
            timeout=30,
        )
        response.raise_for_status()


def _split_message(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks
