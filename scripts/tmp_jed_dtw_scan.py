#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ORIGIN = "JED"
DESTINATION = "DTW"
START = date(2026, 12, 25)
END = date(2027, 1, 5)
DATES = []
d = START
while d <= END:
    DATES.append(d.isoformat())
    d += timedelta(days=1)

SKYTEAM_MARKERS = [
    "delta", "air france", "klm", "saudia", "saudi arabian",
    "middle east airlines", "mea", "virgin atlantic", "aeromexico",
    "aeroméxico", "sas", "scandinavian airlines", "korean air",
    "china airlines", "china eastern", "xiamenair", "xiamen air",
    "garuda indonesia", "vietnam airlines", "kenya airways", "tarom",
    "air europa", "aerolineas argentinas", "aerolíneas argentinas",
]
NON_SKYTEAM_MARKERS = [
    "turkish", "qatar", "etihad", "emirates", "united", "american airlines",
    "british airways", "lufthansa", "swiss", "austrian", "air canada",
    "royal jordanian", "oman air", "egyptair", "wizz", "flyadeal", "flynas",
    "air cairo", "pegasus", "kuwait airways", "gulf air", "ita airways",
]
PROGRAM_KEEP = ("flying blue", "flyingblue", "delta", "skymiles")

OUT = Path("tmp_jed_dtw_results.json")
OUT_MD = Path("tmp_jed_dtw_results.md")


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if dataclasses.is_dataclass(value):
        return {k: jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return jsonable(value.model_dump(mode="json", by_alias=True))
        except Exception:
            return jsonable(value.model_dump())
    if hasattr(value, "dict"):
        try:
            return jsonable(value.dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {k: jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
    return str(value)


def extract_texts(value: Any) -> list[str]:
    obj = jsonable(value)
    found: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("text"), str):
                found.append(x["text"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return found


def maybe_parse_json(text: str) -> Any:
    text = text.strip()
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        candidates.append(fence.group(1).strip())
    blob = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if blob:
        candidates.append(blob.group(1))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def tool_schema(tool: Any) -> dict[str, Any]:
    obj = jsonable(tool)
    for key in ("inputSchema", "input_schema", "schema"):
        if isinstance(obj, dict) and isinstance(obj.get(key), dict):
            return obj[key]
    return {}


def tool_name(tool: Any) -> str:
    obj = jsonable(tool)
    if isinstance(obj, dict):
        return str(obj.get("name") or "")
    return ""


def choose_enum(schema: dict[str, Any], wanted: str) -> Any:
    enum = schema.get("enum") or []
    for item in enum:
        if wanted.lower() in str(item).lower():
            return item
    return enum[0] if enum else wanted


def value_for_property(key: str, schema: dict[str, Any], travel_date: str) -> Any:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    typ = schema.get("type")

    if normalized in {"origin", "from", "fromairport", "departureairport", "departureiata", "originairport", "origincode"}:
        return ORIGIN
    if normalized in {"origins", "fromairports", "departureairports", "originairports"}:
        return [ORIGIN] if typ == "array" else ORIGIN
    if normalized in {"destination", "to", "toairport", "arrivalairport", "arrivaliata", "destinationairport", "destinationcode"}:
        return DESTINATION
    if normalized in {"destinations", "toairports", "arrivalairports", "destinationairports"}:
        return [DESTINATION] if typ == "array" else DESTINATION
    if normalized in {"date", "departuredate", "departdate", "outbounddate", "traveldate", "datefrom", "startdate"}:
        return travel_date
    if normalized in {"dateto", "enddate"}:
        return travel_date
    if normalized in {"cabin", "cabinclass", "class", "travelclass"}:
        return choose_enum(schema, "economy")
    if normalized in {"program", "loyaltyprogram", "source"}:
        enum = schema.get("enum") or []
        if enum:
            for wanted in ("flying", "delta"):
                for item in enum:
                    if wanted in str(item).lower():
                        return item
        return "flyingblue,delta"
    if normalized in {"programs", "loyaltyprograms", "sources"}:
        return ["flyingblue", "delta"] if typ == "array" else "flyingblue,delta"
    if normalized in {"alliance", "alliances"}:
        return ["SkyTeam"] if typ == "array" else "SkyTeam"
    if normalized in {"adults", "adultcount", "passengers", "passengercount"}:
        if typ == "object":
            return {"adults": 1}
        return 1
    if normalized in {"minseats", "seats", "seatcount"}:
        return 1
    if normalized in {"limit", "maxresults", "resultlimit"}:
        return 100
    if normalized in {"offset"}:
        return 0
    if normalized in {"flexdays", "flexibledays", "dateflexibility"}:
        return 0
    if normalized in {"directonly", "nonstoponly", "onlydirectflights"}:
        return False
    if normalized in {"query", "prompt", "request"}:
        return f"One-way economy award flights from {ORIGIN} to {DESTINATION} on {travel_date}; only Delta SkyMiles or Air France/KLM Flying Blue, and only SkyTeam-operated itineraries."
    if "default" in schema:
        return schema["default"]
    return None


def build_arguments(schema: dict[str, Any], travel_date: str) -> dict[str, Any]:
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    args: dict[str, Any] = {}
    for key, spec in props.items():
        if not isinstance(spec, dict):
            spec = {}
        value = value_for_property(key, spec, travel_date)
        if value is not None:
            args[key] = value
    # Fail closed when an unknown required field exists; the error is recorded and the fallback source continues.
    missing = [k for k in required if k not in args]
    if missing:
        raise ValueError(f"Unmapped required fields: {missing}; schema={schema}")
    return args


async def scan_flightpoints(report: dict[str, Any]) -> None:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except Exception as exc:
        report["errors"].append(f"FlightPoints import failed: {exc}")
        return

    endpoints = ["https://mcpv1.flightpoints.com/mcp", "https://mcp.flightpoints.com/mcp"]
    last_error = None
    for endpoint in endpoints:
        try:
            async with streamable_http_client(endpoint) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    tools = list(getattr(listed, "tools", []) or [])
                    report["flightpoints"]["endpoint"] = endpoint
                    report["flightpoints"]["tools"] = [jsonable(t) for t in tools]
                    search_tool = next((t for t in tools if "search" in tool_name(t).lower() and "flight" in tool_name(t).lower()), None)
                    if search_tool is None:
                        raise RuntimeError(f"No search-flight tool found. Tools: {[tool_name(t) for t in tools]}")
                    name = tool_name(search_tool)
                    schema = tool_schema(search_tool)
                    report["flightpoints"]["search_tool"] = name
                    report["flightpoints"]["search_schema"] = schema
                    for travel_date in DATES:
                        try:
                            args = build_arguments(schema, travel_date)
                            response = await session.call_tool(name, arguments=args)
                            report["flightpoints"]["by_date"][travel_date] = {
                                "arguments": args,
                                "response": jsonable(response),
                                "texts": extract_texts(response),
                            }
                        except Exception as exc:
                            report["flightpoints"]["by_date"][travel_date] = {
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(),
                            }
                    return
        except Exception as exc:
            last_error = f"{endpoint}: {type(exc).__name__}: {exc}"
            report["errors"].append(f"FlightPoints endpoint failed: {last_error}")
    report["flightpoints"]["fatal_error"] = last_error


async def scan_award_flight_daily(report: dict[str, Any]) -> None:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except Exception as exc:
        report["errors"].append(f"Award Flight Daily import failed: {exc}")
        return

    endpoints = [
        "https://www.awardflightdaily.com/mcp-server/mcp",
        "https://awardflightdaily.com/mcp-server/mcp",
    ]
    args = {
        "params": {
            "origin": ORIGIN,
            "destination": DESTINATION,
            "date_from": START.isoformat(),
            "date_to": END.isoformat(),
            "cabin": "Y",
            "source": "flyingblue,delta",
            "direct_only": False,
            "min_seats": 1,
            "limit": 200,
            "offset": 0,
            "response_format": "json",
        }
    }
    last_error = None
    for endpoint in endpoints:
        try:
            async with streamable_http_client(endpoint) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    tools = list(getattr(listed, "tools", []) or [])
                    report["award_flight_daily"]["endpoint"] = endpoint
                    report["award_flight_daily"]["tools"] = [jsonable(t) for t in tools]
                    target = next((t for t in tools if tool_name(t) == "afd_search_award_flights"), None)
                    if target is None:
                        raise RuntimeError(f"afd_search_award_flights missing. Tools: {[tool_name(t) for t in tools]}")
                    response = await session.call_tool("afd_search_award_flights", arguments=args)
                    report["award_flight_daily"]["arguments"] = args
                    report["award_flight_daily"]["response"] = jsonable(response)
                    report["award_flight_daily"]["texts"] = extract_texts(response)
                    return
        except Exception as exc:
            last_error = f"{endpoint}: {type(exc).__name__}: {exc}"
            report["errors"].append(f"Award Flight Daily endpoint failed: {last_error}")
    report["award_flight_daily"]["fatal_error"] = last_error


def is_skyteam_name(name: str) -> bool:
    n = re.sub(r"\s+", " ", name.lower()).strip()
    if any(marker in n for marker in NON_SKYTEAM_MARKERS):
        return False
    return any(marker in n for marker in SKYTEAM_MARKERS)


def parse_price(price: str) -> float | None:
    if not price:
        return None
    digits = re.sub(r"[^0-9.]", "", price.replace(",", ""))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def scan_cash(report: dict[str, Any]) -> None:
    try:
        from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter
    except Exception as exc:
        report["errors"].append(f"fast-flights import failed: {exc}")
        return

    for travel_date in DATES:
        entry: dict[str, Any] = {"attempts": []}
        report["cash"]["by_date"][travel_date] = entry
        result = None
        for mode in ("common", "local", "fallback"):
            try:
                flt_filter = create_filter(
                    flight_data=[FlightData(date=travel_date, from_airport=ORIGIN, to_airport=DESTINATION)],
                    trip="one-way",
                    passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
                    seat="economy",
                    max_stops=2,
                )
                result = get_flights_from_filter(flt_filter, currency="USD", mode=mode)
                entry["attempts"].append({"mode": mode, "ok": True})
                entry["mode"] = mode
                break
            except Exception as exc:
                entry["attempts"].append({"mode": mode, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        if result is None:
            entry["error"] = "All fast-flights modes failed"
            continue
        flights = [jsonable(f) for f in getattr(result, "flights", [])]
        entry["current_price"] = getattr(result, "current_price", None)
        entry["all_flights"] = flights
        skyteam = [f for f in flights if is_skyteam_name(str(f.get("name", "")))]
        for f in skyteam:
            f["numeric_price"] = parse_price(str(f.get("price", "")))
        skyteam.sort(key=lambda f: (f.get("numeric_price") is None, f.get("numeric_price") or 10**12))
        entry["skyteam_flights"] = skyteam
        entry["best_skyteam"] = skyteam[0] if skyteam else None


def recursively_extract_awards(value: Any, inherited: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    inherited = dict(inherited or {})
    rows: list[dict[str, Any]] = []
    date_keys = {"date", "departure_date", "departureDate", "travel_date", "outbound_date"}
    program_keys = {"program", "program_name", "source", "loyalty_program", "loyaltyProgram"}
    miles_keys = {"miles", "award_cost", "mileage", "mileage_cost", "points", "points_cost", "pointCost"}
    tax_keys = {"taxes", "fees", "tax", "cash", "cash_cost", "surcharges"}
    airline_keys = {"airline", "airline_name", "marketing_airline", "operating_airline", "carrier"}

    if isinstance(value, dict):
        context = dict(inherited)
        for key, val in value.items():
            if key in date_keys and isinstance(val, str):
                context["date"] = val[:10]
            elif key in program_keys and isinstance(val, (str, int)):
                context["program"] = str(val)
            elif key in airline_keys and isinstance(val, (str, int)):
                context["airline"] = str(val)
            elif key in miles_keys and isinstance(val, (str, int, float)):
                context["miles"] = val
            elif key in tax_keys and isinstance(val, (str, int, float)):
                context["taxes"] = val
            elif key in {"cabin", "cabin_class", "travelClass"} and isinstance(val, (str, int)):
                context["cabin"] = str(val)
            elif key in {"flight_number", "flightNumber", "flight_numbers"}:
                context["flight_number"] = val
        if "miles" in context and ("program" in context or "date" in context):
            rows.append(context)
        for val in value.values():
            rows.extend(recursively_extract_awards(val, context))
    elif isinstance(value, list):
        for item in value:
            rows.extend(recursively_extract_awards(item, inherited))
    return rows


def normalize_award_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_name in ("flightpoints", "award_flight_daily"):
        source = report.get(source_name) or {}
        candidates: list[Any] = []
        if source_name == "flightpoints":
            for travel_date, entry in (source.get("by_date") or {}).items():
                candidates.append({"date": travel_date, "payload": entry.get("response")})
                for text in entry.get("texts") or []:
                    parsed = maybe_parse_json(text)
                    candidates.append({"date": travel_date, "payload": parsed if parsed is not None else text})
        else:
            candidates.append(source.get("response"))
            for text in source.get("texts") or []:
                parsed = maybe_parse_json(text)
                candidates.append(parsed if parsed is not None else text)
        for candidate in candidates:
            extracted = recursively_extract_awards(candidate)
            for row in extracted:
                row["source_service"] = source_name
                rows.append(row)

    # Keep requested dates/programs, then de-duplicate.
    filtered = []
    seen = set()
    for row in rows:
        program = str(row.get("program", ""))
        dt = str(row.get("date", ""))[:10]
        if dt and dt not in DATES:
            continue
        if program and not any(marker in program.lower() for marker in PROGRAM_KEEP):
            continue
        key = json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        filtered.append(row)
    return filtered


def build_markdown(report: dict[str, Any]) -> str:
    awards = normalize_award_rows(report)
    report["normalized_awards"] = awards
    lines = [
        "# JED → DTW one-way scan",
        "",
        "SkyTeam-only target; Economy; 1 adult; USD cash; Flying Blue and Delta SkyMiles awards.",
        "",
        "| Date | Best SkyTeam cash | Cash itinerary | Flying Blue | SkyMiles | Source notes |",
        "|---|---:|---|---:|---:|---|",
    ]
    for dt in DATES:
        cash = ((report.get("cash") or {}).get("by_date") or {}).get(dt, {})
        best = cash.get("best_skyteam") or {}
        cash_price = best.get("price") or "—"
        cash_itin = best.get("name") or "—"
        fb = []
        dl = []
        for row in awards:
            if str(row.get("date", ""))[:10] not in ("", dt):
                continue
            p = str(row.get("program", "")).lower()
            val = row.get("miles")
            if "flying" in p:
                fb.append(val)
            if "delta" in p or "skymiles" in p:
                dl.append(val)
        fb_txt = ", ".join(str(x) for x in fb[:3]) if fb else "—"
        dl_txt = ", ".join(str(x) for x in dl[:3]) if dl else "—"
        notes = []
        if cash.get("error"):
            notes.append("cash failed")
        fp_entry = (((report.get("flightpoints") or {}).get("by_date") or {}).get(dt) or {})
        if fp_entry.get("error"):
            notes.append("FlightPoints failed")
        lines.append(f"| {dt} | {cash_price} | {cash_itin} | {fb_txt} | {dl_txt} | {', '.join(notes) or 'ok'} |")
    lines.extend(["", "## Errors", ""])
    if report.get("errors"):
        lines.extend([f"- {e}" for e in report["errors"]])
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


async def main() -> int:
    report: dict[str, Any] = {
        "query": {
            "origin": ORIGIN,
            "destination": DESTINATION,
            "start": START.isoformat(),
            "end": END.isoformat(),
            "dates": DATES,
            "cabin": "economy",
            "passengers": 1,
            "cash_currency": "USD",
            "restrictions": ["SkyTeam-operated", "Flying Blue or Delta SkyMiles awards"],
        },
        "flightpoints": {"by_date": {}},
        "award_flight_daily": {},
        "cash": {"by_date": {}},
        "errors": [],
    }

    # Each source is isolated. One failure never restarts or erases completed work.
    try:
        await scan_flightpoints(report)
    except Exception as exc:
        report["errors"].append(f"Unhandled FlightPoints failure: {type(exc).__name__}: {exc}")
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    try:
        await scan_award_flight_daily(report)
    except Exception as exc:
        report["errors"].append(f"Unhandled Award Flight Daily failure: {type(exc).__name__}: {exc}")
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    try:
        scan_cash(report)
    except Exception as exc:
        report["errors"].append(f"Unhandled cash failure: {type(exc).__name__}: {exc}")
        report["errors"].append(traceback.format_exc())

    markdown = build_markdown(report)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    OUT_MD.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Wrote {OUT} and {OUT_MD}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
