import json
from pathlib import Path

import pytest

from src import advancement

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "static" / "fixtures_fallback.json")
    .read_text(encoding="utf-8")
)["matches"]

OUTRIGHTS = {"prices": {
    "Spain": 5.0, "France": 6.0, "England": 7.5, "Brazil": 8.0, "Argentina": 8.0,
    "Portugal": 10.0, "Germany": 12.0, "Netherlands": 16.0, "Norway": 40.0,
    "Mexico": 50.0, "USA": 50.0, "Belgium": 30.0, "Croatia": 40.0, "Japan": 60.0,
}}


@pytest.fixture(scope="module")
def adv():
    return advancement.advancement_table(FIXTURES, match_odds=None, outrights=OUTRIGHTS, n_sims=4000)


def test_team_counts_per_round(adv):
    assert adv["R32"].sum() == pytest.approx(32.0, abs=0.6)   # MC noise
    assert adv["R16"].sum() == pytest.approx(16.0, abs=1e-6)  # normalized exactly
    assert adv["QF"].sum() == pytest.approx(8.0, abs=1e-6)
    assert adv["WIN"].sum() == pytest.approx(1.0, abs=1e-6)


def test_probabilities_valid_and_monotone(adv):
    assert ((adv >= 0) & (adv <= 1)).all().all()
    for team in adv.index:
        row = adv.loc[team]
        assert row["R32"] >= row["R16"] >= row["QF"] >= row["SF"] >= row["F"] >= row["WIN"]


def test_favorites_beat_minnows(adv):
    assert adv.loc["Spain", "R32"] > 0.8
    assert adv.loc["Spain", "R32"] > adv.loc["Haiti", "R32"]
    assert adv.loc["Spain", "WIN"] > adv.loc["Norway", "WIN"]


def test_p_plays_lookup_group_rounds_always_one(adv):
    lookup = advancement.p_plays_lookup(adv)
    assert lookup[("Norway", 1)] == 1.0
    assert lookup[("Norway", 3)] == 1.0
    assert lookup[("Norway", 4)] == pytest.approx(adv.loc["Norway", "R32"])
    assert lookup[("Spain", 8)] == pytest.approx(adv.loc["Spain", "SF"])


def test_finished_match_with_partial_score_does_not_crash():
    """Live feeds may flip status to finished before scores propagate."""
    fixtures = [dict(m) for m in FIXTURES]
    broken = next(m for m in fixtures if m["stage"] == "group")
    broken["status"] = "finished"
    broken["score_home"], broken["score_away"] = 2, None
    adv = advancement.advancement_table(fixtures, None, OUTRIGHTS, n_sims=1000)
    assert adv["R32"].sum() == pytest.approx(32.0, abs=1.2)


def test_fully_finished_match_is_deterministic():
    fixtures = [dict(m) for m in FIXTURES]
    done = next(m for m in fixtures if m["stage"] == "group" and "Norway" in (m["home"], m["away"]))
    done["status"] = "finished"
    if done["home"] == "Norway":
        done["score_home"], done["score_away"] = 5, 0   # huge Norway win
    else:
        done["score_home"], done["score_away"] = 0, 5
    base = advancement.advancement_table(FIXTURES, None, OUTRIGHTS, n_sims=2000)
    boosted = advancement.advancement_table(fixtures, None, OUTRIGHTS, n_sims=2000)
    assert boosted.loc["Norway", "R32"] > base.loc["Norway", "R32"]
