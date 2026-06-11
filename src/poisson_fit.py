"""Convert bookmaker match odds into expected goals (mu_home, mu_away).

Method: de-vig the h2h triple; back out total goals from the over/under line
via Poisson; split the total between the teams so an independent-Poisson
scoreline grid best reproduces the de-vigged 1X2 probabilities.
"""
import math

import numpy as np

from src import config

_GOALS = np.arange(0, 11)


def devig(odds: list[float]) -> np.ndarray:
    """Decimal odds -> implied probabilities, overround removed proportionally."""
    inv = 1.0 / np.asarray(odds, dtype=float)
    return inv / inv.sum()


def _poisson_pmf(mu: float) -> np.ndarray:
    return np.exp(-mu) * mu ** _GOALS / np.array([math.factorial(int(k)) for k in _GOALS])


def mu_total_from_over(p_over: float, line: float = 2.5) -> float:
    """Solve P(Poisson(mu) >= line+0.5 rounded up) = p_over by bisection."""
    k = int(math.floor(line)) + 1  # goals needed to beat the line
    lo, hi = 0.2, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2
        p = 1.0 - sum(math.exp(-mid) * mid**i / math.factorial(i) for i in range(k))
        if p < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def outcome_probs(mu_home: float, mu_away: float) -> tuple[float, float, float]:
    """(P_home, P_draw, P_away) from independent Poisson scorelines (0-10 grid)."""
    grid = np.outer(_poisson_pmf(mu_home), _poisson_pmf(mu_away))
    return float(np.tril(grid, -1).sum()), float(np.trace(grid)), float(np.triu(grid, 1).sum())


def split_mu_total(mu_total: float, p_h2h: np.ndarray) -> float:
    """Find home share s in [0.05, 0.95] minimizing squared error vs de-vigged 1X2."""
    best_s, best_err = 0.5, float("inf")
    for s in np.arange(0.05, 0.951, 0.01):
        probs = outcome_probs(s * mu_total, (1 - s) * mu_total)
        err = sum((a - b) ** 2 for a, b in zip(probs, p_h2h))
        if err < best_err:
            best_s, best_err = float(s), err
    return best_s


def match_mus(h2h: dict, totals: dict | None = None) -> tuple[float, float]:
    """h2h={'home':1.65,'draw':3.9,'away':5.5}, totals={'line':2.5,'over':1.85,'under':1.95}
    -> (mu_home, mu_away)."""
    p = devig([h2h["home"], h2h["draw"], h2h["away"]])
    if totals and totals.get("over") and totals.get("under"):
        p_over = devig([totals["over"], totals["under"]])[0]
        mu_total = mu_total_from_over(float(p_over), totals.get("line", 2.5))
    else:
        mu_total = config.FALLBACK_MU_TOTAL
    s = split_mu_total(mu_total, p)
    return s * mu_total, (1 - s) * mu_total
