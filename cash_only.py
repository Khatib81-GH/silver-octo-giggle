#!/usr/bin/env python3

import json
from pathlib import Path

from fare_sweep_v2 import DATES, OUT, failed_cash, run_cash_v3

OUT = Path(OUT)
OUT.mkdir(exist_ok=True)

try:
    cash = run_cash_v3()
except Exception as exc:
    cash = failed_cash(exc)

(OUT / "cash.json").write_text(json.dumps(cash, indent=2, ensure_ascii=False))
status = {
    "cash_ok_dates": [d for d, v in cash.items() if v.get("status") == "ok"],
    "cash_other": {d: v.get("status") for d, v in cash.items() if v.get("status") != "ok"},
}
(OUT / "cash_status.json").write_text(json.dumps(status, indent=2))
print(json.dumps(status, indent=2))
