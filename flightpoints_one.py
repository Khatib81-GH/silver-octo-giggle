#!/usr/bin/env python3

import asyncio
import json
import traceback
from pathlib import Path
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

OUT=Path('results'); OUT.mkdir(exist_ok=True)
URL='https://mcp.flightpoints.com/mcp'


def unpack(r):
    if getattr(r,'structured_content',None): return r.structured_content
    texts=[]
    for b in getattr(r,'content',[]) or []:
        if isinstance(b,TextContent): texts.append(b.text)
    for t in texts:
        try: return json.loads(t)
        except Exception: pass
    return {'texts':texts}

async def main():
    out={}
    args={
      'origin':'JED','destination':'DTW','departure_date':'2026-12-25',
      'passengers':1,'cabin_class':'economy','delta':0,'minimum_seats':1,'only_direct':False,
      'filter_cabin':'DL AF KL SV ME VS SK UX KE KQ RO VN CI MU MF GA AM AR',
      'programmes':'flyingblue,delta','alliances':'skyteam'
    }
    try:
      transport=streamable_http_client(URL,max_sse_event_size=32*1024*1024)
      async with Client(transport) as c:
        out['result']=unpack(await c.call_tool('search-flights',args))
      out['status']='ok'
    except Exception as e:
      out={'status':'error','error':f'{type(e).__name__}: {e}','traceback':traceback.format_exc(limit=20),'args':args}
    (OUT/'flightpoints_one.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
    print(json.dumps(out,indent=2,ensure_ascii=False)[:20000])

asyncio.run(main())
