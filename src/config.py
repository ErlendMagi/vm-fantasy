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
# Authoritative TV 2 VM Fantasy 2026 point table (from the live rules page).
SCORING_VERIFIED = True
SCORING = {
    "appearance": 1,          # played >= 1 sec
    "sixty_minutes": 1,       # extra for 60+ min  -> 2 total
    "full_match": {"GK": 0, "DEF": 0, "MID": 1, "FWD": 1},  # played the whole match
    "goal": {"GK": 8, "DEF": 6, "MID": 5, "FWD": 4},
    "assist": 3,              # official OR "fantasy assist" (rebound) both +3
    "clean_sheet": {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0},  # needs 60+ min
    "concede_per2": {"GK": 1, "DEF": 1, "MID": 0, "FWD": 0},  # -1 per 2 goals conceded
    "penalty_save": 5,        # GK
    "save_per3": 1,           # GK: +1 per 3 saves
    # Man of the Match bonus: best/2nd/3rd rated player in a match (any position)
    "motm": {1: 3, 2: 2, 3: 1},
    "flat_negative_tax": 0.25,  # expected yellow (-1) / pen conceded (-2) / OG (-2) drag
}
CAPTAIN_MULTIPLIER = 2
# MotM modelling: each match distributes 6 bonus points (3+2+1). Research on
# 2022 WC MotM awards: heavily attacker-biased (~28 FWD / 22 MID / 9 GK / 5 DEF
# of 64) - a defender essentially only wins it by scoring. So the standout
# weight is dominated by attacking output, with small per-position priors.
MOTM_POINTS_PER_MATCH = 6.0
MOTM_RESULT_WEIGHT = 0.6   # how much winning lifts a player's MotM odds
MOTM_POSITION_PRIOR = {"FWD": 0.20, "MID": 0.15, "GK": 0.10, "DEF": 0.03}

# ---------------------------------------------------------------- squad rules
SQUAD_SIZE = 15
SQUAD_SHAPE = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
BUDGET = 100.0
MAX_PER_TEAM = 3              # verify vs TV 2; optimizer grandfathers existing excess
FREE_TRANSFERS_PER_ROUND = 2  # confirmed by TV 2 game description
EXTRA_TRANSFER_COST = 4       # points per extra transfer
# the 7 formations the game actually accepts (DEF, MID, FWD), always 1 GK.
# Restricted to this confirmed set so an auto-applied lineup is never rejected.
FORMATIONS = [(3, 4, 3), (3, 5, 2), (4, 3, 3), (4, 4, 2), (4, 5, 1), (5, 3, 2), (5, 4, 1)]

# ---------------------------------------------------------------- heat model
# Evidence: Chmura et al. 2017 (2014 WC); PMC11436032 narrative review.
HEAT_THRESHOLD_C = 28.0       # apparent temperature where decline starts
HEAT_RATE = {"cool": 0.030, "temperate": 0.0225, "warm": 0.015}  # per deg C above threshold
HEAT_FLOOR = 0.70             # multiplier never drops below this

# ---------------------------------------------------------------- projections
HORIZON_WEIGHTS = [1.0, 0.6]  # next round, round after (x p_alive)
# Tournament-long value: a player's worth = expected points summed over ALL
# remaining rounds, each weighted by P(team still playing) ^ this exponent.
# Used for squad building so deep-running teams' players are valued correctly.
TOURNAMENT_DECAY = 0.92       # mild per-round discount on top of survival odds
FALLBACK_MU_TOTAL = 2.6       # league-average total goals when no totals market
ASSISTED_GOAL_SHARE = 0.75    # share of goals that yield an assist
# Dynamic form: after g games, observed points get weight g/(g+K). Short
# tournament -> modest K so 1-2 strong games move the needle without dominating.
FORM_SHRINKAGE_K = 2.5
FORM_MULT_BOUNDS = (0.75, 1.35)  # form can't swing a projection more than this
# Duty bonuses (xP/match, research-calibrated): set-piece takers earn ~0.25
# set-piece assists/match (x3 pts) that no goal-odds market captures; penalty
# duty is applied only when a player's xG is NOT market-quoted (the bookies
# already price pen duty into anytime-scorer odds).
DUTY_SP_BONUS = 0.75
DUTY_PEN_BONUS = {"GK": 1.2, "DEF": 0.9, "MID": 0.7, "FWD": 0.6}
DUTY_RANK_MULT = [1.0, 0.5, 0.35]   # primary, backup, third/shared
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

# ---------------------------------------------------------------- odds credits
# Never let the free-tier balance hit zero (which would break sync mid-cup).
ODDS_CREDIT_FLOOR = 60        # refuse to spend below this many remaining credits
# Goalscorer only (1 credit/match): assist props have thin WC coverage and the
# assist heuristic is a fine fallback - keeps tournament-long credit use ~halved.
PLAYER_PROPS_MARKETS = "player_goal_scorer_anytime"

# ---------------------------------------------------------------- staleness
STALE_AFTER_HOURS = 36
