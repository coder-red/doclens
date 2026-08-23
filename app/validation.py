from __future__ import annotations

from datetime import date, timedelta

from .models import ExtractionPayload, Finding, LineItem


REL_TOL = 0.005
ABS_TOL = 0.02
MAGNITUDE_JUMP = 10.0


def validate_payload(payload: ExtractionPayload) -> list[Finding]:
    findings: list[Finding] = []
    findings += _check_required_fields(payload)
    findings += _check_dates(payload)
    findings += _check_currency(payload)
    findings += _check_line_items_sum(payload)
    findings += _check_subtotal_plus_tax(payload)
    findings += _check_totals_positive(payload)
    findings += _check_line_item_completeness(payload)
    findings += _check_magnitude(payload)
    findings += _check_reported_issues(payload)
    return findings


def _tolerance(amount: float) -> float:
    return max(ABS_TOL, REL_TOL * abs(amount))


def _money(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return round(f, 2)


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _check_required_fields(p: ExtractionPayload) -> list[Finding]:
    out: list[Finding] = []
    for field in ("vendor_name", "invoice_number", "total_amount"):
        if getattr(p, field) is None:
            out.append(
                Finding(
                    rule_id="V001",
                    severity="error",
                    field=field,
                    message=f"required field '{field}' is missing",
                )
            )
    return out


def _check_dates(p: ExtractionPayload) -> list[Finding]:
    out: list[Finding] = []
    doc_date = _parse_iso(p.document_date)
    due_date = _parse_iso(p.due_date)
    if p.document_date and doc_date is None:
        out.append(
            Finding(
                rule_id="V002",
                severity="error",
                field="document_date",
                message=f"document_date '{p.document_date}' is not a valid ISO date",
            )
        )
    elif doc_date and doc_date > date.today() + timedelta(days=1):
        out.append(
            Finding(
                rule_id="V002",
                severity="warning",
                field="document_date",
                message=f"document_date {doc_date} is in the future",
            )
        )
    if p.due_date and due_date is None:
        out.append(
            Finding(
                rule_id="V002",
                severity="error",
                field="due_date",
                message=f"due_date '{p.due_date}' is not a valid ISO date",
            )
        )
    if doc_date and due_date and due_date < doc_date:
        out.append(
            Finding(
                rule_id="V003",
                severity="warning",
                field="due_date",
                message=f"due_date {due_date} precedes document_date {doc_date}",
            )
        )
    return out


def _check_currency(p: ExtractionPayload) -> list[Finding]:
    has_amounts = any(a is not None for a in (p.subtotal, p.tax_amount, p.total_amount))
    if has_amounts and not p.currency:
        return [
            Finding(
                rule_id="V004",
                severity="warning",
                field="currency",
                message="amounts are present but no currency could be determined",
            )
        ]
    return []


def _line_total(item: LineItem) -> float | None:
    if item.line_total is not None:
        return _money(item.line_total)
    if item.quantity is not None and item.unit_price is not None:
        return round(item.quantity * item.unit_price, 2)
    return None


def _check_line_items_sum(p: ExtractionPayload) -> list[Finding]:
    if not p.line_items or p.subtotal is None:
        return []
    total = sum(t for t in (_line_total(i) for i in p.line_items) if t is not None)
    if total == 0 and all(_line_total(i) is None for i in p.line_items):
        return []
    diff = abs(total - p.subtotal)
    if diff > _tolerance(p.subtotal):
        return [
            Finding(
                rule_id="V005",
                severity="error",
                field="subtotal",
                message=(
                    f"line items sum to {total:.2f} but printed subtotal is "
                    f"{p.subtotal:.2f} (difference {diff:.2f}); a row was likely misread or dropped"
                ),
            )
        ]
    return []


def _check_subtotal_plus_tax(p: ExtractionPayload) -> list[Finding]:
    if p.subtotal is None or p.tax_amount is None or p.total_amount is None:
        return []
    expected = round(p.subtotal + p.tax_amount, 2)
    diff = abs(expected - p.total_amount)
    if diff > _tolerance(p.total_amount):
        return [
            Finding(
                rule_id="V006",
                severity="error",
                field="total_amount",
                message=(
                    f"subtotal {p.subtotal:.2f} + tax {p.tax_amount:.2f} = {expected:.2f} "
                    f"but printed total is {p.total_amount:.2f} (difference {diff:.2f})"
                ),
            )
        ]
    return []


def _check_totals_positive(p: ExtractionPayload) -> list[Finding]:
    out: list[Finding] = []
    if p.total_amount is not None and p.total_amount < 0 and p.document_type != "credit_note":
        out.append(
            Finding(
                rule_id="V007",
                severity="warning",
                field="total_amount",
                message="negative total on a non-credit-note document",
            )
        )
    for idx, item in enumerate(p.line_items, start=1):
        for name in ("quantity", "unit_price", "line_total"):
            v = getattr(item, name)
            if v is not None and v < 0 and p.document_type != "credit_note":
                out.append(
                    Finding(
                        rule_id="V007",
                        severity="warning",
                        field=f"line_items[{idx}].{name}",
                        message=f"negative {name} ({v}) on a non-credit-note document",
                    )
                )
    return out


def _check_line_item_completeness(p: ExtractionPayload) -> list[Finding]:
    incomplete = [
        idx
        for idx, item in enumerate(p.line_items, start=1)
        if _line_total(item) is None
    ]
    if incomplete:
        rows = ", ".join(str(i) for i in incomplete[:10])
        return [
            Finding(
                rule_id="V008",
                severity="warning",
                field="line_items",
                message=f"rows with no computable amount: [{rows}]",
            )
        ]
    return []


def _check_magnitude(p: ExtractionPayload) -> list[Finding]:
    if p.subtotal in (None, 0) or p.total_amount is None:
        return []
    ratio = abs(p.total_amount / p.subtotal)  # type: ignore[operator]
    if ratio >= MAGNITUDE_JUMP or ratio <= 1 / MAGNITUDE_JUMP:
        return [
            Finding(
                rule_id="V010",
                severity="warning",
                field="total_amount",
                message=(
                    f"total differs from subtotal by a factor of {ratio:.1f}; "
                    "possible order-of-magnitude misread"
                )
                ,
            )
        ]
    return []


def _check_reported_issues(p: ExtractionPayload) -> list[Finding]:
    if not p.fields_with_issues:
        return []
    names = ", ".join(sorted({issue.field for issue in p.fields_with_issues}))
    return [
        Finding(
            rule_id="V009",
            severity="warning",
            field=names,
            message=(
                f"extraction model reported low confidence on: {names}; "
                "review these fields against the source document"
            ),
        )
    ]
