#!/usr/bin/env python3
from pathlib import Path
import requests,re,json
URL='https://www.pointhound.com/_next/static/immutable/chunks/1n9cbmnmiscsb.js'
out=Path('results/pointhound_route_bundle'); out.mkdir(parents=True,exist_ok=True)
s=requests.get(URL,headers={'user-agent':'Mozilla/5.0'},timeout=60); s.raise_for_status(); text=s.text
(out/'bundle.js').write_text(text)
needles=['Fetch deals','/flights','router.push','push(','replace(','formatFlightSearchErrors','onClick:en','SearchWithPointsToggle','departureDate','dateRange']
h=[]
for n in needles:
 i=0
 while True:
  i=text.find(n,i)
  if i<0: break
  h.append({'needle':n,'index':i,'snippet':text[max(0,i-5000):min(len(text),i+5000)]})
  i+=len(n)
  if sum(1 for x in h if x['needle']==n)>=20:break
(out/'hits.json').write_text(json.dumps(h,indent=2))
(out/'hits.txt').write_text('\n\n'.join(f"## {x['needle']} @{x['index']}\n{x['snippet']}" for x in h))
print((out/'hits.txt').read_text()[:100000])
