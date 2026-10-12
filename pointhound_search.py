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
    result = {"api_responses": [], "steps": []}
    browser = None
    try:
        async with async_playwright() as p:
            chrome = shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
            browser = await p.chromium.launch(headless=False, executable_path=chrome, args=['--no-sandbox','--disable-dev-shm-usage'])
            context = await browser.new_context(locale='en-US', timezone_id='America/Detroit', viewport={'width': 1440, 'height': 1100})
            page = await context.new_page()

            async def on_response(resp):
                try:
                    url = resp.url
                    ctype = (resp.headers.get('content-type') or '').lower()
                    if ('api' in url.lower() or 'graphql' in url.lower() or 'search' in url.lower() or 'flight' in url.lower()) and ('json' in ctype or 'text' in ctype):
                        body = await resp.text()
                        result['api_responses'].append({
                            'url': url,
                            'status': resp.status,
                            'content_type': ctype,
                            'body': body[:500000],
                        })
                except Exception as exc:
                    result['api_responses'].append({'url': getattr(resp,'url',''), 'capture_error': f'{type(exc).__name__}: {exc}'})

            page.on('response', on_response)
            response = await page.goto('https://www.pointhound.com/search', wait_until='domcontentloaded', timeout=60000)
            result['status_code'] = response.status if response else None
            await page.wait_for_timeout(5000)

            origin = page.get_by_placeholder('Origin airport or city')
            await origin.fill('JED')
            await page.wait_for_timeout(1200)
            origin_options = await page.locator('[role=option]').all_inner_texts()
            result['origin_options'] = origin_options
            option = page.locator('[role=option]').filter(has_text='JED').first
            if await option.count() == 0:
                option = page.locator('[role=option]').filter(has_text='Jeddah').first
            await option.click()
            result['steps'].append('origin selected')

            dest = page.get_by_placeholder('Destination airport')
            await dest.fill('DTW')
            await page.wait_for_timeout(1200)
            dest_options = await page.locator('[role=option]').all_inner_texts()
            result['destination_options'] = dest_options
            option = page.locator('[role=option]').filter(has_text='DTW').first
            if await option.count() == 0:
                option = page.locator('[role=option]').filter(has_text='Detroit').first
            await option.click()
            result['steps'].append('destination selected')

            date_input = page.get_by_placeholder('Date or date range')
            await date_input.click()
            await page.wait_for_timeout(500)
            result['calendar_text_initial'] = (await page.locator('body').inner_text())[:30000]
            result['calendar_buttons_initial'] = await page.locator('button:visible').evaluate_all("els => els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,disabled:e.disabled,outer:e.outerHTML.slice(0,800)})).filter(x=>x.text||x.aria||x.title)")

            # Move from October to December 2026 when a next-month control is present.
            for _ in range(2):
                nxt = page.locator('button[aria-label*="next" i], button[title*="next" i]').first
                if await nxt.count() and await nxt.is_visible():
                    await nxt.click()
                    await page.wait_for_timeout(350)
                else:
                    break

            # Prefer an explicit accessible label for Dec 25, then fall back to a visible day button.
            day = page.locator('button[aria-label*="December 25" i]').first
            if await day.count() == 0:
                day = page.locator('button:visible').filter(has_text='25').first
            await day.click()
            await page.wait_for_timeout(500)
            result['date_value'] = await date_input.input_value()
            result['steps'].append('date selected')

            fetch = page.get_by_role('button', name='Fetch deals').first
            result['fetch_disabled_before'] = await fetch.is_disabled()
            await fetch.click()
            result['steps'].append('submitted')

            # Let the search stream in. Record the final URL and visible result text.
            try:
                await page.wait_for_load_state('networkidle', timeout=90000)
            except Exception:
                pass
            await page.wait_for_timeout(15000)
            result['url'] = page.url
            result['title'] = await page.title()
            result['body'] = (await page.locator('body').inner_text())[:120000]
            result['inputs_final'] = await page.locator('input').evaluate_all("els => els.map((e,i)=>({i,type:e.type,placeholder:e.placeholder,value:e.value,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))")
            result['buttons_final'] = await page.locator('button:visible').evaluate_all("els => els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),disabled:e.disabled})).filter(x=>x.text||x.aria)")
            await page.screenshot(path=str(OUT/'pointhound_search.png'), full_page=True)
            result['html'] = (await page.content())[:500000]
            result['status'] = 'ok'
            await browser.close()
    except Exception as exc:
        result['status'] = 'error'
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['traceback'] = traceback.format_exc(limit=15)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
    (OUT/'pointhound_search.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k:v for k,v in result.items() if k not in ('html','body','api_responses')}, indent=2, ensure_ascii=False))

asyncio.run(main())
