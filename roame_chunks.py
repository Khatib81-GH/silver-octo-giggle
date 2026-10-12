#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import re
import shutil
import traceback
from pathlib import Path

from playwright.async_api import async_playwright

OUT=Path('results'); OUT.mkdir(exist_ok=True)
KEYWORDS=[
 'routes.roame.travel','SearchFlight','SearchFlights','FlightsService','Award','FLYING_BLUE','DELTA',
 '/connect/','connectrpc','departureDate','originAirports','destinationAirports','mileagePrograms',
 'search_type','flightSearch','ListFlights','QueryFlights','LiveSearch'
]

async def main():
 out={'status':'starting','matches':[]}
 try:
  async with async_playwright() as p:
   chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
   browser=await p.chromium.launch(headless=False,executable_path=chrome,args=['--no-sandbox','--disable-dev-shm-usage'])
   page=await browser.new_page()
   await page.goto('https://roame.travel/search',wait_until='networkidle',timeout=120000)
   await page.wait_for_timeout(5000)
   scripts=await page.locator('script[src]').evaluate_all("els => els.map(e=>e.src)")
   out['script_count']=len(scripts)
   out['scripts']=scripts
   for i,src in enumerate(scripts):
    try:
     text=await page.evaluate("async u => await (await fetch(u)).text()",src)
     lower=text.lower()
     hits=[k for k in KEYWORDS if k.lower() in lower]
     if not hits: continue
     rec={'src':src,'length':len(text),'hits':hits,'snippets':[]}
     positions=[]
     for k in hits:
      start=0
      while True:
       pos=lower.find(k.lower(),start)
       if pos<0: break
       positions.append((pos,k));start=pos+1
       if len(positions)>300: break
     for pos,k in sorted(positions)[:100]:
      rec['snippets'].append({'keyword':k,'text':text[max(0,pos-600):min(len(text),pos+1600)]})
     out['matches'].append(rec)
    except Exception as exc:
     out.setdefault('fetch_errors',[]).append({'src':src,'error':f'{type(exc).__name__}: {exc}'})
   await browser.close()
  out['status']='ok'
 except Exception as exc:
  out['status']='error';out['error']=f'{type(exc).__name__}: {exc}';out['traceback']=traceback.format_exc(limit=10)
 (OUT/'roame_chunks.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
 print(json.dumps({'status':out.get('status'),'script_count':out.get('script_count'),'matched_chunks':len(out.get('matches',[])),'hits':[(m['src'].split('/')[-1],m['hits']) for m in out.get('matches',[])]},indent=2))

if __name__=='__main__': asyncio.run(main())
