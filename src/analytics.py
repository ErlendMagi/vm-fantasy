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


def live_motm_weight(stats: dict | None) -> float:
    """Standout weight from LIVE match stats — what actually decides Man of the
    Match: the FotMob rating first, then goals/assists, with the awarded POTM
    pinned on top. Returns 0 if the player isn't on the pitch (so people who
    aren't playing can't show up as MotM candidates)."""
    if not stats or (stats.get("rating") is None and (stats.get("minutes") or 0) <= 0):
        return 0.0      # not on the pitch (FotMob omits 'minutes' mid-match, so rating is the tell)
    r = stats.get("rating") or 0.0
    w = (max(0.0, r - 5.0) ** 2.2) if r else 0.3        # rating above average, steepened
    w += 5.0 * (stats.get("goals") or 0) + 3.0 * (stats.get("assists") or 0)
    if stats.get("is_potm"):
        w += 25.0                                        # the actually-awarded POTM dominates
    return float(w)


def motm_probabilities(weights: dict) -> dict:
    """P(player finishes 1st / 2nd / 3rd best in a match) from per-player standout
    weights, via the Plackett-Luce ranking model. We use each player's expected
    Man-of-the-Match points (pts_motm) as the weight — it already encodes
    attacking output, result and a position prior. Returns {pid: {p1, p2, p3}}."""
    items = [(pid, max(float(w), 0.0)) for pid, w in weights.items()]
    W = sum(w for _, w in items)
    if W <= 0 or len(items) < 2:
        u = 1.0 / len(items) if items else 0.0
        return {pid: {"p1": u, "p2": u, "p3": u} for pid, _ in items}
    p1 = {pid: w / W for pid, w in items}
    p2 = {pid: 0.0 for pid, _ in items}
    for j, wj in items:                       # j is first, i is second
        d1 = W - wj
        if d1 <= 0:
            continue
        pj = wj / W
        for i, wi in items:
            if i != j:
                p2[i] += pj * (wi / d1)
    p3 = {pid: 0.0 for pid, _ in items}
    top = sorted(items, key=lambda x: -x[1])[:14]   # tail weights ≈ 0; bound the O(n^3)
    for j, wj in top:
        d1 = W - wj
        if d1 <= 0:
            continue
        pj = wj / W
        for k, wk in top:
            if k == j:
                continue
            d2 = d1 - wk
            if d2 <= 0:
                continue
            pjk = pj * (wk / d1)
            for i, wi in items:
                if i != j and i != k:
                    p3[i] += pjk * (wi / d2)
    return {pid: {"p1": p1.get(pid, 0.0), "p2": p2.get(pid, 0.0), "p3": p3.get(pid, 0.0)} for pid, _ in items}


def squad_risk(proj: pd.DataFrame, squad_ids: list[str], captain_id=None,
               value_col: str = "xp_next", gap_to_field=None, rounds_left=None) -> dict | None:
    """Concentration / variance risk of the scoring XI, so one bad match can't
    quietly tank a round. All from existing proj columns. Returns:
      enb_match        effective number of independent 'bets' (matches your points
                       are spread across, Herfindahl-penalised for lumpiness)
      max_match_share  fraction of the round riding on the single biggest match
      top_match        that match's name
      captain_share    fraction riding on the captain's doubling
      cs_share         fraction of expected points that are clean-sheet points
                       (a single 'low-scoring round' bet across all your defenders)
      sd_round / cv    round-total standard deviation and coefficient of variation
      floor/exp/ceiling the XI's downside, expected and upside totals
      regime           leader / chaser / coinflip + advice, from the league gap
    """
    owned = proj.loc[[i for i in squad_ids if i in proj.index]]
    if len(owned) < 11:
        return None
    xi = optimizer.best_xi(owned, value_col)
    x = owned.loc[[i for i in xi["xi_ids"] if i in owned.index]].copy()
    cap = captain_id if captain_id in set(x.index) else xi["captain_id"]
    mult = pd.Series(1.0, index=x.index)
    if cap in mult.index:
        mult[cap] = float(config.CAPTAIN_MULTIPLIER)
    x["w"] = (x[value_col].clip(lower=0) * mult)
    total = float(x["w"].sum()) or 1.0

    opp = x["opponent"] if "opponent" in x.columns else x["team"]
    x["match"] = [" – ".join(sorted({str(t), str(o)})) for t, o in zip(x["team"], opp)]
    by_match = x.groupby("match")["w"].sum() / total
    hhi = float((by_match ** 2).sum())
    enb = (1.0 / hhi) if hhi else float(len(x))
    top_match = str(by_match.idxmax())
    max_match_share = float(by_match.max())

    by_team = x.groupby("team")["w"].sum() / total
    max_team_share = float(by_team.max())
    max_team_count = int(x["team"].value_counts().max())

    captain_share = float((mult.get(cap, 1.0) - 1.0) * x.loc[cap, value_col] / total) if cap in x.index else 0.0
    cap_match = x.loc[cap, "match"] if cap in x.index else None
    captain_shares_match = bool(cap_match is not None and int((x["match"] == cap_match).sum()) > 1)

    cs_share = float((x["pts_cs"] * mult).sum() / total)

    # per-player variance proxy: secure points are steady, event points lumpy
    secure = (x["pts_appear"] + x["pts_cs"] + x["pts_saves"] + x["pts_concede"]
              + 0.5 * x["pts_duty"]).clip(lower=0)
    event = (x["pts_goals"] + x["pts_assists"] + x["pts_motm"]).clip(lower=0)
    ppe = x["position"].map(config.SCORING["goal"]).fillna(5.0)
    var_i = (0.5 * secure + 1.0 * ppe * event) * (mult ** 2)   # Var(2X)=4Var(X) for captain
    sd_round = float(var_i.sum() ** 0.5)
    cv = sd_round / total if total else 0.0

    floor_sum = float((x["floor"] * mult).sum())
    ceiling_sum = float((x["ceiling"] * mult).sum())

    flags = []
    if captain_shares_match:
        flags.append(f"⚠️ Captain shares a match with another starter — a flat {top_match} doubles down.")
    if max_match_share > 0.30:
        flags.append(f"⚠️ {max_match_share * 100:.0f}% of your round rides on one match ({top_match}).")
    if cs_share > 0.33:
        flags.append(f"⚠️ {cs_share * 100:.0f}% of your points are clean sheets — exposed to an open, high-scoring round.")
    if max_team_count >= 3:
        flags.append(f"⚠️ {max_team_count} starters from one nation — a single result moves them together.")
    if not flags:
        flags.append("✅ Well spread — no single match, team or the captain dominates the round.")

    regime, regime_msg = "unknown", ""
    if gap_to_field is not None and rounds_left is not None and sd_round > 0:
        band = 1.5 * sd_round * (max(int(rounds_left), 1) ** 0.5)
        if gap_to_field > band:
            regime = "leader"
            regime_msg = (f"You lead the field by {gap_to_field:.0f} with ~{rounds_left} rounds left → "
                          "**diversify**. Keep variance low (high effective-bets, no stacked match/captain); "
                          "you only need to not blow up.")
        elif gap_to_field < -band:
            regime = "chaser"
            regime_msg = (f"You trail by {abs(gap_to_field):.0f} with ~{rounds_left} rounds left → you may need "
                          "**variance**. A differential stack your rivals don't own (lower effective-bets) is OK "
                          "here — a steady score won't catch them.")
        else:
            regime = "coinflip"
            regime_msg = (f"The race is tight ({gap_to_field:+.0f}, ~{rounds_left} rounds left) → play the "
                          "**expected-points optimum** and just avoid a single point of failure.")

    return {"enb_match": enb, "max_match_share": max_match_share, "top_match": top_match,
            "max_team_share": max_team_share, "max_team_count": max_team_count,
            "captain_share": captain_share, "captain_shares_match": captain_shares_match,
            "cs_share": cs_share, "sd_round": sd_round, "cv": cv,
            "floor": floor_sum, "expected": total, "ceiling": ceiling_sum,
            "by_match": by_match.sort_values(ascending=False), "captain_id": cap,
            "flags": flags, "regime": regime, "regime_msg": regime_msg}


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


def transfer_reasons(out_row, in_row) -> list[tuple[str, bool]]:
    """Human-readable (reason, is_upgrade) chips explaining a swap, from the
    component deltas. Sorted by impact."""
    out = []

    def add(delta, label_pos, label_neg, thresh=0.25):
        if abs(delta) >= thresh:
            out.append((abs(delta), f"{'+' if delta > 0 else '−'}{abs(delta):.1f} {label_pos if delta > 0 else label_neg}",
                        delta > 0))

    add(in_row["pts_goals"] - out_row["pts_goals"], "goal threat", "goal threat")
    add(in_row["pts_assists"] - out_row["pts_assists"], "assist threat", "assist threat", 0.15)
    add(in_row["pts_cs"] - out_row["pts_cs"], "clean-sheet pts", "clean-sheet pts", 0.2)
    add(in_row["pts_duty"] - out_row["pts_duty"], "set-piece/pen value", "set-piece/pen value", 0.15)
    add(in_row["pts_appear"] - out_row["pts_appear"], "minutes security", "minutes security", 0.3)
    dsurv = (in_row.get("p_plays_after", 1) or 1) - (out_row.get("p_plays_after", 1) or 1)
    if abs(dsurv) >= 0.1:
        out.append((abs(dsurv) * 5, f"{'+' if dsurv > 0 else '−'}{abs(dsurv):.0%} survival odds", dsurv > 0))
    dprice = out_row["price"] - in_row["price"]
    if abs(dprice) >= 0.5:
        out.append((abs(dprice) * 0.3, f"{'frees' if dprice > 0 else 'costs'} {abs(dprice):.1f}M", dprice > 0))
    out.sort(reverse=True)
    return [(txt, up) for _, txt, up in out]


def squad_quality(proj: pd.DataFrame, squad_ids: list) -> dict:
    """Average quality percentile across ALL squad players (not just the XI).
    A player ranked r of N in his position scores 100*(1-(r-1)/N)."""
    n_pool = {p: max(1, int((proj["position"] == p).sum())) for p in POS}
    owned = proj.loc[[i for i in squad_ids if i in proj.index]]
    pct = [100 * (1 - (int(r["pos_rank"]) - 1) / n_pool[r["position"]]) for _, r in owned.iterrows()]
    return {"rating": round(sum(pct) / len(pct), 1) if pct else 0.0,
            "avg_rank": round(float(owned["pos_rank"].mean()), 1) if len(owned) else None}


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
    pos_rating = {p: (round(100 * (1 - (sum(v) / len(v) - 1) / n_pool[p]), 1) if v else None)
                  for p, v in pos_ranks.items()}
    return {"rating": round(rating, 1), "avg_pos_rank": avg_pos_rank, "pos_rating": pos_rating,
            "avg_rank_overall": round(sum(ranks.get(i, 50) for i in xi_ids) / max(len(xi_ids), 1), 1)}
