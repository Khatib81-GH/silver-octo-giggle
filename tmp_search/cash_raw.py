import json
import traceback
from datetime import date, timedelta
from pathlib import Path

from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html
from selectolax.lexbor import LexborHTMLParser

START=date(2026,12,25); END=date(2027,1,5)
DATES=[]; d=START
while d<=END:
    DATES.append(d.isoformat()); d+=timedelta(days=1)

SKYTEAM={
'aerolineas argentinas','aeromexico','air europa','air france','china airlines','china eastern',
'delta','garuda indonesia','kenya airways','klm','korean air','middle east airlines','mea','saudia',
'sas','scandinavian airlines','tarom','vietnam airlines','virgin atlantic'}

def g(obj,*idx,default=None):
    cur=obj
    try:
        for i in idx: cur=cur[i]
        return cur
    except Exception: return default

def timepair(v):
    v=list(v or [])+[None,None]
    return [v[0] or 0,v[1] or 0]

def custom_parse(html):
    parser=LexborHTMLParser(html)
    script=parser.css_first(r'script.ds\:1')
    if script is None: raise RuntimeError('no script.ds:1')
    js=script.text()
    data=js.split('data:',1)[1].rsplit(',',1)[0]
    if data.endswith('errorHasStatus: true'): raise RuntimeError('Google returned errorHasStatus')
    payload=json.loads(data)
    rows=[]
    for section in payload[2:4]:
        if not section or not isinstance(section,list): continue
        group=g(section,0,default=[])
        if not isinstance(group,list): continue
        for k in group:
            if not isinstance(k,list) or not k: continue
            flight=g(k,0,default=[])
            if not isinstance(flight,list): continue
            fare_container=g(k,1,default=[])
            fare=g(fare_container,0,default=[]) if isinstance(fare_container,list) else []
            price=g(fare,1) if isinstance(fare,list) else None
            airlines=g(flight,1,default=[])
            if not isinstance(airlines,list): airlines=[str(airlines)] if airlines else []
            segs=[]
            for s in g(flight,2,default=[]) or []:
                if not isinstance(s,list): continue
                segs.append({
                    'from':g(s,3),'from_name':g(s,4),'to':g(s,6),'to_name':g(s,5),
                    'departure_time':timepair(g(s,8,default=[])),
                    'departure_date':g(s,20,default=[]),
                    'arrival_time':timepair(g(s,10,default=[])),
                    'arrival_date':g(s,21,default=[]),
                    'duration_minutes':g(s,11),'aircraft':g(s,17),
                })
            rows.append({'price':price,'airlines':airlines,'segments':segs,'raw_type':g(flight,0)})
    return rows, {'payload_len':len(payload),'section_shapes':[type(x).__name__+':'+str(len(x) if hasattr(x,'__len__') else '') for x in payload[:12]]}

out=[]
for dt in DATES:
    print('RAW GOOGLE',dt,flush=True)
    try:
        q=create_query(flights=[FlightQuery(date=dt,from_airport='JED',to_airport='DTW')],trip='one-way',seat='economy',passengers=Passengers(adults=1),currency='USD',hide_separate_and_self_transfer=True,exclude_basic_economy=True)
        html=fetch_flights_html(q)
        rows,meta=custom_parse(html)
        sky=[r for r in rows if r['airlines'] and all(str(a).lower() in SKYTEAM for a in r['airlines'])]
        out.append({'date':dt,'skyteam':sky,'all_count':len(rows),'meta':meta})
        print(' rows',len(rows),'sky',len(sky),[(x['price'],x['airlines']) for x in sky[:8]],flush=True)
    except Exception as e:
        traceback.print_exc()
        out.append({'date':dt,'error':f'{type(e).__name__}: {e}'})
Path('cash_raw_results.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
print('CASH_RAW_BEGIN')
print(json.dumps(out,ensure_ascii=False))
print('CASH_RAW_END')
