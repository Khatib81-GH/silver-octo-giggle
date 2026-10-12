import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

root = "https://awardtravelfinder.com"
s = requests.Session()
s.headers.update({"User-Agent": "ChatGPT travel research", "Accept": "application/json"})
registration = s.post(
    root + "/api/v1/agent/register",
    json={"agent_name": "JED-DTW daily fare comparison"},
    timeout=60,
).json()
credential = registration["api_key"]
auth = {"X-API-Key": credential}

base = root + "/api/v1/chatgpt"
airlines_response = s.get(base + "/airlines", headers=auth, timeout=60)
if not airlines_response.ok:
    base = root + "/api/v1"
    airlines_response = s.get(base + "/airlines", headers=auth, timeout=60)
airlines = airlines_response.json()
print("airlines", airlines_response.status_code, json.dumps(airlines)[:5000])

travel_dates = []
d = date(2026, 12, 25)
while d <= date(2027, 1, 5):
    travel_dates.append(d.isoformat())
    d += timedelta(days=1)

rows = []
for travel_date in travel_dates:
    response = s.get(
        base + "/search_all",
        headers=auth,
        params={"departure": "JED", "destination": "DTW", "date": travel_date},
        timeout=180,
    )
    payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"text": response.text[:10000]}
    print("search", travel_date, response.status_code, json.dumps(payload)[:10000])
    item = {"date": travel_date, "http_status": response.status_code, "initial": payload, "polled": {}}
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    pending = data.get("pending_searches", {}) if isinstance(data, dict) else {}
    for airline, pending_item in pending.items():
        label = (airline + " " + json.dumps(pending_item)).lower()
        if not any(name in label for name in ("air france", "air-france", "klm", "delta", "saudia", "saudi", "flying blue", "flying-blue")):
            continue
        cache_key = pending_item.get("cache_key") if isinstance(pending_item, dict) else None
        if not cache_key:
            continue
        status_response = s.get(
            base + "/search_status",
            headers=auth,
            params={"airline": airline, "cache_key": cache_key},
            timeout=180,
        )
        status_payload = status_response.json() if status_response.headers.get("content-type", "").startswith("application/json") else {"text": status_response.text[:10000]}
        item["polled"][airline] = {"http_status": status_response.status_code, "response": status_payload}
        print("poll", travel_date, airline, status_response.status_code, json.dumps(status_payload)[:10000])
    rows.append(item)

output = {
    "source": "AwardTravelFinder REST API",
    "queried_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "route": "JED-DTW",
    "airlines": airlines,
    "results": rows,
}
Path("atf_daily_results.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
Path("atf_daily_registration.json").write_text(json.dumps({
    "account": registration.get("account"),
    "usage": registration.get("usage"),
    "rest_api": registration.get("rest_api"),
    "credential": "redacted",
}, indent=2), encoding="utf-8")
print("ATF_DAILY_RESULTS_BEGIN")
print(json.dumps(output))
print("ATF_DAILY_RESULTS_END")
