#!/usr/bin/env python3
"""Temporary live fare/award sweep for JED->DTW, 2026-12-25 through 2027-01-05.

Each source and date is isolated so a failure does not discard successful results.
Outputs JSON and CSV files under results/.
"""

from __future__ import annotations

import base64
import csv
import json
import re
import time
import traceback
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

OUT = Path("results")
OUT.mkdir(exist_ok=True)

START = date(2026, 12, 25)
END = date(2027, 1, 5)
DATES = []
d = START
while d <= END:
    DATES.append(d.isoformat())
    d += timedelta(days=1)

# Current SkyTeam members relevant to carrier-prefix validation.
SKYTEAM_IATA = {
    "AR", "AM", "UX", "AF", "CI", "MU", "DL", "GA", "KQ", "KL",
    "KE", "ME", "RO", "SV", "SK", "VN", "VS", "MF",
}

SKYTEAM_ALIASES = {
    "aerolineas argentinas": "AR",
    "aerolíneas argentinas": "AR",
    "aeromexico": "AM",
    "aeroméxico": "AM",
    "air europa": "UX",
    "air france": "AF",
    "china airlines": "CI",
    "china eastern": "MU",
    "delta": "DL",
    "delta air lines": "DL",
    "garuda indonesia": "GA",
    "kenya airways": "KQ",
    "klm": "KL",
    "korean air": "KE",
    "middle east airlines": "ME",
    "mea": "ME",
    "tarom": "RO",
    "saudia": "SV",
    "sas": "SK",
    "scandinavian airlines": "SK",
    "vietnam airlines": "VN",
    "virgin atlantic": "VS",
    "xiamenair": "MF",
    "xiamen air": "MF",
}


def jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def parse_price(value: Any) -> float | None:
    if value is None:
        return None
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", str(value))
    return float(m.group(1).replace(",", "")) if m else None


def skyteam_cash_name(name: str) -> tuple[bool, list[str]]:
    """Accept only itineraries whose displayed carrier list consists of SkyTeam airlines."""
    low = (name or "").strip().lower()
    if not low or "multiple airlines" in low:
        return False, []
    # Google generally separates carrier names with commas or 'and'.
    parts = [p.strip(" .") for p in re.split(r",|\s+and\s+|\s*&\s*", low) if p.strip()]
    codes: list[str] = []
    for part in parts:
        # Remove common operating/marketing prefixes without hiding a carrier name.
        part = re.sub(r"^(operated by|marketed by)\s+", "", part).strip()
        match = None
        for alias, code in sorted(SKYTEAM_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
            if part == alias or part.startswith(alias + " "):
                match = code
                break
        if not match:
            return False, []
        codes.append(match)
    return bool(codes), codes


def run_cash() -> dict[str, Any]:
    from fast_flights import FlightData, Passengers, get_flights

    out: dict[str, Any] = {}
    for travel_date in DATES:
        entry: dict[str, Any] = {"date": travel_date, "status": "pending", "options": []}
        try:
            result = get_flights(
                flight_data=[FlightData(date=travel_date, from_airport="JED", to_airport="DTW")],
                trip="one-way",
                seat="economy",
                passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
                fetch_mode="fallback",
            )
            raw = jsonable(result)
            entry["current_price_signal"] = raw.get("current_price") if isinstance(raw, dict) else None
            flights = raw.get("flights", []) if isinstance(raw, dict) else []
            for f in flights:
                ok, codes = skyteam_cash_name(str(f.get("name", "")))
                if not ok:
                    continue
                option = {
                    "airlines": f.get("name"),
                    "airline_codes": codes,
                    "price_usd": parse_price(f.get("price")),
                    "departure": f.get("departure"),
                    "arrival": f.get("arrival"),
                    "arrival_time_ahead": f.get("arrival_time_ahead"),
                    "duration": f.get("duration"),
                    "stops": f.get("stops"),
                    "is_best": f.get("is_best"),
                }
                entry["options"].append(option)
            entry["options"].sort(key=lambda x: (x["price_usd"] is None, x["price_usd"] or 10**9, x.get("duration") or ""))
            entry["status"] = "ok" if entry["options"] else "no_skyteam_in_parsed_results"
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc(limit=4)
        out[travel_date] = entry
        # Keep successful dates even if a later query fails; write checkpoint every iteration.
        (OUT / "cash_checkpoint.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
        time.sleep(2)
    return out


# Anonymous PointsYeah payload constants, mirrored from its public web client.
KEY_PREFIX = "LefjQ2pEXmiy/nNZvhJ43i8"
KEY_SUFFIX = "YHYbn1hOuAgA="
DEFAULT_KEY_SECTION = "hJuaknzb"
STATIC_IV = b"1020304050607080"
API_BASE = "https://api2.pointsyeah.com"
PY_HEADERS = {
    "content-type": "application/json",
    "origin": "https://www.pointsyeah.com",
    "referer": "https://www.pointsyeah.com/",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/147 Safari/537.36",
}


def encrypt_pointsyeah(plaintext: str) -> str:
    key = base64.b64decode(KEY_PREFIX + DEFAULT_KEY_SECTION + KEY_SUFFIX)
    cipher = AES.new(key, AES.MODE_CBC, iv=STATIC_IV)
    return base64.b64encode(cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))).decode("ascii")


def program_bucket(program: str, code: str) -> str | None:
    p = (program or "").lower()
    c = (code or "").upper()
    if "flying blue" in p or c in {"AF", "KL", "FB"}:
        return "flying_blue"
    if "delta" in p or "skymiles" in p or c == "DL":
        return "skymiles"
    return None


def segment_carrier(flight_number: str) -> str | None:
    m = re.match(r"\s*([A-Z0-9]{2})", (flight_number or "").upper())
    return m.group(1) if m else None


def route_is_skyteam(route: dict[str, Any]) -> tuple[bool, list[str]]:
    codes: list[str] = []
    for seg in route.get("segments") or []:
        code = segment_carrier(str(seg.get("flight_number", "")))
        if not code or code not in SKYTEAM_IATA:
            return False, codes + ([code] if code else [])
        codes.append(code)
    return bool(codes), codes


def merge_program_results(merged: dict[str, Any], results: list[dict[str, Any]]) -> None:
    for item in results:
        key = "|".join([
            str(item.get("program", "")), str(item.get("code", "")), str(item.get("date", "")),
            str(item.get("departure", "")), str(item.get("arrival", "")),
        ])
        existing = merged.get(key)
        if not existing or len(item.get("routes") or []) > len(existing.get("routes") or []):
            merged[key] = item


def pointsyeah_range(start: str, end: str, label: str) -> dict[str, Any]:
    session = requests.Session()
    plain = json.dumps({
        "search_type": "one_way",
        "cabins": ["Economy", "Premium Economy", "Business", "First"],
        "segments": [{
            "arrival": "DTW",
            "departure": "JED",
            "departure_date": {"from": start, "to": end},
        }],
        "passengers_v2": {"adults": 1, "children": 0},
        "source": "mobile",
    }, separators=(",", ":"))
    enc = encrypt_pointsyeah(plain)
    output: dict[str, Any] = {"label": label, "start": start, "end": end, "status": "starting"}
    merged: dict[str, Any] = {}
    try:
        r = session.post(
            f"{API_BASE}/flight/search/create_task",
            headers=PY_HEADERS,
            json={"data": enc, "encrypted": enc},
            timeout=45,
        )
        output["create_http"] = r.status_code
        output["create_body_preview"] = r.text[:1000]
        r.raise_for_status()
        created = r.json()
        if not created.get("success"):
            raise RuntimeError(f"create_task failed: {created}")
        task_id = created["data"]["task_id"]
        output["task_id"] = task_id
        deadline = time.time() + 240
        polls = 0
        terminal = None
        while time.time() < deadline:
            polls += 1
            pr = session.post(
                f"{API_BASE}/flight/search/fetch_result",
                headers=PY_HEADERS,
                json={"task_id": task_id},
                timeout=45,
            )
            pr.raise_for_status()
            snap = pr.json()
            data = snap.get("data") or {}
            results = data.get("result") or []
            if isinstance(results, list):
                merge_program_results(merged, results)
            terminal = str(data.get("status", "")).lower()
            output["last_status"] = terminal
            output["polls"] = polls
            output["program_result_count"] = len(merged)
            output["raw_results"] = list(merged.values())
            (OUT / f"points_{label}_checkpoint.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
            if terminal in {"done", "completed"}:
                break
            time.sleep(0.25)
        output["status"] = "ok" if merged else ("empty" if terminal in {"done", "completed"} else "timeout_or_empty")
    except Exception as exc:
        output["status"] = "error"
        output["error"] = f"{type(exc).__name__}: {exc}"
        output["traceback"] = traceback.format_exc(limit=6)
    output["raw_results"] = list(merged.values())
    return output


def filter_awards(range_outputs: list[dict[str, Any]]) -> dict[str, Any]:
    by_date: dict[str, Any] = {
        d: {"flying_blue": [], "skymiles": []} for d in DATES
    }
    for range_out in range_outputs:
        for result in range_out.get("raw_results") or []:
            bucket = program_bucket(str(result.get("program", "")), str(result.get("code", "")))
            travel_date = str(result.get("date", ""))[:10]
            if not bucket or travel_date not in by_date:
                continue
            for route in result.get("routes") or []:
                sky_ok, carrier_codes = route_is_skyteam(route)
                if not sky_ok:
                    continue
                payment = route.get("payment") or {}
                normalized = {
                    "program": result.get("program"),
                    "program_code": result.get("code"),
                    "miles": payment.get("miles"),
                    "tax_usd": payment.get("tax"),
                    "cabin": payment.get("cabin"),
                    "seats": payment.get("seats"),
                    "cash_price_field": payment.get("cash_price"),
                    "duration_minutes": route.get("duration"),
                    "carrier_codes": carrier_codes,
                    "segments": route.get("segments") or [],
                    "booking_code": (route.get("extra") or {}).get("booking_code"),
                    "url": route.get("url"),
                }
                by_date[travel_date][bucket].append(normalized)
    for travel_date in by_date:
        for bucket in ("flying_blue", "skymiles"):
            by_date[travel_date][bucket].sort(key=lambda x: (
                x.get("miles") is None,
                x.get("miles") if isinstance(x.get("miles"), (int, float)) else 10**12,
                x.get("tax_usd") if isinstance(x.get("tax_usd"), (int, float)) else 10**9,
                x.get("duration_minutes") if isinstance(x.get("duration_minutes"), (int, float)) else 10**9,
            ))
    return by_date


def write_combined(cash: dict[str, Any], awards: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    for travel_date in DATES:
        cash_opts = cash.get(travel_date, {}).get("options") or []
        fb = awards.get(travel_date, {}).get("flying_blue") or []
        dl = awards.get(travel_date, {}).get("skymiles") or []
        c = cash_opts[0] if cash_opts else {}
        f = fb[0] if fb else {}
        s = dl[0] if dl else {}
        rows.append({
            "date": travel_date,
            "cash_status": cash.get(travel_date, {}).get("status"),
            "cash_usd": c.get("price_usd"),
            "cash_airlines": c.get("airlines"),
            "cash_duration": c.get("duration"),
            "cash_stops": c.get("stops"),
            "flying_blue_miles": f.get("miles"),
            "flying_blue_tax_usd": f.get("tax_usd"),
            "flying_blue_cabin": f.get("cabin"),
            "flying_blue_carriers": "+".join(f.get("carrier_codes") or []),
            "flying_blue_duration_min": f.get("duration_minutes"),
            "skymiles": s.get("miles"),
            "skymiles_tax_usd": s.get("tax_usd"),
            "skymiles_cabin": s.get("cabin"),
            "skymiles_carriers": "+".join(s.get("carrier_codes") or []),
            "skymiles_duration_min": s.get("duration_minutes"),
        })
    with (OUT / "combined.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "combined.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))


def main() -> None:
    cash = run_cash()
    (OUT / "cash.json").write_text(json.dumps(cash, indent=2, ensure_ascii=False))

    # Requested two batches, independently checkpointed.
    p1 = pointsyeah_range("2026-12-25", "2026-12-30", "dec25_30")
    (OUT / "points_dec25_30.json").write_text(json.dumps(p1, indent=2, ensure_ascii=False))
    p2 = pointsyeah_range("2026-12-31", "2027-01-05", "dec31_jan5")
    (OUT / "points_dec31_jan5.json").write_text(json.dumps(p2, indent=2, ensure_ascii=False))

    awards = filter_awards([p1, p2])
    (OUT / "awards_filtered.json").write_text(json.dumps(awards, indent=2, ensure_ascii=False))
    write_combined(cash, awards)

    status = {
        "dates": DATES,
        "cash_ok_dates": [d for d, v in cash.items() if v.get("status") == "ok"],
        "cash_failed_or_empty": {d: v.get("status") for d, v in cash.items() if v.get("status") != "ok"},
        "award_batches": {"dec25_30": p1.get("status"), "dec31_jan5": p2.get("status")},
    }
    (OUT / "status.json").write_text(json.dumps(status, indent=2))
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
