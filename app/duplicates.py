from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from rapidfuzz import fuzz

from .models import ExtractionPayload, Finding

VENDOR_MATCH = 90.0
STRONG_VENDOR_MATCH = 93.0
DATE_WINDOW_DAYS = 45


def _norm_number(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def check_duplicates(
    payload: ExtractionPayload,
    content_sha256: str,
    history: list[dict[str, Any]],
) -> list[Finding]:
    """Compare a new extraction against previously processed documents.

    history items carry id, content_sha256 and the parsed payload dict of each
    prior approved/flagged document.
    """
    findings: list[Finding] = []
    if payload is None:
        return findings

    for doc in history:
        prior = doc.get("payload") or {}
        if doc.get("content_sha256") == content_sha256:
            findings.append(
                Finding(
                    rule_id="V011",
                    severity="error",
                    field="content_sha256",
                    message=(
                        f"identical file already processed as document {doc.get('id')} "
                        f"({doc.get('created_at')}); possible double submission"
                    ),
                )
            )
            continue

        same_number = (
            _norm_number(payload.invoice_number)
            and _norm_number(payload.invoice_number) == _norm_number(prior.get("invoice_number"))
        )
        vendor_score = max(
            fuzz.token_sort_ratio(
                (payload.vendor_name or "").casefold(),
                (prior.get("vendor_name") or "").casefold(),
            ),
            fuzz.partial_ratio(
                (payload.vendor_name or "").casefold().strip(),
                (prior.get("vendor_name") or "").casefold().strip(),
            ),
        )

        if same_number and vendor_score >= VENDOR_MATCH:
            findings.append(
                Finding(
                    rule_id="V011",
                    severity="error",
                    field="invoice_number",
                    message=(
                        f"invoice number '{payload.invoice_number}' was already processed "
                        f"for a similar vendor as document {doc.get('id')}; likely duplicate"
                    ),
                )
            )
            continue

        totals = (payload.total_amount, prior.get("total_amount"))
        amounts_match = (
            totals[0] is not None
            and totals[1] is not None
            and abs(float(totals[0]) - float(totals[1])) <= 0.01
        )
        dates_close = False
        d1 = _parse_date(payload.document_date)
        d2 = _parse_date(prior.get("document_date"))
        if d1 and d2:
            dates_close = abs((d1 - d2).days) <= DATE_WINDOW_DAYS

        if (
            amounts_match
            and dates_close
            and vendor_score >= STRONG_VENDOR_MATCH
            and not same_number
        ):
            findings.append(
                Finding(
                    rule_id="V012",
                    severity="warning",
                    field="invoice_number",
                    message=(
                        f"same vendor and amount as document {doc.get('id')} but a different "
                        "invoice number; verify this is not the same invoice resubmitted"
                    ),
                )
            )
    return findings


def check_policy_limit(payload: ExtractionPayload, auto_approve_max: float | None) -> list[Finding]:
    if not auto_approve_max or payload.total_amount is None:
        return []
    if abs(payload.total_amount) > auto_approve_max:
        return [
            Finding(
                rule_id="V013",
                severity="warning",
                field="total_amount",
                message=(
                    f"total {abs(payload.total_amount):.2f} exceeds the auto-approval policy "
                    f"limit of {auto_approve_max:.2f}; routed to review by policy"
                ),
            )
        ]
    return []
