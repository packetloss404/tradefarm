"""Headless screenshot run of the stream broadcast UI.

Captures the rotating broadcast scene every 30s for 5 minutes plus a few
component-targeted shots. Intended to be run alongside a parallel POST /tick
loop so the system looks active on a closed market.

Usage:
    uv run python dev/screenshot_stream.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path("docs/screenshots/2026-05-17")
STREAM_URL = "http://localhost:5180"
TOTAL_SECONDS = 300
SHOT_INTERVAL = 30
VIEWPORT = {"width": 1920, "height": 1080}


def stamp() -> str:
    return datetime.now().strftime("%H%M%S")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    shots: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = ctx.new_page()

        print(f"[{stamp()}] navigating to {STREAM_URL}", flush=True)
        page.goto(STREAM_URL, wait_until="domcontentloaded", timeout=30_000)

        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception as e:
            print(f"[{stamp()}] networkidle wait skipped: {e}", flush=True)

        page.wait_for_timeout(4_000)

        baseline = OUT_DIR / f"stream-00-baseline-{stamp()}.png"
        page.screenshot(path=str(baseline), full_page=False)
        shots.append(str(baseline))
        print(f"[{stamp()}] baseline -> {baseline.name}", flush=True)

        idx = 1
        next_shot = start + SHOT_INTERVAL
        while True:
            now = time.monotonic()
            if now - start >= TOTAL_SECONDS:
                break
            sleep_for = max(0.5, next_shot - now)
            time.sleep(min(sleep_for, 5))
            if time.monotonic() < next_shot:
                continue
            path = OUT_DIR / f"stream-{idx:02d}-{stamp()}.png"
            try:
                page.screenshot(path=str(path), full_page=False)
                shots.append(str(path))
                print(f"[{stamp()}] shot #{idx:02d} -> {path.name}", flush=True)
            except Exception as e:
                print(f"[{stamp()}] shot #{idx:02d} FAILED: {e}", flush=True)
            idx += 1
            next_shot += SHOT_INTERVAL

        try:
            print(f"[{stamp()}] capturing component-targeted shots", flush=True)
            for sel, name in [
                ("[data-broadcast-lower-third]", "lower-third"),
                ("[data-broadcast-ticker]", "ticker"),
                ("[data-broadcast-agent-farm]", "agent-farm"),
                ("[data-broadcast-recap]", "recap"),
                (".lower-third, .ticker, .recap", "css-fallback"),
            ]:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        path = OUT_DIR / f"stream-99-{name}-{stamp()}.png"
                        loc.screenshot(path=str(path))
                        shots.append(str(path))
                        print(f"[{stamp()}] component '{name}' -> {path.name}", flush=True)
                except Exception:
                    pass
        except Exception as e:
            print(f"[{stamp()}] component pass skipped: {e}", flush=True)

        browser.close()

    print("\n--- SCREENSHOT MANIFEST ---", flush=True)
    for s in shots:
        print(s, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
