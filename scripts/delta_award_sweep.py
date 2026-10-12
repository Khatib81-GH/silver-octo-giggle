#!/usr/bin/env python3
"""Temporary Delta SkyMiles JED→DTW award sweep with per-date checkpoints."""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

SOURCE_REPO = Path(os.environ.get("POINTS_PILOT_REPO", "/tmp/points-pilot-jobs"))
sys.path.insert(0, str(SOURCE_REPO))

from scrapers.delta import DeltaScraper  # type: ignore  # noqa: E402

OUT = Path("results/delta_award")
OUT.mkdir(parents=True, exist_ok=True)
CHECKPOINT = OUT / "checkpoint.json"
FINAL = OUT / "jed_dtw_delta_skymiles_2026-12-25_to_2027-01-05.json"

BATCHES = [
    [f"2026-12-{d:02d}" for d in range(25, 31)],
    [f"2026-12-{d:02d}" for d in range(31, 32)] + [f"2027-01-{d:02d}" for d in range(1, 6)],
]
SKYTEAM = {"AR","AM","UX","AF","CI","MU","DL","GA","KQ","KL","KE","ME","SV","SK","RO","VN","VS","MF"}


def load() -> dict[str, Any]:
    if CHECKPOINT.exists():
        try:
            return json.loads(CHECKPOINT.read_text())
        except Exception:
            pass
    return {"results": {}, "errors": {}}


def save(state: dict[str, Any]) -> None:
    CHECKPOINT.write_text(json.dumps(state, indent=2, sort_keys=True, default=str))


def serialize(rec: Any) -> dict[str, Any]:
    if is_dataclass(rec):
        d = asdict(rec)
    elif hasattr(rec, "__dict__"):
        d = dict(vars(rec))
    else:
        d = {"raw": str(rec)}
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


def carrier_codes(raw_flight_number: str | None) -> list[str]:
    if not raw_flight_number:
        return []
    return re.findall(r"\b([A-Z0-9]{2})\s*\d+", raw_flight_number.upper())


def keep_skyteam(record: dict[str, Any]) -> bool:
    codes = carrier_codes(record.get("raw_flight_number"))
    return bool(codes) and all(c in SKYTEAM for c in codes)


def main() -> int:
    state = load()
    for batch_index, dates in enumerate(BATCHES, start=1):
        scraper = DeltaScraper()
        # Keep the upstream anti-bot pacing. One browser is reused within each batch.
        try:
            for ds in dates:
                if ds in state["results"]:
                    continue
                try:
                    records = scraper.scrape("JED", "DTW", date.fromisoformat(ds))
                    rows = [serialize(r) for r in records]
                    rows = [r for r in rows if keep_skyteam(r)]
                    rows.sort(key=lambda r: (
                        r.get("cabin_class") != "economy",
                        r.get("points_cost") if isinstance(r.get("points_cost"), (int,float)) else 10**12,
                        r.get("cash_cost") if isinstance(r.get("cash_cost"), (int,float)) else 10**12,
                    ))
                    state["results"][ds] = rows
                    state["errors"].pop(ds, None)
                    print(f"{ds}: {len(rows)} retained SkyTeam options", flush=True)
                except Exception as exc:
                    state["errors"][ds] = f"{type(exc).__name__}: {exc}"
                    print(f"{ds}: ERROR {type(exc).__name__}: {exc}", flush=True)
                    traceback.print_exc()
                save(state)
        finally:
            scraper.close()
        print(f"completed batch {batch_index}", flush=True)

    FINAL.write_text(json.dumps(state, indent=2, sort_keys=True, default=str))
    print(json.dumps({
        "dates_with_results": {k: len(v) for k, v in state["results"].items()},
        "errors": state["errors"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
