#!/usr/bin/env python3

import json
from pathlib import Path
from urllib.parse import urlencode

import requests

OUT = Path("results")
OUT.mkdir(exist_ok=True)

queries = []
for source in ["flyingblue", "delta", "flying_blue", "afklm", "skyteam"]:
    queries.append({"source": source})
    queries.append({"source": source, "origin": "JED", "destination": "DTW", "date": "2026-12-25"})

records = []
for q in queries:
    url = "https://seats.aero/api/availability?" + urlencode(q)
    try:
        r = requests.get(url, headers={"accept": "application/json", "user-agent": "Mozilla/5.0"}, timeout=60)
        text = r.text
        rec = {
            "query": q,
            "url": url,
            "status": r.status_code,
            "headers": dict(r.headers),
            "length": len(text),
            "preview": text[:3000],
        }
        if r.status_code == 200:
            try:
                data = r.json()
                rec["json_type"] = type(data).__name__
                rec["json_count"] = len(data) if hasattr(data, "__len__") else None
                if isinstance(data, list):
                    rec["sample"] = data[:2]
                elif isinstance(data, dict):
                    rec["keys"] = list(data.keys())[:50]
                    for key in ("data", "results", "availability"):
                        if key in data and isinstance(data[key], list):
                            rec["nested_count"] = len(data[key])
                            rec["sample"] = data[key][:2]
                            break
            except Exception as exc:
                rec["json_error"] = f"{type(exc).__name__}: {exc}"
        records.append(rec)
    except Exception as exc:
        records.append({"query": q, "url": url, "error": f"{type(exc).__name__}: {exc}"})

(OUT / "seats_probe.json").write_text(json.dumps(records, indent=2, ensure_ascii=False))
print(json.dumps([{k: r.get(k) for k in ("query", "status", "length", "json_type", "json_count", "nested_count", "error")} for r in records], indent=2))
