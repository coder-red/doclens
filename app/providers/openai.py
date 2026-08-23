from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..ingest import PageImage
from .base import ProviderError, post_with_retries

API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def extract(self, pages: list[PageImage], prompt: str) -> tuple[dict[str, Any], float]:
        content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": page.data_url(), "detail": "high"}}
            for page in pages
        ]
        content.append({"type": "text", "text": prompt})
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content}],
        }
        started = time.monotonic()
        with httpx.Client(timeout=120) as client:
            resp = post_with_retries(
                client,
                "POST",
                API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json_body=body,
            )
        latency = time.monotonic() - started
        try:
            text = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected OpenAI response shape: {json.dumps(resp)[:500]}") from exc
        try:
            return json.loads(text or ""), latency
        except json.JSONDecodeError as exc:
            raise ProviderError(f"OpenAI returned invalid JSON: {(text or '')[:300]}") from exc
