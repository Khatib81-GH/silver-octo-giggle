#!/usr/bin/env python3

import asyncio
import json
import shutil
import traceback
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('results'); OUT.mkdir(exist_ok=True)
URLS={
 'airfrance':'https://wwws.airfrance.us/search/offers?pax=ADT:1&bookingFlow=REWARD&origin=JED&destination=DTW&outwardDate=20261225&cabin=ECONOMY&lang=en-US',
 'klm':'https://www.klm.com/search/offers?pax=ADT:1&bookingFlow=REWARD&origin=JED&destination=DTW&outwardDate=20261225&cabin=ECONOMY&country=US&language=en',
}

async def inspect_site(browser, name, url):
    out={'requested_url':url,'responses':[],'requests':[]}
    ctx=await browser.new_context(locale='en-US',timezone_id='America/Detroit',viewport={'width':1440,'height':1100})
    page=await ctx.new_page()
    async def on_response(resp):
        try:
            u=resp.url; ct=(resp.headers.get('content-type') or '').lower()
            if ('json' in ct or any(x in u.lower() for x in ('api','offer','search','flight','availability','award','reward'))) and resp.request.method in ('GET','POST'):
                body=''
                if 'json' in ct or 'text' in ct:
                    body=(await resp.text())[:750000]
                out['responses'].append({'url':u,'status':resp.status,'method':resp.request.method,'content_type':ct,'body':body})
        except Exception as exc:
            out['responses'].append({'url':getattr(resp,'url',''),'capture_error':f'{type(exc).__name__}: {exc}'})
    def on_request(req):
        try:
            u=req.url
            if any(x in u.lower() for x in ('api','offer','search','flight','availability','award','reward')):
                out['requests'].append({'url':u,'method':req.method,'post_data':(req.post_data or '')[:250000],'headers':{k:v for k,v in req.headers.items() if k.lower() in ('content-type','accept','x-api-key','authorization','afkl-travel-host','x-correlation-id')}})
        except Exception: pass
    page.on('response',on_response); page.on('request',on_request)
    try:
        r=await page.goto(url,wait_until='domcontentloaded',timeout=90000)
        out['initial_status']=r.status if r else None
        await page.wait_for_timeout(25000)
        out['final_url']=page.url
        out['title']=await page.title()
        out['body']=(await page.locator('body').inner_text())[:150000]
        out['html']=(await page.content())[:1000000]
        await page.screenshot(path=str(OUT/f'{name}.png'),full_page=True)
        out['status']='ok'
    except Exception as exc:
        out['status']='error'; out['error']=f'{type(exc).__name__}: {exc}'; out['traceback']=traceback.format_exc(limit=15)
    await ctx.close()
    return out

async def main():
    result={}
    async with async_playwright() as p:
        chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
        browser=await p.chromium.launch(headless=False,executable_path=chrome,args=['--no-sandbox','--disable-dev-shm-usage'])
        for n,u in URLS.items():
            result[n]=await inspect_site(browser,n,u)
        await browser.close()
    (OUT/'flyingblue_probe.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(json.dumps({n:{k:v for k,v in d.items() if k not in ('html','body','responses','requests')}|{'body_start':d.get('body','')[:1000],'response_count':len(d.get('responses',[])),'request_count':len(d.get('requests',[]))} for n,d in result.items()},indent=2,ensure_ascii=False))

asyncio.run(main())
