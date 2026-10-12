#!/usr/bin/env python3

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from fare_sweep import DATES, OUT, SKYTEAM_IATA

OUT = Path(OUT)
OUT.mkdir(exist_ok=True)


def fmt_dt(dt: Any) -> str | None:
    try:
        y, m, d = dt.date
        hh, mm = dt.time
        return f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}"
    except Exception:
        return None


def main() -> None:
    from fast_flights import FlightQuery, Passengers, create_query, get_flights

    output: dict[str, Any] = {}
    for travel_date in DATES:
        entry: dict[str, Any] = {"date": travel_date, "status": "pending", "options": []}
        try:
            query = create_query(
                flights=[FlightQuery(
                    date=travel_date,
                    from_airport="JED",
                    to_airport="DTW",
                    max_stops=2,
                    airlines=["SKYTEAM"],
                )],
                seat="economy",
                trip="one-way",
                passengers=Passengers(adults=1),
                language="en-US",
                currency="USD",
                hide_separate_and_self_transfer=True,
                exclude_basic_economy=True,
            )
            result = get_flights(query)
            airline_names = {a.code: a.name for a in result.metadata.airlines}
            entry["metadata_airlines"] = airline_names
            for itinerary in result:
                codes = [str(c).upper() for c in (itinerary.airlines or [])]
                if itinerary.price is None:
                    continue
                segments = [{
                    "from": seg.from_airport.code,
                    "to": seg.to_airport.code,
                    "departure_local": fmt_dt(seg.departure),
                    "arrival_local": fmt_dt(seg.arrival),
                    "duration_minutes": seg.duration,
                    "plane_type": seg.plane_type,
                } for seg in itinerary.flights]
                entry["options"].append({
                    "price_usd": itinerary.price,
                    "raw_airline_codes": codes,
                    "airlines": [airline_names.get(code, code) for code in codes],
                    "verified_codes_all_skyteam": bool(codes) and all(code in SKYTEAM_IATA for code in codes),
                    "stops": max(0, len(segments) - 1),
                    "air_minutes": sum((s.get("duration_minutes") or 0) for s in segments),
                    "departure_local": segments[0]["departure_local"] if segments else None,
                    "arrival_local": segments[-1]["arrival_local"] if segments else None,
                    "segments": segments,
                    "google_type": itinerary.type,
                })
            entry["options"].sort(key=lambda x: (x["price_usd"], x["stops"], x["air_minutes"]))
            entry["status"] = "ok" if entry["options"] else "empty"
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc(limit=6)
        output[travel_date] = entry
        (OUT / "cash_checkpoint.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))

    (OUT / "cash.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    status = {
        "ok_dates": [d for d, v in output.items() if v.get("status") == "ok"],
        "other": {d: v.get("status") for d, v in output.items() if v.get("status") != "ok"},
        "non_skyteam_codes_seen": sorted({
            c
            for v in output.values()
            for o in v.get("options", [])
            for c in o.get("raw_airline_codes", [])
            if c not in SKYTEAM_IATA
        }),
    }
    (OUT / "cash_status.json").write_text(json.dumps(status, indent=2))
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
