"""Auto-written match analysis — turns the model's numbers into an engaging,
stats-literate brief for each fixture (favourite, expected goals, heat, key
fantasy men, the user's exposure and the sharpest rival threat).

Everything is derived from real model outputs, phrased for a stats/finance
reader: implied probabilities, expected value, variance and risk.
"""
import numpy as np
import pandas as pd


def _devig_draw(p_home: float, p_away: float) -> float:
    return max(0.0, round(1 - p_home - p_away, 3))


def _odds(p: float) -> str:
    return f"{1/p:.2f}" if p and p > 0 else "—"


def top_players(owned: pd.DataFrame, teams, n=3):
    sel = owned[owned["team"].isin(teams)].sort_values("xp_next", ascending=False)
    return sel.head(n)


def match_brief(fx: dict, proj: pd.DataFrame, my_owned: pd.DataFrame,
                rivals: list[tuple[str, pd.DataFrame]]) -> dict:
    """fx is an enriched next-round fixture (mu_home/mu_away/p_home_win/
    p_away_win/apparent_temp/indoor_ac). Returns title + paragraphs + tags."""
    home, away = fx["home"], fx["away"]
    ph, pa = float(fx.get("p_home_win", 0.4)), float(fx.get("p_away_win", 0.4))
    pd_ = _devig_draw(ph, pa)
    mu_h, mu_a = float(fx.get("mu_home", 1.3)), float(fx.get("mu_away", 1.3))
    total = mu_h + mu_a
    fav, dog, pf, pdg = (home, away, ph, pa) if ph >= pa else (away, home, pa, ph)
    margin = abs(ph - pa)

    # --- the read ---
    if margin > 0.45:
        framing = (f"The market makes **{fav}** a heavy favourite — an implied **{pf:.0%}** win "
                   f"probability (fair odds ≈ {_odds(pf)}), versus just {pdg:.0%} for {dog}. "
                   "This is a low-variance spot: the priced edge is large enough that an upset would "
                   "be a genuine tail event.")
    elif margin > 0.18:
        framing = (f"**{fav}** are favoured at an implied **{pf:.0%}** (≈ {_odds(pf)}), but {dog}'s "
                   f"{pdg:.0%} is live. A {pd_:.0%} draw chance sits in between — moderate variance, "
                   "the kind of fixture where a captaincy call swings real points.")
    else:
        framing = (f"A coin-flip: **{home} {ph:.0%} / draw {pd_:.0%} / {away} {pa:.0%}**. High variance, "
                   "low predictability — the model has little edge on the result itself, so player-level "
                   "minutes and set-piece duty matter more than backing a side.")

    if total > 3.1:
        goals = (f"Expected goals run hot at **{mu_h:.1f}–{mu_a:.1f}** ({total:.1f} total) — an open game "
                 "that rewards attackers and punishes clean-sheet bets.")
    elif total < 2.2:
        goals = (f"A tight projection, **{mu_h:.1f}–{mu_a:.1f}** ({total:.1f} total). Low-scoring games "
                 "shift expected value toward defenders and goalkeepers; clean-sheet probability is the edge.")
    else:
        goals = (f"Expected goals: **{mu_h:.1f}–{mu_a:.1f}** ({total:.1f} total) — a balanced model line."
                 )

    heat = ""
    t = fx.get("apparent_temp")
    if fx.get("indoor_ac"):
        heat = "Played indoors with climate control, so heat is a non-factor here."
    elif t is not None and t >= 31:
        heat = (f"Conditions are a real variable: ~**{t:.0f}°C** apparent temperature. Expect lower work-rate "
                "in the closing 20 minutes — late goals and fading legs are more likely, which the model "
                "already discounts for cool-climate sides.")
    elif t is not None and t <= 22:
        heat = f"Comfortable ~{t:.0f}°C — no heat drag on either side."

    # --- key men ---
    pl_lines = []
    for side in (home, away):
        side_players = proj[proj["team"] == side].sort_values("xp_next", ascending=False).head(3)
        if len(side_players):
            names = ", ".join(f"{r['name']} ({r['xp_next']:.1f} xP)" for _, r in side_players.iterrows())
            pl_lines.append(f"**{side}** fantasy threats: {names}.")
    players_para = " ".join(pl_lines)

    # --- my exposure ---
    mine = my_owned[my_owned["team"].isin({home, away})]
    my_stake = float(mine["xp_next"].sum())
    if len(mine):
        my_para = (f"**Your exposure:** {', '.join(mine['name'])} — about **{my_stake:.1f}** expected points "
                   f"riding on this one. " +
                   ("This is one of your big games; watch it." if my_stake >= 6 else
                    "Modest stake, but live."))
    else:
        my_para = "**Your exposure:** none of your players feature — a free watch, no points at risk."

    # --- rival threat ---
    threat_line = ""
    threats = []
    for sn, ow in rivals:
        riv = ow[ow["team"].isin({home, away})]
        gain = float(riv["xp_next"].sum()) - my_stake
        if len(riv):
            threats.append((gain, sn, float(riv["xp_next"].sum())))
    threats.sort(reverse=True)
    if threats and threats[0][0] > 1.5:
        g, sn, val = threats[0]
        threat_line = (f"**Rival watch:** {sn} has ~{val:.1f} points loaded here and stands to gain "
                       f"**+{g:.1f} on you** — one of the games that can cost you ground.")
    elif threats and threats[0][2] > my_stake and my_stake > 0:
        threat_line = f"**Rival watch:** {threats[0][1]} is slightly heavier here, but nothing decisive."

    verdict = _verdict(my_stake, threats[0][0] if threats else 0, margin, total)

    paragraphs = [framing, goals]
    if heat:
        paragraphs.append(heat)
    paragraphs += [players_para, my_para]
    if threat_line:
        paragraphs.append(threat_line)
    paragraphs.append(verdict)

    return {
        "home": home, "away": away,
        "kickoff_utc": fx["kickoff_utc"], "venue": fx.get("venue_id"),
        "ph": ph, "pd": pd_, "pa": pa, "mu_h": mu_h, "mu_a": mu_a,
        "my_stake": round(my_stake, 1),
        "danger": round(threats[0][0], 1) if threats else 0.0,
        "danger_name": threats[0][1] if threats else None,
        "paragraphs": paragraphs,
    }


def _verdict(my_stake, danger, margin, total):
    if my_stake >= 6 and danger < 1:
        return "🟢 **Tactician's take:** a get-the-snacks game — heavy personal stake, little rival downside. Upside night."
    if danger > 2.5:
        return "🔴 **Tactician's take:** a danger game. A rival is over-exposed to your blind side here; a big match for them dents your rank."
    if my_stake >= 4:
        return "🟡 **Tactician's take:** meaningful stake, balanced risk. Worth watching live for the captaincy read."
    if margin < 0.18 and total > 3:
        return "🎲 **Tactician's take:** chaos potential — open, even game. Differential hauls hide in fixtures like this."
    return "⚪ **Tactician's take:** low-leverage for you — monitor, don't sweat it."
