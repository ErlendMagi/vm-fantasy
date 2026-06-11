from src.heat import heat_multiplier


def test_cool_team_in_monterrey_heat():
    assert abs(heat_multiplier(35.0, "cool", indoor_ac=False) - 0.79) < 1e-9


def test_warm_team_suffers_half_as_much():
    assert abs(heat_multiplier(35.0, "warm", indoor_ac=False) - 0.895) < 1e-9


def test_indoor_ac_nullifies_heat():
    assert heat_multiplier(35.0, "cool", indoor_ac=True) == 1.0


def test_below_threshold_no_penalty():
    assert heat_multiplier(24.0, "cool", indoor_ac=False) == 1.0
    assert heat_multiplier(28.0, "cool", indoor_ac=False) == 1.0


def test_floor_at_extreme_temps():
    assert heat_multiplier(60.0, "cool", indoor_ac=False) == 0.70


def test_no_forecast_means_no_adjustment():
    assert heat_multiplier(None, "cool", indoor_ac=False) == 1.0
