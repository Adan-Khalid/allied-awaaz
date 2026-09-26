#!/usr/bin/env python3
"""Console acceptance test in a real browser (Playwright, Chromium).

Needs the backend (seeded) and the console running. Exercises login, triage, the
activation sweep, the approval gate for both roles, disputes with agent reasoning,
merchant detail and the audit log, and fails on any browser console error.

    AWAAZ_CONSOLE=http://localhost:3000 AWAAZ_API=http://localhost:8000 python scripts/e2e_console.py
Optional: AWAAZ_CHROMIUM=/path/to/chrome if Playwright's bundled browser is not installed.
"""
from __future__ import annotations

import os
import sys

import httpx
from playwright.sync_api import Page, expect, sync_playwright

UI = os.getenv("AWAAZ_CONSOLE", "http://localhost:3000")
API = os.getenv("AWAAZ_API", "http://localhost:8000")
RM_TOKEN = os.getenv("AWAAZ_RM_TOKEN", "dev-rm-token")
SUP_TOKEN = os.getenv("AWAAZ_SUP_TOKEN", "dev-sup-token")
results: list[tuple[str, bool, str]] = []
browser_errors: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
        results.append((name, True, ""))
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, str(exc).splitlines()[0][:300]))
        print(f"  FAIL  {name}\n        {str(exc).splitlines()[0][:300]}")


def watch(page: Page) -> None:
    page.on("pageerror", lambda e: browser_errors.append(f"pageerror: {e}"))
    # Resource failures are recorded with their URL. 401/403 are expected (bad token test, RM approval
    # attempt); third-party font hosts are ignored so an offline machine does not fail the check.
    def on_response(r):
        if r.status >= 400 and r.status not in (401, 403) and "fonts.g" not in r.url:
            browser_errors.append(f"HTTP {r.status} {r.request.method} {r.url}")
    page.on("response", on_response)
    page.on("console", lambda m: browser_errors.append(f"console.{m.type}: {m.text}")
            if m.type == "error" and "Failed to load resource" not in m.text else None)


def login(page: Page, token: str) -> None:
    page.goto(f"{UI}/login")
    page.fill("#token", token)
    page.click("button.primary")
    page.wait_for_url("**/merchants")


def main() -> int:
    print(f"Console acceptance: UI {UI}, API {API}")
    # Make sure a terminal-originated dispute exists so the disputes page has an agent trace to show.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    from virtual_terminal import from_env
    t = from_env()
    t.mqtt_host = None
    t.say("customer keh raha hai 4410 bhej diye")

    with sync_playwright() as p:
        exe = os.getenv("AWAAZ_CHROMIUM")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        rm = browser.new_page(viewport={"width": 1360, "height": 900})
        watch(rm)

        def bad_token():
            rm.goto(f"{UI}/login")
            rm.fill("#token", "not-a-token")
            rm.click("button.primary")
            expect(rm.locator(".notice.error")).to_contain_text("isn't recognised")
        check("rejects an unknown staff token", bad_token)

        def merchants():
            login(rm, RM_TOKEN)
            expect(rm.locator("tbody tr")).to_have_count(25, timeout=10000)
            row = rm.locator("tbody tr", has_text="Hamza Auto Workshop")
            expect(row).to_contain_text("At risk")
            expect(row).to_contain_text("Never activated")
        check("RM sees 25 merchants triaged with reasons", merchants)

        def sweep():
            rm.get_by_role("button", name="Find merchants who need attention").click()
            expect(rm.get_by_role("status")).to_contain_text("Checked 25 merchants", timeout=15000)
        check("activation sweep runs from the merchants page", sweep)

        def rm_gate():
            rm.goto(f"{UI}/approvals")
            card = rm.locator("article.approval", has_text="WhatsApp message to merchant").first
            expect(card).to_contain_text("need a supervisor")
            expect(card.get_by_role("button", name="Approve and send")).to_be_disabled()
        check("RM cannot approve a WhatsApp message (explained in UI)", rm_gate)

        def rm_reject():
            card = rm.locator("article.approval", has_text="RM call").first
            card.locator("textarea").fill("Visited yesterday, owner on leave")
            card.get_by_role("button", name="Reject").click()
            expect(rm.get_by_role("status")).to_contain_text("Rejected")
            rm.get_by_role("tab", name="Decided").click()
            expect(rm.locator("article.approval").first).to_contain_text("Visited yesterday, owner on leave")
        check("RM rejects a call with a note that is recorded", rm_reject)

        sup = browser.new_page(viewport={"width": 1360, "height": 900})
        watch(sup)

        def sup_approve():
            login(sup, SUP_TOKEN)
            sup.goto(f"{UI}/approvals")
            sup.screenshot(path="/tmp/sup_debug.png")
            card = sup.locator("article.approval", has_text="WhatsApp message to merchant").first
            card.locator("textarea").fill("Approved for demo")
            card.get_by_role("button", name="Approve and send").click()
            expect(sup.get_by_role("status")).to_contain_text("Approved and sent")
        check("supervisor approves and sends a WhatsApp message", sup_approve)

        def reasoning():
            sup.get_by_role("tab", name="Waiting").click()
            card = sup.locator("article.approval").first
            card.get_by_role("button", name="Show agent reasoning").click()
            expect(card.locator(".ledger li")).not_to_have_count(0)
            expect(card.locator(".ledger")).to_contain_text("Scored health of 25 merchants")
        check("approval card shows the activation agent's reasoning", reasoning)

        def disputes():
            sup.goto(f"{UI}/exceptions")
            row = sup.locator("tbody tr", has_text="PKR 4,410")
            row.click()
            ledger = sup.locator("aside.panel .ledger")
            expect(ledger).to_contain_text("Searched the ledger")
            expect(ledger).to_contain_text("Re-read the ledger")
            expect(sup.locator("aside.panel")).to_contain_text("Claimed, not received")
        check("disputes page shows the exception agent's step-by-step reasoning", disputes)

        def detail():
            sup.goto(f"{UI}/merchants")
            sup.get_by_role("link", name="Ahmed Pharmacy").click()
            expect(sup.get_by_role("heading", name="Ahmed Pharmacy")).to_be_visible()
            expect(sup.locator(".ledger")).to_contain_text("Merchant said")
            expect(sup.locator("text=Recent payments")).to_be_visible()
        check("merchant detail shows terminal agent runs and payments", detail)

        def audit():
            sup.goto(f"{UI}/audit")
            expect(sup.locator("tbody")).to_contain_text("intervention.approved", timeout=10000)
            expect(sup.locator("tbody")).to_contain_text("intervention.rejected")
        check("audit log records both decisions", audit)

        def mobile():
            m = browser.new_page(viewport={"width": 390, "height": 844})
            watch(m)
            login(m, RM_TOKEN)
            width = m.evaluate("document.documentElement.scrollWidth")
            assert width <= 392, f"page scrolls sideways on mobile: {width}px"
        check("mobile layout does not scroll sideways", mobile)

        check("no browser console errors on any page",
              lambda: (_ for _ in ()).throw(AssertionError("; ".join(browser_errors[:5]))) if browser_errors else None)
        browser.close()

    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} console acceptance checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    assert httpx.get(API + "/healthz").status_code == 200, "backend not running"
    sys.exit(main())
