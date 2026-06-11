"""Per-player expected points (xP) for the full TV 2 VM Fantasy scoring system.

Per match, per player we sum the expected value of every scoring component:
  appearance + 60min + full-match (MID/FWD)
  + goals (xG x goal_pts) + assists (xA x 3)
  + clean sheet (GK/DEF/MID) - goals-conceded penalty (GK/DEF)
  + GK saves/penalty-save
  + Man-of-the-Match bonus (3/2/1 allocated across the match by a standout weight)
  - flat discipline tax

xG/xA come from player-level betting markets (anytime-goalscorer / assist props)
when available, scaled to the team's expected goals from match odds; otherwise a
position/price/form heuristic. Attacking output is scaled by a venue-heat factor.

Valuations exposed:
  xp_next       points in the next round
  xp_horizon    next + 0.6 x the round after (x survival)  -> short-term transfers
  xp_tournament expected points over ALL remaining rounds (x survival)  -> squad build
"""
import math

import numpy as np
import pandas as pd

from src import config, data_access, heat, player_profile, poisson_fit, weather

STARTER_SLOTS = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}
GENERIC_MU = 1.3            # knockout fixture vs an unknown average opponent
MARKET_SCORER_SHARE = 0.85  # share of team xG assigned to market-quoted scorers


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
        if odds is None:
            odds = next((m for k, m in posted.items() if k[0] == fx["home"] and k[1] == fx["away"]), None)
        if odds and odds.get("h2h"):
            mu_h, mu_a = poisson_fit.match_mus(odds["h2h"], odds.get("totals"))
            source = "odds"
        elif strengths:
            s_h, s_a = strengths.get(fx["home"], floor), strengths.get(fx["away"], floor)
            p_win_h = s_h / (s_h + s_a) if (s_h + s_a) else 0.5
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
    prior = np.where(rank <= slots, 0.78, np.where(rank <= slots + 2, 0.30, 0.10))
    if completed:
        last = max(completed)
        played = df["round_points"].apply(lambda rp: rp.get(last, 0) > 0)
        df["p_start"] = np.where(played, 0.85, np.minimum(prior, 0.20))
    else:
        df["p_start"] = prior
    df["p_play"] = np.minimum(1.0, df["p_start"] + 0.15)
    return df


def _lambda_from_odds(decimal_odds: float) -> float:
    """Anytime-event decimal odds -> expected count via Poisson:
    p = 1/odds = P(>=1 event)  ->  lambda = -ln(1 - p)."""
    p = min(max(1.0 / decimal_odds, 0.02), 0.92)
    return -math.log(1.0 - p)


def _market_lambdas(df: pd.DataFrame, player_odds: dict, field: str) -> dict:
    """idx -> raw lambda for players quoted in the market for `field`."""
    out = {}
    for idx, row in df.iterrows():
        rec = player_odds.get((row["team"], data_access._fold(row["name"])))
        if rec and rec.get(field):
            out[idx] = _lambda_from_odds(rec[field])
    return out


def _distribute(df: pd.DataFrame, total: float, raw_market: dict,
                heuristic_w: pd.Series, market_share: float) -> pd.Series:
    """Split `total` expected events across players: market-quoted players take
    `market_share` (by their odds), the rest split the remainder by heuristic."""
    out = pd.Series(0.0, index=df.index)
    quoted = list(raw_market)
    if quoted and total > 0:
        sm = sum(raw_market.values())
        for idx in quoted:
            out[idx] = market_share * total * raw_market[idx] / sm
        rest = [i for i in df.index if i not in raw_market]
        w = heuristic_w.loc[rest]
        if rest and w.sum() > 0:
            out.loc[rest] = (1 - market_share) * total * w / w.sum()
    elif heuristic_w.sum() > 0:
        out = total * heuristic_w / heuristic_w.sum()
    return out


def _team_xp(df: pd.DataFrame, mu_team: float, mu_opp: float, multiplier: float,
             player_odds: dict, duties: dict | None = None, full90_p: float = 0.70) -> pd.DataFrame:
    """Base per-player xP for one team in one match (everything except the
    Man-of-the-Match bonus, which needs both teams). Also returns the standout
    weight `w` used to allocate MotM."""
    s = config.SCORING
    involvement = df["price"] ** config.PRICE_INVOLVEMENT_EXP * (1 + df["ppg"] / 4) * df["p_start"]
    goal_w = df["position"].map(config.POSITION_GOAL_FACTOR) * involvement
    assist_w = df["position"].map(config.POSITION_ASSIST_FACTOR) * involvement

    market_goal_idx = set(_market_lambdas(df, player_odds, "anytime_goal"))
    xg = _distribute(df, mu_team, _market_lambdas(df, player_odds, "anytime_goal"),
                     goal_w, MARKET_SCORER_SHARE)
    xa = _distribute(df, config.ASSISTED_GOAL_SHARE * mu_team,
                     _market_lambdas(df, player_odds, "assist"), assist_w, MARKET_SCORER_SHARE)
    xg = np.minimum(xg, df["position"].map(config.MAX_GOAL_SHARE) * mu_team)
    xa = np.minimum(xa, df["position"].map(config.MAX_ASSIST_SHARE) * mu_team * config.ASSISTED_GOAL_SHARE)

    p_cs = float(np.exp(-mu_opp))                      # Poisson zero -> clean sheet
    goal_pts = df["position"].map(s["goal"])
    cs_pts = df["position"].map(s["clean_sheet"])
    concede = df["position"].map(s["concede_per2"]) * (mu_opp / 2.0)
    full_match = df["position"].map(s["full_match"]) * df["p_start"] * full90_p  # P(plays 90 | starts)

    is_gk = (df["position"] == "GK").astype(float)
    gk_saves = is_gk * (2.5 + 0.85 * mu_opp) / 3.0 * s["save_per3"] * df["p_start"]

    # per-component expected points (so value is transparently more than goals)
    pts_appear = df["p_play"] * s["appearance"] + df["p_start"] * s["sixty_minutes"] + full_match
    pts_goals = multiplier * xg * goal_pts
    pts_assists = multiplier * xa * s["assist"]
    pts_cs = p_cs * df["p_start"] * cs_pts
    pts_concede = -df["p_start"] * concede
    pts_saves = gk_saves
    pts_tax = pd.Series(-s["flat_negative_tax"], index=df.index)

    # duty bonuses: set-piece assists (not captured by any market we use) always;
    # penalty duty only when xG is NOT market-quoted (bookies price pen duty in)
    pts_duty = pd.Series(0.0, index=df.index)
    team_duty = (duties or {}).get(df["team"].iloc[0] if len(df) else "", None)
    if team_duty:
        from src.data_access import _fold, duty_rank
        for idx, row in df.iterrows():
            folded = _fold(row["name"])
            sp = duty_rank(folded, team_duty.get("sp", []))
            if sp is not None and sp < len(config.DUTY_RANK_MULT):
                pts_duty[idx] += config.DUTY_SP_BONUS * config.DUTY_RANK_MULT[sp] * row["p_start"] * multiplier
            if idx not in market_goal_idx:
                pen = duty_rank(folded, team_duty.get("pen", []))
                if pen is not None and pen < len(config.DUTY_RANK_MULT):
                    pts_duty[idx] += (config.DUTY_PEN_BONUS.get(row["position"], 0.6)
                                      * config.DUTY_RANK_MULT[pen] * row["p_start"] * multiplier)

    xp_base = pts_appear + pts_goals + pts_assists + pts_cs + pts_concede + pts_saves + pts_duty + pts_tax

    # standout weight ~ what wins a high match rating: dominated by attacking
    # output (goals/assists), small per-position prior, GK clean-sheet heroics
    prior = df["position"].map(config.MOTM_POSITION_PRIOR)
    w = 3.0 * xg + 2.0 * xa + prior * df["p_start"] + 0.4 * p_cs * df["p_start"] * is_gk
    return pd.DataFrame({
        "xp_base": xp_base, "xg": xg, "xa": xa, "p_cs": p_cs, "heat_mult": multiplier, "w": w,
        "pts_appear": pts_appear, "pts_goals": pts_goals, "pts_assists": pts_assists,
        "pts_cs": pts_cs, "pts_concede": pts_concede, "pts_saves": pts_saves, "pts_duty": pts_duty,
    })


def _win_probs(mu_h: float, mu_a: float) -> tuple[float, float]:
    ph, _, pa = poisson_fit.outcome_probs(mu_h, mu_a)
    return ph, pa


def _generic_ko_mu(team: str, strengths: dict, avg_s: float) -> tuple[float, float]:
    """Expected goals for/against in a generic knockout tie, scaled by the
    team's strength vs the average surviving team. Stronger teams score more and
    concede fewer (so their defenders/keepers earn more clean-sheet points)."""
    s = strengths.get(team, avg_s)
    p_win = s / (s + avg_s) if (s + avg_s) > 0 else 0.5
    base = config.KNOCKOUT_BASE_MU
    return base * (0.6 + 0.8 * p_win), base * (0.6 + 0.8 * (1 - p_win))


def project_round(players: pd.DataFrame, fixtures_r: list[dict], mus: dict[str, dict],
                  stadiums: dict, climate: dict, player_odds: dict,
                  temp_fn=weather.apparent_temp_at_kickoff, duties: dict | None = None,
                  stage: str = "group") -> pd.DataFrame:
    """xP for one round, including the match-level MotM allocation. Knockout
    stages scale scoring down (tighter games -> fewer goals, more clean sheets)
    and raise the full-90 probability (no dead rubbers / extra time)."""
    goal_scale = config.STAGE_GOAL_SCALE.get(stage, 1.0)
    full90_p = config.STAGE_FULL90_P.get(stage, 0.70)
    parts, fixture_rows = [], []
    for fx in fixtures_r:
        mu = {"mu_home": mus[fx["match_id"]]["mu_home"] * goal_scale,
              "mu_away": mus[fx["match_id"]]["mu_away"] * goal_scale,
              "source": mus[fx["match_id"]].get("source")}
        stadium = stadiums.get(fx["venue_id"])
        temp = temp_fn(stadium["lat"], stadium["lon"], fx["kickoff_utc"]) \
            if stadium and not stadium["indoor_ac"] else None
        indoor = bool(stadium and stadium["indoor_ac"])
        p_home, p_away = _win_probs(mu["mu_home"], mu["mu_away"])

        sides = []
        for side, opp, mu_t, mu_o, p_win, p_lose in [
                ("home", "away", mu["mu_home"], mu["mu_away"], p_home, p_away),
                ("away", "home", mu["mu_away"], mu["mu_home"], p_away, p_home)]:
            tp = players[players["team"] == fx[side]]
            if tp.empty:
                continue
            mult = heat.heat_multiplier(temp, climate.get(fx[side], "temperate"), indoor)
            part = _team_xp(tp, mu_t, mu_o, mult, player_odds, duties, full90_p)
            part["opponent"] = fx[opp]
            part["venue"] = fx["venue_id"]
            part["apparent_temp"] = np.nan if temp is None else float(temp)
            # result factor: winners win MotM more often
            part["_rf"] = 1.0 + config.MOTM_RESULT_WEIGHT * (p_win - p_lose)
            sides.append(part)

        if sides:
            match = pd.concat(sides)
            denom = float((match["w"] * match["_rf"]).sum())
            motm = (config.MOTM_POINTS_PER_MATCH * match["w"] * match["_rf"] / denom) if denom > 0 \
                else match["w"] * 0.0
            match["xp"] = match["xp_base"] + motm
            match["pts_motm"] = motm
            parts.append(match.drop(columns=["_rf"]))
        fixture_rows.append({**fx, **mu, "apparent_temp": temp, "indoor_ac": indoor,
                             "p_home_win": p_home, "p_away_win": p_away})

    cols = ["xp", "xp_base", "pts_motm", "xg", "xa", "p_cs", "heat_mult", "opponent", "venue",
            "apparent_temp", "pts_appear", "pts_goals", "pts_assists", "pts_cs", "pts_concede",
            "pts_saves", "pts_duty"]
    if not parts:
        return pd.DataFrame(columns=cols)
    result = pd.concat(parts)
    result.attrs["fixtures"] = fixture_rows
    return result


def project(players: pd.DataFrame, fixtures: list[dict], match_odds: dict | None,
            outrights: dict | None, completed: list[int], next_rnd: int,
            p_plays: dict[tuple[str, int], float] | None = None,
            temp_fn=weather.apparent_temp_at_kickoff,
            player_odds: dict | None = None) -> pd.DataFrame:
    """Adds xp_next, xp_after, xp_horizon, xp_tournament (+ detail columns)."""
    stadiums = data_access.load_stadiums()
    climate = data_access.load_climate()
    duties = data_access.load_duties()
    if player_odds is None:
        player_odds = data_access.load_player_odds()
    strengths = team_strengths(outrights)
    mus = fixture_mus(fixtures, match_odds, strengths)

    df = start_probabilities(players, completed)
    df["ppg"] = df["total_points"] / max(1, len(completed))
    p_plays = p_plays or {}

    component_cols = ["pts_appear", "pts_goals", "pts_assists", "pts_cs", "pts_concede",
                      "pts_saves", "pts_duty", "pts_motm"]
    out = df.copy()
    per_match, comps_next = {}, None
    for label, rnd in [("next", next_rnd), ("after", next_rnd + 1)]:
        if rnd > 8:
            out[f"xp_{label}"] = 0.0
            per_match[label] = pd.Series(0.0, index=out.index)
            if label == "after":
                out["p_plays_after"] = 0.0
            continue
        stage = config.STAGE_OF_ROUND.get(rnd, "group")
        fixtures_r = data_access.round_fixtures(fixtures, rnd)
        proj = project_round(df, fixtures_r, mus, stadiums, climate, player_odds, temp_fn, duties, stage)
        raw = proj["xp"].reindex(out.index).astype(float).fillna(0.0)
        if label == "next":
            for col in ["xg", "xa", "heat_mult", "opponent", "venue", "apparent_temp"]:
                out[col] = proj[col].reindex(out.index)
            comps_next = proj.reindex(out.index).reindex(columns=component_cols).fillna(0.0)
            out["motm"] = comps_next["pts_motm"]
            out.attrs["fixtures_next"] = proj.attrs.get("fixtures", [])
        if rnd > 3:  # knockout round with unknown pairings -> strength-aware generic tie
            covered = {fx["home"] for fx in fixtures_r} | {fx["away"] for fx in fixtures_r}
            generic = ~out["team"].isin(covered)
            full90_p = config.STAGE_FULL90_P.get(stage, 0.82)
            avg_s = (sum(strengths.values()) / len(strengths)) if strengths else 1.0
            for team, tp in df[generic].groupby("team"):
                mu_for, mu_against = _generic_ko_mu(team, strengths, avg_s)
                g = _team_xp(tp, mu_for, mu_against, 1.0, player_odds, duties, full90_p)
                raw.loc[g.index] = g["xp_base"] + config.MOTM_POINTS_PER_MATCH * g["w"] / max(g["w"].sum(), 1e-9) / 2
        per_match[label] = raw

    # dynamic form: blend the odds prior with observed fantasy points so far
    prior_ppm = (per_match["next"] + per_match["after"]) / 2.0
    form = player_profile.form_multiplier(df, completed, prior_ppm)
    out["form_mult"] = form
    for label in ("next", "after"):
        per_match[label] = per_match[label] * form
    if comps_next is not None:
        comps_next = comps_next.mul(form, axis=0)
        for col in component_cols:
            out[col] = comps_next[col]

    for label, rnd in [("next", next_rnd), ("after", next_rnd + 1)]:
        alive = out["team"].map(lambda t, r=rnd: p_plays.get((t, r), 1.0)) if rnd <= 8 \
            else pd.Series(0.0, index=out.index)
        out[f"xp_{label}"] = per_match[label] * alive
        out[f"p_plays_{label}"] = alive

    w1, w2 = config.HORIZON_WEIGHTS
    out["xp_horizon"] = w1 * out["xp_next"] + w2 * out["xp_after"]

    # tournament-long value: a smoothed per-match base x expected remaining matches
    base = (per_match["next"] + per_match["after"]) / 2.0
    base = base.where(base > 0, per_match["next"])
    rem = pd.Series(0.0, index=out.index)
    for r in range(next_rnd, 9):
        w = config.TOURNAMENT_DECAY ** (r - next_rnd)
        rem = rem + out["team"].map(lambda t, rr=r: p_plays.get((t, rr), 1.0 if rr <= 3 else 0.0)) * w
    out["xp_tournament"] = base * rem
    return out
