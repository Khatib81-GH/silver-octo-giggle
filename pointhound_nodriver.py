#!/usr/bin/env python3

import asyncio
import json
import shutil
import subprocess
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

import nodriver as uc
from nodriver.core.config import find_chrome_executable
from nodriver.core.util import free_port

OUT = Path('results')
OUT.mkdir(exist_ok=True)
URL = 'https://www.pointhound.com/flights?q=CiIKA0pFRBIbS2luZyBBYmR1bGF6aXogSW50bCBBaXJwb3J0EjAKA0RUVxIpRGV0cm9pdCBNZXRyb3BvbGl0YW4gV2F5bmUgQ291bnR5IEFpcnBvcnQaCjIwMjYtMTItMjUoATAB'

async def run():
    result = {'url_requested': URL}
    port = free_port()
    profile = tempfile.mkdtemp(prefix='ph_nodriver_')
    proc = None
    browser = None
    try:
        flags = [
            '--remote-allow-origins=*',
            '--remote-debugging-host=127.0.0.1',
            f'--remote-debugging-port={port}',
            f'--user-data-dir={profile}',
            '--no-first-run',
            '--no-default-browser-check',
            '--no-service-autorun',
            '--homepage=about:blank',
            '--no-pings',
            '--password-store=basic',
            '--disable-breakpad',
            '--disable-dev-shm-usage',
            '--disable-infobars',
            '--disable-session-crashed-bubble',
            '--disable-search-engine-choice-screen',
            '--no-sandbox',
            '--window-size=1440,1100',
        ]
        proc = subprocess.Popen([find_chrome_executable(), *flags], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1).read()
                break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            raise RuntimeError('Chrome CDP did not open')

        browser = await uc.start(host='127.0.0.1', port=port)
        tab = await browser.get('https://www.pointhound.com/search')
        await tab.sleep(10)
        result['search_page_url'] = tab.url
        result['search_page_text'] = await tab.evaluate('document.body.innerText')
        result['cookies_before'] = await tab.evaluate('document.cookie')

        tab = await browser.get(URL)
        await tab.sleep(30)
        result['final_url'] = tab.url
        result['title'] = await tab.evaluate('document.title')
        result['body'] = await tab.evaluate('document.body.innerText')
        result['html'] = await tab.get_content()
        result['cookies_after'] = await tab.evaluate('document.cookie')
        try:
            await tab.save_screenshot(str(OUT / 'pointhound_nodriver.png'))
        except Exception as exc:
            result['screenshot_error'] = f'{type(exc).__name__}: {exc}'
        result['status'] = 'ok'
    except Exception as exc:
        result['status'] = 'error'
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['traceback'] = traceback.format_exc(limit=15)
    finally:
        try:
            if browser:
                browser.stop()
        except Exception:
            pass
        if proc:
            try:
                proc.terminate(); proc.wait(timeout=5)
            except Exception:
                try: proc.kill()
                except Exception: pass
        shutil.rmtree(profile, ignore_errors=True)
    (OUT / 'pointhound_nodriver.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k:v for k,v in result.items() if k not in ('html','body','search_page_text')}, indent=2, ensure_ascii=False))

uc.loop().run_until_complete(run())
