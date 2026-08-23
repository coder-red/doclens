from __future__ import annotations

import copy

import pytest

from app.models import ExtractionPayload
from app.pipeline import process_document
from app.providers.base import ProviderError

from tests.conftest import FakeProvider, _default_payload


def test_schema_repair_pass_recovers_from_bad_first_response(store, settings, sample_pdf_bytes):
    bad = {"document_type": "invoice", "vendor_name": "Acme", "line_items": [{"quantity": "many"}]}
    good = _default_payload()
    provider = FakeProvider([bad, good])
    result = process_document(
        sample_pdf_bytes, "repair.pdf", provider=provider, store=store, settings=settings
    )
    assert provider.calls == 2
    assert result.disposition == "approved"


def test_irreparable_payload_becomes_failed_not_crash(store, settings, sample_pdf_bytes):
    provider = FakeProvider([{"line_items": [{"quantity": "many"}]}])
    result = process_document(
        sample_pdf_bytes, "bad.pdf", provider=provider, store=store, settings=settings
    )
    assert result.disposition == "failed"
    assert any(f.rule_id == "V000" for f in result.findings)


def test_empty_payload_fails_with_missing_critical_findings(store, settings, sample_pdf_bytes):
    provider = FakeProvider([{"totally": "unrelated"}])
    result = process_document(
        sample_pdf_bytes, "empty.pdf", provider=provider, store=store, settings=settings
    )
    assert result.disposition == "failed"
    v001 = [f for f in result.findings if f.rule_id == "V001"]
    assert len(v001) == 3


def test_flagged_document_still_persisted_with_findings(store, settings, sample_pdf_bytes):
    flagged = _default_payload()
    flagged["currency"] = None
    provider = FakeProvider([flagged])
    result = process_document(
        sample_pdf_bytes, "flagged.pdf", provider=provider, store=store, settings=settings
    )
    assert result.disposition == "flagged"
    stored = store.get_document(result.document_id)
    assert any(f["rule_id"] == "V004" for f in stored["findings"])
    assert stored["raw_response"] == flagged


def test_duplicate_uploads_get_distinct_ids_and_same_hash(store, settings, sample_pdf_bytes):
    payload = _default_payload()
    provider = FakeProvider([payload, copy.deepcopy(payload)])
    r1 = process_document(sample_pdf_bytes, "same.pdf", provider=provider, store=store, settings=settings)
    r2 = process_document(sample_pdf_bytes, "same.pdf", provider=provider, store=store, settings=settings)
    assert r1.document_id != r2.document_id
    recs = store.list_documents()
    hashes = {r["content_sha256"] for r in recs}
    assert len(hashes) == 1


def test_payload_model_rejects_bad_enum():
    with pytest.raises(Exception):
        ExtractionPayload.model_validate({"document_type": "carrier_pigeon"})


