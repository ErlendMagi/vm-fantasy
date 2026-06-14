"""Daily rating snapshot: computes today's squad/XI/position ratings from the
freshly synced data and upserts them into data/tv2/rating_history.json.

Run by the cloud workflow after each sync; one entry per calendar day (the
last run of the day wins, so the snapshot reflects the freshest odds/form).
The My Team page charts this history.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import advancement, analytics, config, data_access, optimizer, projections  # noqa: E402

HIST = ROOT / "data" / "tv2" / "rating_history.json"
ACC = ROOT / "data" / "tv2" / "model_accuracy.json"


def _record_accuracy(proj, my, live_round: int) -> None:
    """Persist the model's expected vs my actual points for the LIVE round, so
    the My Team page can chart calibration over the tournament. `expected` is
    locked the first time a round is seen (the model's pre/early projection for
    the XI I actually fielded); `actual` updates each run as matches finish."""
    league = data_access.load_league()
    me = None
    for lg in (league or {}).get("leagues", []):
        for mm in lg.get("members", []):
            if mm.get("squad_name") == my.get("squad_name"):
                me = mm
    if me is None:
        return
    rd = next((r for r in (me.get("rounds") or []) if r.get("number") == live_round), {})
    starters = rd.get("starter_ids") or []
    capid = rd.get("captain_id")
    if not starters:
        return
    scores = rd.get("scores") or {}

    def xp_of(pid, cap=True):
        x = float(proj.loc[pid, "xp_next"]) if pid in proj.index else 0.0
        return x * (2 if (cap and pid == capid) else 1)

    expected = round(sum(xp_of(p) for p in starters), 1)                 # full XI
    expected_played = round(sum(xp_of(p) for p in starters if p in scores), 1)  # finished games only
    actual = rd.get("points")
    played = sum(1 for v in scores.values() if v is not None)
    finalized = played >= len(starters)
    # per-position expected vs actual (captain un-doubled, for a clean level signal)
    by_pos = {}
    for p in starters:
        pos = proj.loc[p, "position"] if p in proj.index else "?"
        d = by_pos.setdefault(pos, {"expected": 0.0, "actual": 0.0, "n": 0})
        d["expected"] += xp_of(p, cap=False)
        if scores.get(p) is not None:
            d["actual"] += scores[p] / (2 if p == capid else 1)
            d["n"] += 1
    by_pos = {k: {"expected": round(v["expected"], 2), "actual": round(v["actual"], 2), "n": v["n"]}
              for k, v in by_pos.items()}

    acc = data_access.load_model_accuracy()
    rounds = acc.setdefault("rounds", {})
    entry = rounds.get(str(live_round), {})
    entry.setdefault("expected", expected)          # legacy locked field (My Team chart)
    entry["expected_full"] = expected
    entry["expected_played"] = expected_played
    entry["actual"] = int(actual) if actual is not None else entry.get("actual", 0)
    entry["played"] = played
    entry["starters"] = len(starters)
    entry["finalized"] = finalized
    entry["by_pos"] = by_pos
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    rounds[str(live_round)] = entry
    ACC.write_text(json.dumps(acc, indent=1), encoding="utf-8")
    print(f"model accuracy r{live_round}: expected {expected} (played {expected_played}) | "
          f"actual {entry['actual']} ({played}/{len(starters)} played, finalized={finalized})")
    _update_calibration(acc)


def _update_calibration(acc: dict) -> None:
    """Learn a global + positional xP scale from FINALISED rounds (every fielded
    starter's match finished), heavily shrunk toward 1.0 so a tiny sample is safe.
    Global = sum(actual)/sum(expected_played); positional re-weights relative to it."""
    fin = [v for v in acc.get("rounds", {}).values() if v.get("finalized")]
    sum_exp = sum(v.get("expected_played", v.get("expected", 0)) for v in fin)
    sum_act = sum(v.get("actual", 0) for v in fin)
    n = sum(v.get("starters", 0) for v in fin)                 # player-rounds of evidence
    if not fin or sum_exp <= 0:
        print("calibration: no finalised rounds yet - staying at 1.0")
        return
    raw = sum_act / sum_exp
    g = (n * raw + config.CALIBRATION_K0) / (n + config.CALIBRATION_K0)
    lo, hi = config.CALIBRATION_BOUNDS
    g = min(hi, max(lo, g))
    pos_scale = {}
    plo, phi = config.POSITION_CALIBRATION_BOUNDS
    for pos in ("GK", "DEF", "MID", "FWD"):
        pe = sum((v.get("by_pos", {}).get(pos, {}) or {}).get("expected", 0) for v in fin)
        pa = sum((v.get("by_pos", {}).get(pos, {}) or {}).get("actual", 0) for v in fin)
        npr = sum((v.get("by_pos", {}).get(pos, {}) or {}).get("n", 0) for v in fin)
        if pe > 0 and npr > 0:
            rel = (pa / pe) / raw                              # position level vs the global level
            ps = (npr * rel + config.POSITION_CALIBRATION_K) / (npr + config.POSITION_CALIBRATION_K)
            pos_scale[pos] = round(min(phi, max(plo, ps)), 3)
    cal = {"global_scale": round(g, 3), "positional": pos_scale, "raw": round(raw, 3),
           "n_finalized_rounds": len(fin), "updated_at": datetime.now(timezone.utc).isoformat()}
    (ROOT / "data" / "tv2" / "calibration.json").write_text(json.dumps(cal, indent=1), encoding="utf-8")
    print(f"calibration: global {cal['global_scale']} (raw {cal['raw']}, {len(fin)} finalised round(s)) "
          f"| positional {pos_scale}")


def main() -> None:
    players = data_access.load_players()
    my = data_access.load_my_team()
    if players is None or my is None:
        sys.exit("no player/team data - run sync first")
    fixtures = data_access.load_fixtures()
    mo, ou = data_access.load_match_odds(), data_access.load_outrights()
    completed = data_access.completed_rounds(fixtures)
    live_round = data_access.next_round(fixtures)
    adv = advancement.advancement_table(fixtures, mo, ou)
    p_plays = advancement.p_plays_lookup(adv)
    proj = projections.project(players, fixtures, mo, ou, completed,
                               live_round, p_plays)
    proj = analytics.add_kpis(proj)
    ranks = analytics.position_ranks(proj, "xp_tournament")

    owned = proj.loc[[i for i in my["squad"] if i in proj.index]]
    xi = optimizer.best_xi(owned, "xp_next")
    tr = analytics.team_rating(proj, my["squad"], ranks)
    sq = analytics.squad_quality(proj, my["squad"])

    today = datetime.now(timezone.utc).date().isoformat()
    hist = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {"days": {}}
    hist["days"][today] = {
        "squad_rating": sq["rating"],
        "xi_rating": tr["rating"],
        "pos_rating": tr["pos_rating"],
        "exp_next": round(xi["total"], 1),
        "points_so_far": int(sum((my.get("round_history") or {}).values())
                             or owned["total_points"].sum()),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    HIST.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    print(f"rating snapshot {today}: squad {sq['rating']} | XI {tr['rating']} | "
          f"pos {tr['pos_rating']}")
    _record_accuracy(proj, my, live_round)


if __name__ == "__main__":
    main()
