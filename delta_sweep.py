#!/usr/bin/env python3
"""Run the proven Delta guest GraphQL scraper for JED->DTW, date by date."""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, "/tmp/points-pilot-jobs")

from scrapers.delta import DeltaScraper  # noqa: E402

OUT = Path("results")
OUT.mkdir(exist_ok=True)

START = date(2026, 12, 25)
END = date(2027, 1, 5)
DATES: list[date] = []
d = START
while d <= END:
    DATES.append(d)
    d += timedelta(days=1)

SKYTEAM = {"AR", "AM", "UX", "AF", "CI", "MU", "DL", "GA", "KQ", "KL", "KE", "ME", "RO", "SV", "SK", "VN", "VS", "MF"}


def enc(v: Any) -> Any:
    if isinstance(v, (date,)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass
    return v


def carrier_codes(raw_flight_number: str | None) -> list[str]:
    if not raw_flight_number:
        return []
    out = []
    for part in raw_flight_number.split("+"):
        code = part.strip().split(" ", 1)[0].upper()
        if len(code) == 2:
            out.append(code)
    return out


def main() -> None:
    scraper = DeltaScraper()
    output: dict[str, Any] = {}
    try:
        for travel_date in DATES:
            key = travel_date.isoformat()
            entry: dict[str, Any] = {"date": key, "status": "pending", "options": []}
            try:
                records = scraper.scrape("JED", "DTW", travel_date)
                for record in records:
                    item = asdict(record)
                    codes = carrier_codes(item.get("raw_flight_number"))
                    item["marketing_carrier_codes"] = codes
                    item["all_marketing_codes_skyteam"] = bool(codes) and all(c in SKYTEAM for c in codes)
                    item = {k: enc(v) for k, v in item.items()}
                    entry["options"].append(item)
                entry["options"].sort(key=lambda x: (
                    x.get("cabin_class") != "economy",
                    x.get("points_cost") or 10**12,
                    x.get("cash_cost") or 10**9,
                    x.get("duration_minutes") or 10**9,
                ))
                entry["status"] = "ok" if entry["options"] else "no_results"
            except Exception as exc:
                entry["status"] = "error"
                entry["error"] = f"{type(exc).__name__}: {exc}"
                entry["traceback"] = traceback.format_exc(limit=8)
            output[key] = entry
            (OUT / "delta_skymiles_checkpoint.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    finally:
        scraper.close()

    (OUT / "delta_skymiles.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    summary = {
        "ok_dates": [d for d, v in output.items() if v.get("status") == "ok"],
        "no_results": [d for d, v in output.items() if v.get("status") == "no_results"],
        "errors": {d: v.get("error") for d, v in output.items() if v.get("status") == "error"},
        "cheapest_economy": {
            d: next(({
                "miles": o.get("points_cost"),
                "tax_usd": o.get("cash_cost"),
                "flight_numbers": o.get("raw_flight_number"),
                "stops": o.get("stops"),
                "duration_minutes": o.get("duration_minutes"),
            } for o in v.get("options", []) if o.get("cabin_class") == "economy"), None)
            for d, v in output.items()
        },
    }
    (OUT / "delta_skymiles_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
