from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("LEDGERLENS_LIVE_TEST"),
    reason="set LEDGERLENS_LIVE_TEST=1 plus a provider key to run live extraction",
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def _make_settings():
    from app.config import Settings

    return Settings()


def test_live_extraction_matches_ground_truth(tmp_path):
    from app.config import get_settings
    from app.pipeline import process_document
    from app.providers import ProviderError, get_provider
    from app.store import Store

    settings = get_settings()
    try:
        provider = get_provider(settings)
    except ProviderError as exc:
        pytest.skip(str(exc))

    ground_truth = __import__("json").loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    expected = ground_truth["layout_a"]
    store = Store(tmp_path / "live.db")

    result = process_document(
        (FIXTURES / expected["file"]).read_bytes(),
        expected["file"],
        provider=provider,
        store=store,
        settings=settings,
    )
    payload = result.payload
    assert payload is not None
    assert payload.vendor_name.casefold() == expected["vendor_name"].casefold()
    assert payload.invoice_number == expected["invoice_number"]
    assert abs(payload.total_amount - expected["total_amount"]) < 0.05
    assert abs(payload.subtotal - expected["subtotal"]) < 0.05
    assert result.disposition == "approved"
