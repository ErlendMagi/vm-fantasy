"""Regression tests for the scraper pipeline normalizers and the sync
validation gate (no network, no Playwright)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scraper"))

import sync as sync_mod  # noqa: E402
from tv2_client import Tv2Client  # noqa: E402


def client() -> Tv2Client:
    return Tv2Client.__new__(Tv2Client)  # skip __init__ (needs endpoints.json)


# ------------------------------------------- playerMatchScores -> round points

def test_round_points_from_scores_accumulates():
    scores = [{"roundNumber": 1, "points": 5}, {"roundNumber": 2, "points": 0},
              {"round": 3, "totalPoints": 7}]
    by_round, total = Tv2Client._round_points_from_scores(scores)
    assert by_round == {"1": 5, "2": 0, "3": 7}
    assert total == 12


def test_round_points_from_scores_empty_and_junk():
    assert Tv2Client._round_points_from_scores([]) == ({}, 0)
    assert Tv2Client._round_points_from_scores(None) == ({}, 0)
    assert Tv2Client._round_points_from_scores(["x"]) == ({}, 0)


# ------------------------------------------------------- my_team picks shapes

def test_my_team_real_shape():
    out = client().normalize_my_team(
        {"players": [{"playerId": "a"}, {"playerId": "b"}], "budgetRemainingCents": 2500000,
         "name": "Erlend er best"},
        {"unlimitedTransfers": False, "freeTransfersAvailable": 2})
    assert out["squad"] == ["a", "b"]
    assert out["bank"] == 2.5
    assert out["free_transfers"] == 2
    assert out["squad_name"] == "Erlend er best"


def test_my_team_scalar_and_dict_fallback():
    out = client().normalize_my_team({"picks": [101, {"id": 9}]})
    assert out["squad"] == ["101", "9"]


def test_my_team_unlimited_pretournament():
    out = client().normalize_my_team(
        {"players": [{"playerId": "a"}]}, {"unlimitedTransfers": True})
    assert out["free_transfers"] >= 15


# ------------------------------------------------------- sync validation gate

def _pos_for(i: int) -> str:
    m = i % 15
    return "GK" if m < 2 else "DEF" if m < 7 else "MID" if m < 12 else "FWD"


def make_payload(n=450):
    players = [{"id": f"p{i}", "name": f"P{i}", "position": _pos_for(i),
                "team": "Norway", "price": 5.0, "ownership_pct": 10.0} for i in range(n)]
    # deterministic legal squad: 2 GK / 5 DEF / 5 MID / 3 FWD
    squad = []
    for pos, count in [("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]:
        squad.extend([p["id"] for p in players if p["position"] == pos][:count])
    return players, {"squad": squad}


def test_validate_passes_clean_payload():
    players, my_team = make_payload()
    assert sync_mod.validate(players, my_team) == []


def test_validate_catches_duplicate_player_ids():
    players, my_team = make_payload()
    players.append(dict(players[0]))
    assert any("duplicate player ids" in e for e in sync_mod.validate(players, my_team))


def test_validate_catches_duplicate_squad_ids():
    players, my_team = make_payload()
    my_team["squad"][1] = my_team["squad"][0]
    errors = sync_mod.validate(players, my_team)
    assert any("duplicate ids in squad" in e for e in errors)


def test_validate_catches_bad_squad_shape():
    players, my_team = make_payload()
    gks = [p["id"] for p in players if p["position"] == "GK"]
    my_team["squad"] = gks[:15] if len(gks) >= 15 else my_team["squad"][:14] + [gks[2]]
    errors = sync_mod.validate(players, my_team)
    assert any("squad shape" in e or "expected 15" in e for e in errors)


def test_validate_catches_empty_names():
    players, my_team = make_payload()
    players[0]["name"] = None
    assert any("empty names" in e for e in sync_mod.validate(players, my_team))
