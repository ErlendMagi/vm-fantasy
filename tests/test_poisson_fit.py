import numpy as np

from src import poisson_fit


def test_devig_sums_to_one():
    p = poisson_fit.devig([1.65, 3.9, 5.5])
    assert abs(p.sum() - 1.0) < 1e-9
    assert p[0] > p[1] > p[2]


def test_mu_total_even_over_under():
    # P(N >= 3) = 0.5  ->  mu just above 2.67
    mu = poisson_fit.mu_total_from_over(0.5, line=2.5)
    assert 2.5 < mu < 2.85


def test_symmetric_match_splits_evenly():
    h2h = {"home": 2.9, "draw": 3.1, "away": 2.9}
    totals = {"line": 2.5, "over": 2.0, "under": 2.0}
    mu_h, mu_a = poisson_fit.match_mus(h2h, totals)
    assert abs(mu_h - mu_a) < 0.1
    assert 1.1 < mu_h < 1.5


def test_heavy_favorite_takes_large_share():
    h2h = {"home": 1.2, "draw": 6.5, "away": 13.0}
    mu_h, mu_a = poisson_fit.match_mus(h2h)
    assert mu_h / (mu_h + mu_a) > 0.7


def test_outcome_probs_consistent():
    ph, pd_, pa = poisson_fit.outcome_probs(2.0, 0.8)
    assert ph > pa
    assert abs(ph + pd_ + pa - 1.0) < 1e-3  # tiny tail beyond 10 goals


def test_no_totals_falls_back_to_league_average():
    mu_h, mu_a = poisson_fit.match_mus({"home": 2.0, "draw": 3.4, "away": 3.8})
    assert abs((mu_h + mu_a) - 2.6) < 1e-6
