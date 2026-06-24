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
    xi = owned.loc[[i for i in optimizer.best_xi(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)["xi_ids"]
                    if i in owned.index]]
    cap, _ = optimizer.choose_captain(xi, regime=ls.get("regime"), field_own=fo)
    assert tbl.iloc[0]["name"] == owned.loc[cap, "name"]


# ── invariant: the captain is the highest availability-weighted EV LIKELY-STARTER (no regime tilt) ──
def test_captain_is_top_availability_weighted_ev(d, squad):
    proj = d["proj_plan"]
    owned = proj.loc[[i for i in squad if i in proj.index]]
    xi = owned.loc[[i for i in optimizer.best_xi(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)["xi_ids"]
                    if i in owned.index]]
    cap, vice = optimizer.choose_captain(xi)          # regime=None -> pure availability-weighted argmax
    pp = xi.get("p_play").fillna(0.85) if "p_play" in xi else None
    ps = xi.get("p_start").fillna(1.0) if "p_start" in xi else None
    if pp is not None:
        ev = (xi["xp_next"].clip(lower=0) * pp)
        # the armband gate requires BOTH the play floor and the start floor (no unproven captain)
        gate = (pp >= config.CAPTAIN_PPLAY_FLOOR) & (ps >= config.XI_PSTART_FLOOR)
        eligible = ev[gate]
        assert cap == (eligible.idxmax() if len(eligible) else ev.idxmax())
        assert pp.get(vice, 1.0) >= config.CAPTAIN_PPLAY_FLOOR   # vice never below the play floor
        assert ps.get(vice, 1.0) >= config.XI_PSTART_FLOOR or len(eligible) == 0   # nor unproven


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
        hits = 0.0                                    # transfer_hit is stored signed (e.g. -8)
        for r in m["rounds"]:
            hits += r.get("transfer_hit", 0) or 0
            st = set(r.get("starter_ids") or [])
            for pid, v in (r.get("scores") or {}).items():
                if not st or pid in st:               # only banked (starting-XI) points count
                    col += v or 0
        # standings = gross banked XI points NET of −4/transfer-hit penalties
        assert int(round(col + hits)) == int(m.get("total_points", 0)), m["squad_name"]


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


# ── invariant: the applied XI fields every available likely-starter before any benched
#    player — a proven starter is NEVER sat for a likely-benched one at the same position
#    (tiered playtime guarantee; a thin squad may still field fillers, but only as a last resort) ──
def test_applied_xi_no_proven_player_benched(d, squad):
    import scraper.apply_team as apply
    proj = d["proj_plan"]
    t = apply.compose_lineup(proj, list(squad))
    owned = proj.loc[[i for i in squad if i in proj.index]]
    floor = config.XI_PSTART_FLOOR
    started = set(t["starterIds"])
    for pos in ("GK", "DEF", "MID", "FWD"):
        pool = owned[owned["position"] == pos]
        # a below-floor STARTER at this position is only allowed if NO above-floor squad
        # player of the same position was left on the bench (i.e. we used every proven one)
        benched_proven = [i for i in pool.index if i not in started and pool.loc[i, "p_start"] >= floor]
        sub_floor_starters = [i for i in pool.index if i in started and pool.loc[i, "p_start"] < floor]
        if sub_floor_starters:
            assert not benched_proven, (
                f"{pos}: benched proven {[proj.loc[i,'name'] for i in benched_proven]} "
                f"while starting unproven {[proj.loc[i,'name'] for i in sub_floor_starters]}")


# ── invariant: a player we've seen ZERO minutes of (once games exist) is capped below the
#    fielding/buy floors — an unknown is never auto-fielded on a bare price prior ──
def test_unproven_player_capped_below_floor(d, squad):
    proj = d["proj_plan"]
    unproven = proj[proj.get("p_start_src") == "unproven"]
    if unproven.empty:
        pytest.skip("no unproven players in the pool (all have minutes or lineups)")
    assert (unproven["p_start"] <= config.UNPROVEN_PSTART + 1e-9).all()
    assert config.UNPROVEN_PSTART < config.XI_PSTART_FLOOR        # so it's never fielded
    assert config.UNPROVEN_PSTART < config.BUY_PSTART_FLOOR       # nor bought


# ── invariant: a manual override is honoured above every model signal (your real-world knowledge) ──
def test_manual_override_benches_a_player(d, squad):
    from src import projections, data_access
    players = data_access.load_players()
    completed = data_access.completed_rounds(data_access.load_fixtures())
    target = next(iter(players.index))
    base = projections.start_probabilities(players, completed)
    forced = projections.start_probabilities(players, completed,
                                             manual={"players": {target: "out"}})
    assert forced.loc[target, "p_start"] == config.MANUAL_PSTART["out"]
    assert str(forced.loc[target, "p_start_src"]).startswith("manual")
    # and it actually drops a player who would otherwise have started
    if base.loc[target, "p_start"] >= config.XI_PSTART_FLOOR:
        assert forced.loc[target, "p_start"] < config.XI_PSTART_FLOOR


# ── invariant: the captain/vice is never an unproven (0-minute) player when a proven starter exists ──
def test_captain_never_unproven(d, squad):
    proj = d["proj_plan"]
    owned = proj.loc[[i for i in squad if i in proj.index]]
    xi_ids = optimizer.best_xi(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)["xi_ids"]
    xi = owned.loc[[i for i in xi_ids if i in owned.index]]
    cap, vice = optimizer.choose_captain(xi)
    if (xi["p_start"] >= config.XI_PSTART_FLOOR).any():     # a likely starter is available to captain
        assert xi.loc[cap, "p_start"] >= config.XI_PSTART_FLOOR, f"captain unproven: {proj.loc[cap,'name']}"
        assert xi.loc[vice, "p_start"] >= config.XI_PSTART_FLOOR, f"vice unproven: {proj.loc[vice,'name']}"


# ── invariant: a team we never scraped (data gap) keeps its prior — its real XI is NOT benched ──
def test_unenriched_team_not_capped_unproven(d):
    from src import player_profile
    proj = d["proj_plan"]
    completed = data_access.completed_rounds(data_access.load_fixtures())
    gap = set(proj["team"].unique()) - player_profile.enriched_teams(proj, completed)
    if not gap:
        pytest.skip("no scrape-gap teams (every team that played was enriched)")
    for tm in gap:                                          # a scrape gap must never read as 'unproven'
        assert (proj[proj["team"] == tm]["p_start_src"] != "unproven").all(), tm


# ── invariant: the captain-by-P(1st) title sim actually RUNS and returns a legal armband (this path
#    is what the autopilot uses every round — a regression here silently breaks the live decision) ──
def test_captain_by_win_runs_in_title_mode(d, squad, league):
    from src import analytics, rank_sim
    proj = d["proj_plan"]
    ls = analytics.league_state(data_access.load_league(), d["my_team"].get("squad_name"),
                                data_access.completed_rounds(data_access.load_fixtures()))
    if not (ls and ls.get("rival_squads") and ls.get("rival_totals")):
        pytest.skip("no league field to simulate the title race")
    fx = proj.attrs.get("fixtures_next") or proj.attrs.get("fixtures") or []
    if not fx:
        pytest.skip("no next-round fixtures to simulate")
    res = rank_sim.formation_win_probs(proj, list(squad), fx, ls["rival_squads"],
                                       ls.get("rival_captains"), my_current=ls.get("my_total", 0.0),
                                       rival_current=ls.get("rival_totals"),
                                       rounds_left=ls.get("rounds_left", 1))
    assert res, "title-mode formation_win_probs returned nothing"
    top = res[0]
    assert top["captain_id"] in top["xi_ids"]                  # captain is a fielded starter
    assert top["vice_id"] != top["captain_id"]                 # vice is distinct
    owned = proj.loc[[i for i in top["xi_ids"] if i in proj.index]]
    assert owned.loc[top["captain_id"], "p_start"] >= config.XI_PSTART_FLOOR   # never unproven


# ── invariant: enforce_proven_xi yields a FULLY clean XI (or leaves it unchanged when it genuinely
#    can't), is idempotent, keeps 15 players, and never breaks the per-nation cap ──
def test_enforce_proven_xi_cleans_or_noops(d, squad):
    proj = d["proj_plan"]
    cap = config.soft_team_cap(d["target_round"])
    bank = float(d["my_team"].get("bank", 0))

    def forced(sq):
        o = proj.loc[[i for i in sq if i in proj.index]]
        if len(o) < 11:
            return 0
        xi = optimizer.best_xi(o, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)["xi_ids"]
        return sum(1 for i in xi if o.loc[i, "p_start"] < config.XI_PSTART_FLOOR)

    new_sq, swaps = optimizer.enforce_proven_xi(squad, proj, bank, team_cap=cap)
    assert len(new_sq) == config.SQUAD_SIZE
    assert forced(new_sq) <= forced(squad)                       # never makes the XI worse
    if swaps:                                                    # if it acted, the XI must end clean
        assert forced(new_sq) == 0
    _, again = optimizer.enforce_proven_xi(new_sq, proj, bank, team_cap=cap)
    assert again == []                                           # idempotent
    counts = proj.loc[[i for i in new_sq if i in proj.index], "team"].value_counts()
    for team, c in counts.items():                              # never exceeds the grandfathered count
        prior = (proj.loc[[i for i in squad if i in proj.index], "team"] == team).sum()
        assert c <= max(cap, prior), team


# ── invariant: the transfer search never proposes BUYING a likely-benched player ──
def test_transfers_never_buy_benched(d, squad):
    proj = d["proj_plan"]
    plans = services.get_transfer_plans(squad, float(d["my_team"].get("bank", 0)),
                                        int(d["my_team"].get("free_transfers", 2)))
    for p in plans:
        for pid in p["in_ids"]:
            if pid in proj.index:
                assert proj.loc[pid, "p_start"] >= config.BUY_PSTART_FLOOR, proj.loc[pid, "name"]
