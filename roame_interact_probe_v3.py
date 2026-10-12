#!/usr/bin/env python3

from __future__ import annotations
import asyncio,json,re,shutil,traceback
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('results');OUT.mkdir(exist_ok=True)

async def snap(page,label,out):
 rec={'label':label,'url':page.url}
 rec['body']=(await page.locator('body').inner_text())[:50000]
 rec['inputs']=await page.locator('input').evaluate_all("els=>els.map((e,i)=>({i,type:e.type,placeholder:e.placeholder,value:e.value,aria:e.getAttribute('aria-label'),role:e.getAttribute('role'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),outer:e.outerHTML.slice(0,1800)}))")
 rec['buttons']=await page.locator('button').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,role:e.getAttribute('role'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),disabled:e.disabled,outer:e.outerHTML.slice(0,1500)})).filter(x=>x.text||x.aria||x.title)")
 rec['options']=await page.locator('[role=option]').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),outer:e.outerHTML.slice(0,2500)}))")
 rec['dialogs']=await page.locator('[role=dialog]').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim().slice(0,20000),visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),outer:e.outerHTML.slice(0,12000)}))")
 out.append(rec);(OUT/'roame_interact_v3.json').write_text(json.dumps(out,indent=2,ensure_ascii=False));await page.screenshot(path=str(OUT/f'{label}.png'),full_page=True)

async def choose_airport(page,current_text,remove_code,input_aria,query,select_regex,out,prefix):
 btn=page.get_by_role('button',name=re.compile(re.escape(current_text))).first
 await btn.click(force=True);await page.wait_for_timeout(700)
 rem=page.get_by_role('button',name=f'Remove {remove_code}')
 if await rem.count(): await rem.click(force=True)
 await page.wait_for_timeout(300)
 box=page.get_by_role('combobox',name=input_aria)
 await box.fill(query);await page.wait_for_timeout(2000);await snap(page,f'{prefix}_typed',out)
 # Click matching text, preferring a role option/list item if present.
 match=page.get_by_text(re.compile(select_regex,re.I))
 if not await match.count(): raise RuntimeError(f'No airport match for {query}')
 await match.last.click(force=True);await page.wait_for_timeout(500)
 done=page.get_by_text('Done',exact=True)
 if await done.count(): await done.last.click(force=True)
 await page.wait_for_timeout(800);await snap(page,f'{prefix}_selected',out)

async def main():
 out=[]
 try:
  async with async_playwright() as p:
   chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
   b=await p.chromium.launch(headless=False,executable_path=chrome,args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
   c=await b.new_context(locale='en-US',timezone_id='America/Detroit',viewport={'width':1440,'height':1200})
   page=await c.new_page();await page.goto('https://roame.travel/',wait_until='networkidle',timeout=120000);await page.wait_for_timeout(2500)
   await choose_airport(page,'New York (JFK)','JFK','From','JED',r'Jeddah.*\(JED\)|JED.*Jeddah',out,'01_origin')
   await choose_airport(page,'San Francisco (SFO)','SFO','To','DTW',r'Detroit.*\(DTW\)|DTW.*Detroit',out,'02_dest')
   date_btn=page.locator('button.date-picker:visible').first
   await date_btn.click(force=True);await page.wait_for_timeout(1000);await snap(page,'03_date_open',out)
   await b.close()
 except Exception as e:
  out.append({'label':'fatal','error':f'{type(e).__name__}: {e}','traceback':traceback.format_exc(limit=12)})
 (OUT/'roame_interact_v3.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
 print(json.dumps([{k:r.get(k) for k in ('label','url','error')}|{'options':r.get('options',[])[:20],'dialogs':r.get('dialogs',[])[:5],'buttons':r.get('buttons',[])[:80]} for r in out],indent=2,ensure_ascii=False))

asyncio.run(main())
