#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import shutil
import traceback
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path('results')
OUT.mkdir(exist_ok=True)
Q = 'CgUKA0pFRBIFCgNEVFcaCjIwMjYtMTItMjgoATAB'
URL = f'https://www.pointhound.com/flights?q={Q}'


def interesting(url: str) -> bool:
    low = url.lower()
    return any(x in low for x in ('/flights', '/api/offers', 'searchid', 'ofs_', 'filter-options'))


async def main():
    out = {'start_url': URL, 'events': []}
    try:
        async with async_playwright() as p:
            chrome = shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
            browser = await p.chromium.launch(headless=False, executable_path=chrome, args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
            context = await browser.new_context(locale='en-US', timezone_id='America/Detroit', viewport={'width':1440,'height':1200})
            page = await context.new_page()
            page.on('request', lambda req: out['events'].append({'kind':'request','method':req.method,'url':req.url,'post_data':(req.post_data or '')[:50000]}) if interesting(req.url) else None)
            async def rec(resp):
                if not interesting(resp.url):
                    return
                item = {'kind':'response','status':resp.status,'url':resp.url,'content_type':resp.headers.get('content-type')}
                try:
                    item['body'] = (await resp.text())[:100000]
                except Exception as exc:
                    item['body_error'] = f'{type(exc).__name__}: {exc}'
                out['events'].append(item)
            page.on('response', rec)
            response = await page.goto(URL, wait_until='domcontentloaded', timeout=120000)
            out['navigation_status'] = response.status if response else None
            for elapsed in (5, 10, 20, 35, 50):
                await page.wait_for_timeout(5000 if elapsed == 5 else elapsed - (5 if elapsed == 10 else {20:10,35:20,50:35}[elapsed]))
                out.setdefault('snapshots', []).append({'elapsed':elapsed,'url':page.url,'body':(await page.locator('body').inner_text())[:80000]})
                (OUT/'pointhound_direct_probe.json').write_text(json.dumps(out, indent=2, ensure_ascii=False))
            out['final_url'] = page.url
            out['title'] = await page.title()
            out['body'] = (await page.locator('body').inner_text())[:100000]
            out['html'] = (await page.content())[:400000]
            await page.screenshot(path=str(OUT/'pointhound_direct_probe.png'), full_page=True)
            out['status'] = 'ok'
            await browser.close()
    except Exception as exc:
        out['status'] = 'error'
        out['error'] = f'{type(exc).__name__}: {exc}'
        out['traceback'] = traceback.format_exc(limit=12)
    (OUT/'pointhound_direct_probe.json').write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({k:out.get(k) for k in ('status','navigation_status','final_url','title','error')} | {'event_count':len(out.get('events',[])), 'body':(out.get('body') or '')[:5000]}, indent=2, ensure_ascii=False))

asyncio.run(main())
