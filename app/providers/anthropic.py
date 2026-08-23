from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..ingest import PageImage
from ..models import ExtractionPayload
from .base import ProviderError, post_with_retries

API_URL = "https://api.anthropic.com/v1/messages"
TOOL_NAME = "record_extraction"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def extract(self, pages: list[PageImage], prompt: str) -> tuple[dict[str, Any], float]:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": page.data_url().split(",", 1)[1],
                },
            }
            for page in pages
        ]
        content.append({"type": "text", "text": prompt})
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0,
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": "Record the extracted document fields.",
                    "input_schema": ExtractionPayload.model_json_schema(),
                }
            ],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
            "messages": [{"role": "user", "content": content}],
        }
        started = time.monotonic()
        with httpx.Client(timeout=120) as client:
            resp = post_with_retries(
                client,
                "POST",
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json_body=body,
            )
        latency = time.monotonic() - started
        for block in resp.get("content", []):
            if block.get("type") == "tool_use":
                return block.get("input") or {}, latency
        raise ProviderError(f"Anthropic returned no tool_use block: {json.dumps(resp)[:500]}")
