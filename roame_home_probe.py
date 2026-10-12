#!/usr/bin/env python3

import asyncio,json,shutil,traceback
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('results');OUT.mkdir(exist_ok=True)

async def main():
 out={}
 try:
  async with async_playwright() as p:
   chrome=shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')
   b=await p.chromium.launch(headless=False,executable_path=chrome,args=['--no-sandbox','--disable-dev-shm-usage'])
   c=await b.new_context(locale='en-US',timezone_id='America/Detroit')
   page=await c.new_page(); await page.goto('https://roame.travel/',wait_until='networkidle',timeout=120000);await page.wait_for_timeout(6000)
   out['url']=page.url;out['title']=await page.title();out['body']=(await page.locator('body').inner_text())[:40000]
   out['inputs']=await page.locator('input').evaluate_all("els=>els.map((e,i)=>({i,type:e.type,name:e.name,id:e.id,placeholder:e.placeholder,value:e.value,aria:e.getAttribute('aria-label'),role:e.getAttribute('role'),outer:e.outerHTML.slice(0,1500)}))")
   out['buttons']=await page.locator('button').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),title:e.title,role:e.getAttribute('role'),disabled:e.disabled,outer:e.outerHTML.slice(0,1200)})).filter(x=>x.text||x.aria||x.title)")
   out['comboboxes']=await page.locator('[role=combobox]').evaluate_all("els=>els.map((e,i)=>({i,text:(e.innerText||'').trim(),aria:e.getAttribute('aria-label'),outer:e.outerHTML.slice(0,2000)}))")
   out['status']='ok'
   await page.screenshot(path=str(OUT/'roame_home.png'),full_page=True)
   await b.close()
 except Exception as e:
  out['status']='error';out['error']=f'{type(e).__name__}: {e}';out['traceback']=traceback.format_exc(limit=8)
 (OUT/'roame_home.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
 print(json.dumps({k:out.get(k) for k in ['status','url','title','error']}|{'inputs':out.get('inputs',[])[:20],'comboboxes':out.get('comboboxes',[])[:20],'buttons':out.get('buttons',[])[:40]},indent=2,ensure_ascii=False))

asyncio.run(main())
