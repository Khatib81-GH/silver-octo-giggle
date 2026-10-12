#!/usr/bin/env python3
"""Fetch Pointhound's public JS bundles and extract award-search endpoint strings."""
from __future__ import annotations
import json, re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE='https://www.pointhound.com'
OUT=Path('results/pointhound_bundle_probe'); OUT.mkdir(parents=True,exist_ok=True)
TERMS=[
 'scout.pointhound.com','Fetch deals','fetch deals','award','redemption','itinerar',
 'flight/search','flights/search','search-flights','availability','programs','loyalty',
 'originAirport','destinationAirport','departureDate','places/search','api/search',
 'queryKey','searchParams','standard search','standardSearch','point.me','seats.aero'
]
URL_RE=re.compile(r'https?://[^"\'`\\\s)]+|/[A-Za-z0-9_./?=&%:-]{4,}')

s=requests.Session(); s.headers['user-agent']='Mozilla/5.0'
html=s.get(BASE+'/search',timeout=60).text
soup=BeautifulSoup(html,'html.parser')
scripts=[]
for tag in soup.find_all('script',src=True):
    src=urljoin(BASE,tag['src'])
    if '/_next/' in src: scripts.append(src)

hits=[]
for i,url in enumerate(dict.fromkeys(scripts)):
    try:
        text=s.get(url,timeout=60).text
    except Exception as e:
        hits.append({'url':url,'error':str(e)}); continue
    local=[]
    lower=text.lower()
    for term in TERMS:
        start=0
        while True:
            idx=lower.find(term.lower(),start)
            if idx<0: break
            lo=max(0,idx-500); hi=min(len(text),idx+1200)
            local.append({'term':term,'index':idx,'snippet':text[lo:hi]})
            start=idx+max(1,len(term))
            if sum(1 for x in local if x['term']==term)>=8: break
    # also keep URL-like strings from bundles with any relevant hit
    if local:
        urls=sorted(set(URL_RE.findall(text)))
        relevant=[u for u in urls if any(k in u.lower() for k in ('flight','search','award','scout','point','place','avail'))]
        hits.append({'url':url,'size':len(text),'hits':local,'relevant_urls':relevant[:300]})

(OUT/'bundle_hits.json').write_text(json.dumps({'script_count':len(scripts),'bundles':hits},indent=2))
# compact text for logs
lines=[f'scripts={len(scripts)} hit_bundles={len(hits)}']
for b in hits:
    if 'hits' not in b: continue
    lines.append('\n### '+b['url'])
    for h in b['hits'][:20]:
        lines.append(f"TERM {h['term']}: {h['snippet'][:1200]}")
    for u in b.get('relevant_urls',[])[:50]: lines.append('URL '+u)
(OUT/'bundle_hits.txt').write_text('\n'.join(lines))
print('\n'.join(lines)[:100000])
