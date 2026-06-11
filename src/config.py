"""Single source of truth for every assumption in the model.

IMPORTANT: SCORING / squad rules below are FPL-style DEFAULTS and are NOT yet
verified against TV 2's actual rules (their site is a login-walled SPA).
After running scraper/discover_endpoints.py, check the game's bootstrap JSON
for the real scoring table and update here. Until SCORING_VERIFIED is True the
app shows a warning banner.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TV2_DIR = DATA / "tv2"
ODDS_DIR = DATA / "odds"
STATIC_DIR = DATA / "static"

# ---------------------------------------------------------------- scoring
# Verified 2026-06-11 from the live game ruleset endpoint
# (/tournaments/vm-2026/ruleset/active "scoringJson").
SCORING_VERIFIED = True
SCORING = {
    "appearance": 1,          # any minutes (the 2-pt 60+ tier is encoded as 1 + 1)
    "sixty_minutes": 1,       # extra point for 60+ minutes -> 2 total, matches ruleset
    "goal": {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assist": 3,
    "clean_sheet": {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "flat_negative_tax": 0.2,  # expected yellow (-1) / own goal (-2) / pen miss (-2) drag
}
# other ruleset scoring (folded into the tax or modeled post-MVP):
# ownGoal -2, redCard -3, yellowCard -1, penaltyMiss -2, penaltySave +5,
# savesForThree +1 (1 pt per 3 GK saves)
CAPTAIN_MULTIPLIER = 2

# ---------------------------------------------------------------- squad rules
SQUAD_SIZE = 15
SQUAD_SHAPE = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
BUDGET = 100.0
MAX_PER_TEAM = 3              # verify vs TV 2; optimizer grandfathers existing excess
FREE_TRANSFERS_PER_ROUND = 2  # confirmed by TV 2 game description
EXTRA_TRANSFER_COST = 4       # points per extra transfer
# legal XI formations: (DEF, MID, FWD), always 1 GK, total 11
FORMATIONS = [
    (d, m, f)
    for d in range(3, 6)
    for m in range(2, 6)
    for f in range(1, 4)
    if d + m + f == 10
]

# ---------------------------------------------------------------- heat model
# Evidence: Chmura et al. 2017 (2014 WC); PMC11436032 narrative review.
HEAT_THRESHOLD_C = 28.0       # apparent temperature where decline starts
HEAT_RATE = {"cool": 0.030, "temperate": 0.0225, "warm": 0.015}  # per deg C above threshold
HEAT_FLOOR = 0.70             # multiplier never drops below this

# ---------------------------------------------------------------- projections
HORIZON_WEIGHTS = [1.0, 0.6]  # next round, round after (x p_alive)
FALLBACK_MU_TOTAL = 2.6       # league-average total goals when no totals market
ASSISTED_GOAL_SHARE = 0.75    # share of goals that yield an assist
POSITION_GOAL_FACTOR = {"FWD": 1.0, "MID": 0.5, "DEF": 0.15, "GK": 0.0}
POSITION_ASSIST_FACTOR = {"FWD": 0.6, "MID": 1.0, "DEF": 0.35, "GK": 0.05}
PRICE_INVOLVEMENT_EXP = 1.5   # weight ~ price^exp: stars take bigger attacking share
# no single player takes more than this share of team goals/assists - keeps
# projections sane when a team has few listed players (e.g. seed data)
MAX_GOAL_SHARE = {"FWD": 0.45, "MID": 0.35, "DEF": 0.15, "GK": 0.02}
MAX_ASSIST_SHARE = {"FWD": 0.35, "MID": 0.40, "DEF": 0.25, "GK": 0.05}

# ---------------------------------------------------------------- optimizer
HIT_MARGIN = 2.0              # take a -4 hit only if extra gain > 4 + this margin

# ---------------------------------------------------------------- advancement
MC_SIMS = 10_000
KNOCKOUT_ROUNDS = ["R32", "R16", "QF", "SF", "F"]

# ---------------------------------------------------------------- staleness
STALE_AFTER_HOURS = 36
