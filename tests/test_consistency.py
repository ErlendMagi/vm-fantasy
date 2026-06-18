"""Cross-tab CONSISTENCY invariants — the numbers/identities that MUST agree across
the app, so a future change can't silently make graphs/lists/tables/model disagree.

These run against the live synced data (skipped if it isn't present). Each locks one
guarantee the app surfaced as broken at some point this tournament.
"""
from collections import defaultdict

import pytest

from src import analytics, config, data_access, optimizer, services


@pytest.fixture(scope="module")
def d():
    data = services.get_data()
    if data.get("proj") is None or data.get("proj_plan") is None or data.get("my_team") is None:
        pytest.skip("no live squad/projection data")
    return data


@pytest.fixture(scope="module")
def squad(d):
    return d["my_team"]["squad"]


@pytest.fixture(scope="module")
def league(d):
    lg = services.get_live_league() or data_access.load_league()
    if not lg or not lg.get("leagues"):
        pytest.skip("no league data")
    return lg


# ── invariant: live tabs rank on the live round, planning tabs on the editable round ──
def test_ranks_live_vs_planning_distinct_sources(d):
    rl = analytics.position_ranks(d["proj"], "xp_tournament")
    rp = analytics.position_ranks(d["proj_plan"], "xp_tournament")
    assert d["ranks_live"] == rl                 # My Team / Home live tabs use this
    assert d["ranks"] == rp                       # Players / Transfers planning tabs use this


# ── invariant: the displayed captain == what choose_captain picks (one armband everywhere) ──
def test_captain_table_equals_choose_captain(d, squad):
    proj = d["proj_plan"]
    owned = proj.loc[[i for i in squad if i in proj.index]]
    ls = services.get_league_state() or {}
    fo = analytics.field_effective_ownership(ls.get("rival_squads") or [], ls.get("rival_captains"))
    tbl = optimizer.captain_options(owned, regime=ls.get("regime"), field_own=fo)
    xi = owned.loc[[i for i in optimizer.best_xi(owned, "xp_next")["xi_ids"] if i in owned.index]]
    cap, _ = optimizer.choose_captain(xi, regime=ls.get("regime"), field_own=fo)
    assert tbl.iloc[0]["name"] == owned.loc[cap, "name"]


# ── invariant: the captain is the highest availability-weighted EV starter (no regime tilt) ──
def test_captain_is_top_availability_weighted_ev(d, squad):
    proj = d["proj_plan"]
    owned = proj.loc[[i for i in squad if i in proj.index]]
    xi = owned.loc[[i for i in optimizer.best_xi(owned, "xp_next")["xi_ids"] if i in owned.index]]
    cap, vice = optimizer.choose_captain(xi)          # regime=None -> pure availability-weighted argmax
    pp = xi.get("p_play").fillna(0.85) if "p_play" in xi else None
    if pp is not None:
        ev = (xi["xp_next"].clip(lower=0) * pp)
        eligible = ev[pp >= config.CAPTAIN_PPLAY_FLOOR]
        assert cap == (eligible.idxmax() if len(eligible) else ev.idxmax())
        assert pp.get(vice, 1.0) >= config.CAPTAIN_PPLAY_FLOOR   # vice never below the play floor


# ── invariant: Home win-prob == Transfers keep-plan p_win (same title objective) ──
def test_home_winprob_matches_transfers_keep(d, squad, league):
    home = services.get_win_probability()
    if home is None:
        pytest.skip("no rivals to simulate against")
    plans = services.get_transfer_plans(squad, float(d["my_team"].get("bank", 0)),
                                        int(d["my_team"].get("free_transfers", 2)))
    keep = next((p.get("p_win") for p in plans if p["n_transfers"] == 0), None)
    assert keep is not None
    assert abs(home - keep) < 0.03                    # equal bar shared-RNG Monte-Carlo noise


# ── invariant: every group-stage transfer plan respects the hard max-2-per-team cap ──
def test_no_group_stage_three_stack_bought(d, squad):
    proj, target = d["proj_plan"], d["target_round"]
    cap = config.soft_team_cap(target)
    plans = services.get_transfer_plans(squad, float(d["my_team"].get("bank", 0)),
                                        int(d["my_team"].get("free_transfers", 2)))
    cur_counts = proj.loc[[i for i in squad if i in proj.index]]["team"].value_counts().to_dict()
    for p in plans:
        ids = [i for i in squad if i not in p["out_ids"]] + p["in_ids"]
        counts = proj.loc[[i for i in ids if i in proj.index]]["team"].value_counts()
        in_teams = {proj.loc[i, "team"] for i in p["in_ids"] if i in proj.index}
        for team in in_teams:                         # a team you bought into can't end over the cap
            assert counts.get(team, 0) <= cap, f"plan buys {team} over cap: {p['in_ids']}"
        for team, c in counts.items():                # never exceed the grandfathered count either
            assert c <= max(cap, cur_counts.get(team, 0))


# ── invariant: the BPG player-points heatmap column sums == official standings ──
def test_heatmap_columns_equal_standings(d, league):
    myname = d["my_team"].get("squad_name")
    bpg = next((L for L in league["leagues"]
                if any(m.get("squad_name") == myname for m in L.get("members", []))
                and any(m.get("rounds") for m in L.get("members", []))), None)
    if not bpg:
        pytest.skip("no BPG league with per-round scores")
    for m in bpg["members"]:
        if not m.get("rounds"):
            continue
        col = 0.0
        for r in m["rounds"]:
            st = set(r.get("starter_ids") or [])
            for pid, v in (r.get("scores") or {}).items():
                if not st or pid in st:               # only banked (starting-XI) points count
                    col += v or 0
        assert int(round(col)) == int(m.get("total_points", 0)), m["squad_name"]


# ── invariant: squad_power_index.proj_next == the fielded XI's value (captain ×2) ──
def test_spi_proj_next_equals_fielded_value(d, league):
    proj = d["proj"]
    members = [m for L in league["leagues"] for m in L.get("members", []) if m.get("squad")]
    if not members:
        pytest.skip("no rival squads yet")

    def fielded(m):
        ow = proj.loc[[i for i in m["squad"] if i in proj.index]]
        if len(ow) < 11:
            return None
        best = optimizer.best_xi(ow, "xp_next")
        starters = [i for i in (m.get("starter_ids") or []) if i in ow.index]
        xi = starters if len(starters) == 11 else best["xi_ids"]
        cap = m.get("captain_id") if m.get("captain_id") in ow.index else best["captain_id"]
        return (xi, cap)
    ff = {m["squad_name"]: fielded(m) for m in members}
    mgrs = [{"squad_name": m["squad_name"], "manager": m.get("manager"), "is_me": False,
             "squad": m["squad"], "total_points": m.get("total_points", 0)} for m in members]
    spi = analytics.squad_power_index(proj, mgrs, fielded=ff)
    for _, row in spi.iterrows():
        xi, cap = ff[row["squad_name"]]
        owned = proj.loc[[i for i in row["squad"] if i in proj.index]]
        manual = float(owned.loc[xi, "xp_next"].sum()) + (float(owned.loc[cap, "xp_next"]) if cap in xi else 0.0)
        assert abs(row["proj_next"] - manual) < 0.01, row["squad_name"]
