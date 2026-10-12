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
PROTOCOL_VERSION = "2025-11-25"


def parse_sse(text: str) -> list[Any]:
    messages: list[Any] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data_lines = []
        for line in block.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        try:
            messages.append(json.loads(data))
        except json.JSONDecodeError:
            messages.append({"unparsed": data})
    return messages


def rpc_post(client: httpx.Client, payload: dict[str, Any], session_id: str | None = None) -> tuple[list[Any], str | None, str, int]:
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    with client.stream("POST", URL, headers=headers, json=payload, timeout=180.0) as response:
        status = response.status_code
        response.raise_for_status()
        new_session = response.headers.get("mcp-session-id") or session_id
        content_type = response.headers.get("content-type", "")
        chunks = []
        for chunk in response.iter_text():
            chunks.append(chunk)
        text = "".join(chunks)
    if "text/event-stream" in content_type:
        return parse_sse(text), new_session, content_type, status
    if not text.strip():
        return [], new_session, content_type, status
    return [json.loads(text)], new_session, content_type, status


def main() -> int:
    with httpx.Client(http2=True, follow_redirects=True, headers={"user-agent": "flight-research/1.0"}) as client:
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "flight-research", "version": "1.0"},
            },
        }
        init_messages, session_id, init_ct, init_status = rpc_post(client, init_payload)
        (OUT / "direct_initialize.json").write_text(json.dumps({
            "status": init_status,
            "content_type": init_ct,
            "session_id": session_id,
            "messages": init_messages,
        }, indent=2))

        # Complete MCP initialization. A notification may return an empty 202.
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        notify_messages, session_id, notify_ct, notify_status = rpc_post(client, notification, session_id)
        (OUT / "direct_initialized_notification.json").write_text(json.dumps({
            "status": notify_status,
            "content_type": notify_ct,
            "messages": notify_messages,
        }, indent=2))

        args = {
            "origin": "JED",
            "destination": "DTW",
            "departure_date": "2026-12-25",
            "passengers": 1,
            "cabin_class": "economy",
            "minimum_seats": 1,
            "only_direct": False,
            "filter_cabin": "AR AM UX AF CI MU DL GA KQ KL KE ME SV SK RO VN VS MF",
            "operating_carriers_exclude": False,
        }
        call_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search-flights", "arguments": args},
        }
        call_messages, session_id, call_ct, call_status = rpc_post(client, call_payload, session_id)
        raw = {
            "status": call_status,
            "content_type": call_ct,
            "session_id": session_id,
            "arguments": args,
            "messages": call_messages,
        }
        (OUT / "direct_valid_call.json").write_text(json.dumps(raw, indent=2))
        print(json.dumps({
            "status": call_status,
            "content_type": call_ct,
            "message_count": len(call_messages),
            "serialized_bytes": len(json.dumps(call_messages)),
            "top_level_keys": [sorted(m.keys()) if isinstance(m, dict) else type(m).__name__ for m in call_messages],
        }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        (OUT / "direct_probe_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        raise
