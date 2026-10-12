#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ORIGIN = "JED"
DESTINATION = "DTW"
START = date(2026, 12, 25)
END = date(2027, 1, 5)
DATES: list[str] = []
d = START
while d <= END:
    DATES.append(d.isoformat())
    d += timedelta(days=1)

OUT = Path("tmp_jed_dtw_results_v2.json")
OUT_MD = Path("tmp_jed_dtw_results_v2.md")

SKYTEAM = [
    "delta", "air france", "klm", "saudia", "saudi arabian", "middle east airlines",
    "mea", "virgin atlantic", "aeromexico", "aeroméxico", "sas", "scandinavian airlines",
    "korean air", "china airlines", "china eastern", "xiamenair", "xiamen air",
    "garuda indonesia", "vietnam airlines", "kenya airways", "tarom", "air europa",
    "aerolineas argentinas", "aerolíneas argentinas",
]
NOT_SKYTEAM = [
    "turkish", "qatar", "etihad", "emirates", "united", "american airlines",
    "british airways", "lufthansa", "swiss", "austrian", "air canada", "royal jordanian",
    "oman air", "egyptair", "wizz", "flyadeal", "flynas", "air cairo", "pegasus",
    "kuwait airways", "gulf air", "ita airways",
]


def js(x: Any) -> Any:
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    if dataclasses.is_dataclass(x):
        return {k: js(v) for k, v in dataclasses.asdict(x).items()}
    if isinstance(x, dict):
        return {str(k): js(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [js(v) for v in x]
    if hasattr(x, "model_dump"):
        try:
            return js(x.model_dump(mode="json", by_alias=True))
        except Exception:
            return js(x.model_dump())
    if hasattr(x, "__dict__"):
        return {k: js(v) for k, v in vars(x).items() if not k.startswith("_")}
    return str(x)


def texts(x: Any) -> list[str]:
    obj = js(x)
    out: list[str] = []
    def walk(v: Any) -> None:
        if isinstance(v, dict):
            if isinstance(v.get("text"), str):
                out.append(v["text"])
            for z in v.values():
                walk(z)
        elif isinstance(v, list):
            for z in v:
                walk(z)
    walk(obj)
    return out


def parse_price(s: str) -> float | None:
    raw = re.sub(r"[^0-9.]", "", (s or "").replace(",", ""))
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def is_skyteam(name: str) -> bool:
    n = re.sub(r"\s+", " ", (name or "").lower()).strip()
    if any(bad in n for bad in NOT_SKYTEAM):
        return False
    return any(ok in n for ok in SKYTEAM)


async def call_flightpoints_batch(center_date: str, delta: int) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    endpoint_errors: list[str] = []
    for endpoint in ("https://mcp.flightpoints.com/mcp", "https://mcpv1.flightpoints.com/mcp"):
        try:
            async with streamable_http_client(endpoint) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    args = {
                        "origin": ORIGIN,
                        "destination": DESTINATION,
                        "departure_date": center_date,
                        "passengers": 1,
                        "cabin_class": "economy",
                        "delta": delta,
                        "minimum_seats": 1,
                        "only_direct": False,
                        "alliances": "SkyTeam",
                    }
                    response = await session.call_tool("search-flights", arguments=args)
                    snapshots = [js(response)]
                    obj = snapshots[-1]
                    sc = obj.get("structuredContent") or {}
                    key = sc.get("search_key")
                    complete = bool(sc.get("is_complete")) or str(sc.get("status", "")).upper() in {"COMPLETED", "DONE"}
                    # Poll the same search rather than starting over.
                    for _ in range(12):
                        if complete or not key:
                            break
                        await asyncio.sleep(5)
                        response = await session.call_tool("search-flights", arguments={"search_key": key})
                        snapshots.append(js(response))
                        obj = snapshots[-1]
                        sc = obj.get("structuredContent") or {}
                        complete = bool(sc.get("is_complete")) or str(sc.get("status", "")).upper() in {"COMPLETED", "DONE"}
                    return {
                        "endpoint": endpoint,
                        "arguments": args,
                        "snapshots": snapshots,
                        "final": snapshots[-1],
                        "texts": texts(snapshots[-1]),
                        "endpoint_errors": endpoint_errors,
                    }
        except Exception as exc:
            endpoint_errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
    return {"error": "Both FlightPoints endpoints failed", "endpoint_errors": endpoint_errors}


async def scan_flightpoints(report: dict[str, Any]) -> None:
    # Batch 1 covers Dec 25-31. Batch 2 covers Jan 1-5. The enforced pause avoids
    # FlightPoints' one-search-at-a-time throttle while preserving completed batch 1.
    batches = [
        {"label": "2026-12-25_to_2026-12-31", "center": "2026-12-28", "delta": 3},
        {"label": "2027-01-01_to_2027-01-05", "center": "2027-01-03", "delta": 2},
    ]
    for idx, spec in enumerate(batches):
        if idx:
            await asyncio.sleep(35)
        try:
            report["flightpoints"][spec["label"]] = await call_flightpoints_batch(spec["center"], spec["delta"])
        except Exception as exc:
            report["flightpoints"][spec["label"]] = {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def scan_cash(report: dict[str, Any]) -> None:
    from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter

    for dt in DATES:
        entry: dict[str, Any] = {"attempts": []}
        report["cash"][dt] = entry
        result = None
        for mode in ("common", "local", "fallback"):
            try:
                filt = create_filter(
                    flight_data=[FlightData(date=dt, from_airport=ORIGIN, to_airport=DESTINATION)],
                    trip="one-way",
                    passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
                    seat="economy",
                    max_stops=2,
                )
                result = get_flights_from_filter(filt, currency="USD", mode=mode)
                entry["attempts"].append({"mode": mode, "ok": True})
                entry["mode"] = mode
                break
            except Exception as exc:
                entry["attempts"].append({"mode": mode, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        if result is None:
            entry["error"] = "All cash modes failed"
            continue
        flights = [js(f) for f in getattr(result, "flights", [])]
        for f in flights:
            f["numeric_price"] = parse_price(str(f.get("price", "")))
            f["skyteam"] = is_skyteam(str(f.get("name", "")))
        sky = [f for f in flights if f["skyteam"]]
        sky.sort(key=lambda f: (f.get("numeric_price") is None, f.get("numeric_price") or 10**12))
        entry["current_price"] = getattr(result, "current_price", None)
        entry["all_flights"] = flights
        entry["skyteam_flights"] = sky
        entry["best_skyteam"] = sky[0] if sky else None
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def get_fp_flights(report: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for batch, payload in (report.get("flightpoints") or {}).items():
        final = (payload or {}).get("final") or {}
        sc = final.get("structuredContent") or {}
        for f in sc.get("flights") or []:
            if isinstance(f, dict):
                row = dict(f)
                row["batch"] = batch
                found.append(row)
    return found


def pick(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return None


def normalize_fp(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in get_fp_flights(report):
        # Keep raw fields and add common aliases used in the final table.
        row = {
            "date": pick(raw, "date", "departure_date", "departureDate", "travel_date"),
            "program": pick(raw, "program", "programme", "program_name", "loyalty_program", "source"),
            "miles": pick(raw, "miles", "points", "award_cost", "mileage", "point_cost"),
            "fees": pick(raw, "fees", "taxes", "tax", "cash", "cash_cost"),
            "airline": pick(raw, "airline", "airline_name", "operating_airline", "carrier"),
            "route": pick(raw, "route", "flight_number", "flight_numbers", "itinerary"),
            "raw": raw,
        }
        rows.append(row)
    report["normalized_awards"] = rows
    return rows


def render(report: dict[str, Any]) -> str:
    awards = normalize_fp(report)
    lines = [
        "# JED → DTW: Dec 25, 2026 through Jan 5, 2027",
        "",
        "One-way, Economy, one passenger. Cash fares from Google Flights; award data from FlightPoints. SkyTeam only.",
        "",
        "| Date | Cheapest SkyTeam cash | Cash airline(s) | Flying Blue | Delta SkyMiles |",
        "|---|---:|---|---:|---:|",
    ]
    for dt in DATES:
        c = (report.get("cash") or {}).get(dt) or {}
        best = c.get("best_skyteam") or {}
        fb: list[str] = []
        dl: list[str] = []
        for a in awards:
            adt = str(a.get("date") or "")[:10]
            if adt and adt != dt:
                continue
            p = str(a.get("program") or "").lower()
            value = a.get("miles")
            fees = a.get("fees")
            label = str(value) + (f" + {fees}" if fees not in (None, "") else "")
            if "flying" in p or "air france" in p or "klm" in p:
                fb.append(label)
            if "delta" in p or "skymiles" in p:
                dl.append(label)
        lines.append(
            f"| {dt} | {best.get('price') or '—'} | {best.get('name') or '—'} | "
            f"{', '.join(fb[:3]) or '—'} | {', '.join(dl[:3]) or '—'} |"
        )
    lines.append("")
    lines.append("## Source failures preserved without deleting completed work")
    errors = report.get("errors") or []
    if errors:
        lines.extend(f"- {e}" for e in errors)
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


async def main() -> None:
    report: dict[str, Any] = {
        "query": {"origin": ORIGIN, "destination": DESTINATION, "dates": DATES, "cabin": "economy", "passengers": 1},
        "flightpoints": {},
        "cash": {},
        "errors": [],
    }
    try:
        await scan_flightpoints(report)
    except Exception as exc:
        report["errors"].append(f"FlightPoints unhandled: {type(exc).__name__}: {exc}")
        report["errors"].append(traceback.format_exc())
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    try:
        scan_cash(report)
    except Exception as exc:
        report["errors"].append(f"Cash unhandled: {type(exc).__name__}: {exc}")
        report["errors"].append(traceback.format_exc())

    md = render(report)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    print(md)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
