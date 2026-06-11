"""Projection tests on a synthetic roster (independent of whatever the live
sync has written into data/tv2), using the real openfootball fixture schedule
and a stubbed weather function (no network)."""
import pandas as pd
import pytest

from src import advancement, data_access, projections

# every team plays in group rounds, so any of these has a round-1/2 fixture
ROSTER = [
    # team,        name,          pos,  price
    ("France",     "FR-keeper",   "GK", 5.0),
    ("France",     "FR-striker",  "FWD", 10.0),
    ("France",     "FR-mid",      "MID", 8.0),
    ("Norway",     "NO-keeper",   "GK", 5.0),
    ("Norway",     "NO-striker",  "FWD", 10.0),
    ("Norway",     "NO-mid",      "MID", 8.0),
    ("England",    "EN-keeper",   "GK", 5.0),
    ("England",    "EN-striker",  "FWD", 10.0),
    ("England",    "EN-mid",      "MID", 8.0),
    ("Brazil",     "BR-keeper",   "GK", 5.0),
    ("Brazil",     "BR-striker",  "FWD", 10.0),
    ("Brazil",     "BR-defender", "DEF", 6.0),
]


def make_players() -> pd.DataFrame:
    rows = [{"id": f"s{i}", "name": n, "team": t, "position": p, "price": pr,
             "ownership_pct": 10.0, "total_points": 0, "round_points": {}, "status": "available"}
            for i, (t, n, p, pr) in enumerate(ROSTER)]
    return pd.DataFrame(rows).set_index("id", drop=False)


def hot_everywhere(lat, lon, kickoff_utc):
    return 35.0


@pytest.fixture(scope="module")
def proj():
    players = make_players()
    fixtures = data_access.load_fixtures()
    adv = advancement.advancement_table(fixtures, None, None, n_sims=1000)
    p_plays = advancement.p_plays_lookup(adv)
    return projections.project(players, fixtures, None, None, [], 1, p_plays, temp_fn=hot_everywhere)


def test_every_player_projects(proj):
    assert (proj["xp_next"] >= 0).all()
    assert proj["xp_next"].notna().all()
    assert proj["opponent"].notna().all()  # every synthetic team plays round 1


def test_attackers_outproject_their_keepers(proj):
    by_name = proj.set_index("name")
    assert by_name.loc["FR-striker", "xp_next"] > by_name.loc["FR-keeper", "xp_next"]
    assert by_name.loc["NO-striker", "xp_next"] > by_name.loc["NO-keeper", "xp_next"]


def test_heat_multiplier_by_climate(proj):
    # Norway is cool-climate: outdoor 35C -> 0.79, indoor A/C -> 1.0
    norway = proj[proj["team"] == "Norway"]
    assert norway["heat_mult"].isin([0.79, 1.0]).all()
    # Brazil is warm-climate: outdoor 35C -> 0.895, indoor -> 1.0
    brazil = proj[proj["team"] == "Brazil"]
    assert brazil["heat_mult"].isin([0.895, 1.0]).all()


def test_horizon_blends_two_rounds(proj):
    assert (proj["xp_horizon"] >= proj["xp_next"] * 0.99).all()  # group stage: p_alive=1


def test_no_phantom_round_after_final():
    """next round 8 (final + 3rd place) has no round 9 - xp_after must be 0."""
    players = make_players()
    fixtures = data_access.load_fixtures()
    proj = projections.project(players, fixtures, None, None, [], 8, {}, temp_fn=hot_everywhere)
    assert (proj["xp_after"] == 0).all()
    assert (proj["p_plays_after"] == 0).all()


def test_generic_knockout_share_is_per_team():
    """With no concrete round-5 fixtures, each team's striker takes the capped
    share of HIS team's generic mu - not a share of a pooled all-teams attack."""
    players = make_players()
    fixtures = [m for m in data_access.load_fixtures() if m["stage"] == "group"]
    proj = projections.project(players, fixtures, None, None, [], 5, {}, temp_fn=hot_everywhere)
    by_name = proj.set_index("name")
    # equal-priced strikers on different teams project identically in a generic match
    assert by_name.loc["FR-striker", "xp_next"] == pytest.approx(by_name.loc["EN-striker", "xp_next"], abs=0.3)
    assert by_name.loc["FR-striker", "xp_next"] > 2.0  # not diluted into a many-team pool
