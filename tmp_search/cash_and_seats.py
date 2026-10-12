import dataclasses
import json
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

SKYTEAM_NAMES = {
    'aerolineas argentinas', 'aeromexico', 'air europa', 'air france',
    'china airlines', 'china eastern', 'delta', 'garuda indonesia',
    'kenya airways', 'klm', 'korean air', 'middle east airlines', 'mea',
    'saudia', 'sas', 'scandinavian airlines', 'tarom', 'vietnam airlines',
    'virgin atlantic',
}


def jsonify(obj, depth=0):
    if depth > 10:
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


def all_skyteam(flight):
    airlines = [str(x).strip().lower() for x in (flight.get('airlines') or [])]
    return bool(airlines) and all(a in SKYTEAM_NAMES for a in airlines)


cash = []
try:
    from fast_flights import FlightQuery, Passengers, create_query, get_flights
    for travel_date in DATES:
        print(f'Google Flights all-carrier query, SkyTeam filter: {travel_date}', flush=True)
        try:
            query = create_query(
                flights=[FlightQuery(
                    date=travel_date,
                    from_airport='JED',
                    to_airport='DTW',
                )],
                trip='one-way',
                seat='economy',
                passengers=Passengers(adults=1),
                currency='USD',
                hide_separate_and_self_transfer=True,
                exclude_basic_economy=True,
            )
            result = get_flights(query)
            raw = jsonify(result)
            flights = raw if isinstance(raw, list) else raw.get('flights', []) if isinstance(raw, dict) else []
            skyteam = [f for f in flights if all_skyteam(f)]
            metadata = jsonify(getattr(result, 'metadata', None))
            cash.append({
                'date': travel_date,
                'skyteam_flights': skyteam,
                'all_flight_count': len(flights),
                'metadata': metadata,
            })
            print(f'  all={len(flights)} skyteam={len(skyteam)}', flush=True)
            for f in skyteam[:8]:
                print(' ', json.dumps(f, ensure_ascii=False)[:1600], flush=True)
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

# Secondary third-party award source. Preserve the exact status/body so failure is
# distinguishable from an empty award search.
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
