#!/usr/bin/env python3

import asyncio
import json
import shutil
import traceback
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path('results')
OUT.mkdir(exist_ok=True)

async def main():
    result = {}
    browser = None
    try:
        async with async_playwright() as p:
            chrome = shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
            browser = await p.chromium.launch(headless=False, executable_path=chrome, args=['--no-sandbox','--disable-dev-shm-usage'])
            context = await browser.new_context(locale='en-US', timezone_id='America/Detroit', viewport={'width': 1440, 'height': 1200})
            page = await context.new_page()
            response = await page.goto('https://www.pointhound.com/search', wait_until='domcontentloaded', timeout=60000)
            result['status_code'] = response.status if response else None
            await page.wait_for_timeout(10000)
            result['url'] = page.url
            result['title'] = await page.title()
            result['body'] = (await page.locator('body').inner_text())[:60000]
            result['inputs'] = await page.locator('input').evaluate_all("els => els.map((e,i)=>({i,type:e.type,name:e.name,id:e.id,placeholder:e.placeholder,value:e.value,aria:e.getAttribute('aria-label'),role:e.getAttribute('role'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),outer:e.outerHTML.slice(0,1800)}))")
            result['buttons'] = await page.locator('button').evaluate_all("els => els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,role:e.getAttribute('role'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),disabled:e.disabled,outer:e.outerHTML.slice(0,1400)})).filter(x=>x.text||x.aria||x.title)")
            result['comboboxes'] = await page.locator('[role=combobox]').evaluate_all("els => els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),outer:e.outerHTML.slice(0,2000)}))")
            result['html'] = (await page.content())[:300000]
            await page.screenshot(path=str(OUT/'pointhound_probe.png'), full_page=True)
            result['status'] = 'ok'
            await browser.close()
    except Exception as exc:
        result['status'] = 'error'
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['traceback'] = traceback.format_exc(limit=10)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
    (OUT/'pointhound_probe.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))

asyncio.run(main())
