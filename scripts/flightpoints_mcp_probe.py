#!/usr/bin/env python3
"""Connect to Flightpoints' no-auth MCP and test one valid JED→DTW award search."""

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


async def main() -> None:
    async with streamable_http_client(URL) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            (OUT / "initialize.json").write_text(json.dumps(to_jsonable(init), indent=2))
            listed = await session.list_tools()
            tools = to_jsonable(listed)
            (OUT / "tools.json").write_text(json.dumps(tools, indent=2))

            tool_list = tools.get("tools", []) if isinstance(tools, dict) else []
            search_tool = next((t for t in tool_list if t.get("name") == "search-flights"), None)
            if not search_tool:
                raise RuntimeError("search-flights tool not found")

            args = {
                "origin": "JED",
                "destination": "DTW",
                "departure_date": "2026-12-25",
                "passengers": 1,
                "cabin_class": "economy"
            }
            (OUT / "valid_args.json").write_text(json.dumps(args, indent=2))
            result = await session.call_tool(search_tool["name"], args)
            result_json = to_jsonable(result)
            (OUT / "valid_call.json").write_text(json.dumps(result_json, indent=2))
            print(json.dumps(result_json, indent=2)[:100000])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        (OUT / "probe_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        raise
