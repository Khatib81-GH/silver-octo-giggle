#!/usr/bin/env python3
"""Second-pass JED->DTW sweep using fast-flights v3 and isolated award batches."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from fare_sweep import (
    DATES,
    OUT,
    SKYTEAM_IATA,
    filter_awards,
    pointsyeah_range,
    write_combined,
)

OUT = Path(OUT)
OUT.mkdir(exist_ok=True)


def fmt_dt(dt: Any) -> str | None:
    try:
        y, m, d = dt.date
        hh, mm = dt.time
        return f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}"
    except Exception:
        return None


def run_cash_v3() -> dict[str, Any]:
    from fast_flights import FlightQuery, Passengers, create_query, get_flights

    output: dict[str, Any] = {}
    for travel_date in DATES:
        entry: dict[str, Any] = {"date": travel_date, "status": "pending", "options": []}
        try:
            query = create_query(
                flights=[
                    FlightQuery(
                        date=travel_date,
                        from_airport="JED",
                        to_airport="DTW",
                        max_stops=2,
                        airlines=["SKYTEAM"],
                    )
                ],
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
                if not codes or any(code not in SKYTEAM_IATA for code in codes):
                    continue
                if itinerary.price is None:
                    continue
                segments = []
                for seg in itinerary.flights:
                    segments.append({
                        "from": seg.from_airport.code,
                        "to": seg.to_airport.code,
                        "departure_local": fmt_dt(seg.departure),
                        "arrival_local": fmt_dt(seg.arrival),
                        "duration_minutes": seg.duration,
                        "plane_type": seg.plane_type,
                    })
                entry["options"].append({
                    "price_usd": itinerary.price,
                    "airline_codes": codes,
                    "airlines": [airline_names.get(code, code) for code in codes],
                    "stops": max(0, len(segments) - 1),
                    "air_minutes": sum((s.get("duration_minutes") or 0) for s in segments),
                    "departure_local": segments[0]["departure_local"] if segments else None,
                    "arrival_local": segments[-1]["arrival_local"] if segments else None,
                    "segments": segments,
                    "google_type": itinerary.type,
                })
            entry["options"].sort(key=lambda x: (x["price_usd"], x["stops"], x["air_minutes"]))
            entry["status"] = "ok" if entry["options"] else "no_skyteam_results"
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc(limit=6)
        output[travel_date] = entry
        (OUT / "cash_checkpoint.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    return output


def failed_cash(exc: Exception) -> dict[str, Any]:
    return {
        d: {
            "date": d,
            "status": "cash_source_fatal_error",
            "options": [],
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }
        for d in DATES
    }


def main() -> None:
    try:
        cash = run_cash_v3()
    except Exception as exc:
        cash = failed_cash(exc)
    (OUT / "cash.json").write_text(json.dumps(cash, indent=2, ensure_ascii=False))

    # Requested split: each award batch survives failure of the other.
    try:
        p1 = pointsyeah_range("2026-12-25", "2026-12-30", "dec25_30")
    except Exception as exc:
        p1 = {"label": "dec25_30", "status": "fatal_error", "error": f"{type(exc).__name__}: {exc}"}
    (OUT / "points_dec25_30.json").write_text(json.dumps(p1, indent=2, ensure_ascii=False))

    try:
        p2 = pointsyeah_range("2026-12-31", "2027-01-05", "dec31_jan5")
    except Exception as exc:
        p2 = {"label": "dec31_jan5", "status": "fatal_error", "error": f"{type(exc).__name__}: {exc}"}
    (OUT / "points_dec31_jan5.json").write_text(json.dumps(p2, indent=2, ensure_ascii=False))

    awards = filter_awards([p1, p2])
    (OUT / "awards_filtered.json").write_text(json.dumps(awards, indent=2, ensure_ascii=False))
    write_combined(cash, awards)

    status = {
        "dates": DATES,
        "cash_ok_dates": [d for d, v in cash.items() if v.get("status") == "ok"],
        "cash_other": {d: v.get("status") for d, v in cash.items() if v.get("status") != "ok"},
        "award_batches": {"dec25_30": p1.get("status"), "dec31_jan5": p2.get("status")},
        "flying_blue_dates": [d for d, v in awards.items() if v.get("flying_blue")],
        "skymiles_dates": [d for d, v in awards.items() if v.get("skymiles")],
    }
    (OUT / "status.json").write_text(json.dumps(status, indent=2))
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
