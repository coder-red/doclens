from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .config import Settings, get_settings
from .exports import build_workbook
from .exports.webhook import delivery_log_jsonl
from .pipeline import PipelineError, process_document
from .providers import ProviderError, get_provider
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ALLOWED_REVIEW_STATUSES = ("pending", "approved", "rejected")


class ReviewRequest(BaseModel):
    review_status: str
    review_note: str | None = None

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="DocLens", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_store_instance: Store | None = None


def get_store(settings: Settings = Depends(get_settings)) -> Store:
    global _store_instance
    if _store_instance is None or _store_instance.db_path != settings.db_path:
        _store_instance = Store(settings.db_path)
    return _store_instance


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/extract")
async def extract(
    request: Request,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: Store = Depends(get_store),
):
    data = await file.read()
    filename = file.filename or "upload.bin"
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        provider = get_provider(settings)
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        result = process_document(
            data, filename, provider=provider, store=store, settings=settings
        )
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"extraction provider failed: {exc}") from exc
    record = store.get_document(result.document_id)
    if _wants_html(request):
        return RedirectResponse(f"/documents/{result.document_id}", status_code=303)
    return JSONResponse(status_code=201, content=record)


@app.get("/")
def dashboard(
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
):
    counts = store.counts_by_disposition()
    recent = store.list_documents(limit=25)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"counts": counts, "recent": recent, "provider_configured": _provider_name(settings)},
    )


@app.get("/documents/{doc_id}")
def document_detail(
    doc_id: str,
    request: Request,
    store: Store = Depends(get_store),
):
    record = store.get_document(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document not found")
    return templates.TemplateResponse(request, "detail.html", {"record": record})


@app.get("/api/documents")
def api_list_documents(
    disposition: str | None = None,
    limit: int = 100,
    store: Store = Depends(get_store),
):
    return store.list_documents(disposition=disposition, limit=min(limit, 500))


@app.get("/api/documents/{doc_id}")
def api_get_document(doc_id: str, store: Store = Depends(get_store)):
    record = store.get_document(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document not found")
    return record


@app.patch("/api/documents/{doc_id}/review")
def api_review(doc_id: str, body: ReviewRequest, store: Store = Depends(get_store)):
    if body.review_status not in ALLOWED_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="review_status must be approved/rejected/pending")
    try:
        updated = store.update_review(doc_id, body.review_status, body.review_note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="document not found")
    return store.get_document(doc_id)


@app.post("/documents/{doc_id}/review")
def ui_review(
    doc_id: str,
    review_status: str = Form(...),
    review_note: str = Form(""),
    store: Store = Depends(get_store),
):
    if review_status in ("approved", "rejected"):
        try:
            store.update_review(doc_id, review_status, review_note or None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/documents/{doc_id}", status_code=303)


@app.get("/export/excel.xlsx")
def export_excel(store: Store = Depends(get_store)):
    records = store.list_documents(limit=100000)
    content = build_workbook(records)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="DocLens_extractions.xlsx"'},
    )


@app.get("/export/audit-log.jsonl")
def export_audit_log(store: Store = Depends(get_store)):
    lines = "\n".join(store.audit_log_lines())
    return Response(
        content=(lines + "\n") if lines else "",
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="audit_log.jsonl"'},
    )


@app.get("/export/webhook-deliveries.jsonl")
def export_webhook_log(store: Store = Depends(get_store)):
    return Response(
        content=delivery_log_jsonl(store) + "\n",
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": 'attachment; filename="webhook_deliveries.jsonl"'
        },
    )


def _provider_name(settings: Settings) -> str | None:
    from .providers import get_provider as _gp

    try:
        return _gp(settings).name
    except ProviderError:
        return None
