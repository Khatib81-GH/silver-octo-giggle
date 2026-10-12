#!/usr/bin/env python3
"""Run one public Pointhound award search and capture its network responses."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright

OUT = Path("results/pointhound_probe")
OUT.mkdir(parents=True, exist_ok=True)


def dump(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, default=str))


def click_visible(locator) -> bool:
    for i in range(locator.count()):
        x = locator.nth(i)
        try:
            if x.is_visible():
                x.click()
                return True
        except Exception:
            pass
    return False


def select_airport(page, placeholder: str, code: str) -> None:
    box = page.get_by_placeholder(placeholder, exact=False).first
    box.click()
    box.fill(code)
    page.wait_for_timeout(900)
    for opt in (
        page.get_by_role("option").filter(has_text=re.compile(rf"\b{code}\b", re.I)),
        page.locator("[role='option']").filter(has_text=re.compile(rf"\b{code}\b", re.I)),
        page.get_by_text(re.compile(rf"\b{code}\b", re.I)),
    ):
        if click_visible(opt):
            return
    box.press("ArrowDown")
    box.press("Enter")


def select_dec_25_2026(page) -> str:
    field = page.get_by_placeholder("Date or date range", exact=False).first
    field.click()
    page.wait_for_timeout(500)
    next_button = page.locator("button[aria-label='Go to the Next Month']")
    next_button.wait_for(state="visible", timeout=10_000)
    # The date picker opens on the current month: October 2026.
    next_button.click()
    page.wait_for_timeout(250)
    next_button = page.locator("button[aria-label='Go to the Next Month']")
    next_button.click()
    page.wait_for_timeout(350)

    target = page.locator("button[aria-label='Friday, December 25th, 2026']")
    target.wait_for(state="visible", timeout=10_000)
    target.click()
    page.wait_for_timeout(250)
    select_button = page.get_by_role("button", name="Select", exact=True)
    select_button.wait_for(state="visible", timeout=10_000)
    select_button.click()
    page.wait_for_timeout(500)
    return field.input_value()


def main() -> int:
    network: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, locale="en-US")
        page = context.new_page()

        def capture(resp) -> None:
            req = resp.request
            if req.resource_type not in {"xhr", "fetch"}:
                return
            row: dict[str, Any] = {
                "url": resp.url,
                "status": resp.status,
                "method": req.method,
                "post_data": req.post_data,
                "content_type": resp.headers.get("content-type", ""),
            }
            try:
                body = resp.body()
                if len(body) <= 20_000_000:
                    row["body"] = body.decode("utf-8", errors="replace")
            except Exception as exc:
                row["body_error"] = str(exc)
            network.append(row)

        page.on("response", capture)
        page.goto("https://www.pointhound.com/search", wait_until="networkidle", timeout=120_000)
        select_airport(page, "Origin airport or city", "JED")
        select_airport(page, "Destination airport", "DTW")
        input_value = select_dec_25_2026(page)

        (OUT / "selected_date.txt").write_text(input_value)
        page.screenshot(path=str(OUT / "ready_to_search.png"), full_page=True)
        if "December 25, 2026" not in input_value:
            raise RuntimeError(f"unexpected date value: {input_value!r}")

        if not click_visible(page.get_by_role("button", name=re.compile("Fetch deals", re.I))):
            raise RuntimeError("Fetch deals button not found")

        deadline = time.time() + 180
        previous_count = -1
        unchanged = 0
        while time.time() < deadline:
            page.wait_for_timeout(2500)
            count = len(network)
            body_text = page.locator("body").inner_text()
            unchanged = unchanged + 1 if count == previous_count else 0
            previous_count = count
            low = body_text.lower()
            if unchanged >= 4 and any(x in low for x in ("miles", "points", "no flights", "no results", "error")):
                break

        result_text = page.locator("body").inner_text()
        (OUT / "results_text.txt").write_text(result_text)
        (OUT / "results_html.html").write_text(page.content())
        page.screenshot(path=str(OUT / "results.png"), full_page=True)
        dump("network.json", network)
        dump("summary.json", {"url": page.url, "selected_date": input_value, "network_count": len(network)})
        browser.close()

    print(result_text[:30000])
    print(f"Captured {len(network)} XHR/fetch responses")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        (OUT / "probe_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        raise
