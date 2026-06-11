"""Heat multiplier: scales a player's attacking output by venue heat and the
heat-acclimatization class of their national team.

Evidence basis (see plan/README): performance declines above ~28C apparent
temperature; ~3%/C for cool-climate teams, ~1.5%/C for warm-climate teams.
Indoor air-conditioned stadiums get no penalty.
"""
from src import config


def heat_multiplier(apparent_temp_c: float | None, climate_class: str, indoor_ac: bool) -> float:
    if indoor_ac or apparent_temp_c is None:
        return 1.0
    rate = config.HEAT_RATE.get(climate_class, config.HEAT_RATE["temperate"])
    excess = max(0.0, apparent_temp_c - config.HEAT_THRESHOLD_C)
    return max(config.HEAT_FLOOR, 1.0 - rate * excess)
