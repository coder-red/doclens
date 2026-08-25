from __future__ import annotations

import pytest

from app.config import Settings
from app.duplicates import check_duplicates, check_policy_limit
from app.models import ExtractionPayload
from app.pipeline import process_document
from app.store import Store

from tests.conftest import FakeProvider, _default_payload


def _payload(**over) -> ExtractionPayload:
    base = dict(
        document_type="invoice",
        vendor_name="Acme Corp",
        invoice_number="INV-77",
        document_date="2026-08-01",
        currency="USD",
        subtotal=100.0,
        tax_amount=None,
        total_amount=100.0,
        line_items=[{"description": "Widget", "quantity": 1, "unit_price": 100.0, "line_total": 100.0}],
    )
    base.update(over)
    return ExtractionPayload.model_validate(base)


class TestDuplicateDetection:
    def test_identical_file_hash_is_error(self):
        history = [{"id": "abc123", "created_at": "2026-08-01T00:00:00", "content_sha256": "samehash",
                    "payload": _payload().model_dump()}]
        findings = check_duplicates(_payload(), "samehash", history)
        assert any(f.rule_id == "V011" and f.severity == "error" for f in findings)

    def test_same_vendor_and_number_is_error_even_if_file_differs(self):
        history = [{"id": "doc01", "created_at": "x", "content_sha256": "other",
                    "payload": _payload(total_amount=102.0).model_dump()}]
        findings = check_duplicates(
            _payload(invoice_number="inv 77", total_amount=99.0), "newhash", history
        )
        v011 = [f for f in findings if f.rule_id == "V011"]
        assert len(v011) == 1 and v011[0].severity == "error"

    def test_lookalike_vendor_same_number_caught(self):
        history = [{"id": "doc02", "created_at": "x", "content_sha256": "h2",
                    "payload": _payload(vendor_name="ACME Corporation").model_dump()}]
        findings = check_duplicates(_payload(), "h3", history)
        assert any(f.rule_id == "V011" for f in findings)

    def test_same_vendor_amount_date_different_number_warns(self):
        history = [{"id": "doc03", "created_at": "x", "content_sha256": "h4",
                    "payload": _payload(invoice_number="INV-76").model_dump()}]
        findings = check_duplicates(
            _payload(invoice_number="INV-78"), "h5", history
        )
        assert any(f.rule_id == "V012" and f.severity == "warning" for f in findings)

    def test_unrelated_document_no_findings(self):
        history = [{"id": "doc04", "created_at": "x", "content_sha256": "h6",
                    "payload": _payload(vendor_name="Zeta GmbH", invoice_number="X-9",
                                        total_amount=555.0, document_date="2026-05-01").model_dump()}]
        assert check_duplicates(_payload(), "h7", history) == []

    def test_empty_history_no_findings(self):
        assert check_duplicates(_payload(), "h8", []) == []


class TestEndToEndDuplicates:
    def test_second_upload_of_same_file_routes_flagged(self, store, settings, sample_pdf_bytes):
        provider = FakeProvider()
        r1 = process_document(sample_pdf_bytes, "a.pdf", provider=provider, store=store, settings=settings)
        r2 = process_document(sample_pdf_bytes, "a.pdf", provider=provider, store=store, settings=settings)
        assert r1.disposition == "approved"
        assert r2.disposition == "flagged"
        stored = store.get_document(r2.document_id)
        dupes = [f for f in stored["findings"] if f["rule_id"] == "V011"]
        assert len(dupes) == 1


class TestPolicyLimit:
    def test_over_limit_flags_even_when_clean(self):
        findings = check_policy_limit(_payload(total_amount=900.0), auto_approve_max=500.0)
        assert len(findings) == 1
        assert findings[0].rule_id == "V013"

    def test_under_limit_clear(self):
        assert check_policy_limit(_payload(total_amount=100.0), auto_approve_max=500.0) == []

    def test_disabled_when_zero(self):
        assert check_policy_limit(_payload(total_amount=90000.0), auto_approve_max=0) == []

    @pytest.mark.parametrize("total,expected", [(4000.0, "approved"), (6000.0, "flagged")])
    def test_end_to_end_threshold(self, store, tmp_path, sample_pdf_bytes, total, expected):
        payload = _payload(
            vendor_name="Threshold Test Co",
            invoice_number=f"TT-{int(total)}",
            subtotal=total,
            tax_amount=None,
            total_amount=total,
            line_items=[
                {"description": "Block", "quantity": 1, "unit_price": total, "line_total": total}
            ],
        ).model_dump()

        s = Settings(db_path=tmp_path / f"t{int(total)}.db", auto_approve_max=5000.0)
        st = Store(s.db_path)
        result = process_document(
            sample_pdf_bytes, "t.pdf", provider=FakeProvider([payload]), store=st, settings=s
        )
        assert result.disposition == expected
