from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import Settings
from ..store import Store

log = logging.getLogger("doclens.webhook")


def dispatch_approved(record: dict[str, Any], store: Store, settings: Settings) -> bool:
    """Best-effort POST of an approved record. Never raises into the pipeline."""
    if not settings.webhook_url:
        return False
    status_code: int | None = None
    ok = False
    error: str | None = None
    try:
        resp = httpx.post(
            settings.webhook_url,
            json={"event": "document.approved", "data": record},
            headers=_headers(settings),
            timeout=settings.webhook_timeout_s,
        )
        status_code = resp.status_code
        ok = resp.is_success
        if not ok:
            error = f"non-success status {resp.status_code}: {resp.text[:200]}"
    except httpx.HTTPError as exc:
        error = str(exc)[:300]
    store.insert_webhook_delivery(
        document_id=record["id"],
        url=settings.webhook_url,
        status_code=status_code,
        ok=ok,
        error=error,
    )
    if not ok:
        log.warning("webhook delivery failed for %s: %s", record["id"], error)
    return ok


def _headers(settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.webhook_secret:
        headers["X-Webhook-Secret"] = settings.webhook_secret
    return headers


def delivery_log_jsonl(store: Store) -> str:
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM webhook_deliveries ORDER BY created_at"
        ).fetchall()
    lines = []
    for r in rows:
        d = dict(r)
        d["ok"] = bool(d.pop("ok"))
        lines.append(json.dumps(d, default=str))
    return "\n".join(lines)
