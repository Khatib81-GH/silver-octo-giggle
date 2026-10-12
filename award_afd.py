#!/usr/bin/env python3
"""Query Award Flight Daily over MCP for Flying Blue and SkyMiles in two batches."""

from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path
from typing import Any

from mcp.client import Client

URL = "https://awardflightdaily.com/mcp-server/mcp"
OUT = Path("results")
OUT.mkdir(exist_ok=True)

BATCHES = {
    "dec25_30": ("2026-12-25", "2026-12-30"),
    "dec31_jan5": ("2026-12-31", "2027-01-05"),
}
SOURCES = ["flyingblue", "delta"]


def dump_model(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {str(k): dump_model(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [dump_model(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: dump_model(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def extract_text(result: Any) -> list[str]:
    texts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            texts.append(text)
    return texts


async def main() -> None:
    output: dict[str, Any] = {"url": URL, "status": "starting", "queries": {}}
    try:
        async with Client(URL) as client:
            listed = await client.list_tools()
            output["tools"] = [getattr(t, "name", None) for t in listed.tools]
            (OUT / "afd_checkpoint.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))

            for batch_name, (date_from, date_to) in BATCHES.items():
                output["queries"].setdefault(batch_name, {})
                for source in SOURCES:
                    key = f"{batch_name}:{source}:Y"
                    query_record: dict[str, Any] = {
                        "origin": "JED",
                        "destination": "DTW",
                        "date_from": date_from,
                        "date_to": date_to,
                        "cabin": "Y",
                        "source": source,
                        "direct_only": False,
                        "min_seats": 1,
                        "limit": 200,
                        "offset": 0,
                        "response_format": "json",
                    }
                    try:
                        result = await client.call_tool("afd_search_award_flights", query_record)
                        raw = dump_model(result)
                        texts = extract_text(result)
                        parsed_texts: list[Any] = []
                        for text in texts:
                            try:
                                parsed_texts.append(json.loads(text))
                            except Exception:
                                parsed_texts.append(text)
                        output["queries"][batch_name][source] = {
                            "status": "ok" if not getattr(result, "is_error", False) else "tool_error",
                            "arguments": query_record,
                            "result": raw,
                            "text_payloads": parsed_texts,
                        }
                    except Exception as exc:
                        output["queries"][batch_name][source] = {
                            "status": "exception",
                            "arguments": query_record,
                            "error": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc(limit=8),
                        }
                    (OUT / "afd_checkpoint.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))

        output["status"] = "completed"
    except Exception as exc:
        output["status"] = "connection_error"
        output["error"] = f"{type(exc).__name__}: {exc}"
        output["traceback"] = traceback.format_exc(limit=12)

    (OUT / "award_afd.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(json.dumps({
        "status": output.get("status"),
        "tools": output.get("tools"),
        "query_statuses": {
            batch: {source: record.get("status") for source, record in sources.items()}
            for batch, sources in output.get("queries", {}).items()
        },
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
