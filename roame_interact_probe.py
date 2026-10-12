#!/usr/bin/env python3

from __future__ import annotations

import asyncio,json,re,shutil,traceback
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('results');OUT.mkdir(exist_ok=True)

async def snap(page,label,out):
    rec={"label":label,"url":page.url}
    try: rec['body']=(await page.locator('body').inner_text())[:30000]
    except Exception as e: rec['body_error']=str(e)
    try: rec['inputs']=await page.locator('input').evaluate_all("els=>els.map((e,i)=>({i,type:e.type,name:e.name,id:e.id,placeholder:e.placeholder,value:e.value,aria:e.getAttribute('aria-label'),role:e.getAttribute('role'),outer:e.outerHTML.slice(0,1500)}))")
    except Exception as e: rec['inputs_error']=str(e)
    try: rec['buttons']=await page.locator('button').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,role:e.getAttribute('role'),disabled:e.disabled,outer:e.outerHTML.slice(0,1200)})).filter(x=>x.text||x.aria||x.title)")
    except Exception as e: rec['buttons_error']=str(e)
    try: rec['options']=await page.locator('[role=option]').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),outer:e.outerHTML.slice(0,2000)}))")
    except Exception as e: rec['options_error']=str(e)
    try: rec['dialogs']=await page.locator('[role=dialog]').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim().slice(0,10000),outer:e.outerHTML.slice(0,5000)}))")
    except Exception as e: rec['dialogs_error']=str(e)
    out.append(rec)
    await page.screenshot(path=str(OUT/f'{label}.png'),full_page=True)
    (OUT/'roame_interact_probe.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))

async def main():
    out=[]
    try:
      async with async_playwright() as p:
       chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
       b=await p.chromium.launch(headless=False,executable_path=chrome,args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
       c=await b.new_context(locale='en-US',timezone_id='America/Detroit')
       page=await c.new_page();await page.goto('https://roame.travel/',wait_until='networkidle',timeout=120000);await page.wait_for_timeout(3000)
       await snap(page,'00_home',out)
       # First origin control on the desktop search bar.
       origin=page.get_by_role('button',name=re.compile(r'New York \(JFK\)')).first
       await origin.click();await page.wait_for_timeout(1000);await snap(page,'01_origin_open',out)
       boxes=page.locator('input')
       count=await boxes.count()
       search_box=None
       for i in range(count):
        el=boxes.nth(i)
        ph=(await el.get_attribute('placeholder') or '').lower();aria=(await el.get_attribute('aria-label') or '').lower()
        if any(x in ph+aria for x in ('airport','city','search','from','where')):
         search_box=el;break
       if search_box is None and count: search_box=boxes.nth(count-1)
       if search_box is not None:
        await search_box.fill('JED');await page.wait_for_timeout(1800);await snap(page,'02_origin_typed',out)
        candidates=page.get_by_text(re.compile(r'Jeddah.*JED|JED.*Jeddah',re.I))
        if await candidates.count():
         await candidates.first.click();await page.wait_for_timeout(800);await snap(page,'03_origin_selected',out)
       await b.close()
    except Exception as e:
      out.append({'label':'fatal','error':f'{type(e).__name__}: {e}','traceback':traceback.format_exc(limit=10)})
    (OUT/'roame_interact_probe.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
    print(json.dumps([{k:r.get(k) for k in ('label','url','error')}|{'inputs':r.get('inputs',[])[:10],'options':r.get('options',[])[:20],'dialogs':r.get('dialogs',[])[:5]} for r in out],indent=2,ensure_ascii=False))

asyncio.run(main())
