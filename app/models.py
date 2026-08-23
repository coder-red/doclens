from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IssueType = Literal["not_found", "partial", "conflicting", "ambiguous"]
Severity = Literal["error", "warning"]
Disposition = Literal["approved", "flagged", "failed"]


class LineItem(BaseModel):
    description: str | None = Field(default=None, description="Item description exactly as printed.")
    quantity: float | None = Field(default=None, description="Units purchased. Null when not shown.")
    unit_price: float | None = Field(
        default=None, description="Price per single unit, numeric only. Null when not shown."
    )
    line_total: float | None = Field(
        default=None,
        description="Extended price for the row (quantity x unit price as printed), numeric only.",
    )


class FieldIssue(BaseModel):
    field: str = Field(description="Name of the schema field that has a problem.")
    issue_type: IssueType = Field(
        description=(
            "not_found: field does not appear on the document. "
            "partial: value visible but incomplete or partly illegible. "
            "conflicting: multiple different values present. "
            "ambiguous: value present but cannot be read reliably."
        )
    )
    notes: str | None = Field(default=None, description="Short explanation of the issue.")


class ExtractionPayload(BaseModel):
    """Single extraction contract every provider must satisfy.

    Rules the model must follow are embedded in these descriptions and in the
    prompt: never infer values, use null instead of guessing.
    """

    document_type: Literal["invoice", "receipt", "credit_note", "unknown"] = Field(
        default="unknown", description="Best classification of the document."
    )
    vendor_name: str | None = Field(
        default=None, description="Supplier or merchant legal/trading name exactly as printed."
    )
    vendor_tax_id: str | None = Field(
        default=None, description="VAT/GST/EIN/tax registration identifier if shown, else null."
    )
    invoice_number: str | None = Field(
        default=None,
        description="Invoice, receipt, or credit note number exactly as printed, else null.",
    )
    document_date: str | None = Field(
        default=None, description="Issue date normalized to YYYY-MM-DD. Null if missing/ambiguous."
    )
    due_date: str | None = Field(
        default=None, description="Payment due date YYYY-MM-DD. Null if not shown."
    )
    currency: str | None = Field(
        default=None,
        description=(
            "Three-letter ISO 4217 code matching the symbols/codes on the document "
            "(e.g. USD, EUR, GBP). Derive from the symbol only when unambiguous; else null."
        ),
    )
    subtotal: float | None = Field(
        default=None, description="Pre-tax subtotal as printed, numeric only, no symbols."
    )
    tax_amount: float | None = Field(
        default=None, description="Total tax/VAT as printed. Null when no tax line exists."
    )
    total_amount: float | None = Field(
        default=None, description="Final payable amount as printed, numeric only."
    )
    line_items: list[LineItem] = Field(
        default_factory=list, description="One entry per purchased item row, in document order."
    )
    fields_with_issues: list[FieldIssue] = Field(
        default_factory=list,
        description="Every field you could not read with certainty. Empty list only if all clear.",
    )


CRITICAL_FIELDS = ("vendor_name", "invoice_number", "total_amount")


def critical_missing(payload: ExtractionPayload) -> list[str]:
    return [f for f in CRITICAL_FIELDS if getattr(payload, f) is None]


class Finding(BaseModel):
    rule_id: str
    severity: Severity
    field: str
    message: str
