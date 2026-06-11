"""End-to-end projection smoke test on the committed seed data + real fixture
list, with a stubbed weather function (no network)."""
import pytest

from src import advancement, data_access, projections


def hot_everywhere(lat, lon, kickoff_utc):
    return 35.0


@pytest.fixture(scope="module")
def proj():
    players = data_access.load_players()
    fixtures = data_access.load_fixtures()
    completed = data_access.completed_rounds(fixtures)
    next_rnd = data_access.next_round(fixtures)
    assert next_rnd == 1 and completed == []
    adv = advancement.advancement_table(fixtures, None, None, n_sims=1000)
    p_plays = advancement.p_plays_lookup(adv)
    return projections.project(players, fixtures, None, None, completed, next_rnd,
                               p_plays, temp_fn=hot_everywhere)


def test_every_player_projects(proj):
    assert (proj["xp_next"] >= 0).all()
    assert proj["xp_next"].notna().all()
    # every seed player's team plays in round 1, so all should have an opponent
    assert proj["opponent"].notna().all()


def test_attackers_outproject_their_keepers(proj):
    by_id = proj.set_index("name")
    assert by_id.loc["Mbappe", "xp_next"] > by_id.loc["Maignan", "xp_next"]
    assert by_id.loc["Haaland", "xp_next"] > by_id.loc["Nyland", "xp_next"]


def test_heat_multiplier_applied_by_climate(proj):
    outdoor = proj[proj["apparent_temp"].notna()]
    assert not outdoor.empty
    cool_outdoor = outdoor[outdoor["team"].map(data_access.load_climate()) == "cool"]
    if not cool_outdoor.empty:
        assert (abs(cool_outdoor["heat_mult"] - 0.79) < 1e-9).all()
    indoor_or_unknown = proj[proj["apparent_temp"].isna()]
    assert (indoor_or_unknown["heat_mult"] == 1.0).all()


def test_horizon_blends_two_rounds(proj):
    assert (proj["xp_horizon"] >= proj["xp_next"] * 0.99).all()  # group stage: p_alive=1
