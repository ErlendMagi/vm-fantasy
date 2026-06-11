import pandas as pd
import pytest

from src import optimizer


def make_players():
    rows = []

    def add(pid, pos, team, price, xp):
        rows.append({"id": pid, "name": pid, "team": team, "position": pos,
                     "price": price, "xp_next": xp, "xp_horizon": xp, "status": "available"})

    # owned 15: 2 GK / 5 DEF / 5 MID / 3 FWD across distinct teams
    add("gk1", "GK", "T1", 5.0, 4.0); add("gk2", "GK", "T2", 4.0, 2.0)
    for i in range(5):
        add(f"d{i}", "DEF", f"T{i+3}", 5.0, 3.0 + i * 0.2)
    for i in range(5):
        add(f"m{i}", "MID", f"T{i+8}", 7.0, 4.0 + i * 0.2)
    add("f0", "FWD", "T13", 9.0, 5.0)
    add("f1", "FWD", "T14", 8.0, 4.5)
    add("f2", "FWD", "T15", 7.0, 0.0)   # dud: team eliminated (p_alive ~ 0)
    # pool
    add("star_fwd", "FWD", "T20", 9.5, 8.0)        # affordable upgrade on the dud (with bank)
    add("too_pricey", "FWD", "T21", 14.0, 9.9)     # never affordable
    add("mid_up", "MID", "T22", 7.5, 6.0)
    add("def_up", "DEF", "T23", 5.5, 4.5)
    add("gk_up", "GK", "T24", 5.0, 4.2)
    return pd.DataFrame(rows).set_index("id", drop=False)


def test_best_xi_legal_and_doubles_captain():
    players = make_players()
    owned = players.iloc[:15]
    xi = optimizer.best_xi(owned, "xp_next")
    assert len(xi["xi_ids"]) == 11
    assert xi["captain_id"] == "f0"  # highest xp in XI
    positions = owned.loc[xi["xi_ids"], "position"].value_counts()
    assert positions["GK"] == 1
    d, m, f = (int(x) for x in xi["formation"].split("-"))
    assert 3 <= d <= 5 and 2 <= m <= 5 and 1 <= f <= 3 and d + m + f == 10
    assert xi["total"] == pytest.approx(xi["xi_xp"] + xi["captain_xp"])


def test_eliminated_player_transferred_out():
    players = make_players()
    squad = list(players.index[:15])
    plans = optimizer.transfer_plans(players, squad, bank=3.0)
    best = plans[0]
    out_ids = best["out_ids"]
    assert "f2" in out_ids          # the 0-xp dud goes
    assert best["net_gain"] > 0


def test_budget_infeasible_excluded():
    players = make_players()
    squad = list(players.index[:15])
    plans = optimizer.transfer_plans(players, squad, bank=0.0)
    for p in plans:
        assert "too_pricey" not in p["in_ids"]


def test_hit_only_with_margin():
    players = make_players()
    squad = list(players.index[:15])
    plans = optimizer.transfer_plans(players, squad, bank=3.0)
    doubles = [p for p in plans if p["n_transfers"] == 2]
    triples = [p for p in plans if p["n_transfers"] == 3]
    if triples and doubles:
        assert triples[0]["net_gain"] > doubles[0]["net_gain"]
        assert triples[0]["hit_cost"] == 4


def test_zero_transfer_baseline_present():
    players = make_players()
    squad = list(players.index[:15])
    plans = optimizer.transfer_plans(players, squad, bank=0.0)
    assert any(p["n_transfers"] == 0 and p["net_gain"] == 0.0 for p in plans)
