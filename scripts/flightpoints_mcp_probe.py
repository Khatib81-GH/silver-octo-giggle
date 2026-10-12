#!/usr/bin/env python3
"""Connect to Flightpoints' documented, no-auth MCP and inspect/call search-flights."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

OUT = Path("results/flightpoints_probe")
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://mcp.flightpoints.com/mcp"


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    return value


def build_guess(schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    args: dict[str, Any] = {}
    for name, spec in props.items():
        low = name.lower()
        typ = spec.get("type")
        if low in {"origin", "from", "from_airport", "departure", "departure_airport", "origin_airport"}:
            args[name] = "JED"
        elif low in {"destination", "to", "to_airport", "arrival", "arrival_airport", "destination_airport"}:
            args[name] = "DTW"
        elif low in {"date", "departure_date", "depart_date", "travel_date", "outbound_date"}:
            args[name] = "2026-12-25"
        elif "start" in low and "date" in low:
            args[name] = "2026-12-25"
        elif ("end" in low or "to" in low) and "date" in low:
            args[name] = "2026-12-30"
        elif "cabin" in low or "class" in low:
            enum = spec.get("enum") or []
            choice = next((v for v in enum if "econom" in str(v).lower()), None)
            args[name] = choice if choice is not None else "economy"
        elif "program" in low:
            if typ == "array":
                args[name] = ["Flying Blue", "Delta SkyMiles"]
            else:
                args[name] = "Flying Blue"
        elif low in {"passengers", "adults", "seats", "number_of_passengers", "travelers", "travellers"}:
            args[name] = 1
        elif "max" in low and "stop" in low:
            args[name] = 3
        elif low in {"limit", "max_results", "page_size"}:
            args[name] = 50
        elif low in required:
            # Last-resort defaults for required scalar fields.
            if typ == "integer" or typ == "number":
                args[name] = 1
            elif typ == "boolean":
                args[name] = False
            elif typ == "array":
                args[name] = []
            elif typ == "object":
                args[name] = {}
            else:
                args[name] = ""
    return args


async def main() -> None:
    async with streamable_http_client(URL) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            (OUT / "initialize.json").write_text(json.dumps(to_jsonable(init), indent=2))
            listed = await session.list_tools()
            tools = to_jsonable(listed)
            (OUT / "tools.json").write_text(json.dumps(tools, indent=2))
            print(json.dumps(tools, indent=2)[:30000])

            tool_list = tools.get("tools", []) if isinstance(tools, dict) else []
            search_tool = next((t for t in tool_list if t.get("name") in {"search-flights", "search_flights"}), None)
            if not search_tool:
                search_tool = next((t for t in tool_list if "search" in str(t.get("name", "")).lower()), None)
            if not search_tool:
                raise RuntimeError("No search tool found")

            schema = search_tool.get("inputSchema") or search_tool.get("input_schema") or {}
            args = build_guess(schema)
            (OUT / "guessed_args.json").write_text(json.dumps(args, indent=2))
            print("CALL", search_tool.get("name"), json.dumps(args))
            try:
                result = await session.call_tool(search_tool["name"], args)
                result_json = to_jsonable(result)
                (OUT / "first_call.json").write_text(json.dumps(result_json, indent=2))
                print(json.dumps(result_json, indent=2)[:50000])
            except Exception as exc:
                (OUT / "first_call_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
                raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        (OUT / "probe_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        raise
