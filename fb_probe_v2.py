#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import shutil
import traceback
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

OUT = Path("results")
OUT.mkdir(exist_ok=True)

DATE = "20261228"
AF_URLS = [
    f"https://wwws.airfrance.us/search/offers?pax=1:0:0:0:0:0:0:0&cabinClass=ECONOMY&activeConnection=0&connections={quote(f'JED:C:{DATE}>DTW')}&bookingFlow=REWARD",
    f"https://wwws.airfrance.us/search/offers?pax=1:0:0:0:0:0:0:0&cabinClass=ECONOMY&activeConnection=0&connections={quote(f'JED:A:{DATE}>DTW:A')}&bookingFlow=REWARD",
]
KLM_URLS = [
    f"https://www.klm.com/search/offers?pax=1:0:0:0:0:0:0:0&cabinClass=ECONOMY&activeConnection=0&connections={quote(f'JED:C:{DATE}>DTW')}&bookingFlow=REWARD",
    f"https://www.klm.com/search/offers?pax=ADT:1&origin=JED&destination=DTW&outwardDate={DATE}&cabin=ECONOMY&bookingFlow=REWARD",
]
URLS = [("af1", AF_URLS[0]), ("af2", AF_URLS[1]), ("kl1", KLM_URLS[0]), ("kl2", KLM_URLS[1])]


def interesting(url: str) -> bool:
    low = url.lower()
    return any(x in low for x in ("gql", "graphql", "offer", "flight", "reward", "award", "miles", "booking", "search")) and not any(x in low for x in (".css", ".woff", ".png", ".jpg", ".svg"))


async def run_one(browser, label: str, url: str) -> dict:
    context = await browser.new_context(
        locale="en-US",
        timezone_id="America/Detroit",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    )
    page = await context.new_page()
    events = []
    page.on("request", lambda req: events.append({"kind":"request","method":req.method,"url":req.url,"post_data":(req.post_data or "")[:20000]}) if interesting(req.url) else None)
    async def resp_handler(resp):
        if not interesting(resp.url):
            return
        rec={"kind":"response","status":resp.status,"url":resp.url,"content_type":resp.headers.get("content-type")}
        if any(t in (rec.get("content_type") or "").lower() for t in ("json","text","html")):
            try: rec["body"]=(await resp.text())[:30000]
            except Exception as exc: rec["body_error"]=f"{type(exc).__name__}: {exc}"
        events.append(rec)
    page.on("response", resp_handler)
    out={"label":label,"start_url":url,"events":events}
    try:
        nav=await page.goto(url,wait_until="domcontentloaded",timeout=120000)
        out["navigation_status"]=nav.status if nav else None
        await page.wait_for_timeout(20000)
        out["final_url"]=page.url
        out["title"]=await page.title()
        out["body_text"]=(await page.locator("body").inner_text())[:30000]
        out["status"]="ok"
        await page.screenshot(path=str(OUT/f"{label}.png"),full_page=True)
    except Exception as exc:
        out["status"]="error"; out["error"]=f"{type(exc).__name__}: {exc}"; out["traceback"]=traceback.format_exc(limit=8)
    await context.close()
    (OUT/f"{label}.json").write_text(json.dumps(out,indent=2,ensure_ascii=False))
    return out


async def main():
    results=[]
    async with async_playwright() as p:
        chrome=shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
        browser=await p.chromium.launch(headless=False,executable_path=chrome,args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"])
        for label,url in URLS:
            results.append(await run_one(browser,label,url))
        await browser.close()
    summary=[{"label":r["label"],"status":r.get("status"),"final_url":r.get("final_url"),"title":r.get("title"),"body":(r.get("body_text") or "")[:1000]} for r in results]
    (OUT/"fb_probe_v2_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False))
    print(json.dumps(summary,indent=2))

if __name__=="__main__": asyncio.run(main())
