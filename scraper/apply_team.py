"""Apply the model's optimal squad to your TV 2 team via the game's own API.

SAFETY: dry-run by default — it prints the exact team and payload but sends
nothing. Add --confirm to actually write. After writing it re-reads your squad
and verifies the 15 players match, aborting loudly if not.

    python scraper/apply_team.py                 # dry run: show the team + payload
    python scraper/apply_team.py --confirm        # actually set the team
    python scraper/apply_team.py --next --confirm  # optimise for the next round only

Auth: locally uses your saved browser session; in cloud/CI set TV2_TOKEN.

NOTE: the `formation` field format is the one field not verified against the
game (the UI builds it client-side). We send the standard "D-M-F" string
(e.g. "3-4-3"); if the API rejects it the script aborts without leaving a
half-applied squad — re-run after adjusting FORMATION_FMT below.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import advancement, config, data_access, optimizer, projections, squad_builder  # noqa: E402

API = "https://vm-fantasyapi-production.up.railway.app"
TID = "vm-2026"


def build_target(value_col: str) -> dict:
    players = data_access.load_players()
    fixtures = data_access.load_fixtures()
    mo, ou = data_access.load_match_odds(), data_access.load_outrights()
    nr = data_access.next_round(fixtures)
    adv = advancement.advancement_table(fixtures, mo, ou)
    pp = advancement.p_plays_lookup(adv)
    proj = projections.project(players, fixtures, mo, ou,
                               data_access.completed_rounds(fixtures), nr, pp)
    res = squad_builder.build_optimal_squad(proj, value_col=value_col)
    xi = optimizer.best_xi(proj.loc[res["squad_ids"]], "xp_next")
    starters = xi["xi_ids"]
    bench = [p for p in res["squad_ids"] if p not in starters]
    # bench order: backup GK first, then outfield by descending next-round xP
    bench.sort(key=lambda i: (proj.loc[i, "position"] != "GK", -proj.loc[i, "xp_next"]))
    xi_by_xp = proj.loc[starters].sort_values("xp_next", ascending=False)
    d_, m_, f_ = (int(x) for x in xi["formation"].split("-"))
    return {
        "proj": proj,
        "playerIds": res["squad_ids"],
        "starterIds": starters,
        "benchIds": bench,
        "captainId": xi["captain_id"],
        "viceCaptainId": xi_by_xp.index[1],
        "formation": f"{d_}-{m_}-{f_}",
        "res": res,
    }


def _print_team(t: dict) -> None:
    proj = t["proj"]
    print(f"\nOptimal squad — {t['res']['price']}/{config.BUDGET:.0f}M, formation {t['formation']}, "
          f"captain {proj.loc[t['captainId'], 'name']}, model value {t['res']['value']}")
    for pid in t["starterIds"] + t["benchIds"]:
        r = proj.loc[pid]
        tag = "C" if pid == t["captainId"] else ("V" if pid == t["viceCaptainId"] else
              ("XI" if pid in t["starterIds"] else "bench"))
        print(f"  {tag:5} {r['name']:24} {r['team']:14} {r['position']} {r['price']:>4}M  xP {r['xp_next']:.2f}")


def _payload(t: dict, round_id: str) -> dict:
    return {
        "playerIds": t["playerIds"], "roundId": round_id,
        "starterIds": t["starterIds"], "benchIds": t["benchIds"],
        "captainId": t["captainId"], "viceCaptainId": t["viceCaptainId"],
        "formation": t["formation"],
    }


def _apply_and_verify(t: dict) -> None:
    token = os.environ.get("TV2_TOKEN")
    if token:
        _apply_with_requests(t, token)
    else:
        _apply_with_browser(t)


def _verify(applied_ids, target_ids) -> None:
    if set(applied_ids) != set(target_ids):
        sys.exit(f"VERIFY FAILED: applied squad {sorted(applied_ids)} != target — check the app!")
    print(f"\n✓ verified: all {len(target_ids)} players set correctly on TV 2.")


def _apply_with_requests(t: dict, token: str) -> None:
    import requests
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    rid = requests.get(f"{API}/tournaments/{TID}/active-round", headers=h, timeout=30).json()["round"]["id"]
    r = requests.put(f"{API}/squad/update", params={"tournamentId": TID},
                     json=_payload(t, rid), headers=h, timeout=30)
    if not r.ok:
        sys.exit(f"PUT /squad/update failed: HTTP {r.status_code} {r.text[:300]}")
    full = requests.get(f"{API}/squad/full", params={"tournamentId": TID}, headers=h, timeout=30).json()
    _verify([p["playerId"] for p in full["players"]], t["playerIds"])


def _apply_with_browser(t: dict) -> None:
    from playwright.sync_api import sync_playwright
    profile = ROOT / "playwright-profile"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(profile), headless=True, ignore_https_errors=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        cap = {}
        page.on("request", lambda rq: cap.__setitem__("auth", rq.headers.get("authorization"))
                if rq.headers.get("authorization") and "railway.app" in rq.url else None)
        page.goto("https://vmfantasy.tv2.no/", wait_until="networkidle")
        auth = {"Authorization": cap.get("auth"), "Content-Type": "application/json"}
        rid = ctx.request.get(f"{API}/tournaments/{TID}/active-round", headers=auth).json()["round"]["id"]
        resp = ctx.request.put(f"{API}/squad/update?tournamentId={TID}",
                               data=json.dumps(_payload(t, rid)), headers=auth)
        if not resp.ok:
            ctx.close()
            sys.exit(f"PUT /squad/update failed: HTTP {resp.status} {resp.text()[:300]}")
        full = ctx.request.get(f"{API}/squad/full?tournamentId={TID}", headers=auth).json()
        ctx.close()
        _verify([p["playerId"] for p in full["players"]], t["playerIds"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--next", action="store_true", help="optimise for the next round only (default: 2-round horizon)")
    args = ap.parse_args()

    t = build_target("xp_next" if args.next else "xp_horizon")
    _print_team(t)
    if not args.confirm:
        print("\n[dry run] nothing sent. Re-run with --confirm to apply this to your TV 2 team.")
        return
    print("\napplying to TV 2...")
    _apply_and_verify(t)


if __name__ == "__main__":
    main()
