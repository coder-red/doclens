from __future__ import annotations

import time
from typing import Any, Protocol

import httpx

from ..ingest import PageImage

MAX_ATTEMPTS = 3
BACKOFF_S = [1.0, 3.0]


class ProviderError(RuntimeError):
    pass


class ExtractionProvider(Protocol):
    name: str
    model: str

    def extract(self, pages: list[PageImage], prompt: str) -> tuple[dict[str, Any], float]:
        """Return (raw JSON dict from the model, latency seconds)."""
        ...


def post_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = client.request(method, url, headers=headers, json=json_body)
            if resp.status_code < 400:
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = ProviderError(
                    f"{resp.status_code} from {url}: {resp.text[:300]}"
                )
            else:
                raise ProviderError(f"{resp.status_code} from {url}: {resp.text[:500]}")
        except httpx.HTTPError as exc:
            last_exc = exc
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    raise ProviderError(f"request to {url} failed after {MAX_ATTEMPTS} attempts: {last_exc}")
