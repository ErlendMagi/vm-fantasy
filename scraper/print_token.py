"""Print your current TV 2 bearer token, for pasting into the GitHub Actions
secret TV2_TOKEN (so the cloud sync can authenticate).

    python scraper/print_token.py

Uses your saved browser login (playwright-profile/). The token is valid ~120
days; re-run and update the secret if cloud syncs start returning 401.
"""
import base64
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = Path(__file__).resolve().parents[1] / "playwright-profile"


def main() -> None:
    cap = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=True, ignore_https_errors=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("request", lambda rq: cap.__setitem__("auth", rq.headers["authorization"].split(" ")[-1])
                if rq.headers.get("authorization") and "railway.app" in rq.url else None)
        page.goto("https://vmfantasy.tv2.no/", wait_until="networkidle")
        if "auth" not in cap:
            token = page.evaluate(
                "() => { for (const k in localStorage){ const v=localStorage[k];"
                " if (v && v.split('.').length===3 && v.length>40) return v; } return null; }")
            if token:
                cap["auth"] = token
        ctx.close()

    token = cap.get("auth")
    if not token:
        sys.exit("Could not find a token — are you logged in? Run scraper/discover_endpoints.py first.")
    payload = token.split(".")[1] + "==="
    exp = json.loads(base64.urlsafe_b64decode(payload[: len(payload) // 4 * 4])).get("exp")
    print("\nTV2_TOKEN (paste this as the GitHub Actions secret):\n")
    print(token)
    if exp:
        print(f"\nexpires: {time.strftime('%Y-%m-%d', time.gmtime(exp))}")


if __name__ == "__main__":
    main()
