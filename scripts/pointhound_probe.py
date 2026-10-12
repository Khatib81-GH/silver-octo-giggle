#!/usr/bin/env python3
"""Probe Pointhound's public award-search UI and capture search responses.

This uses the public, no-login Standard Search exactly as a browser would. It
records only flight-search requests/responses and page diagnostics needed to
extract award availability.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

OUT = Path("results/pointhound_probe")
OUT.mkdir(parents=True, exist_ok=True)


def dump_json(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, default=str))


def input_snapshot(page) -> list[dict[str, Any]]:
    return page.locator("input").evaluate_all(
        """els => els.map((e, i) => ({
            i,
            type: e.type,
            name: e.name,
            placeholder: e.placeholder,
            value: e.value,
            readOnly: e.readOnly,
            disabled: e.disabled,
            ariaLabel: e.getAttribute('aria-label'),
            role: e.getAttribute('role'),
            className: e.className
        }))"""
    )


def click_first_visible(locator) -> bool:
    try:
        count = locator.count()
    except Exception:
        return False
    for i in range(count):
        item = locator.nth(i)
        try:
            if item.is_visible():
                item.click()
                return True
        except Exception:
            continue
    return False


def choose_airport(page, placeholder: str, code: str) -> None:
    field = page.get_by_placeholder(placeholder, exact=False).first
    field.click()
    field.fill(code)
    page.wait_for_timeout(1200)
    dump_json(f"after_{code.lower()}_inputs.json", input_snapshot(page))
    (OUT / f"after_{code.lower()}_text.txt").write_text(page.locator("body").inner_text())

    # Prefer an autocomplete option containing the airport code.
    candidates = [
        page.get_by_role("option").filter(has_text=re.compile(rf"\b{code}\b", re.I)),
        page.get_by_role("button").filter(has_text=re.compile(rf"\b{code}\b", re.I)),
        page.locator("[role='option']").filter(has_text=re.compile(rf"\b{code}\b", re.I)),
        page.get_by_text(re.compile(rf"\b{code}\b", re.I)),
    ]
    for candidate in candidates:
        if click_first_visible(candidate):
            return
    field.press("ArrowDown")
    field.press("Enter")


def navigate_calendar_to(page, target_year: int, target_month: int) -> None:
    # Read visible calendar heading and advance until target month appears.
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    target = f"{month_names[target_month - 1]} {target_year}"
    for _ in range(18):
        body_text = page.locator("body").inner_text()
        if target.lower() in body_text.lower():
            return
        next_locators = [
            page.get_by_role("button", name=re.compile("next month", re.I)),
            page.get_by_role("button", name=re.compile("next", re.I)),
            page.locator("button[aria-label*='next' i]"),
        ]
        moved = False
        for loc in next_locators:
            if click_first_visible(loc):
                moved = True
                break
        if not moved:
            # Fallback: choose the rightmost visible icon-only button in calendar dialog.
            dialog = page.locator("[role='dialog']")
            buttons = dialog.locator("button") if dialog.count() else page.locator("button")
            visible = []
            for i in range(buttons.count()):
                b = buttons.nth(i)
                try:
                    if b.is_visible():
                        visible.append(b)
                except Exception:
                    pass
            if visible:
                visible[-1].click()
                moved = True
        if not moved:
            raise RuntimeError(f"Could not advance calendar toward {target}")
        page.wait_for_timeout(250)
    raise RuntimeError(f"Calendar did not reach {target}")


def click_calendar_day(page, year: int, month: int, day: int) -> None:
    month_name = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ][month - 1]
    patterns = [
        re.compile(rf"{month_name}\s+{day}(?:st|nd|rd|th)?,?\s+{year}", re.I),
        re.compile(rf"{month_name}\s+{day},\s+{year}", re.I),
        re.compile(rf"{year}-0?{month}-0?{day}", re.I),
    ]
    for pattern in patterns:
        locs = [
            page.get_by_role("button", name=pattern),
            page.locator("button").filter(has_text=re.compile(rf"^{day}$")),
        ]
        for loc in locs:
            if click_first_visible(loc):
                return
    raise RuntimeError(f"Could not click {year}-{month:02d}-{day:02d}")


def choose_date_range(page) -> None:
    field = page.get_by_placeholder("Date or date range", exact=False).first
    field.click()
    page.wait_for_timeout(500)
    (OUT / "calendar_open_text.txt").write_text(page.locator("body").inner_text())
    dump_json("calendar_buttons.json", page.locator("button").evaluate_all(
        "els => els.filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)).map((e,i)=>({i,text:e.innerText,aria:e.getAttribute('aria-label'),title:e.title,className:e.className}))"
    ))
    page.screenshot(path=str(OUT / "calendar_open.png"), full_page=True)

    navigate_calendar_to(page, 2026, 12)
    click_calendar_day(page, 2026, 12, 25)
    page.wait_for_timeout(300)
    # The picker may remain open for end date; advance to January 2027 if needed.
    navigate_calendar_to(page, 2027, 1)
    click_calendar_day(page, 2027, 1, 5)
    page.wait_for_timeout(300)

    # Some pickers require Apply/Done.
    for pattern in ("apply", "done", "confirm", "save"):
        if click_first_visible(page.get_by_role("button", name=re.compile(pattern, re.I))):
            break


def main() -> int:
    network: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="en-US",
            timezone_id="America/Detroit",
        )
        page = context.new_page()

        def on_response(resp) -> None:
            req = resp.request
            if req.resource_type not in {"xhr", "fetch"}:
                return
            entry: dict[str, Any] = {
                "url": resp.url,
                "status": resp.status,
                "method": req.method,
                "post_data": req.post_data,
                "resource_type": req.resource_type,
                "content_type": resp.headers.get("content-type", ""),
            }
            try:
                body = resp.body()
                if len(body) <= 3_000_000:
                    text = body.decode("utf-8", errors="replace")
                    entry["body"] = text
            except Exception as exc:
                entry["body_error"] = str(exc)
            network.append(entry)

        page.on("response", on_response)
        page.goto("https://www.pointhound.com/search", wait_until="networkidle", timeout=120_000)
        page.screenshot(path=str(OUT / "landing.png"), full_page=True)
        dump_json("landing_inputs.json", input_snapshot(page))
        (OUT / "landing_text.txt").write_text(page.locator("body").inner_text())

        choose_airport(page, "Origin airport or city", "JED")
        choose_airport(page, "Destination airport", "DTW")
        choose_date_range(page)
        dump_json("filled_inputs.json", input_snapshot(page))
        page.screenshot(path=str(OUT / "filled.png"), full_page=True)

        fetch_button = page.get_by_role("button", name=re.compile("fetch deals|search", re.I))
        if not click_first_visible(fetch_button):
            raise RuntimeError("Could not find Fetch deals/Search button")

        # Allow streaming providers to finish; stop early when results text appears.
        deadline = time.time() + 210
        last_text = ""
        while time.time() < deadline:
            page.wait_for_timeout(2500)
            last_text = page.locator("body").inner_text()
            low = last_text.lower()
            if any(token in low for token in ("flying blue", "skymiles", "miles +", "book with")):
                # Continue a little longer so all programs can arrive.
                page.wait_for_timeout(20_000)
                last_text = page.locator("body").inner_text()
                break
            if any(token in low for token in ("no results", "no flights found", "try another")):
                break

        (OUT / "results_text.txt").write_text(last_text)
        (OUT / "results_html.html").write_text(page.content())
        page.screenshot(path=str(OUT / "results.png"), full_page=True)
        dump_json("network.json", network)
        dump_json("final_inputs.json", input_snapshot(page))
        browser.close()

    print((OUT / "results_text.txt").read_text()[:20_000])
    print(f"Captured {len(network)} XHR/fetch responses")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        (OUT / "probe_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        raise
