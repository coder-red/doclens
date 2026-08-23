from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from .config import Settings
from .exports.webhook import dispatch_approved
from .ingest import IngestError, PageImage, load_document
from .models import Disposition, ExtractionPayload, Finding
from .prompt import build_prompt, build_repair_prompt
from .providers.base import ExtractionProvider, ProviderError
from .routing import decide_disposition
from .store import Store
from .validation import validate_payload

log = logging.getLogger("ledgerlens.pipeline")


@dataclass
class ProcessResult:
    document_id: str
    disposition: Disposition
    findings: list[Finding]
    payload: ExtractionPayload | None
    latency_ms: int


class PipelineError(RuntimeError):
    pass


def process_document(
    data: bytes,
    filename: str,
    *,
    provider: ExtractionProvider,
    store: Store,
    settings: Settings,
) -> ProcessResult:
    try:
        pages = load_document(data, filename, settings)
    except IngestError as exc:
        raise PipelineError(str(exc)) from exc

    raw, latency_s = _extract_with_repair(pages, provider)
    payload = _parse_payload(raw)

    findings = validate_payload(payload) if payload else [
        Finding(
            rule_id="V000",
            severity="error",
            field="document",
            message="model output could not be parsed into the extraction schema",
        )
    ]
    disposition = decide_disposition(payload, findings)

    doc_id = store.insert_document(
        source_filename=filename,
        content_sha256=hashlib.sha256(data).hexdigest(),
        page_count=len(pages),
        provider=provider.name,
        model=provider.model,
        latency_ms=int(latency_s * 1000),
        disposition=disposition,
        payload=payload,
        findings=findings,
        raw_response=raw,
    )

    if disposition == "approved" and settings.webhook_url:
        record = store.get_document(doc_id)
        if record is not None:
            dispatch_approved(record, store, settings)

    return ProcessResult(
        document_id=doc_id,
        disposition=disposition,
        findings=findings,
        payload=payload,
        latency_ms=int(latency_s * 1000),
    )


def _extract_with_repair(
    pages: list[PageImage], provider: ExtractionProvider
) -> tuple[dict, float]:
    started = time.monotonic()
    prompt = build_prompt()
    raw, _ = provider.extract(pages, prompt)
    if _is_schema_valid(raw):
        return raw, time.monotonic() - started
    log.info("schema validation failed on first pass; requesting repair")
    repair_prompt = build_repair_prompt(_dumps(raw), _schema_error(raw))
    try:
        raw2, _ = provider.extract(pages[:1], repair_prompt)
        if _is_schema_valid(raw2):
            log.info("repair pass produced a schema-valid payload")
            return raw2, time.monotonic() - started
    except ProviderError as exc:
        log.warning("repair pass failed: %s", exc)
    return raw, time.monotonic() - started


def _parse_payload(raw: dict) -> ExtractionPayload | None:
    try:
        return ExtractionPayload.model_validate(raw)
    except ValidationError as exc:
        log.warning("payload failed schema validation: %s", exc.error_count())
        return None


def _is_schema_valid(raw: dict) -> bool:
    try:
        ExtractionPayload.model_validate(raw)
        return True
    except ValidationError:
        return False


def _schema_error(raw: dict) -> str:
    try:
        ExtractionPayload.model_validate(raw)
        return "unknown"
    except ValidationError as exc:
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:5]
        )


def _dumps(raw: dict) -> str:
    import json

    try:
        return json.dumps(raw)[:4000]
    except TypeError:
        return str(raw)[:4000]
