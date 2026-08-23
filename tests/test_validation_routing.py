from __future__ import annotations

import pytest

from app.models import ExtractionPayload, FieldIssue, Finding
from app.routing import decide_disposition
from app.validation import validate_payload


def base_payload(**overrides) -> ExtractionPayload:
    data = dict(
        document_type="invoice",
        vendor_name="Acme Corp",
        invoice_number="INV-1",
        document_date="2026-06-01",
        due_date="2026-07-01",
        currency="USD",
        subtotal=100.00,
        tax_amount=8.50,
        total_amount=108.50,
        line_items=[
            {"description": "Widget", "quantity": 10, "unit_price": 10.0, "line_total": 100.00},
        ],
        fields_with_issues=[],
    )
    data.update(overrides)
    return ExtractionPayload.model_validate(data)


def rule_ids(findings):
    return {f.rule_id for f in findings}


class TestCleanPayload:
    def test_perfect_payload_has_no_findings(self):
        assert validate_payload(base_payload()) == []

    def test_missing_tax_is_not_an_error(self):
        p = base_payload(tax_amount=None)
        assert validate_payload(p) == []


class TestRequiredFields:
    def test_missing_critical_fields_are_errors(self):
        p = base_payload(vendor_name=None, invoice_number=None, total_amount=None, line_items=[])
        ids = rule_ids(validate_payload(p))
        assert "V001" in ids

    def test_each_missing_critical_field_reported(self):
        findings = validate_payload(base_payload(total_amount=None))
        v001 = [f for f in findings if f.rule_id == "V001"]
        assert any(f.field == "total_amount" for f in v001)


class TestArithmetic:
    def test_line_items_must_sum_to_subtotal(self):
        p = base_payload(
            line_items=[
                {"description": "A", "quantity": 1, "unit_price": 10.0, "line_total": 10.00},
                {"description": "B", "quantity": 1, "unit_price": 10.0, "line_total": 10.00},
            ]
        )
        findings = [f for f in validate_payload(p) if f.rule_id == "V005"]
        assert len(findings) == 1
        assert findings[0].severity == "error"
        assert "80.00" in findings[0].message

    def test_subtotal_plus_tax_must_equal_total(self):
        p = base_payload(total_amount=118.50)
        findings = [f for f in validate_payload(p) if f.rule_id == "V006"]
        assert len(findings) == 1
        assert findings[0].field == "total_amount"

    def test_small_rounding_difference_passes(self):
        p = base_payload(subtotal=100.00, tax_amount=8.51, total_amount=108.49)
        assert validate_payload(p) == []

    def test_dropped_row_detected_via_quantity_times_unit_price(self):
        p = base_payload(
            line_items=[
                {"description": "Widget", "quantity": 10, "unit_price": 10.0, "line_total": None},
            ]
        )
        assert validate_payload(p) == []

    def test_order_of_magnitude_flagged(self):
        p = base_payload(subtotal=100.00, tax_amount=0.0, total_amount=1000.00)
        assert "V010" in rule_ids(validate_payload(p))


class TestDates:
    def test_invalid_date_string_is_error(self):
        p = base_payload(document_date="01/06/2026")
        findings = [f for f in validate_payload(p) if f.rule_id == "V002"]
        assert any(f.severity == "error" for f in findings)

    def test_future_document_date_warns(self):
        p = base_payload(document_date="2099-01-01")
        findings = [f for f in validate_payload(p) if f.rule_id == "V002"]
        assert any(f.severity == "warning" for f in findings)

    def test_due_before_issue_warns(self):
        p = base_payload(due_date="2026-05-01")
        assert "V003" in rule_ids(validate_payload(p))


class TestCurrencyAndTotals:
    def test_amounts_without_currency_warn(self):
        p = base_payload(currency=None)
        assert "V004" in rule_ids(validate_payload(p))

    def test_negative_total_on_invoice_warns(self):
        p = base_payload(total_amount=-108.50)
        assert "V007" in rule_ids(validate_payload(p))

    def test_negative_total_on_credit_note_does_not_warn(self):
        p = base_payload(document_type="credit_note", total_amount=-108.50,
                         line_items=[{"description": "R", "quantity": -1, "unit_price": 100.0, "line_total": -100.0}])
        assert "V007" not in rule_ids(validate_payload(p))


class TestCompletenessAndReportedIssues:
    def test_incomplete_line_item_rows_warn(self):
        p = base_payload(
            line_items=[
                {"description": "Mystery row", "quantity": None, "unit_price": None, "line_total": None},
                {"description": "Ok", "quantity": 1, "unit_price": 100.0, "line_total": 100.0},
            ]
        )
        findings = [f for f in validate_payload(p) if f.rule_id == "V008"]
        assert len(findings) == 1
        assert "1" in findings[0].message

    def test_model_reported_issues_become_warnings(self):
        p = base_payload(
            fields_with_issues=[
                FieldIssue(field="due_date", issue_type="not_found"),
            ]
        )
        findings = [f for f in validate_payload(p) if f.rule_id == "V009"]
        assert len(findings) == 1
        assert "due_date" in findings[0].message


class TestRouting:
    def test_no_payload_fails(self):
        assert decide_disposition(None, []) == "failed"

    def test_all_critical_missing_fails(self):
        p = base_payload(vendor_name=None, invoice_number=None, total_amount=None, line_items=[])
        assert decide_disposition(p, []) == "failed"

    def test_no_total_but_line_items_is_flagged(self):
        p = base_payload(total_amount=None)
        assert decide_disposition(p, []) == "flagged"

    def test_clean_payload_approved(self):
        assert decide_disposition(base_payload(), []) == "approved"

    def test_any_warning_flags_for_review(self):
        f = Finding(rule_id="V004", severity="warning", field="currency", message="no currency")
        assert decide_disposition(base_payload(), [f]) == "flagged"

    def test_any_error_flags_for_review(self):
        f = Finding(rule_id="V005", severity="error", field="subtotal", message="mismatch")
        assert decide_disposition(base_payload(), [f]) == "flagged"

    @pytest.mark.parametrize(
        "mutate",
        [
            {"currency": None},
            {"fields_with_issues": [FieldIssue(field="vendor_name", issue_type="partial")]},
        ],
        ids=["missing-currency", "reported-issue"],
    )
    def test_realistic_flagged_documents_route_correctly(self, mutate):
        p = base_payload(**mutate)
        findings = validate_payload(p)
        assert decide_disposition(p, findings) == "flagged"
