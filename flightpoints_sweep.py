#!/usr/bin/env python3

import asyncio
import json
import traceback
from pathlib import Path
from typing import Any

from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

OUT = Path('results')
OUT.mkdir(exist_ok=True)
URL = 'https://mcp.flightpoints.com/mcp'
TARGET_DATES = {
    '2026-12-25','2026-12-26','2026-12-27','2026-12-28','2026-12-29','2026-12-30','2026-12-31',
    '2027-01-01','2027-01-02','2027-01-03','2027-01-04','2027-01-05',
}
SKYTEAM = {'AR','AM','UX','AF','CI','MU','DL','GA','KQ','KL','KE','ME','SV','SK','RO','VN','VS','MF'}


def unpack_result(result: Any) -> dict:
    if getattr(result, 'structured_content', None):
        return result.structured_content
    for block in getattr(result, 'content', []) or []:
        if isinstance(block, TextContent):
            text = block.text.strip()
            try:
                return json.loads(text)
            except Exception:
                return {'text': text}
    return {'raw': str(result)}


def is_flying_blue(f: dict) -> bool:
    text = ' '.join(str(f.get(k) or '') for k in ('program','program_name','airline')).lower()
    return 'flying blue' in text or 'flyingblue' in text or 'air france/klm' in text or 'air france-klm' in text


def is_skymiles(f: dict) -> bool:
    text = ' '.join(str(f.get(k) or '') for k in ('program','program_name','airline')).lower()
    return 'skymiles' in text or text.strip() == 'delta' or 'delta skymiles' in text


def normalized_codes(f: dict) -> list[str]:
    codes = f.get('economy_airlines_codes') or []
    if isinstance(codes, str):
        codes = [x.strip().upper() for x in codes.replace(',', ' ').split() if x.strip()]
    return [str(x).upper() for x in codes]


def skyteam_operated(f: dict) -> bool:
    codes = normalized_codes(f)
    if codes:
        return all(code in SKYTEAM for code in codes)
    alliance = str(f.get('alliance') or '').lower()
    return 'skyteam' in alliance


async def main():
    output = {'url': URL, 'status': 'starting'}
    args = {
        'origin': 'JED',
        'destination': 'DTW',
        'departure_date': '2026-12-30',
        'passengers': 1,
        'cabin_class': 'economy',
        'delta': 6,
        'minimum_seats': 1,
        'only_direct': False,
    }
    try:
        transport = streamable_http_client(URL, max_sse_event_size=64*1024*1024)
        async with Client(transport) as client:
            result = unpack_result(await client.call_tool('search-flights', args))
        output['status'] = 'ok'
        output['request'] = args
        output['result'] = result
    except Exception as exc:
        output['status'] = 'error'
        output['error'] = f'{type(exc).__name__}: {exc}'
        output['traceback'] = traceback.format_exc(limit=25)

    flights = [f for f in output.get('result', {}).get('flights', []) or [] if str(f.get('departure_date')) in TARGET_DATES]
    programmes: dict[str,int] = {}
    filtered = {'flying_blue': [], 'skymiles': [], 'skyteam_other': [], 'program_counts': programmes}
    for f in flights:
        program = str(f.get('program_name') or f.get('program') or 'unknown')
        programmes[program] = programmes.get(program, 0) + 1
        if not skyteam_operated(f):
            continue
        if is_flying_blue(f):
            filtered['flying_blue'].append(f)
        elif is_skymiles(f):
            filtered['skymiles'].append(f)
        else:
            filtered['skyteam_other'].append(f)

    for key in ('flying_blue','skymiles','skyteam_other'):
        filtered[key].sort(key=lambda f: (str(f.get('departure_date')), float(f.get('economy_miles') or 1e18), float(f.get('economy_tax') or 1e18)))

    output['filtered'] = filtered
    output['target_flight_count'] = len(flights)
    (OUT/'flightpoints_sweep.json').write_text(json.dumps(output, indent=2, ensure_ascii=False))
    (OUT/'flightpoints_filtered.json').write_text(json.dumps(filtered, indent=2, ensure_ascii=False))
    print(json.dumps({
        'status': output.get('status'),
        'search_status': output.get('result',{}).get('status'),
        'is_complete': output.get('result',{}).get('is_complete'),
        'total_results': output.get('result',{}).get('total_results'),
        'target_flight_count': len(flights),
        'flying_blue': len(filtered['flying_blue']),
        'skymiles': len(filtered['skymiles']),
        'skyteam_other': len(filtered['skyteam_other']),
        'programs': programmes,
        'error': output.get('error'),
    }, indent=2, ensure_ascii=False))

asyncio.run(main())
