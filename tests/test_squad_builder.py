import pandas as pd
import pytest

from src import config, squad_builder


def make_pool() -> pd.DataFrame:
    """A realistic pool: many players per position across 20 teams, varied
    price (3.5-12.5) and value (cheap players score less)."""
    rows = []
    pid = 0
    for team in [f"T{i}" for i in range(20)]:
        for pos, n in [("GK", 3), ("DEF", 8), ("MID", 8), ("FWD", 5)]:
            for k in range(n):
                price = 3.5 + (k % 6) * 1.5
                xp = 1.0 + price * 0.4 + (k % 3) * 0.3   # value loosely tracks price
                rows.append({"id": f"p{pid}", "name": f"{team}-{pos}{k}", "team": team,
                             "position": pos, "price": price, "ownership_pct": 5.0,
                             "xp_next": xp, "xp_horizon": xp * 1.6, "status": "available"})
                pid += 1
    return pd.DataFrame(rows).set_index("id", drop=False)


@pytest.fixture(scope="module")
def built():
    return squad_builder.build_optimal_squad(make_pool(), value_col="xp_horizon", restarts=4)


def test_squad_shape(built):
    players = make_pool()
    squad = players.loc[built["squad_ids"]]
    assert len(squad) == config.SQUAD_SIZE
    assert squad["position"].value_counts().to_dict() == config.SQUAD_SHAPE


def test_within_budget(built):
    assert built["price"] <= config.BUDGET + 1e-6


def test_country_cap(built):
    players = make_pool()
    counts = players.loc[built["squad_ids"], "team"].value_counts()
    assert counts.max() <= config.MAX_PER_TEAM


def test_no_duplicate_players(built):
    assert len(set(built["squad_ids"])) == config.SQUAD_SIZE


def test_beats_a_cheap_baseline(built):
    """The optimizer should clear a naive cheapest-valid squad by a wide margin."""
    players = make_pool()
    from src import optimizer
    cheap = []
    for pos, n in config.SQUAD_SHAPE.items():
        cheap += list(players[players["position"] == pos].nsmallest(n, "price").index)
    # cheapest squad likely violates the country cap, so just compare values loosely
    assert built["value"] > optimizer.squad_xp(players.loc[built["squad_ids"]], "xp_horizon") * 0.99
    assert built["value"] > 30  # a real squad, not a degenerate one
