#!/usr/bin/env python3
"""Call Flightpoints' no-auth MCP without the SDK's 1 MiB SSE limit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import httpx

OUT = Path("results/flightpoints_probe")
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://mcp.flightpoints.com/mcp"


def parse_sse(text: str) -> list[Any]:
    out: list[Any] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
        if data:
            try:
                out.append(json.loads(data))
            except json.JSONDecodeError:
                out.append({"unparsed": data})
    return out


def post(client: httpx.Client, payload: dict[str, Any], sid: str | None = None):
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if sid:
        headers["mcp-session-id"] = sid
    with client.stream("POST", URL, headers=headers, json=payload, timeout=180.0) as response:
        response.raise_for_status()
        sid = response.headers.get("mcp-session-id") or sid
        ct = response.headers.get("content-type", "")
        text = "".join(response.iter_text())
        status = response.status_code
    messages = parse_sse(text) if "text/event-stream" in ct else ([json.loads(text)] if text.strip() else [])
    return messages, sid, ct, status


def main() -> int:
    with httpx.Client(follow_redirects=True, headers={"user-agent": "flight-research/1.0"}) as client:
        init, sid, init_ct, init_status = post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "flight-research", "version": "1.0"}},
        })
        (OUT / "direct_initialize.json").write_text(json.dumps({"status": init_status, "content_type": init_ct, "session_id": sid, "messages": init}, indent=2))
        post(client, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, sid)

        args = {
            "origin": "JED",
            "destination": "DTW",
            "departure_date": "2026-12-25",
            "passengers": 1,
            "cabin_class": "economy"
        }
        messages, sid, ct, status = post(client, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "search-flights", "arguments": args},
        }, sid)
        raw = {"status": status, "content_type": ct, "session_id": sid, "arguments": args, "messages": messages}
        (OUT / "direct_unfiltered_call.json").write_text(json.dumps(raw, indent=2))
        summary = {"status": status, "content_type": ct, "message_count": len(messages), "serialized_bytes": len(json.dumps(messages))}
        try:
            sc = messages[0]["result"]["structuredContent"]
            summary.update({"total_results": sc.get("total_results"), "total_flights": sc.get("total_flights"), "status_text": sc.get("status"), "search_key": sc.get("search_key")})
        except Exception:
            pass
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        (OUT / "direct_unfiltered_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        raise
