from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..ingest import PageImage
from .base import ProviderError, post_with_retries

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def extract(self, pages: list[PageImage], prompt: str) -> tuple[dict[str, Any], float]:
        parts: list[dict[str, Any]] = [
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": page.data_url().split(",", 1)[1],
                }
            }
            for page in pages
        ]
        parts.append({"text": prompt})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        started = time.monotonic()
        with httpx.Client(timeout=120) as client:
            resp = post_with_retries(
                client,
                "POST",
                API_URL.format(model=self.model),
                headers={"x-goog-api-key": self.api_key},
                json_body=body,
            )
        latency = time.monotonic() - started
        try:
            candidate = resp["candidates"][0]
            text = candidate["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected Gemini response shape: {json.dumps(resp)[:500]}") from exc
        try:
            return json.loads(text), latency
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Gemini returned invalid JSON: {text[:300]}") from exc
