#!/usr/bin/env python3

import asyncio
import json
import shutil
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path('results')
OUT.mkdir(exist_ok=True)

async def main():
    result = {}
    async with async_playwright() as p:
        chrome = shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
        browser = await p.chromium.launch(headless=False, executable_path=chrome, args=['--no-sandbox','--disable-dev-shm-usage'])
        page = await browser.new_page(viewport={'width': 1440, 'height': 1200})
        response = await page.goto('https://www.awardtool.com/flight/', wait_until='networkidle', timeout=120000)
        result['status'] = response.status if response else None
        result['url'] = page.url
        result['title'] = await page.title()
        result['body'] = (await page.locator('body').inner_text())[:50000]
        result['inputs'] = await page.locator('input').evaluate_all("els => els.map((e,i)=>({i,type:e.type,placeholder:e.placeholder,value:e.value,aria:e.getAttribute('aria-label'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))")
        result['buttons'] = await page.locator('button').evaluate_all("els => els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)})).filter(x=>x.text||x.aria)")
        await page.screenshot(path=str(OUT/'awardtool.png'), full_page=True)
        await browser.close()
    (OUT/'awardtool.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))

asyncio.run(main())
