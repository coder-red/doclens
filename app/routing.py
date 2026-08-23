from __future__ import annotations

from .models import CRITICAL_FIELDS, Disposition, ExtractionPayload, Finding
from .models import critical_missing


def decide_disposition(payload: ExtractionPayload | None, findings: list[Finding]) -> Disposition:
    """Route on arithmetic + evidence, never on model self-reported confidence."""
    if payload is None:
        return "failed"
    missing = critical_missing(payload)
    if len(missing) == len(CRITICAL_FIELDS):
        return "failed"
    if payload.total_amount is None:
        return "flagged"
    if findings:
        return "flagged"
    return "approved"
