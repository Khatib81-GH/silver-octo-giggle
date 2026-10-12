#!/usr/bin/env python3

import asyncio
import json
import re
import shutil
import traceback
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path('results')
OUT.mkdir(exist_ok=True)
URLS = {
    'airfrance': 'https://wwws.airfrance.us/search/offers?pax=ADT:1&bookingFlow=REWARD&origin=JED&destination=DTW&outwardDate=20261225&cabin=ECONOMY&lang=en-US',
    'klm': 'https://www.klm.com/search/offers?pax=ADT:1&bookingFlow=REWARD&origin=JED&destination=DTW&outwardDate=20261225&cabin=ECONOMY&country=US&language=en',
}

async def inspect_site(browser, name, url):
    out = {'requested_url': url, 'responses': [], 'steps': []}
    ctx = await browser.new_context(
        locale='en-US',
        timezone_id='America/Detroit',
        viewport={'width': 1440, 'height': 1100},
    )
    page = await ctx.new_page()

    async def on_response(resp):
        try:
            u = resp.url
            ctype = (resp.headers.get('content-type') or '').lower()
            relevant = any(x in u.lower() for x in ('offer', 'search', 'flight', 'availability', 'award', 'reward'))
            if relevant and ('json' in ctype or 'text' in ctype):
                body = (await resp.text())[:750000]
                out['responses'].append({
                    'url': u,
                    'status': resp.status,
                    'method': resp.request.method,
                    'content_type': ctype,
                    'body': body,
                })
        except Exception as exc:
            out['responses'].append({'url': getattr(resp, 'url', ''), 'capture_error': f'{type(exc).__name__}: {exc}'})

    page.on('response', on_response)
    try:
        response = await page.goto(url, wait_until='domcontentloaded', timeout=90000)
        out['initial_status'] = response.status if response else None
        await page.wait_for_timeout(3500)
        out['before_consent_url'] = page.url
        out['before_consent_body'] = (await page.locator('body').inner_text())[:30000]
        await page.screenshot(path=str(OUT / f'{name}_before_consent.png'), full_page=True)

        clicked = False
        for pattern in (r'^Accept$', r'Accept all', r'Allow all', r'Agree'):
            button = page.get_by_role('button', name=re.compile(pattern, re.I)).last
            try:
                if await button.count() and await button.is_visible():
                    await button.click(timeout=5000)
                    clicked = True
                    out['steps'].append(f'closed consent dialog with {pattern}')
                    break
            except Exception:
                pass
        if not clicked:
            button = page.get_by_role('button', name=re.compile(r'Reject|Decline|Only necessary', re.I)).last
            try:
                if await button.count() and await button.is_visible():
                    await button.click(timeout=5000)
                    clicked = True
                    out['steps'].append('closed consent dialog with reject/necessary-only')
            except Exception:
                pass
        out['consent_clicked'] = clicked

        try:
            await page.wait_for_load_state('networkidle', timeout=90000)
        except Exception:
            pass
        await page.wait_for_timeout(30000)

        out['final_url'] = page.url
        out['title'] = await page.title()
        out['body'] = (await page.locator('body').inner_text())[:200000]
        out['visible_buttons'] = await page.locator('button:visible').evaluate_all(
            "els => els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),disabled:e.disabled})).filter(x=>x.text||x.aria)"
        )
        out['html'] = (await page.content())[:1500000]
        await page.screenshot(path=str(OUT / f'{name}_after_consent.png'), full_page=True)
        out['status'] = 'ok'
    except Exception as exc:
        out['status'] = 'error'
        out['error'] = f'{type(exc).__name__}: {exc}'
        out['traceback'] = traceback.format_exc(limit=15)
    await ctx.close()
    return out

async def main():
    result = {}
    async with async_playwright() as p:
        chrome = shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
        browser = await p.chromium.launch(
            headless=False,
            executable_path=chrome,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        for name, url in URLS.items():
            result[name] = await inspect_site(browser, name, url)
        await browser.close()
    (OUT / 'flyingblue_probe.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    summary = {
        name: {
            'status': data.get('status'),
            'initial_status': data.get('initial_status'),
            'consent_clicked': data.get('consent_clicked'),
            'final_url': data.get('final_url'),
            'title': data.get('title'),
            'body_start': data.get('body', '')[:2000],
            'response_count': len(data.get('responses', [])),
            'steps': data.get('steps'),
        }
        for name, data in result.items()
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))

asyncio.run(main())
