# DocLens

**Live demo: [doclenss.onrender.com](https://doclenss.onrender.com)** — free-tier hosting, so the first load after 15 idle minutes takes ~50 seconds to spin up. Uploads from the demo are disposable (ephemeral disk).

![DocLens: upload → extraction → arithmetic validation → flagged vs approved routing](docs/demo.gif)

Invoice, receipt, and credit-note extraction with **arithmetic guardrails**. Upload a PDF or photo; get back structured fields (vendor, dates, totals, line items) that have been mechanically verified before they touch your books. Clean records are exported. Everything else is flagged — never silently booked.

Built for the messy real world: any vendor layout, scanned documents, phone photos of receipts.

## What it does

| Capability | How DocLens handles it |
|---|---|
| Structured fields from PDFs **and images** | Every input is rasterized (PyMuPDF/Pillow) and read by a vision LLM under a strict JSON schema — digital PDFs, scans, photos, and Word documents take the same path (.docx is normalized to rendered pages first) |
| Flag low-confidence extractions | Two independent flag sources: model-declared uncertainties (`fields_with_issues`) plus deterministic validation findings. Any finding routes the document out of the clean lane |
| Validate totals against line items | Rule engine checks line items → subtotal → subtotal + tax = total within tolerance, plus date sanity, currency presence, sign rules, and magnitude-shift detection |
| Handle multiple layouts | One schema-driven extractor covers all layouts — proven against three deliberately different fixtures (classic AP invoice, narrow thermal-receipt layout, Word-document invoice) and a degraded photo variant |
| Output to a real destination | Styled Excel workbook (Summary + LineItems sheets, disposition color-coding), optional shared-secret webhook POST (`X-Webhook-Secret` header) for approved records |
| Auditability | SQLite audit trail: SHA-256 of every source file, raw model response, per-rule findings, disposition, latency — exportable as JSONL |
| Duplicate & policy guards | Every upload is checked against processing history: identical files and repeated invoice numbers from similar vendors are rejected as likely duplicates (V011), resubmissions with a new number are warned (V012), and totals above `AUTO_APPROVE_MAX` always route to review (V013) |

## Why routing runs on arithmetic, not model confidence

Vision models are frequently *confidently wrong* on a misread digit, and their self-reported certainty correlates poorly with correctness. DocLens therefore treats the model's own uncertainty flags as advisory only and makes the go/no-go decision from deterministic invariants:

```
line items sum ≈ printed subtotal          (V005, error)
printed subtotal + tax ≈ printed total     (V006, error)
required fields present                    (V001, error)
duplicate file or repeated invoice number  (V011, error)
dates parse / due ≥ issue                  (V002–V003)
amounts without currency                   (V004, warning)
negative amounts outside credit notes      (V007, warning)
rows missing computable amounts            (V008, warning)
magnitude shift between subtotal/total     (V010, warning)
model-reported uncertain fields            (V009, warning)
same vendor+amount, new invoice number     (V012, warning)
total above auto-approval policy limit     (V013, warning)
```

Dispositions:

- **approved** — zero findings. Safe to auto-post; goes to Excel/webhook.
- **flagged** — usable data, at least one finding. Held in the review queue with the exact failing rules highlighted next to each field.
- **failed** — nothing bookable (unparseable output, not a financial document, all critical fields missing).

A malformed first pass triggers one automatic schema-repair re-request before giving up.

## Architecture

```
            ┌──────────┐   pages    ┌─────────────────────┐
 upload ──▶ │  ingest  ├──────────▶ │  vision provider    │
 PDF/img    │ PyMuPDF  │  PNG       │ Gemini/OpenAI/Claude│
            │ Pillow   │            │ JSON-mode output,   │
            └──────────┘            │ schema-validated    │
                                    └──────────┬──────────┘
                                               │ raw JSON (+1 repair retry)
                                               ▼
            ┌──────────┐   findings  ┌─────────────────────┐
            │ validate │◀────────────┤ ExtractionPayload   │
            │ V001-V010│             │ (Pydantic contract) │
            └────┬─────┘             └─────────────────────┘
                 ▼
            ┌──────────┐      ┌──────────────────────────────┐
            │  route   ├────▶ │ approved → Excel + webhook   │
            └────┬─────┘      │ flagged   → review queue UI  │
                 │            │ failed    → audit log only   │
                 ▼            └──────────────────────────────┘
            ┌──────────┐
            │  store   │  SQLite: payload, findings, raw response,
            └──────────┘  SHA-256, review state, webhook deliveries
```

## Quickstart

```bash
python -m venv .venv
pip install -r requirements.txt
cp .env.example .env        # then add at least one API key (Windows: copy .env.example .env)
uvicorn app.main:app --reload
```

Any one of `GEMINI_API_KEY` (free tier works), `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` enables extraction. Provider is auto-selected by available keys, or pinned via `PROVIDER=`.

### Test documents

Generate the fixture set (no API key needed):

```bash
python fixtures/generate_fixtures.py
```

- `layout_a_classic_invoice.pdf` — classic AP invoice: header block, itemized grid, totals block
- `layout_b_receipt_style.pdf` — narrow receipt layout, EUR, inline items
- `layout_c_word_invoice.docx` — Word-document invoice (plumbing services): proves the .docx normalization path
- `layout_b_receipt_degraded.jpg` — rotated, blurred, noisy JPEG simulating a phone photo

## Tests

```bash
python -m pytest
```

55 tests run fully offline against a fake provider. A live end-to-end test against the real LLM is opt-in:

```cmd
set DOCLENS_LIVE_TEST=1 && set GEMINI_API_KEY=... && python -m pytest tests\test_integration_live.py -v
```

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| POST | `/extract` | multipart `file` → full pipeline; returns the stored record |
| GET | `/api/documents?disposition=flagged` | list records (filterable) |
| GET | `/api/documents/{id}` | single record incl. findings + raw model response |
| PATCH | `/api/documents/{id}/review` | human review decision `{review_status, review_note}` |
| GET | `/export/excel.xlsx` | workbook: Summary + LineItems, color-coded dispositions |
| GET | `/export/audit-log.jsonl` | full audit trail, one JSON record per processed file |
| GET | `/export/webhook-deliveries.jsonl` | webhook delivery outcomes |
| GET | `/healthz` | liveness probe |

Example:

```bash
curl -F "file=@fixtures/layout_b_receipt_style.pdf" http://127.0.0.1:8000/extract
```

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `PROVIDER` | `auto` | `gemini` \| `openai` \| `anthropic` \| `auto` |
| `GEMINI_API_KEY` etc. | — | first available key wins in auto mode |
| `*_MODEL` | `gemini-2.5-flash` / `gpt-4o-mini` / `claude-sonnet-4-5-20250929` | override to pin whatever your provider currently offers |
| `MAX_PAGES` | `5` | multi-page PDFs truncated defensively |
| `MAX_IMAGE_PX` | `2000` | longest-side cap before upload |
| `DB_PATH` | `data/doclens.db` | SQLite audit store |
| `WEBHOOK_URL` / `WEBHOOK_SECRET` | — | POSTs approved records with `X-Webhook-Secret`; delivery attempts are logged |
| `AUTO_APPROVE_MAX` | `5000` | totals above this route to review even when all checks pass; set 0 to disable |

## Deployment

The repo ships `render.yaml` + `Dockerfile`. Easiest path on [Render](https://render.com): Dashboard → **New → Web Service** → connect this repo → Free instance → add `GEMINI_API_KEY` in Environment.

Free-instance caveats: the service sleeps after 15 idle minutes (~1 min wake-up), and the filesystem is ephemeral — hosted demo data is disposable. For production, attach a persistent disk or swap `store.py` for Postgres.

## Engineering decisions

1. **One schema, N layouts.** Per-vendor templates don't scale past ~10 vendors. The Pydantic contract (`app/models.py`) doubles as the JSON-schema constraint sent to providers and the runtime validator — one source of truth.
2. **Escape hatches over guesses.** The prompt and schema make `null` + an issue entry a *first-class success outcome*. The failure mode that matters isn't crashing, it's a plausible wrong total.
3. **Arithmetic as the routing signal.** Line-item reconciliation catches dropped/misread rows deterministically — no model opinion involved.
4. **Repair pass instead of hard fail.** One bounded re-ask with the exact validation error recovers most schema drift without unbounded retries.
5. **Provenance everywhere.** SHA-256 of inputs, raw responses, per-rule findings, review state — the audit log can answer "why did the system believe this number?" months later.

## Known limitations

- **Single-node storage.** SQLite is deliberate at this scale but means one worker; multi-instance needs Postgres.
- **Demo hosting is disposable by design** — free-tier filesystem wipes on restart; durable deployments need a disk or managed DB.
- **English/latin-script documents only** were validated; other scripts need prompt and fixture coverage.
- **No auth** on the review UI — fine as an internal tool behind a VPN, not exposed as-is.
- **Next up:** reviewer-side field correction with re-validation, and per-vendor accuracy tracking from the audit log.

