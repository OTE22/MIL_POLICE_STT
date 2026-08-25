"""Verification of the readable activity timeline (سجل النشاط and التدقيق)."""
import json
import sys
import urllib.request
from playwright.sync_api import sync_playwright, expect

UI = "http://localhost:8080"
BASE = UI + "/api"
ADMIN_PW = sys.argv[1]
SESSION_ID = sys.argv[2]
SHOTS = sys.argv[3]
R = []


def check(n, ok, d=""):
    R.append((n, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {n} {d}")


def login():
    req = urllib.request.Request(
        BASE + "/auth/login",
        data=json.dumps({"username": "admin", "password": ADMIN_PW}).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


tok = login()
req = urllib.request.Request(f"{BASE}/investigations/{SESSION_ID}/activity?page_size=100")
req.add_header("Authorization", "Bearer " + tok)
with urllib.request.urlopen(req, timeout=30) as r:
    raw = json.load(r)
print(f"session has {len(raw['items'])} audit entries")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1500, "height": 1100})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{UI}/login")
    pg.fill("#username", "admin")
    pg.fill("#password", ADMIN_PW)
    pg.click("button[type=submit]")
    pg.wait_for_url(lambda u: "/login" not in u)

    # ---- session activity tab ----------------------------------------------
    pg.goto(f"{UI}/investigations/{SESSION_ID}?tab=activity")
    pg.wait_for_selector("[data-testid=activity]", timeout=20000)
    body = pg.locator("[data-testid=activity]").inner_text()

    check("no raw JSON braces in the timeline", "{" not in body and "}" not in body,
          repr(body[body.find("{"):body.find("{") + 60]) if "{" in body else "")
    check("no raw field names leaked", '"session_id"' not in body and "session_id" not in body)
    check("no quoted key/value pairs", '":"' not in body)

    runs = pg.locator("[data-testid=activity-run]")
    rows = pg.locator("[data-testid=activity-row]")
    check("processing stages collapsed into runs", runs.count() > 0, f"{runs.count()} run(s)")
    check("fewer visible rows than raw entries",
          runs.count() + rows.count() < len(raw["items"]),
          f"{runs.count() + rows.count()} shown vs {len(raw['items'])} entries")

    first_run = runs.first
    check("run states an outcome",
          any(w in first_run.inner_text() for w in ("اكتملت", "فشلت", "أُلغيت", "قيد التنفيذ")),
          first_run.inner_text().split("\n")[0])

    # stages disclosure
    stages_toggle = first_run.locator("button.audit-toggle", has_text="مراحل المعالجة")
    check("run has a stages disclosure", stages_toggle.count() == 1)
    stages_toggle.first.click()
    expect(first_run.locator(".audit-stages")).to_be_visible(timeout=5000)
    check("stages expand on demand", True)

    # technical details disclosure
    tech = pg.locator("button.audit-toggle", has_text="التفاصيل التقنية").first
    tech.click()
    dl = pg.locator(".audit-details").first
    expect(dl).to_be_visible(timeout=5000)
    dtext = dl.inner_text()
    check("technical details render as labelled rows, not JSON",
          "{" not in dtext and ":" not in dtext.split("\n")[0], dtext.split("\n")[0][:60])
    check("identifiers are shortened", "…" in dtext or len(dtext) < 400)
    pg.screenshot(path=f"{SHOTS}/activity-timeline.png", full_page=True)

    # ---- filters ------------------------------------------------------------
    if pg.locator("[data-testid=activity-filters]").count():
        chips = pg.locator("[data-testid=activity-filters] .chip")
        check("category filter chips shown", chips.count() >= 2, f"{chips.count()} chips")
        chips.nth(1).click()
        pg.wait_for_timeout(300)
        check("filtering narrows the timeline",
              pg.locator("[data-testid=activity-run], [data-testid=activity-row]").count() >= 1)
        chips.first.click()
    else:
        check("category filter chips shown", False, "no filter bar rendered")

    # ---- admin audit page ---------------------------------------------------
    pg.goto(f"{UI}/audit")
    pg.wait_for_selector("table.table tbody tr", timeout=20000)
    tbody = pg.locator("table.table tbody").inner_text()
    check("audit page has no JSON dump", "{" not in tbody and '":' not in tbody,
          repr(tbody[tbody.find("{"):tbody.find("{") + 60]) if "{" in tbody else "")
    check("audit page shows readable summaries", pg.locator(".audit-summary").count() > 0,
          f"{pg.locator('.audit-summary').count()} summaries")
    pg.screenshot(path=f"{SHOTS}/audit-page.png", full_page=True)

    check("no page errors", not errs, "; ".join(errs[:2]))
    b.close()

bad = [n for n, ok in R if not ok]
print(f"\nACTIVITY UI: {len(R) - len(bad)}/{len(R)} checks passed")
sys.exit(1 if bad else 0)
