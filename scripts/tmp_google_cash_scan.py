#!/usr/bin/env python3
from __future__ import annotations

import dataclasses
import json
import re
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fast_flights import FlightData, Passengers, get_flights

ORIGIN = "JED"
DESTINATION = "DTW"
START = date(2026, 12, 25)
END = date(2027, 1, 5)
OUT = Path("tmp_google_cash_results.json")

SKYTEAM = [
    "delta", "air france", "klm", "saudia", "saudi arabian", "middle east airlines",
    "mea", "virgin atlantic", "aeromexico", "aeroméxico", "sas", "scandinavian airlines",
    "korean air", "china airlines", "china eastern", "xiamenair", "xiamen air",
    "garuda indonesia", "vietnam airlines", "kenya airways", "tarom", "air europa",
    "aerolineas argentinas", "aerolíneas argentinas",
]
NON_SKYTEAM = [
    "turkish", "qatar", "etihad", "emirates", "united", "american airlines",
    "british airways", "lufthansa", "swiss", "austrian", "air canada", "royal jordanian",
    "oman air", "egyptair", "wizz", "flyadeal", "flynas", "air cairo", "pegasus",
    "kuwait airways", "gulf air", "ita airways",
]


def jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if dataclasses.is_dataclass(v):
        return {k: jsonable(x) for k, x in dataclasses.asdict(v).items()}
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if hasattr(v, "__dict__"):
        return {k: jsonable(x) for k, x in vars(v).items() if not k.startswith("_")}
    return str(v)


def price_number(s: str) -> float | None:
    x = re.sub(r"[^0-9.]", "", (s or "").replace(",", ""))
    try:
        return float(x) if x else None
    except ValueError:
        return None


def skyteam_name(name: str) -> bool:
    n = re.sub(r"\s+", " ", (name or "").lower()).strip()
    if any(x in n for x in NON_SKYTEAM):
        return False
    return any(x in n for x in SKYTEAM)


def dates() -> list[str]:
    out: list[str] = []
    d = START
    while d <= END:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def save(report: dict[str, Any]) -> None:
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> None:
    report: dict[str, Any] = {
        "source": "Google Flights via fast-flights local Playwright",
        "query": {"origin": ORIGIN, "destination": DESTINATION, "cabin": "economy", "currency": "USD"},
        "by_date": {},
    }
    save(report)

    for dt in dates():
        entry: dict[str, Any] = {}
        report["by_date"][dt] = entry
        try:
            result = get_flights(
                flight_data=[FlightData(date=dt, from_airport=ORIGIN, to_airport=DESTINATION)],
                trip="one-way",
                seat="economy",
                passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
                fetch_mode="local",
                max_stops=2,
            )
            flights = [jsonable(f) for f in result.flights]
            for flight in flights:
                flight["numeric_price"] = price_number(str(flight.get("price", "")))
                flight["skyteam"] = skyteam_name(str(flight.get("name", "")))
            sky = [f for f in flights if f.get("skyteam")]
            sky.sort(key=lambda f: (f.get("numeric_price") is None, f.get("numeric_price") or 10**12))
            entry.update({
                "current_price": result.current_price,
                "all_flights": flights,
                "skyteam_flights": sky,
                "best_skyteam": sky[0] if sky else None,
            })
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc()
        save(report)

    print(json.dumps({
        dt: {
            "error": entry.get("error"),
            "best_skyteam": entry.get("best_skyteam"),
            "all_names": [f.get("name") for f in entry.get("all_flights", [])],
        }
        for dt, entry in report["by_date"].items()
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
