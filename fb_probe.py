#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import shutil
import traceback
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("results")
OUT.mkdir(exist_ok=True)
URL = (
    "https://www.airfrance.us/search/offers?"
    "pax=1:0:0:0:0:0:0:0&cabinClass=ECONOMY&activeConnection=0"
    "&connections=JED%3EDTW:20261228&bookingFlow=REWARD"
)


async def main() -> None:
    events = []
    result = {"start_url": URL, "events": events}
    try:
        async with async_playwright() as p:
            chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
            result["chrome"] = chrome
            browser = await p.chromium.launch(
                headless=False,
                executable_path=chrome,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                locale="en-US",
                timezone_id="America/Detroit",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            def keep_url(url: str) -> bool:
                low = url.lower()
                return any(k in low for k in ("offer", "flight", "award", "reward", "booking", "miles", "search", "/api/", "graphql")) and not any(x in low for x in (".png", ".jpg", ".svg", ".woff", ".css"))

            page.on("request", lambda req: events.append({
                "kind": "request", "method": req.method, "url": req.url,
                "post_data": (req.post_data or "")[:5000],
            }) if keep_url(req.url) else None)

            async def record_response(resp):
                if not keep_url(resp.url):
                    return
                rec = {"kind": "response", "status": resp.status, "url": resp.url, "content_type": resp.headers.get("content-type")}
                ctype = (rec.get("content_type") or "").lower()
                if "json" in ctype or "text" in ctype:
                    try:
                        rec["body"] = (await resp.text())[:10000]
                    except Exception as exc:
                        rec["body_error"] = f"{type(exc).__name__}: {exc}"
                events.append(rec)

            page.on("response", record_response)
            response = await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
            result["navigation_status"] = response.status if response else None
            await page.wait_for_timeout(30000)
            result["final_url"] = page.url
            result["title"] = await page.title()
            try:
                result["body_text"] = (await page.locator("body").inner_text())[:30000]
            except Exception:
                result["body_text"] = ""
            result["html"] = (await page.content())[:100000]
            await page.screenshot(path=str(OUT / "flying_blue_probe.png"), full_page=True)
            await browser.close()
            result["status"] = "ok"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc(limit=10)

    (OUT / "flying_blue_probe.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k: result.get(k) for k in ("status", "final_url", "title", "navigation_status", "error")}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
