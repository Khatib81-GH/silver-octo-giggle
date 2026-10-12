#!/usr/bin/env python3
"""Temporary JED→DTW SkyTeam cash + award sweep.

Searches two independent date batches so a source/batch failure does not erase
successful work. Cash data comes from Google Flights through fast-flights.
Award data comes from the public/anonymous PointsYeah search endpoint and is
filtered to Flying Blue and Delta SkyMiles plus all-SkyTeam itineraries.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import traceback
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

OUT_DIR = Path("results")
OUT_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_PATH = OUT_DIR / "jed_dtw_sweep_checkpoint.json"
RESULT_PATH = OUT_DIR / "jed_dtw_skyteam_2026-12-25_to_2027-01-05.json"
MARKDOWN_PATH = OUT_DIR / "jed_dtw_skyteam_2026-12-25_to_2027-01-05.md"

DATE_BATCHES = [
    ("2026-12-25", "2026-12-30"),
    ("2026-12-31", "2027-01-05"),
]

# Current SkyTeam airlines relevant to filtering Google Flights and award legs.
SKYTEAM_CODES = {
    "AR", "AM", "UX", "AF", "CI", "MU", "DL", "GA", "KQ", "KL",
    "KE", "ME", "SV", "SK", "RO", "VN", "VS", "MF",
}
SKYTEAM_NAMES = {
    "aerolineas argentinas", "aerolíneas argentinas", "aeromexico", "aeroméxico",
    "air europa", "air france", "china airlines", "china eastern", "delta",
    "delta air lines", "garuda indonesia", "kenya airways", "klm",
    "klm royal dutch airlines", "korean air", "middle east airlines", "mea",
    "saudia", "saudi arabian airlines", "sas", "scandinavian airlines",
    "tarom", "vietnam airlines", "virgin atlantic", "xiamenair", "xiamen air",
}

# PointsYeah public web-client constants. These are embedded in its public JS client.
KEY_PREFIX = "LefjQ2pEXmiy/nNZvhJ43i8"
KEY_SUFFIX = "YHYbn1hOuAgA="
DEFAULT_KEY_SECTION = "hJuaknzb"
STATIC_IV = b"1020304050607080"
POINTSYEAH_API = "https://api2.pointsyeah.com"
BROWSER_HEADERS = {
    "content-type": "application/json",
    "origin": "https://www.pointsyeah.com",
    "referer": "https://www.pointsyeah.com/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154 Safari/537.36"
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def daterange(start: str, end: str) -> list[str]:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    out: list[str] = []
    while s <= e:
        out.append(s.isoformat())
        s += timedelta(days=1)
    return out


ALL_DATES = [d for batch in DATE_BATCHES for d in daterange(*batch)]


def load_checkpoint() -> dict[str, Any]:
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text())
        except Exception:
            pass
    return {
        "generated_at": utc_now(),
        "cash": {},
        "awards": {},
        "errors": {"cash": {}, "awards": {}},
        "metadata": {},
    }


def save_checkpoint(state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    CHECKPOINT_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def normalize_airline_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def is_skyteam_cash_name(name: str) -> bool:
    """Google Flights normally returns comma-separated operating airlines."""
    raw = normalize_airline_name(name)
    if not raw or "multiple airlines" in raw:
        return False
    pieces = [
        normalize_airline_name(p)
        for p in re.split(r",|\s+&\s+|\s+/\s+", raw)
        if p.strip()
    ]
    if not pieces:
        return False
    return all(piece in SKYTEAM_NAMES for piece in pieces)


def price_number(value: Any) -> float | None:
    if value is None:
        return None
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", str(value))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def serialize_obj(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict") and callable(obj.dict):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {"raw": str(obj)}


def search_cash_date(day: str) -> dict[str, Any]:
    from fast_flights import FlightData, Passengers
    from fast_flights.core import get_flights_from_filter
    from fast_flights.filter import TFSData

    filt = TFSData.from_interface(
        flight_data=[FlightData(date=day, from_airport="JED", to_airport="DTW")],
        trip="one-way",
        passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
        seat="economy",
        max_stops=None,
    )

    errors: list[str] = []
    result = None
    for mode in ("local", "fallback", "common"):
        try:
            result = get_flights_from_filter(filt, currency="USD", mode=mode)
            break
        except Exception as exc:  # preserve failure and continue to fallback
            errors.append(f"{mode}: {type(exc).__name__}: {exc}")

    if result is None:
        raise RuntimeError(" | ".join(errors))

    all_options: list[dict[str, Any]] = []
    skyteam_options: list[dict[str, Any]] = []
    for flight in result.flights:
        raw = serialize_obj(flight)
        item = {
            "airlines": str(raw.get("name", "")),
            "price_text": str(raw.get("price", "")),
            "price_usd": price_number(raw.get("price")),
            "departure": raw.get("departure"),
            "arrival": raw.get("arrival"),
            "arrival_time_ahead": raw.get("arrival_time_ahead"),
            "duration": raw.get("duration"),
            "stops": raw.get("stops"),
            "is_best": raw.get("is_best"),
            "delay": raw.get("delay"),
        }
        all_options.append(item)
        if is_skyteam_cash_name(item["airlines"]):
            skyteam_options.append(item)

    skyteam_options.sort(
        key=lambda x: (x["price_usd"] is None, x["price_usd"] or 10**12, x.get("stops") or 99)
    )
    return {
        "source": "Google Flights via fast-flights",
        "date": day,
        "current_price_signal": getattr(result, "current_price", None),
        "skyteam_options": skyteam_options,
        "all_result_count": len(all_options),
        "search_errors_before_success": errors,
    }


def build_key(section: str = DEFAULT_KEY_SECTION) -> bytes:
    return base64.b64decode(KEY_PREFIX + section + KEY_SUFFIX)


def encrypt_payload(plaintext: str, section: str = DEFAULT_KEY_SECTION) -> str:
    cipher = AES.new(build_key(section), AES.MODE_CBC, STATIC_IV)
    encrypted = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("ascii")


def pointsyeah_search(start: str, end: str) -> list[dict[str, Any]]:
    plaintext = json.dumps(
        {
            "search_type": "one_way",
            "cabins": ["Economy"],
            "segments": [
                {
                    "arrival": "DTW",
                    "departure": "JED",
                    "departure_date": {"from": start, "to": end},
                }
            ],
            "passengers_v2": {"adults": 1, "children": 0},
            "source": "mobile",
        },
        separators=(",", ":"),
    )
    encrypted = encrypt_payload(plaintext)
    create = requests.post(
        f"{POINTSYEAH_API}/flight/search/create_task",
        headers=BROWSER_HEADERS,
        json={"data": encrypted, "encrypted": encrypted},
        timeout=45,
    )
    create.raise_for_status()
    created = create.json()
    if not created.get("success"):
        raise RuntimeError(f"create_task failed: {created}")
    task_id = created["data"]["task_id"]

    merged: dict[str, dict[str, Any]] = {}
    deadline = time.time() + 150
    last_status = ""
    while time.time() < deadline:
        res = requests.post(
            f"{POINTSYEAH_API}/flight/search/fetch_result",
            headers=BROWSER_HEADERS,
            json={"task_id": task_id},
            timeout=45,
        )
        res.raise_for_status()
        snap = res.json()
        if snap.get("success"):
            payload = snap.get("data") or {}
            last_status = str(payload.get("status", ""))
            for program_result in payload.get("result") or []:
                key = "|".join(
                    str(program_result.get(k, ""))
                    for k in ("code", "date", "departure", "arrival")
                )
                existing = merged.get(key)
                if existing is None or len(program_result.get("routes") or []) > len(existing.get("routes") or []):
                    merged[key] = program_result
            if last_status.lower() in {"done", "completed"}:
                break
        time.sleep(0.3)
    else:
        raise TimeoutError(f"PointsYeah polling timed out; last_status={last_status}")

    return list(merged.values())


def segment_carrier(segment: dict[str, Any]) -> str:
    fn = str(segment.get("flight_number") or "").strip().upper()
    m = re.match(r"([A-Z0-9]{2})", fn)
    return m.group(1) if m else ""


def all_skyteam_segments(route: dict[str, Any]) -> bool:
    segments = route.get("segments") or []
    if not segments:
        return False
    codes = [segment_carrier(s) for s in segments]
    return bool(codes) and all(code in SKYTEAM_CODES for code in codes)


def classify_program(name: str, code: str) -> str | None:
    token = f"{name} {code}".lower()
    if "flying blue" in token or code.upper() in {"AF", "FB"}:
        return "Flying Blue"
    if "delta" in token or "skymiles" in token or code.upper() == "DL":
        return "Delta SkyMiles"
    return None


def flatten_awards(program_results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pr in program_results:
        program_name = str(pr.get("program") or "")
        code = str(pr.get("code") or "")
        normalized_program = classify_program(program_name, code)
        if not normalized_program:
            continue
        result_date = str(pr.get("date") or "")
        for route in pr.get("routes") or []:
            if not all_skyteam_segments(route):
                continue
            payment = route.get("payment") or {}
            segments = route.get("segments") or []
            out.append(
                {
                    "date": result_date or (str(segments[0].get("dt", ""))[:10] if segments else ""),
                    "program": normalized_program,
                    "program_raw": program_name,
                    "program_code": code,
                    "miles": payment.get("miles"),
                    "tax_usd": payment.get("tax"),
                    "cash_price_field": payment.get("cash_price"),
                    "cabin": payment.get("cabin"),
                    "seats": payment.get("seats"),
                    "duration_minutes": route.get("duration"),
                    "segments": segments,
                    "route": "-".join(
                        [str(segments[0].get("da"))]
                        + [str(s.get("aa")) for s in segments]
                    ) if segments else "",
                    "flight_numbers": [str(s.get("flight_number")) for s in segments],
                    "booking_code": (route.get("extra") or {}).get("booking_code"),
                    "booking_url": route.get("url"),
                }
            )
    out.sort(
        key=lambda x: (
            x.get("date") or "",
            x.get("program") or "",
            x.get("miles") is None,
            x.get("miles") or 10**12,
            x.get("tax_usd") or 0,
        )
    )
    return out


def best_award(options: list[dict[str, Any]], program: str) -> dict[str, Any] | None:
    matches = [o for o in options if o.get("program") == program]
    if not matches:
        return None
    return min(
        matches,
        key=lambda x: (
            x.get("miles") is None,
            x.get("miles") or 10**12,
            x.get("tax_usd") or 0,
            x.get("duration_minutes") or 10**9,
        ),
    )


def fmt_cash(item: dict[str, Any] | None) -> str:
    if not item:
        return "—"
    p = item.get("price_usd")
    airline = item.get("airlines") or ""
    stops = item.get("stops")
    duration = item.get("duration") or ""
    price = f"${p:,.0f}" if isinstance(p, (int, float)) else str(item.get("price_text") or "?")
    return f"{price} · {airline} · {stops} stop(s) · {duration}"


def fmt_award(item: dict[str, Any] | None) -> str:
    if not item:
        return "—"
    miles = item.get("miles")
    tax = item.get("tax_usd")
    route = item.get("route") or ""
    flights = "/".join(item.get("flight_numbers") or [])
    miles_s = f"{int(miles):,}" if isinstance(miles, (int, float)) else "?"
    tax_s = f"${float(tax):,.2f}" if isinstance(tax, (int, float)) else "?"
    return f"{miles_s} + {tax_s} · {route} · {flights}"


def build_final(state: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    all_awards = [o for options in state.get("awards", {}).values() for o in options]
    for day in ALL_DATES:
        cash_opts = (state.get("cash", {}).get(day) or {}).get("skyteam_options") or []
        award_opts = [o for o in all_awards if o.get("date") == day]
        rows.append(
            {
                "date": day,
                "cash_best": cash_opts[0] if cash_opts else None,
                "cash_options": cash_opts[:8],
                "flying_blue_best": best_award(award_opts, "Flying Blue"),
                "delta_best": best_award(award_opts, "Delta SkyMiles"),
                "award_options": award_opts,
                "cash_error": state.get("errors", {}).get("cash", {}).get(day),
            }
        )
    return {
        "generated_at": utc_now(),
        "route": "JED-DTW",
        "trip_type": "one-way",
        "cabin": "economy",
        "filters": "SkyTeam-operated itineraries only; programs Flying Blue and Delta SkyMiles",
        "date_batches": DATE_BATCHES,
        "rows": rows,
        "award_batch_errors": state.get("errors", {}).get("awards", {}),
        "source_metadata": state.get("metadata", {}),
    }


def write_markdown(final: dict[str, Any]) -> None:
    lines = [
        "# JED → DTW: SkyTeam cash + award sweep",
        "",
        f"Generated: {final['generated_at']}",
        "",
        "Economy, one-way, one adult. Cash prices are Google Flights snapshots; award prices are PointsYeah snapshots. All displayed itineraries are filtered to SkyTeam-operated segments.",
        "",
        "| Date | Cheapest SkyTeam cash | Flying Blue | Delta SkyMiles |",
        "|---|---|---|---|",
    ]
    for row in final["rows"]:
        lines.append(
            "| {date} | {cash} | {fb} | {dl} |".format(
                date=row["date"],
                cash=fmt_cash(row.get("cash_best")).replace("|", "/"),
                fb=fmt_award(row.get("flying_blue_best")).replace("|", "/"),
                dl=fmt_award(row.get("delta_best")).replace("|", "/"),
            )
        )

    lines.extend(["", "## Errors / gaps", ""])
    any_errors = False
    for row in final["rows"]:
        if row.get("cash_error"):
            any_errors = True
            lines.append(f"- {row['date']} cash: `{row['cash_error']}`")
    for batch, err in final.get("award_batch_errors", {}).items():
        any_errors = True
        lines.append(f"- Award batch {batch}: `{err}`")
    if not any_errors:
        lines.append("None recorded.")

    lines.extend(["", "## Full retained options", ""])
    for row in final["rows"]:
        lines.append(f"### {row['date']}")
        lines.append("")
        lines.append("**Cash:**")
        if row["cash_options"]:
            for item in row["cash_options"]:
                lines.append(f"- {fmt_cash(item)}")
        else:
            lines.append("- No retained SkyTeam option.")
        lines.append("")
        lines.append("**Awards:**")
        if row["award_options"]:
            for item in row["award_options"]:
                lines.append(f"- {item['program']}: {fmt_award(item)}")
        else:
            lines.append("- No retained Flying Blue or SkyMiles option.")
        lines.append("")

    MARKDOWN_PATH.write_text("\n".join(lines))


def main() -> int:
    state = load_checkpoint()
    state["metadata"].update(
        {
            "started_at": state.get("metadata", {}).get("started_at") or utc_now(),
            "cash_source": "Google Flights via fast-flights",
            "award_source": "PointsYeah anonymous public search",
        }
    )
    save_checkpoint(state)

    # Awards: two isolated batches, checkpoint after each.
    for start, end in DATE_BATCHES:
        batch_key = f"{start}:{end}"
        if batch_key in state["awards"]:
            continue
        try:
            raw = pointsyeah_search(start, end)
            state["awards"][batch_key] = flatten_awards(raw)
            state["errors"]["awards"].pop(batch_key, None)
        except Exception as exc:
            state["errors"]["awards"][batch_key] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        save_checkpoint(state)

    # Cash: date-by-date; successful dates survive later failures.
    for day in ALL_DATES:
        if day in state["cash"]:
            continue
        try:
            state["cash"][day] = search_cash_date(day)
            state["errors"]["cash"].pop(day, None)
        except Exception as exc:
            state["errors"]["cash"][day] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        save_checkpoint(state)
        time.sleep(0.8)

    final = build_final(state)
    RESULT_PATH.write_text(json.dumps(final, indent=2, sort_keys=False))
    write_markdown(final)
    print(MARKDOWN_PATH.read_text())
    # Always succeed so partial data is committed for inspection/retry.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
