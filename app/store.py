from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Disposition, ExtractionPayload, Finding

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    payload_json TEXT,
    findings_json TEXT NOT NULL,
    raw_response_json TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_disposition ON documents(disposition);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    url TEXT NOT NULL,
    status_code INTEGER,
    ok INTEGER NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    record = dict(row)
    payload_json = record.pop("payload_json", None)
    record["payload"] = json.loads(payload_json) if payload_json else None
    findings_json = record.pop("findings_json", None)
    record["findings"] = json.loads(findings_json) if findings_json else []
    raw_json = record.pop("raw_response_json", None)
    record["raw_response"] = json.loads(raw_json) if raw_json else None
    return record


class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_document(
        self,
        *,
        source_filename: str,
        content_sha256: str,
        page_count: int,
        provider: str,
        model: str,
        latency_ms: int,
        disposition: Disposition,
        payload: ExtractionPayload | None,
        findings: list[Finding],
        raw_response: dict[str, Any] | None,
    ) -> str:
        doc_id = uuid.uuid4().hex[:12]
        row = (
            doc_id,
            _now(),
            source_filename,
            content_sha256,
            page_count,
            provider,
            model,
            latency_ms,
            disposition,
            payload.model_dump_json() if payload else None,
            json.dumps([f.model_dump() for f in findings]),
            json.dumps(raw_response) if raw_response is not None else None,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO documents (
                       id, created_at, source_filename, content_sha256, page_count,
                       provider, model, latency_ms, disposition, payload_json,
                       findings_json, raw_response_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        return doc_id

    def list_documents(
        self, disposition: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        query = """SELECT id, created_at, source_filename, content_sha256, page_count,
                          provider, model, latency_ms, disposition, payload_json,
                          findings_json, review_status, review_note
                   FROM documents"""
        params: list[Any] = []
        if disposition:
            query += " WHERE disposition = ?"
            params.append(disposition)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        return [_decode_row(r) for r in rows]

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
        if row is None:
            return None
        return _decode_row(dict(row))

    def update_review(
        self, doc_id: str, review_status: str, review_note: str | None
    ) -> bool:
        if review_status not in ("approved", "rejected"):
            raise ValueError("review_status must be 'approved' or 'rejected'")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE documents SET review_status = ?, review_note = ? WHERE id = ?",
                (review_status, review_note, doc_id),
            )
            return cur.rowcount > 0

    def counts_by_disposition(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT disposition, COUNT(*) AS n FROM documents GROUP BY disposition"
            ).fetchall()
        counts = {r["disposition"]: r["n"] for r in rows}
        return {
            "approved": counts.get("approved", 0),
            "flagged": counts.get("flagged", 0),
            "failed": counts.get("failed", 0),
        }

    def documents_for_duplicate_check(self) -> list[dict[str, Any]]:
        query = """SELECT id, created_at, content_sha256, payload_json
                   FROM documents WHERE disposition IN ('approved', 'flagged')"""
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(query).fetchall()]
        out = []
        for r in rows:
            payload_json = r.pop("payload_json", None)
            r["payload"] = json.loads(payload_json) if payload_json else None
            out.append(r)
        return out

    def audit_log_lines(self) -> list[str]:
        records = self.list_documents(limit=100000)
        return [json.dumps(r, default=str) for r in records]

    def insert_webhook_delivery(
        self, *, document_id: str, url: str, status_code: int | None, ok: bool, error: str | None
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO webhook_deliveries (id, document_id, url, status_code, ok, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (uuid.uuid4().hex[:12], document_id, url, status_code, int(ok), error, _now()),
            )
