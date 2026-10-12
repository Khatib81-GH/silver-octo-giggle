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
URL = "https://roame.travel/search"


def interesting(url: str) -> bool:
    low = url.lower()
    return any(x in low for x in ("api", "search", "flight", "award", "query", "graphql", "trpc")) and not any(x in low for x in (".css", ".woff", ".png", ".jpg", ".svg", "google-analytics", "googletagmanager"))


async def main():
    output={"start_url":URL,"events":[]}
    try:
        async with async_playwright() as p:
            chrome=shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
            browser=await p.chromium.launch(headless=False,executable_path=chrome,args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"])
            context=await browser.new_context(locale="en-US",timezone_id="America/Detroit",user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
            page=await context.new_page()
            page.on("request",lambda req: output["events"].append({"kind":"request","method":req.method,"url":req.url,"post_data":(req.post_data or "")[:10000]}) if interesting(req.url) else None)
            async def record(resp):
                if not interesting(resp.url): return
                rec={"kind":"response","status":resp.status,"url":resp.url,"content_type":resp.headers.get("content-type")}
                if any(x in (rec.get("content_type") or "").lower() for x in ("json","text","html")):
                    try: rec["body"]=(await resp.text())[:30000]
                    except Exception as exc: rec["body_error"]=f"{type(exc).__name__}: {exc}"
                output["events"].append(rec)
            page.on("response",record)
            nav=await page.goto(URL,wait_until="networkidle",timeout=120000)
            output["navigation_status"]=nav.status if nav else None
            output["final_url"]=page.url
            output["title"]=await page.title()
            await page.wait_for_timeout(5000)
            output["body_text"]=(await page.locator("body").inner_text())[:50000]
            output["inputs"]=await page.locator("input").evaluate_all("els => els.map(e => ({type:e.type,name:e.name,id:e.id,placeholder:e.placeholder,value:e.value,aria:e.getAttribute('aria-label'),role:e.getAttribute('role'),autocomplete:e.autocomplete,outer:e.outerHTML.slice(0,1000)}))")
            output["buttons"]=await page.locator("button").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),type:e.type,disabled:e.disabled,outer:e.outerHTML.slice(0,1000)}))")
            output["links"]=await page.locator("a").evaluate_all("els => els.map(e => ({text:(e.innerText||'').trim(),href:e.href,aria:e.getAttribute('aria-label')})).filter(x=>x.text||x.aria).slice(0,200)")
            output["html"]=(await page.content())[:200000]
            await page.screenshot(path=str(OUT/"roame_probe.png"),full_page=True)
            output["status"]="ok"
            await browser.close()
    except Exception as exc:
        output["status"]="error";output["error"]=f"{type(exc).__name__}: {exc}";output["traceback"]=traceback.format_exc(limit=10)
    (OUT/"roame_probe.json").write_text(json.dumps(output,indent=2,ensure_ascii=False))
    print(json.dumps({k:output.get(k) for k in ("status","final_url","title","navigation_status","error")}|{"inputs":output.get("inputs",[])[:20],"buttons":output.get("buttons",[])[:30]},indent=2,ensure_ascii=False))

if __name__=="__main__": asyncio.run(main())
