"""Step 1 (run once, needs YOU at the keyboard): discover TV 2 VM Fantasy's
internal JSON API.

    pip install -r scraper/requirements-local.txt
    playwright install chromium
    python scraper/discover_endpoints.py

A Chromium window opens on vmfantasy.tv2.no. Log in, then click around:
your squad page, the full player list, one player's point breakdown, the
transfers page, and the league standings. Every JSON response the site makes
is dumped to scrape_dumps/ (gitignored). When done, come back here and press
Enter.

Then: open the dumps, find the responses containing (a) all players with
prices/ownership, (b) your squad, (c) fixtures/deadlines, and copy their URLs
into scraper/endpoints.json (template printed at the end).

Your login session persists in playwright-profile/ (gitignored) so sync.py
can reuse it without logging in again.
"""
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "playwright-profile"
DUMPS = ROOT / "scrape_dumps"
SKIP_HOSTS = ("plausible.io", "google", "facebook", "hotjar", "doubleclick", "cookiebot")

ENDPOINTS_TEMPLATE = {
    "_comment": "Fill in from scrape_dumps/. {round} is substituted by tv2_client.",
    "players": "https://...",
    "my_team": "https://...",
    "fixtures": "https://...",
    "bootstrap_or_rules": "https://...",
}


def main() -> None:
    DUMPS.mkdir(exist_ok=True)
    seen = 0

    def on_response(response):
        nonlocal seen
        try:
            ct = response.headers.get("content-type", "")
            url = response.url
            if "json" not in ct or any(h in url for h in SKIP_HOSTS):
                return
            body = response.json()
            seen += 1
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", url.split("://", 1)[-1])[:120]
            out = DUMPS / f"{seen:03d}_{slug}.json"
            out.write_text(
                json.dumps({"url": url, "status": response.status, "body": body},
                           indent=1, ensure_ascii=False)[:500_000],
                encoding="utf-8",
            )
            print(f"  [{seen:03d}] {response.status} {url}")
        except Exception:
            pass  # non-JSON body or stream already consumed; ignore

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)
        page.goto("https://vmfantasy.tv2.no/")
        print("\n>>> Log in and click through: squad, player list, a player's points,")
        print(">>> transfers, league. JSON responses are being recorded above.")
        input(">>> Press Enter here when you are done...")
        ctx.close()

    print(f"\nDumped {seen} JSON responses to {DUMPS}/")
    template_path = ROOT / "scraper" / "endpoints.json"
    if not template_path.exists():
        template_path.write_text(json.dumps(ENDPOINTS_TEMPLATE, indent=2), encoding="utf-8")
        print(f"Wrote template {template_path} - fill in the URLs you found.")


if __name__ == "__main__":
    main()
