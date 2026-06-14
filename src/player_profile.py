"""Dynamic per-player profile: turns each completed round's ACTUAL fantasy
points and minutes into a form/role signal, blended with the odds-based model
prior. Weight on observed data grows as games accumulate (shrinkage), so the
model self-corrects after every match without overreacting to one game.

Sources, all refreshed each sync:
  - round_points (actual TV 2 fantasy points per round) -> form
  - which rounds the player actually scored/appeared -> minutes reliability
  - the odds-based model prior (per-match xP) -> the anchor before any games

Tonight (no completed rounds) every multiplier is 1.0 and start probs come from
the price prior; the mechanism activates automatically once round 1 is scored.
"""
import numpy as np
import pandas as pd

from src import config


def observed_stats(players: pd.DataFrame, completed: list[int]) -> pd.DataFrame:
    """Per-player observed history over the completed rounds."""
    out = pd.DataFrame(index=players.index)
    if not completed:
        out["games_appeared"] = 0
        out["observed_ppg"] = np.nan
        out["started_last"] = np.nan
        return out
    last = max(completed)

    def appeared(rp):
        return [r for r in completed if rp.get(r, 0) != 0]

    apps = players["round_points"].apply(appeared)
    out["games_appeared"] = apps.apply(len)
    pts = players["round_points"].apply(lambda rp: sum(rp.get(r, 0) for r in completed))
    out["observed_ppg"] = np.where(out["games_appeared"] > 0, pts / out["games_appeared"].clip(lower=1), np.nan)
    out["started_last"] = players["round_points"].apply(lambda rp: rp.get(last, 0) != 0)
    return out


def minutes_start_prob(players: pd.DataFrame, completed: list[int]) -> pd.Series | None:
    """Observed start probability from FotMob minutes over completed rounds:
    a player averaging ~90' is a nailed starter, ~0' is benched. Returns None
    when no enriched stats are available yet (graceful no-op).

    Minutes are the single most predictive fantasy signal — far better than 'did
    they score fantasy points', which misses a 90-minute blank from a starter.
    """
    from src import data_access
    store = data_access.load_player_stats().get("rounds", {})
    if not completed or not store:
        return None
    obs = pd.Series(np.nan, index=players.index)
    for idx in players.index:
        mins = []
        for r in completed:
            rec = (store.get(str(r), {}).get("players", {}) or {}).get(idx)
            if rec and rec.get("minutes") is not None:
                mins.append(min(float(rec["minutes"]), 95.0))
        if mins:
            # recent-weighted mean minutes / 90, with a soft cap
            w = np.linspace(1.0, 1.6, len(mins))
            avg = float(np.average(mins, weights=w))
            obs[idx] = min(0.97, max(0.05, avg / 90.0))
    return obs if obs.notna().any() else None


def observed_attacking(players: pd.DataFrame, completed: list[int]) -> pd.DataFrame:
    """Observed xG/xA per 90 from FotMob (minutes-weighted, recent-weighted),
    ignoring cameos. NaN where there's no data yet. Used to sharpen WHO a team's
    goals/assists go to — real shot volume is steadier than goals themselves."""
    out = pd.DataFrame(index=players.index)
    out["xg_per90"] = np.nan
    out["xa_per90"] = np.nan
    out["att_games"] = 0
    from src import data_access
    store = data_access.load_player_stats().get("rounds", {})
    if not completed or not store:
        return out
    for idx in players.index:
        xs, as_, mins = [], [], []
        for r in completed:
            rec = (store.get(str(r), {}).get("players", {}) or {}).get(idx)
            if rec and rec.get("minutes") and float(rec["minutes"]) >= 20:   # skip cameos
                mins.append(float(rec["minutes"]))
                xs.append(float(rec["xg"]) if rec.get("xg") is not None else np.nan)
                as_.append(float(rec["xa"]) if rec.get("xa") is not None else np.nan)
        if mins and np.isfinite(np.nansum(xs + as_)):
            w = np.linspace(1.0, 1.6, len(mins))                              # recency weight
            tot = float(np.dot(mins, w))
            out.loc[idx, "xg_per90"] = float(np.nansum(np.array(xs) * w)) / tot * 90 if tot else np.nan
            out.loc[idx, "xa_per90"] = float(np.nansum(np.array(as_) * w)) / tot * 90 if tot else np.nan
            out.loc[idx, "att_games"] = len(mins)
    return out


def form_multiplier(players: pd.DataFrame, completed: list[int], prior_ppm: pd.Series) -> pd.Series:
    """Blend each player's observed points-per-appearance with their model
    prior (per-match xP) via shrinkage; return a bounded multiplier on the
    prior. After g games the observed weight is g / (g + K)."""
    if not completed:
        return pd.Series(1.0, index=players.index)
    stats = observed_stats(players, completed)
    g = stats["games_appeared"].to_numpy(dtype=float)
    obs = stats["observed_ppg"].to_numpy(dtype=float)
    prior = prior_ppm.reindex(players.index).to_numpy(dtype=float)

    K = config.FORM_SHRINKAGE_K
    w_obs = np.where(g > 0, g / (g + K), 0.0)
    obs_filled = np.where(np.isnan(obs), prior, obs)
    blended = (1 - w_obs) * prior + w_obs * obs_filled
    with np.errstate(divide="ignore", invalid="ignore"):
        mult = np.where(prior > 0.2, blended / prior, 1.0)
    lo, hi = config.FORM_MULT_BOUNDS
    return pd.Series(np.clip(np.nan_to_num(mult, nan=1.0), lo, hi), index=players.index)
