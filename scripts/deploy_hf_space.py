from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "mhmdxch/doclens"


def read_key() -> str:
    text = (ROOT / ".env").read_text(encoding="utf-8")
    match = re.search(r"^GEMINI_API_KEY=(.+)$", text, re.MULTILINE)
    if not match:
        sys.exit("GEMINI_API_KEY not found in .env")
    return match.group(1).strip()


SPACE_README = """---
title: DocLens
emoji: "\U0001F9FE"
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: true
---

# DocLens

Invoice/receipt extraction with arithmetic guardrails: vision-LLM extraction,
deterministic validation rules, clean-vs-flagged routing, Excel/webhook export,
full audit trail. Code: https://github.com/coder-red/doclens
"""

SPACE_DOCKERFILE = """FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY static ./static
COPY fixtures ./fixtures

RUN mkdir -p /data

ENV DB_PATH=/data/data.db
EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
"""


def main() -> None:
    api = HfApi()
    api.create_repo(
        repo_id=REPO_ID,
        repo_type="space",
        space_sdk="docker",
        private=False,
        exist_ok=True,
    )
    print(f"space ensured: {REPO_ID}")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "README.md").write_text(SPACE_README, encoding="utf-8")
        (tmpdir / "Dockerfile").write_text(SPACE_DOCKERFILE, encoding="utf-8")
        api.upload_folder(
            repo_id=REPO_ID,
            repo_type="space",
            folder_path=str(tmpdir),
            commit_message="Space config",
        )

    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="space",
        folder_path=str(ROOT / "app"),
        path_in_repo="app",
        commit_message="application code",
    )
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="space",
        folder_path=str(ROOT / "templates"),
        path_in_repo="templates",
        commit_message="templates",
    )
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="space",
        folder_path=str(ROOT / "static"),
        path_in_repo="static",
        commit_message="static assets",
    )
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="space",
        folder_path=str(ROOT / "fixtures"),
        path_in_repo="fixtures",
        commit_message="demo fixtures",
    )
    api.upload_file(
        repo_id=REPO_ID,
        repo_type="space",
        path_or_fileobj=str(ROOT / "requirements.txt"),
        path_in_repo="requirements.txt",
        commit_message="requirements",
    )

    api.add_space_secret(repo_id=REPO_ID, key="GEMINI_API_KEY", value=read_key())
    print("secret set: GEMINI_API_KEY")

    runtime = api.get_space_runtime(repo_id=REPO_ID)
    print(f"stage: {runtime.stage}")


if __name__ == "__main__":
    main()
