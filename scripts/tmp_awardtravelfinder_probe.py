#!/usr/bin/env python3
import json
from pathlib import Path
import requests

BASE = "https://awardtravelfinder.com"
out = {}

for path in ["/.well-known/agent.json", "/openapi.json", "/api/openapi.json", "/docs/openapi.json"]:
    try:
        r = requests.get(BASE + path, timeout=30)
        out[path] = {"status": r.status_code, "headers": dict(r.headers), "text": r.text[:2_000_000]}
    except Exception as e:
        out[path] = {"error": repr(e)}

try:
    r = requests.post(BASE + "/api/v1/agent/register", json={"agent_name": "JED-DTW-fare-research"}, timeout=30)
    out["register"] = {"status": r.status_code, "headers": dict(r.headers), "text": r.text}
except Exception as e:
    out["register"] = {"error": repr(e)}

Path("tmp_awardtravelfinder_probe.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps({k: {"status": v.get("status"), "preview": v.get("text", "")[:1000], "error": v.get("error")} for k,v in out.items()}, indent=2))
