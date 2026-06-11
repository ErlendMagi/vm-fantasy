"""The 'consensus' team: most-owned legal squad, and my-team-vs-template frames.

Template definition (a modeling choice, shown in the app): top-2 GK, top-5 DEF,
top-5 MID, top-3 FWD by current ownership; XI = most-owned legal formation;
captain = most-owned player in the XI. Historical rounds are scored with the
players' actual round points (ownership is today's snapshot - documented bias).
"""
import pandas as pd

from src import config, optimizer


def template_squad(players: pd.DataFrame) -> pd.DataFrame | None:
    if players["ownership_pct"].isna().all():
        return None
    parts = [
        players[players["position"] == pos]
        .sort_values(["ownership_pct", "total_points"], ascending=False)
        .head(n)
        for pos, n in config.SQUAD_SHAPE.items()
    ]
    squad = pd.concat(parts)
    return squad if len(squad) == config.SQUAD_SIZE else None


def ownership_xi(squad: pd.DataFrame) -> dict:
    """Most-owned legal XI (uses best_xi machinery with ownership as the metric)."""
    tmp = squad.copy()
    tmp["_own"] = tmp["ownership_pct"].fillna(0.0)
    return optimizer.best_xi(tmp, xp_col="_own")


def squad_round_points(players: pd.DataFrame, xi_ids: list[str], captain_id: str | None,
                       round_no: int) -> int:
    pts = 0
    for pid in xi_ids:
        if pid in players.index:
            pts += players.loc[pid, "round_points"].get(round_no, 0)
    if captain_id and captain_id in players.index:
        pts += players.loc[captain_id, "round_points"].get(round_no, 0)
    return int(pts)


def comparison_frame(players: pd.DataFrame, my_team: dict, completed: list[int]) -> pd.DataFrame | None:
    """Per-round + cumulative points, mine vs template. Uses my actual round
    history when the scraper provided it, else estimates from my current XI."""
    template = template_squad(players)
    if template is None or not completed:
        return None
    t_xi = ownership_xi(template)

    my_xi_ids = my_team.get("starting_xi") or my_team.get("squad", [])[:11]
    my_captain = my_team.get("captain_id")
    history = {int(k): v for k, v in (my_team.get("round_history") or {}).items()}

    rows = []
    for r in completed:
        mine = history.get(r, squad_round_points(players, my_xi_ids, my_captain, r))
        tmpl = squad_round_points(players, t_xi["xi_ids"], t_xi["captain_id"], r)
        rows.append({"round": r, "mine": mine, "template": tmpl,
                     "mine_estimated": r not in history})
    df = pd.DataFrame(rows)
    df["mine_cum"] = df["mine"].cumsum()
    df["template_cum"] = df["template"].cumsum()
    return df


def differentials(players: pd.DataFrame, my_squad_ids: list[str]) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    template = template_squad(players)
    if template is None:
        return None
    cols = [c for c in ["name", "team", "position", "price", "ownership_pct",
                        "total_points", "xp_next", "xp_horizon"] if c in players.columns]
    mine = set(my_squad_ids)
    tmpl = set(template.index)
    mine_only = players.loc[sorted(mine - tmpl, key=lambda i: -players.loc[i].get("ownership_pct") or 0)][cols] \
        if mine - tmpl else players.head(0)[cols]
    tmpl_only = players.loc[list(tmpl - mine)][cols].sort_values("ownership_pct", ascending=False) \
        if tmpl - mine else players.head(0)[cols]
    return mine_only, tmpl_only
