#!/usr/bin/env python3

from __future__ import annotations
import asyncio,json,shutil,time,traceback
from pathlib import Path
from urllib.parse import urlencode
from playwright.async_api import async_playwright

OUT=Path('results');OUT.mkdir(exist_ok=True)
params=[
 ('origin','JED'),('originType','airport'),('destination','DTW'),('destinationType','airport'),
 ('departureDate','2026-12-28'),('endDepartureDate','2026-12-28'),('pax','1'),
 ('searchClass','ECON'),('fareClasses','ECON'),('isSkyview','false'),('flexibleDates','0'),
 ('selectedPrograms','FLYING_BLUE'),('selectedPrograms','DELTA'),('programSelectionMode','include'),
 ('maxStops','3'),('maxPoints','300000'),('maxSurcharge','800'),('viewType','List')
]
URL='https://roame.travel/search-v2?'+urlencode(params)

async def main():
 out={'start_url':URL,'events':[],'snapshots':[]}
 try:
  async with async_playwright() as p:
   chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
   b=await p.chromium.launch(headless=False,executable_path=chrome,args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
   c=await b.new_context(locale='en-US',timezone_id='America/Detroit',viewport={'width':1440,'height':1200},user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36')
   page=await c.new_page()
   def keep(u): return 'SearchAwardFares' in u or 'searchawardfares' in u.lower() or 'routes.roame.travel/connect' in u
   page.on('request',lambda req: out['events'].append({'kind':'request','method':req.method,'url':req.url,'headers':dict(req.headers),'post_data':(req.post_data or '')[:100000]}) if keep(req.url) else None)
   async def rec(resp):
    if not keep(resp.url): return
    x={'kind':'response','status':resp.status,'url':resp.url,'headers':dict(resp.headers)}
    try: x['body']=(await resp.body()).hex()[:400000]
    except Exception as e: x['body_error']=f'{type(e).__name__}: {e}'
    out['events'].append(x);(OUT/'roame_direct_test.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
   page.on('response',rec)
   nav=await page.goto(URL,wait_until='domcontentloaded',timeout=120000);out['navigation_status']=nav.status if nav else None
   for sec in range(0,121,5):
    await page.wait_for_timeout(5000)
    body=(await page.locator('body').inner_text())[:60000]
    frames=[{'url':f.url,'name':f.name} for f in page.frames]
    out['snapshots'].append({'elapsed':sec+5,'url':page.url,'body':body,'frames':frames})
    # Try obvious Turnstile checkbox controls if the interaction challenge appears.
    if 'Quick security check' in body or 'Tick the box' in body:
     for f in page.frames:
      try:
       checks=f.locator('input[type=checkbox], [role=checkbox]')
       if await checks.count(): await checks.first.click(force=True,timeout=3000)
      except Exception: pass
    (OUT/'roame_direct_test.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
    if any(s in body.lower() for s in ['flying blue','delta skymiles','no results','no flights found']) and sec>=15:
     break
   out['final_url']=page.url;out['title']=await page.title();out['body_text']=(await page.locator('body').inner_text())[:100000]
   out['html']=(await page.content())[:300000]
   await page.screenshot(path=str(OUT/'roame_direct_test.png'),full_page=True)
   await c.storage_state(path=str(OUT/'roame_state.json'))
   await b.close();out['status']='ok'
 except Exception as e:
  out['status']='error';out['error']=f'{type(e).__name__}: {e}';out['traceback']=traceback.format_exc(limit=12)
 (OUT/'roame_direct_test.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
 print(json.dumps({'status':out.get('status'),'final_url':out.get('final_url'),'event_count':len(out.get('events',[])),'title':out.get('title'),'body':(out.get('body_text') or '')[:5000],'error':out.get('error')},indent=2,ensure_ascii=False))

asyncio.run(main())
