from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.main import app
from app.store import Store

from fixtures.generate_fixtures import GROUND_TRUTH_A


class FakeProvider:
    name = "fake"
    model = "fake-vision-1"

    def __init__(self, responses: list[dict] | None = None):
        self.responses = responses or [copy.deepcopy(_default_payload())]
        self.calls = 0

    def extract(self, pages, prompt) -> tuple[dict, float]:
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return copy.deepcopy(self.responses[idx]), 0.042


def _default_payload() -> dict:
    return {
        "document_type": "invoice",
        "vendor_name": GROUND_TRUTH_A["vendor_name"],
        "vendor_tax_id": "US-47-2913856",
        "invoice_number": GROUND_TRUTH_A["invoice_number"],
        "document_date": GROUND_TRUTH_A["document_date"],
        "due_date": GROUND_TRUTH_A["due_date"],
        "currency": GROUND_TRUTH_A["currency"],
        "subtotal": GROUND_TRUTH_A["subtotal"],
        "tax_amount": GROUND_TRUTH_A["tax_amount"],
        "total_amount": GROUND_TRUTH_A["total_amount"],
        "line_items": [
            {"description": "Executive Mesh Chair", "quantity": 4, "unit_price": 189.00, "line_total": 756.00},
            {"description": "Electric Standing Desk 160cm", "quantity": 2, "unit_price": 449.50, "line_total": 899.00},
            {"description": "Dual Monitor Arm", "quantity": 6, "unit_price": 54.25, "line_total": 325.50},
        ],
        "fields_with_issues": [],
    }


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    s = Settings(
        db_path=tmp_path / "test-DocLens.db",
        export_dir=tmp_path / "exports",
        gemini_api_key="test-key",
    )
    from app.config import get_settings

    app.dependency_overrides[get_settings] = lambda: s
    yield s
    app.dependency_overrides.clear()


@pytest.fixture()
def store(settings) -> Store:
    return Store(settings.db_path)


@pytest.fixture()
def sample_pdf_bytes() -> bytes:
    return (ROOT / "fixtures" / "layout_a_classic_invoice.pdf").read_bytes()


@pytest.fixture()
def client(settings, monkeypatch):
    from fastapi.testclient import TestClient

    fake = FakeProvider()
    monkeypatch.setattr("app.main.get_provider", lambda s: fake)
    with TestClient(app) as c:
        c.fake_provider = fake  # type: ignore[attr-defined]
        yield c
