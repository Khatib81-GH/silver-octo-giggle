#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import re
import shutil
import traceback
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

OUT=Path('results/roame_full_chunks'); OUT.mkdir(parents=True,exist_ok=True)
TERMS=['SearchAwardFares','searchAwardFares','FlightsService','fareSearchIdentity','parseFareSearchSubmission','SearchMode','buildMutableFilters','routes.roame.travel','departureDateRange','mileagePrograms','selectedPrograms','searchRequest']

async def main():
 summary={'status':'starting','saved':[]}
 try:
  async with async_playwright() as p:
   chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
   browser=await p.chromium.launch(headless=False,executable_path=chrome,args=['--no-sandbox','--disable-dev-shm-usage'])
   page=await browser.new_page()
   await page.goto('https://roame.travel/search',wait_until='networkidle',timeout=120000)
   await page.wait_for_timeout(4000)
   scripts=await page.locator('script[src]').evaluate_all("els => [...new Set(els.map(e=>e.src))]")
   summary['script_count']=len(scripts)
   for src in scripts:
    try:
     text=await page.evaluate("async u => await (await fetch(u)).text()",src)
     hits=[t for t in TERMS if t.lower() in text.lower()]
     if not hits: continue
     name=Path(urlparse(src).path).name or f'chunk_{len(summary["saved"])}.js'
     path=OUT/name
     path.write_text(text)
     summary['saved'].append({'src':src,'file':str(path),'length':len(text),'hits':hits})
    except Exception as exc:
     summary.setdefault('errors',[]).append({'src':src,'error':f'{type(exc).__name__}: {exc}'})
   await browser.close()
  summary['status']='ok'
 except Exception as exc:
  summary['status']='error';summary['error']=f'{type(exc).__name__}: {exc}';summary['traceback']=traceback.format_exc(limit=10)
 (OUT.parent/'roame_full_chunks_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
 print(json.dumps({'status':summary.get('status'),'script_count':summary.get('script_count'),'saved':[(x['file'],x['length'],x['hits']) for x in summary.get('saved',[])]},indent=2))

if __name__=='__main__': asyncio.run(main())
