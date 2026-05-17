"""Capture 5 high-resolution screenshots of the sentinel-memory analyst console.

Intended to be run inside a Microsoft Playwright Python container that has
network access to the host on http://host.docker.internal:8000.

    docker run --rm \
      -v "$PWD/scripts/take_ui_screenshots.py:/take.py" \
      -v "$HOME/Downloads/sentinel-memory-private/screenshots:/out" \
      -e BASE_URL=http://host.docker.internal:8000 \
      mcr.microsoft.com/playwright/python:v1.49.0-noble \
      python /take.py

Each shot is 1600x1000 (16:10) so Canva can crop without losing detail.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = os.environ.get("BASE_URL", "http://host.docker.internal:8000")
OUT = Path(os.environ.get("OUT_DIR", "/out"))
OUT.mkdir(parents=True, exist_ok=True)

# Override the chat sample question via CHAT_PROMPT if you want a different demo.
CHAT_PROMPT = os.environ.get(
    "CHAT_PROMPT",
    "Seeing 47 failed logins from a single IP. What now?",
)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,  # retina-quality output
            color_scheme="dark",
        )
        page = await ctx.new_page()

        print(f"[shot] opening {BASE}/ui/")
        await page.goto(f"{BASE}/ui/", wait_until="networkidle")
        await page.wait_for_selector("#analyst-id")
        # Ensure cristian is the active identity
        await page.fill("#analyst-id", "cristian")
        await page.click("#refresh-role")
        await page.wait_for_timeout(800)

        # 1. CHAT — single, concise exchange so the screenshot stays clean
        print("[shot] tab: chat")
        await page.click('button.tab[data-tab="chat"]')
        await page.click("#chat-new")  # ensure a fresh, empty thread
        await page.wait_for_timeout(300)
        await page.fill("#chat-input", CHAT_PROMPT)
        await page.click('#chat-form button[type="submit"]')
        await page.wait_for_selector(".turn.assistant .bubble", timeout=40000)
        await page.wait_for_selector(".turn.assistant .citation", timeout=10000)
        # Scroll the thread to top so the user turn + start of the reply are visible
        await page.evaluate("document.querySelector('#chat-thread').scrollTop = 0")
        # Hide any lingering toast so the shot is clean
        await page.evaluate("document.querySelector('#toast').classList.add('hidden')")
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(OUT / "01-chat.png"), full_page=False)

        # 2. SEARCH — run a query in each column
        print("[shot] tab: search")
        await page.click('button.tab[data-tab="search"]')
        await page.fill("#search-pb-q", "SSH brute force from rotating IPs")
        await page.click('#search-pb-form button.primary')
        await page.fill("#search-al-q", "data exfiltration to suspicious domain")
        # The real <input> is display:none; click the wrapping .pill label.
        await page.locator(
            '#search-al-form label.pill', has=page.locator('input[value="critical"]')
        ).click()
        await page.locator(
            '#search-al-form label.pill', has=page.locator('input[value="high"]')
        ).click()
        await page.click('#search-al-form button.primary')
        await page.wait_for_selector("#search-pb-results .row-item")
        await page.wait_for_selector("#search-al-results .row-item")
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "02-search.png"), full_page=False)

        # 3. ALERTS — list + timeline
        print("[shot] tab: alerts")
        await page.click('button.tab[data-tab="alerts"]')
        await page.wait_for_selector("#alerts-list .row-item")
        # Click the first alert that has SCD2 history (the one we PATCH'd)
        # We just pick the first item; the timeline appears on the right.
        await page.locator("#alerts-list .row-item").first.click()
        await page.wait_for_selector("#alert-detail-body .timeline-item, #alert-detail-body p.muted")
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "03-alerts-timeline.png"), full_page=False)

        # 4. AUDIT LOG
        print("[shot] tab: audit")
        await page.click('button.tab[data-tab="audit"]')
        await page.wait_for_selector(".audit-row.head")
        # Force a refresh to make sure rows render
        await page.click("#audit-refresh")
        await page.wait_for_timeout(1200)
        await page.screenshot(path=str(OUT / "04-audit.png"), full_page=False)

        # 5. PREFERENCES (LTM)
        print("[shot] tab: prefs")
        await page.click('button.tab[data-tab="prefs"]')
        await page.wait_for_selector("#prefs-list .row-item")
        await page.wait_for_timeout(600)
        await page.screenshot(path=str(OUT / "05-preferences.png"), full_page=False)

        await ctx.close()
        await browser.close()

    files = sorted(OUT.glob("*.png"))
    print(f"\n[done] wrote {len(files)} screenshots to {OUT}")
    for f in files:
        print(f"  - {f.name}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise
