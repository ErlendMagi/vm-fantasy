"""Per-player expected points (xP) from odds, involvement proxies and heat.

Pipeline per round:
  match odds -> (mu_home, mu_away)            [poisson_fit; strength fallback]
  venue + forecast + team climate -> M        [heat multiplier on attacking output]
  team mu -> player xG/xA shares              [position * price^1.5 * form * p_start]
  xP = appearance + M*(attack) + clean-sheet - flat tax
"""
import numpy as np
import pandas as pd

from src import config, heat, poisson_fit, weather

STARTER_SLOTS = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}
GENERIC_MU = 1.3  # knockout fixture with unknown opponent


def team_strengths(outrights: dict | None) -> dict[str, float]:
    """De-vigged tournament-winner probabilities as strength ratings."""
    if not outrights or not outrights.get("prices"):
        return {}
    prices = outrights["prices"]
    probs = poisson_fit.devig(list(prices.values()))
    return dict(zip(prices.keys(), probs.tolist()))


def fixture_mus(fixtures: list[dict], match_odds: dict | None,
                strengths: dict[str, float]) -> dict[str, dict]:
    """match_id -> {mu_home, mu_away, source}. Prefers posted odds; falls back
    to outright-strength split, then to an even league-average match."""
    posted = {}
    for m in (match_odds or {}).get("matches", []):
        posted[(m["home"], m["away"], m.get("kickoff_utc", "")[:10])] = m

    out = {}
    floor = min(strengths.values()) / 2 if strengths else 0.0
    for fx in fixtures:
        key = (fx["home"], fx["away"], fx["kickoff_utc"][:10])
        odds = posted.get(key) or posted.get((fx["home"], fx["away"], ""))
        if odds is None:  # date-insensitive fallback join
            odds = next((m for k, m in posted.items() if k[0] == fx["home"] and k[1] == fx["away"]), None)
        if odds and odds.get("h2h"):
            mu_h, mu_a = poisson_fit.match_mus(odds["h2h"], odds.get("totals"))
            source = "odds"
        elif strengths:
            s_h = strengths.get(fx["home"], floor)
            s_a = strengths.get(fx["away"], floor)
            p_win_h = s_h / (s_h + s_a)
            share = 0.25 + 0.5 * p_win_h
            mu_h, mu_a = share * config.FALLBACK_MU_TOTAL, (1 - share) * config.FALLBACK_MU_TOTAL
            source = "strengths"
        else:
            mu_h = mu_a = config.FALLBACK_MU_TOTAL / 2
            source = "default"
        out[fx["match_id"]] = {"mu_home": mu_h, "mu_away": mu_a, "source": source}
    return out


def start_probabilities(players: pd.DataFrame, completed: list[int]) -> pd.DataFrame:
    """Adds p_start / p_play. Price-rank prior before round 1; evidence from
    the latest completed round afterwards."""
    df = players.copy()
    rank = df.groupby(["team", "position"])["price"].rank(ascending=False, method="first")
    slots = df["position"].map(STARTER_SLOTS)
    prior = np.where(rank <= slots, 0.75, np.where(rank <= slots + 2, 0.30, 0.10))
    if completed:
        last = max(completed)
        played = df["round_points"].apply(lambda rp: rp.get(last, 0) > 0)
        df["p_start"] = np.where(played, 0.85, np.minimum(prior, 0.20))
    else:
        df["p_start"] = prior
    df["p_play"] = np.minimum(1.0, df["p_start"] + 0.15)
    return df


def _team_attack_xp(team_players: pd.DataFrame, mu_team: float, mu_opp: float,
                    multiplier: float) -> pd.DataFrame:
    s = config.SCORING
    df = team_players
    involvement = df["price"] ** config.PRICE_INVOLVEMENT_EXP * (1 + df["ppg"] / 4) * df["p_start"]
    goal_w = df["position"].map(config.POSITION_GOAL_FACTOR) * involvement
    assist_w = df["position"].map(config.POSITION_ASSIST_FACTOR) * involvement
    xg = mu_team * goal_w / goal_w.sum() if goal_w.sum() > 0 else goal_w * 0
    xa = mu_team * config.ASSISTED_GOAL_SHARE * assist_w / assist_w.sum() if assist_w.sum() > 0 else assist_w * 0
    xg = np.minimum(xg, df["position"].map(config.MAX_GOAL_SHARE) * mu_team)
    xa = np.minimum(xa, df["position"].map(config.MAX_ASSIST_SHARE) * mu_team * config.ASSISTED_GOAL_SHARE)
    p_cs = float(np.exp(-mu_opp))

    goal_pts = df["position"].map(s["goal"])
    cs_pts = df["position"].map(s["clean_sheet"])
    xp = (
        df["p_play"] * s["appearance"]
        + df["p_start"] * s["sixty_minutes"]
        + multiplier * (xg * goal_pts + xa * s["assist"])
        + p_cs * df["p_start"] * cs_pts
        - s["flat_negative_tax"]
    )
    return pd.DataFrame({"xp": xp, "xg": xg, "xa": xa, "p_cs": p_cs, "heat_mult": multiplier})


def project_round(players: pd.DataFrame, fixtures_r: list[dict], mus: dict[str, dict],
                  stadiums: dict, climate: dict,
                  temp_fn=weather.apparent_temp_at_kickoff) -> pd.DataFrame:
    """xP for one round. Players whose team has no fixture project 0.
    Returns per-player frame: xp, heat_mult, opponent, venue, apparent_temp."""
    parts = []
    fixture_rows = []
    for fx in fixtures_r:
        mu = mus[fx["match_id"]]
        stadium = stadiums.get(fx["venue_id"])
        temp = None
        if stadium and not stadium["indoor_ac"]:
            temp = temp_fn(stadium["lat"], stadium["lon"], fx["kickoff_utc"])
        indoor = bool(stadium and stadium["indoor_ac"])
        for side, opp_side, mu_t, mu_o in [("home", "away", mu["mu_home"], mu["mu_away"]),
                                           ("away", "home", mu["mu_away"], mu["mu_home"])]:
            team = fx[side]
            tp = players[players["team"] == team]
            if tp.empty:
                continue
            mult = heat.heat_multiplier(temp, climate.get(team, "temperate"), indoor)
            part = _team_attack_xp(tp, mu_t, mu_o, mult)
            part["opponent"] = fx[opp_side]
            part["venue"] = fx["venue_id"]
            part["apparent_temp"] = np.nan if temp is None else float(temp)
            parts.append(part)
        fixture_rows.append({**fx, **mu, "apparent_temp": temp, "indoor_ac": indoor})

    if not parts:
        empty = pd.DataFrame(columns=["xp", "xg", "xa", "p_cs", "heat_mult", "opponent", "venue", "apparent_temp"])
        return empty
    result = pd.concat(parts)
    result.attrs["fixtures"] = fixture_rows
    return result


def project(players: pd.DataFrame, fixtures: list[dict], match_odds: dict | None,
            outrights: dict | None, completed: list[int], next_rnd: int,
            p_plays: dict[tuple[str, int], float] | None = None,
            temp_fn=weather.apparent_temp_at_kickoff) -> pd.DataFrame:
    """Master projection: adds xp_next, xp_after, xp_horizon (+ heat columns)
    to the players frame. p_plays[(team, round)] = P(team plays that round)."""
    from src import data_access  # local import to avoid cycles in tests

    stadiums = data_access.load_stadiums()
    climate = data_access.load_climate()
    strengths = team_strengths(outrights)
    mus = fixture_mus(fixtures, match_odds, strengths)

    df = start_probabilities(players, completed)
    df["ppg"] = df["total_points"] / max(1, len(completed))
    p_plays = p_plays or {}

    out = df.copy()
    for label, rnd in [("next", next_rnd), ("after", next_rnd + 1)]:
        fixtures_r = data_access.round_fixtures(fixtures, rnd)
        proj = project_round(df, fixtures_r, mus, stadiums, climate, temp_fn)
        out[f"xp_{label}"] = proj["xp"].reindex(out.index).fillna(0.0)
        if label == "next":
            for col in ["heat_mult", "opponent", "venue", "apparent_temp"]:
                out[col] = proj[col].reindex(out.index)
            out.attrs["fixtures_next"] = proj.attrs.get("fixtures", [])
        # teams alive but without a concrete fixture (unknown knockout pairing):
        # generic average match, no heat adjustment
        if rnd > 3:
            covered = {fx["home"] for fx in fixtures_r} | {fx["away"] for fx in fixtures_r}
            generic = ~out["team"].isin(covered)
            if generic.any():
                gen_proj = _team_attack_xp(df[generic], GENERIC_MU, GENERIC_MU, 1.0)
                out.loc[generic, f"xp_{label}"] = gen_proj["xp"]
        alive = out["team"].map(lambda t, r=rnd: p_plays.get((t, r), 1.0))
        out[f"xp_{label}"] = out[f"xp_{label}"] * alive
        if label == "next":
            out["p_plays_next"] = alive
        else:
            out["p_plays_after"] = alive

    w1, w2 = config.HORIZON_WEIGHTS
    out["xp_horizon"] = w1 * out["xp_next"] + w2 * out["xp_after"]
    return out
