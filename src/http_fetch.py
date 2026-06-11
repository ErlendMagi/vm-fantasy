"""HTTPS JSON fetch with a Windows fallback.

Some local setups (AV/TLS interception) reset OpenSSL handshakes while letting
the Windows TLS stack (Schannel) through. We try `requests` first - the normal
path everywhere, including Streamlit Cloud - and on Windows fall back to
PowerShell's Invoke-WebRequest when the TLS layer fails.
"""
import json
import subprocess
import sys
import time
from urllib.parse import urlencode

import requests


def fetch_json(url: str, params: dict | None = None, timeout: int = 20,
               retries: int = 2) -> tuple[dict | list | None, dict]:
    """Returns (parsed_json | None, response_headers)."""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(1.0 * attempt)
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json(), dict(r.headers)
        except requests.RequestException:
            if sys.platform == "win32":
                payload, headers = _fetch_via_powershell(url, params, timeout)
                if payload is not None:
                    return payload, headers
    return None, {}


def _fetch_via_powershell(url: str, params: dict | None, timeout: int) -> tuple[dict | list | None, dict]:
    full = url + ("?" + urlencode(params) if params else "")
    ps = (
        "$ProgressPreference='SilentlyContinue';"
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;"
        f"$r = Invoke-WebRequest -UseBasicParsing -Uri '{full}' -TimeoutSec {timeout};"
        "$h = @{}; foreach ($k in $r.Headers.Keys) { $h[$k] = [string]$r.Headers[$k] };"
        "@{status=[int]$r.StatusCode; headers=$h; content=$r.Content} | ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=timeout + 15, encoding="utf-8",
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None, {}
        wrapper = json.loads(out.stdout)
        if wrapper.get("status") != 200:
            return None, wrapper.get("headers", {})
        return json.loads(wrapper["content"]), wrapper.get("headers", {})
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None, {}
