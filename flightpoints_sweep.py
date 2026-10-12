#!/usr/bin/env python3

import asyncio
import json
import traceback
from pathlib import Path
from typing import Any

from mcp.client import Client
from mcp.types import TextContent

OUT = Path('results')
OUT.mkdir(exist_ok=True)
URL = 'https://mcp.flightpoints.com/mcp'

BATCHES = [
    ('dec25_31', '2026-12-28', 3),
    ('dec31_jan6', '2027-01-03', 3),
]
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


def merge_flights(snapshots: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for snap in snapshots:
        for f in snap.get('flights', []) or []:
            key = str(f.get('id') or json.dumps(f, sort_keys=True))
            merged[key] = f
    return list(merged.values())


def is_flying_blue(f: dict) -> bool:
    text = ' '.join(str(f.get(k) or '') for k in ('program','program_name','airline')).lower()
    return 'flying blue' in text or 'flyingblue' in text or 'air france/klm' in text or 'air france-klm' in text


def is_skymiles(f: dict) -> bool:
    text = ' '.join(str(f.get(k) or '') for k in ('program','program_name','airline')).lower()
    return 'skymiles' in text or text.strip() == 'delta' or 'delta skymiles' in text


def skyteam_operated(f: dict) -> bool:
    codes = f.get('economy_airlines_codes') or []
    if isinstance(codes, str):
        codes = [x.strip().upper() for x in codes.replace(',', ' ').split() if x.strip()]
    codes = [str(x).upper() for x in codes]
    if codes:
        return all(code in SKYTEAM for code in codes)
    alliance = str(f.get('alliance') or '').lower()
    return 'skyteam' in alliance


async def run_search(client: Client, label: str, date: str, delta: int) -> dict:
    snapshots: list[dict] = []
    args = {
        'origin': 'JED',
        'destination': 'DTW',
        'departure_date': date,
        'passengers': 1,
        'cabin_class': 'economy',
        'delta': delta,
        'minimum_seats': 1,
        'only_direct': False,
    }
    first = unpack_result(await client.call_tool('search-flights', args))
    snapshots.append(first)
    key = first.get('search_key')
    for _ in range(18):
        if snapshots[-1].get('is_complete') or not key:
            break
        await asyncio.sleep(5)
        snap = unpack_result(await client.call_tool('search-flights', {'search_key': key}))
        snapshots.append(snap)
        key = snap.get('search_key') or key
    flights = merge_flights(snapshots)
    return {
        'label': label,
        'request': args,
        'snapshots': snapshots,
        'flights': flights,
        'final_status': snapshots[-1].get('status') if snapshots else None,
        'is_complete': bool(snapshots and snapshots[-1].get('is_complete')),
        'search_key': key,
    }


async def main():
    output = {'url': URL, 'batches': {}, 'status': 'starting'}
    try:
        async with Client(URL) as client:
            for label, date, delta in BATCHES:
                try:
                    output['batches'][label] = await run_search(client, label, date, delta)
                except Exception as exc:
                    output['batches'][label] = {
                        'status': 'error',
                        'error': f'{type(exc).__name__}: {exc}',
                        'traceback': traceback.format_exc(limit=20),
                    }
                (OUT/'flightpoints_checkpoint.json').write_text(json.dumps(output, indent=2, ensure_ascii=False))
        output['status'] = 'ok'
    except Exception as exc:
        output['status'] = 'connection_error'
        output['error'] = f'{type(exc).__name__}: {exc}'
        output['traceback'] = traceback.format_exc(limit=20)

    all_flights: dict[str, dict] = {}
    for batch in output.get('batches', {}).values():
        for f in batch.get('flights', []) if isinstance(batch, dict) else []:
            if str(f.get('departure_date')) not in TARGET_DATES:
                continue
            all_flights[str(f.get('id') or json.dumps(f, sort_keys=True))] = f

    filtered = {'flying_blue': [], 'skymiles': [], 'other_programs': {}}
    for f in all_flights.values():
        program = str(f.get('program_name') or f.get('program') or 'unknown')
        filtered['other_programs'][program] = filtered['other_programs'].get(program, 0) + 1
        if not skyteam_operated(f):
            continue
        if is_flying_blue(f):
            filtered['flying_blue'].append(f)
        if is_skymiles(f):
            filtered['skymiles'].append(f)

    for key in ('flying_blue','skymiles'):
        filtered[key].sort(key=lambda f: (str(f.get('departure_date')), float(f.get('economy_miles') or 1e18), float(f.get('economy_tax') or 1e18)))

    output['filtered'] = filtered
    output['total_unique_target_flights'] = len(all_flights)
    (OUT/'flightpoints_sweep.json').write_text(json.dumps(output, indent=2, ensure_ascii=False))
    (OUT/'flightpoints_filtered.json').write_text(json.dumps(filtered, indent=2, ensure_ascii=False))
    print(json.dumps({
        'status': output.get('status'),
        'batches': {k: {'is_complete': v.get('is_complete'), 'flight_count': len(v.get('flights', [])), 'final_status': v.get('final_status'), 'error': v.get('error')} for k,v in output.get('batches',{}).items()},
        'total_unique_target_flights': len(all_flights),
        'flying_blue': len(filtered['flying_blue']),
        'skymiles': len(filtered['skymiles']),
        'programs': filtered['other_programs'],
    }, indent=2, ensure_ascii=False))

asyncio.run(main())
