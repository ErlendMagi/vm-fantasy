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
               retries: int = 2, headers: dict | None = None) -> tuple[dict | list | None, dict]:
    """Returns (parsed_json | None, response_headers)."""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(1.0 * attempt)
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=headers)
            if r.status_code == 429:        # rate limited - back off and retry
                time.sleep(5.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json(), dict(r.headers)
        except requests.RequestException:
            if sys.platform == "win32":
                payload, resp_headers = _fetch_via_powershell(url, params, timeout, headers)
                if payload is not None:
                    return payload, resp_headers
    return None, {}


def _fetch_via_powershell(url: str, params: dict | None, timeout: int,
                          headers: dict | None = None) -> tuple[dict | list | None, dict]:
    full = url + ("?" + urlencode(params) if params else "")
    full = full.replace("'", "''")  # PS single-quote escape: closes the injection sink
    hdr_ps = ""
    if headers:
        pairs = "; ".join(
            f"$hd['{k.replace(chr(39), chr(39)*2)}']='{str(v).replace(chr(39), chr(39)*2)}'"
            for k, v in headers.items())
        hdr_ps = f"$hd=@{{}}; {pairs};"
    ps = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$ProgressPreference='SilentlyContinue';"
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;"
        + hdr_ps +
        f"$r = Invoke-WebRequest -UseBasicParsing -Uri '{full}' -TimeoutSec {timeout}"
        + (" -Headers $hd" if headers else "") + ";"
        "$h = @{}; foreach ($k in $r.Headers.Keys) { $h[$k] = [string]$r.Headers[$k] };"
        "@{status=[int]$r.StatusCode; headers=$h; content=$r.Content} | ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=timeout + 15,
            encoding="utf-8", errors="replace",
        )
        if out.returncode != 0 or not out.stdout or not out.stdout.strip():
            return None, {}
        wrapper = json.loads(out.stdout)
        if wrapper.get("status") != 200:
            return None, wrapper.get("headers", {})
        return json.loads(wrapper["content"]), wrapper.get("headers", {})
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None, {}
