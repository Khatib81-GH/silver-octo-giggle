#!/usr/bin/env python3

import json
from pathlib import Path

import requests

OUT = Path("results")
OUT.mkdir(exist_ok=True)

URLS = [
    "https://awardflightdaily.com/mcp-server/mcp",
    "https://awardflightdaily.com/mcp-server/mcp/",
    "https://awardflightdaily.com/mcp-server",
    "https://mcp.awardflightdaily.com/mcp",
]
VERSIONS = ["2025-03-26", "2024-11-05"]

records = []
for url in URLS:
    try:
        r = requests.get(url, headers={"Accept": "application/json, text/event-stream"}, timeout=30, allow_redirects=True)
        records.append({
            "kind": "GET", "url": url, "final_url": r.url, "status": r.status_code,
            "headers": dict(r.headers), "body": r.text[:5000],
        })
    except Exception as exc:
        records.append({"kind": "GET", "url": url, "error": f"{type(exc).__name__}: {exc}"})
    for version in VERSIONS:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "fare-sweep-probe", "version": "1.0"},
            },
        }
        try:
            r = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json=payload,
                timeout=45,
                allow_redirects=True,
            )
            records.append({
                "kind": "POST-initialize", "protocol": version, "url": url, "final_url": r.url,
                "status": r.status_code, "headers": dict(r.headers), "body": r.text[:10000],
            })
        except Exception as exc:
            records.append({
                "kind": "POST-initialize", "protocol": version, "url": url,
                "error": f"{type(exc).__name__}: {exc}",
            })

(OUT / "mcp_probe.json").write_text(json.dumps(records, indent=2, ensure_ascii=False))
print(json.dumps([
    {k: rec.get(k) for k in ("kind", "protocol", "url", "final_url", "status", "error") if rec.get(k) is not None}
    for rec in records
], indent=2))
