"""Warn (loudly, in the Actions log) if the TV 2 token is close to expiring, so
there's time to refresh the secret before the automation breaks. Exits 0 always
- this is a heads-up, not a gate.
"""
import base64
import json
import os
import sys
import time

WARN_DAYS = 14

token = os.environ.get("TV2_TOKEN")
if not token:
    print("::warning:: TV2_TOKEN not set")
    sys.exit(0)
try:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    days = (exp - time.time()) / 86400
    if days < 0:
        print(f"::error:: TV2_TOKEN EXPIRED {-days:.0f} days ago - run scraper/print_token.py and update the secret")
    elif days < WARN_DAYS:
        print(f"::warning:: TV2_TOKEN expires in {days:.0f} days - refresh it soon "
              "(run scraper/print_token.py, update the GitHub secret TV2_TOKEN)")
    else:
        print(f"TV2_TOKEN healthy: {days:.0f} days until expiry")
except Exception as exc:
    print(f"::warning:: could not decode TV2_TOKEN expiry: {exc}")
