"""Quick 3-shot capture of the stream UI to verify visible state."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path("docs/screenshots/2026-05-17/names-verify")
OUT_DIR.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
    page.goto("http://localhost:5180", wait_until="domcontentloaded", timeout=30_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    page.wait_for_timeout(14_000)  # past pre-roll
    for i in range(3):
        path = OUT_DIR / f"names-{i:02d}-{datetime.now().strftime('%H%M%S')}.png"
        page.screenshot(path=str(path), full_page=False)
        print(f"-> {path.name}", flush=True)
        time.sleep(8)
    browser.close()
