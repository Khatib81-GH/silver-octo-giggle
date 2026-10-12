#!/usr/bin/env python3

from __future__ import annotations

import asyncio,json,re,shutil,traceback
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('results');OUT.mkdir(exist_ok=True)

async def snap(page,label,out):
 rec={'label':label,'url':page.url}
 rec['body']=(await page.locator('body').inner_text())[:40000]
 rec['inputs']=await page.locator('input').evaluate_all("els=>els.map((e,i)=>({i,type:e.type,name:e.name,id:e.id,placeholder:e.placeholder,value:e.value,aria:e.getAttribute('aria-label'),role:e.getAttribute('role'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),outer:e.outerHTML.slice(0,1800)}))")
 rec['buttons']=await page.locator('button').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,role:e.getAttribute('role'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),disabled:e.disabled,outer:e.outerHTML.slice(0,1200)})).filter(x=>x.text||x.aria||x.title)")
 rec['options']=await page.locator('[role=option]').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),outer:e.outerHTML.slice(0,2000)}))")
 rec['dialogs']=await page.locator('[role=dialog]').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim().slice(0,15000),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),outer:e.outerHTML.slice(0,8000)}))")
 out.append(rec);(OUT/'roame_interact_v2.json').write_text(json.dumps(out,indent=2,ensure_ascii=False));await page.screenshot(path=str(OUT/f'{label}.png'),full_page=True)

async def main():
 out=[]
 try:
  async with async_playwright() as p:
   chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
   b=await p.chromium.launch(headless=False,executable_path=chrome,args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
   c=await b.new_context(locale='en-US',timezone_id='America/Detroit',viewport={'width':1440,'height':1200})
   page=await c.new_page();await page.goto('https://roame.travel/',wait_until='networkidle',timeout=120000);await page.wait_for_timeout(3000)
   await snap(page,'00_home',out)
   origin=page.get_by_role('button',name=re.compile(r'New York \(JFK\)')).filter(visible=True) if False else page.get_by_role('button',name=re.compile(r'New York \(JFK\)')).first
   await origin.click(force=True);await page.wait_for_timeout(1500);await snap(page,'01_open',out)
   # Find visible non-email text input.
   inputs=page.locator('input:visible:not([type=email])')
   if await inputs.count():
    box=inputs.last
    await box.fill('JED');await page.wait_for_timeout(2000);await snap(page,'02_typed',out)
    opts=page.locator('[role=option]:visible')
    if await opts.count():
     await opts.first.click(force=True);await page.wait_for_timeout(1000);await snap(page,'03_selected_first_option',out)
    else:
     cand=page.get_by_text(re.compile(r'Jeddah.*JED|JED.*Jeddah',re.I))
     if await cand.count():
      await cand.last.click(force=True);await page.wait_for_timeout(1000);await snap(page,'03_selected_text',out)
   await b.close()
 except Exception as e:
  out.append({'label':'fatal','error':f'{type(e).__name__}: {e}','traceback':traceback.format_exc(limit=10)})
 (OUT/'roame_interact_v2.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
 print(json.dumps([{k:r.get(k) for k in ('label','url','error')}|{'inputs':r.get('inputs',[])[:15],'options':r.get('options',[])[:30],'dialogs':r.get('dialogs',[])[:5]} for r in out],indent=2,ensure_ascii=False))

asyncio.run(main())
