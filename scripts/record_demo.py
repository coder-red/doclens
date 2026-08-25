from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "scripts" / "shots"
BASE = "http://127.0.0.1:8081"
REC_DB = ROOT / "data" / "demo_recording.db"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def wait_for_server(timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/healthz", timeout=5) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(2)
    raise RuntimeError("recording server did not start")


def shoot(page, name: str) -> tuple[Path, int]:
    out = SHOTS / f"{name}.png"
    page.screenshot(path=str(out))
    print(f"captured {name}")
    return out, 4000


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    REC_DB.unlink(missing_ok=True)

    env = {**os.environ, "DB_PATH": str(REC_DB)}
    server = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--port", "8081"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    frames: list[tuple[Path, int]] = []
    try:
        wait_for_server()

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 860})

            page.goto(BASE, wait_until="networkidle")
            page.wait_for_timeout(800)
            frames.append(shoot(page, "1_dashboard"))

            def upload(fixture: str) -> None:
                page.goto(BASE, wait_until="networkidle")
                page.set_input_files("#file-input", str(ROOT / "fixtures" / fixture))
                page.click("button[type=submit]")
                page.wait_for_url("**/documents/*", timeout=240_000)
                page.wait_for_selector(".badge.approved, .badge.flagged", timeout=60_000)
                page.wait_for_timeout(700)

            upload("layout_a_classic_invoice.pdf")
            frames.append(shoot(page, "2_approved_invoice"))

            upload("layout_c_word_invoice.docx")
            frames.append(shoot(page, "3_word_doc"))

            upload("layout_b_receipt_degraded.jpg")
            frames.append(shoot(page, "4_degraded"))

            upload("layout_a_classic_invoice.pdf")
            frames.append(shoot(page, "5_duplicate_flagged"))

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    images = []
    target_w = 980
    for path, _ in frames:
        img = Image.open(path).convert("RGB")
        ratio = target_w / img.width
        img = img.resize((target_w, int(img.height * ratio)), Image.LANCZOS)
        images.append(img)

    out_gif = ROOT / "docs" / "demo.gif"
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        out_gif,
        save_all=True,
        append_images=images[1:],
        duration=[d for _, d in frames],
        loop=0,
        optimize=True,
    )
    print(f"GIF saved: {out_gif} ({out_gif.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
