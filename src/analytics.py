"""Player KPIs, position ranks and a team rating, for the engaging visuals."""
import pandas as pd

from src import config, optimizer

POS = ["GK", "DEF", "MID", "FWD"]


def position_ranks(proj: pd.DataFrame, value_col: str = "xp_tournament") -> dict:
    """player id -> rank within its position (1 = best)."""
    r = proj.groupby("position")[value_col].rank(ascending=False, method="min")
    return {idx: int(v) for idx, v in r.items()}


def add_kpis(proj: pd.DataFrame) -> pd.DataFrame:
    """Adds floor, ceiling, risk, roi, value, pos_rank (research-calibrated).

    secure  = points banked just by playing (minutes + clean sheet + saves - concede)
    attack  = volatile, event-driven points (goals + assists + MotM)
    floor   = a quiet game: ~secure, no goals needed.
    ceiling = their big game: secure + the attacking events all landing.
    risk    = chance they cost you (no-show / auto-sub) = 1 - P(play).
    roi     = actual points so far per million (purchase satisfaction).
    value   = whole-cup expected points per million (forward value).
    """
    out = proj.copy()
    secure = (out["pts_appear"] + out["pts_cs"] + out["pts_saves"] + out["pts_concede"]
              + 0.5 * out["pts_duty"]).clip(lower=0)
    attack = (out["pts_goals"] + out["pts_assists"] + out["pts_motm"]).clip(lower=0)
    out["floor"] = (secure * 0.9).round(2)
    out["ceiling"] = (secure + 2.0 * attack).round(2)
    p_play = out.get("p_play", pd.Series(0.85, index=out.index)).fillna(0.85)
    out["risk"] = (100 * (1 - p_play)).clip(0, 100).round(0)
    out["roi"] = (out["total_points"] / out["price"].clip(lower=0.1)).round(2)
    out["value"] = (out["xp_tournament"] / out["price"].clip(lower=0.1)).round(2)
    out["pos_rank"] = out.groupby("position")["xp_tournament"].rank(ascending=False, method="min").astype(int)
    return out


def squad_power_index(proj: pd.DataFrame, managers: list[dict]) -> pd.DataFrame:
    """Squad Power Index (0-100) across a field of managers: a blend of this
    round's projected XI (60%), whole-cup durability (25%) and value-per-million
    (15%), each min-max normalised across the field (robust for small leagues)."""
    rows = []
    for m in managers:
        owned = proj.loc[[i for i in m["squad"] if i in proj.index]]
        if len(owned) < 11:
            continue
        cost = max(float(owned["price"].sum()), 0.1)
        rows.append({**m,
                     "proj_next": optimizer.squad_xp(owned, "xp_next"),
                     "proj_tour": optimizer.squad_xp(owned, "xp_tournament"),
                     "cost": cost})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["eff"] = df["proj_next"] / df["cost"]

    def mm(s):
        rng = s.max() - s.min()
        return (s - s.min()) / rng if rng else pd.Series(1.0, index=s.index)

    df["SPI"] = (100 * (0.60 * mm(df["proj_next"]) + 0.25 * mm(df["proj_tour"]) + 0.15 * mm(df["eff"]))).round(1)
    return df.sort_values("SPI", ascending=False).reset_index(drop=True)


def roi_label(roi: float, total_points: float) -> str:
    if total_points == 0:
        return "⚪ no points yet"
    if roi >= 2.0:
        return "🟢 great buy"
    if roi >= 1.0:
        return "🟢 solid"
    if roi >= 0.5:
        return "🟡 ok"
    return "🔴 poor return"


def team_rating(proj: pd.DataFrame, squad_ids: list, ranks: dict, n_pool: dict | None = None) -> dict:
    """A headline 0-100 team rating + per-position average rank.

    Per-position percentile: a player ranked r of N in his position scores
    100*(1 - (r-1)/N). The team rating is the best-XI's average percentile,
    lightly tilted by captain quality. Lower avg-rank-number is better.
    """
    if n_pool is None:
        n_pool = {p: max(1, int((proj["position"] == p).sum())) for p in POS}
    owned = proj.loc[[i for i in squad_ids if i in proj.index]]
    xi = optimizer.best_xi(owned, "xp_next")
    xi_ids = [i for i in xi["xi_ids"] if i in owned.index]

    pct, pos_ranks = [], {p: [] for p in POS}
    for idx in xi_ids:
        pos = owned.loc[idx, "position"]
        r = ranks.get(idx, n_pool[pos])
        pct.append(100 * (1 - (r - 1) / n_pool[pos]))
        pos_ranks[pos].append(r)
    rating = sum(pct) / len(pct) if pct else 0.0
    avg_pos_rank = {p: (round(sum(v) / len(v), 1) if v else None) for p, v in pos_ranks.items()}
    return {"rating": round(rating, 1), "avg_pos_rank": avg_pos_rank,
            "avg_rank_overall": round(sum(ranks.get(i, 50) for i in xi_ids) / max(len(xi_ids), 1), 1)}
