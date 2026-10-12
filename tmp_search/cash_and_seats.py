import dataclasses
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests

START = date(2026, 12, 25)
END = date(2027, 1, 5)
DATES = []
d = START
while d <= END:
    DATES.append(d.isoformat())
    d += timedelta(days=1)

SKYTEAM_NAMES = (
    'delta', 'air france', 'klm', 'saudia', 'saudi arabian', 'middle east airlines',
    'mea', 'virgin atlantic', 'korean air', 'aeromexico', 'china airlines',
    'china eastern', 'garuda', 'kenya airways', 'vietnam airlines', 'sas',
    'scandinavian airlines', 'aerolineas argentinas', 'tarom', 'air europa',
)


def jsonify(obj, depth=0):
    if depth > 7:
        return repr(obj)
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if dataclasses.is_dataclass(obj):
        return {k: jsonify(v, depth + 1) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): jsonify(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonify(v, depth + 1) for v in obj]
    if hasattr(obj, '__dict__'):
        return {k: jsonify(v, depth + 1) for k, v in vars(obj).items() if not k.startswith('_')}
    return repr(obj)


def skyteam_likely(record):
    text = json.dumps(record, ensure_ascii=False).lower()
    return any(name in text for name in SKYTEAM_NAMES)


cash = []
try:
    from fast_flights import FlightData, Passengers, get_flights
    for travel_date in DATES:
        print(f'Google Flights via fast-flights: {travel_date}', flush=True)
        try:
            result = get_flights(
                flight_data=[FlightData(date=travel_date, from_airport='JED', to_airport='DTW')],
                trip='one-way',
                seat='economy',
                passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
                fetch_mode='fallback',
            )
            raw = jsonify(result)
            flights = raw.get('flights', []) if isinstance(raw, dict) else []
            cash.append({
                'date': travel_date,
                'current_price': raw.get('current_price') if isinstance(raw, dict) else None,
                'all_flights': flights,
                'skyteam_name_matches': [f for f in flights if skyteam_likely(f)],
                'raw_result': raw,
            })
            print(f'  flights={len(flights)} skyteam_name_matches={sum(skyteam_likely(f) for f in flights)}', flush=True)
        except Exception as exc:
            cash.append({'date': travel_date, 'error': f'{type(exc).__name__}: {exc}'})
            print(f'  ERROR {type(exc).__name__}: {exc}', flush=True)
        time.sleep(1)
except Exception as exc:
    cash.append({'fatal_error': f'{type(exc).__name__}: {exc}'})
    print('FAST_FLIGHTS_FATAL', repr(exc), flush=True)

Path('cash_results.json').write_text(json.dumps(cash, indent=2, ensure_ascii=False), encoding='utf-8')
print('CASH_RESULTS_BEGIN')
print(json.dumps(cash, ensure_ascii=False))
print('CASH_RESULTS_END')

# Secondary third-party award source. This may be blocked by Cloudflare; preserve the
# exact status/body so failure is distinguishable from an empty award search.
params = {
    'min_seats': '1',
    'additional_days': 'true',
    'additional_days_num': '12',
    'max_fees': '40000',
    'show_individual': 'true',
    'date': START.isoformat(),
    'origins': 'JED',
    'destinations': 'DTW',
    'applicable_cabin': 'economy',
}
headers = {
    'accept': 'application/json',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
    'referer': 'https://seats.aero/search?date=2026-12-25&origins=JED&destinations=DTW',
}
try:
    r = requests.get('https://seats.aero/_api/search_partial', params=params, headers=headers, timeout=60)
    payload = {'status_code': r.status_code, 'url': r.url, 'content_type': r.headers.get('content-type'), 'body_prefix': r.text[:2000]}
    try:
        payload['json'] = r.json()
    except Exception:
        pass
except Exception as exc:
    payload = {'error': f'{type(exc).__name__}: {exc}'}
Path('seats_aero_results.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
print('SEATS_AERO_RESULT_BEGIN')
print(json.dumps(payload, ensure_ascii=False))
print('SEATS_AERO_RESULT_END')
