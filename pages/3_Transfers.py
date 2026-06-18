import streamlit as st

st.set_page_config(page_title="Transfers", page_icon="🔁", layout="wide")

from src import config, nav, optimizer, services
from src.viz import GAIN_BLUE as viz_gain
from src.viz import NEUTRAL as viz_neutral
from src.viz import short_name as viz_short

nav.render("Transfers")
d = services.get_data()
st.title("🔁 Transfer suggestions")
services.render_banners(d)
if d["proj_plan"] is None or d["my_team"] is None:
    st.stop()

proj, my = d["proj_plan"], d["my_team"]
target, live = d["target_round"], d["next_round"]
st.caption(f"Everything here plans the **editable round you can still change — round {target}**"
           + (f". Round {live} is locked and scoring live." if target != live else "."))

_ls = services.get_league_state()
if _ls and _ls.get("regime"):
    _modes = {
        "leader": "🛡️ **Leader mode** — you're ahead, so plans favour **covering** rivals' big guns and "
                  "shedding variance (protect the lead).",
        "chaser": "⚔️ **Chaser mode** — you're behind, so plans favour **differentials** your rivals don't own "
                  "and a little more variance (you need swings to catch up).",
        "coinflip": "⚖️ **Coin-flip** — the race is tight, so plans play the straight expected-points optimum.",
    }
    st.info(f"🤖 The autopilot is playing in {_modes.get(_ls['regime'], _ls['regime'])}", icon="🏆")
    st.caption(f"gap {_ls['gap_to_field']:+.0f} vs the field · ~{_ls['rounds_left']} rounds left · "
               "transfers, captain and the −4 bar are all tuned to this.")

owned = proj.loc[[i for i in my["squad"] if i in proj.index]]

st.subheader(f"Current squad health — round {target}")
st.caption(f"All figures are for round {target} (the round you're planning). **P(through to R{target + 1})** "
           "is the odds-derived chance the team is still in the tournament — low values mean the player is "
           "about to stop scoring (elimination risk).")
sq = owned.sort_values("xp_horizon", ascending=False)
st.dataframe(
    sq[["name", "team", "position", "price", "p_start", "opponent", "heat_mult", "rotation_risk",
        "xp_next", "xp_horizon", "p_plays_after"]],
    column_config={
        "opponent": st.column_config.TextColumn(f"opp R{target}"),
        "p_start": st.column_config.NumberColumn("start %", format="percent",
                                                 help=f"Chance this player starts round {target} — it scales "
                                                      "the whole projection. Low here = benching risk, which "
                                                      "'rot risk' (blowout rest of a nailed starter) misses."),
        "heat_mult": st.column_config.NumberColumn("heat ×", format="%.2f"),
        "rotation_risk": st.column_config.NumberColumn("rot risk", format="percent",
                                                       help="Chance this nailed starter is rested in a "
                                                            "lopsided game — already shaved off xP."),
        "xp_next": st.column_config.NumberColumn(f"xP R{target}", format="%.2f"),
        "xp_horizon": st.column_config.NumberColumn("xP horizon", format="%.2f"),
        "p_plays_after": st.column_config.ProgressColumn(f"P(through to R{target + 1})",
                                                         min_value=0, max_value=1, format="%.2f"),
    },
    hide_index=True, width="stretch",
)

st.subheader("Best transfer plans")
default_free = int(my.get("free_transfers", 2))
unlimited = default_free >= config.SQUAD_SIZE
if unlimited:
    st.info("Transfers are currently **unlimited** (the squad isn't locked yet) — no −4 hits apply. "
            "Once the squad locks you get 2 free transfers per round (a 3rd costs −4).")
c1, c2 = st.columns(2)
free = c1.number_input("Free transfers", 0, max(5, default_free),
                       5 if unlimited else default_free)
bank = c2.number_input("Bank (M)", 0.0, 50.0, float(my.get("bank", 0.0)), 0.1)

missing = [i for i in my["squad"] if i not in proj.index]
if len(my["squad"]) - len(missing) < config.SQUAD_SIZE:
    st.error("Some of your players aren't in the latest player data (a withdrawal or a sync gap). "
             "Re-run the sync; transfer planning needs the full squad.")
    st.stop()

plans = services.get_transfer_plans(my["squad"], bank, free)
_free_default = 5 if unlimited else default_free          # the input's own default (unlimited shows 5)
is_live = (free == _free_default) and abs(bank - float(my.get("bank", 0.0))) < 1e-6
best = plans[0] if plans else None
auto_note = ("The autopilot runs this exact search with your live transfers and bank before the deadline."
             if is_live else "What-if with your edited inputs — the autopilot uses your real values.")

st.subheader("💡 The move the model would make")
from src import analytics, viz
id_by_name = {(proj.loc[i, "name"], proj.loc[i, "team"]): i for i in proj.index}


def row_of(name, team):
    return proj.loc[id_by_name[(name, team)]]


_keep_pw = next((p.get("p_win") for p in plans if p["n_transfers"] == 0), None)
if _keep_pw is None:                       # baseline always available, even if the keep plan ranks low
    _keep_pw = services.get_win_probability()
if best and best["n_transfers"] > 0:
    _pw = (f" It lifts your **win probability to {best['p_win'] * 100:.0f}%**"
           + (f" (from {_keep_pw * 100:.0f}% if you keep)." if _keep_pw is not None else ".")
           if best.get("p_win") is not None else "")
    _n_trim = int(round(best.get("diversify_credit", 0) / config.CONCENTRATION_CREDIT))
    _div = (f" It also **trims {_n_trim} over-cap player(s)** back inside the {config.soft_team_cap(target)}-"
            "per-team limit (a correlated group-stage risk)." if _n_trim > 0 else "")
    st.caption(f"Best plan: **+{best['net_gain']:.1f}** points over the rest of the cup"
               + (f" after a −{best['hit_cost']} hit." if best["hit_cost"] else ".") + _pw + _div + f" {auto_note}")
    per = best["net_gain"] / best["n_transfers"]
    for (on, ot), (inn, it) in zip(best["outs"], best["ins"]):
        o_row, i_row = row_of(on, ot), row_of(inn, it)
        reasons = analytics.transfer_reasons(o_row, i_row)
        st.markdown(viz.transfer_card_html(o_row, i_row, per, reasons, hit=0), unsafe_allow_html=True)
        with st.expander(f"Why {viz_short(inn)} over {viz_short(on)}? — the breakdown"):
            comp = ["pts_appear", "pts_goals", "pts_assists", "pts_cs", "pts_duty", "pts_motm"]
            labels = ["Minutes", "Goals", "Assists", "Clean sheet", "Set-piece/pen", "Man of Match"]
            import plotly.graph_objects as go
            f = go.Figure()
            f.add_bar(name=on, x=labels, y=[o_row[c] for c in comp], marker_color=viz_neutral)
            f.add_bar(name=inn, x=labels, y=[i_row[c] for c in comp], marker_color="#00b894")
            f.update_layout(barmode="group", height=300, yaxis_title=f"Expected pts (round {target})",
                            legend=dict(orientation="h", y=-0.25), margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(f, width="stretch", config={"displayModeBar": False})
            st.caption(f"{inn} ({it}) survives to {i_row.get('p_plays_after', 1):.0%} vs {on}'s "
                       f"{o_row.get('p_plays_after', 1):.0%}; whole-cup value "
                       f"{i_row['xp_tournament']:.1f} vs {o_row['xp_tournament']:.1f}.")
else:
    st.success(f"**Keep the squad** — no transfer clears the bar this round. {auto_note}")

# ---------------------------------------------------------------- the transfer formula, with numbers
st.subheader("🧮 How transfers are decided — the formula")
_capn = config.soft_team_cap(target)
_stage_lbl = "group stage" if _capn < config.MAX_PER_TEAM else "knockouts"
st.markdown(
    "The model scores **every** plan that fits your budget (all single, double and triple swaps), then "
    "re-simulates the shortlist for **win probability**. The rules it applies, in order:\n\n"
    "1. **Playtime first** — every rating is scaled by **P(start)**, so a benched/cameo player is worth little "
    "and a nailed starter keeps full value *(no minutes → no points)*.\n"
    f"2. **Max {_capn} per team** ({_stage_lbl}) — a plan can **never** take a team above {_capn}, and any swap "
    "touching an over-cap team **must reduce it** (the correlated-risk guard you asked for).\n"
    "3. **Sell dead weight** — low-playtime players carry a low rating, so transferring them out is a positive "
    "gain on its own.\n"
    "4. **Buy the best** — replacements maximise **whole-tournament** expected points within budget and the cap "
    "*(a single elite player can outscore your entire bench)*.")
st.markdown("**Plan score** = ΔEV − transfer hits + diversification credit + league tilt&nbsp;&nbsp;→&nbsp;&nbsp;"
            "then the top plans are ranked by **simulated win probability**.")
_demo = best if (best and best["n_transfers"] > 0) else next((p for p in plans if p["n_transfers"] > 0), None)
if _demo:
    # round every term to 1dp and derive each subtotal FROM the rounded terms, so the
    # displayed column always adds up (no 2dp-vs-1dp drift in any regime).
    _hit = _demo["hit_cost"]
    _net = round(_demo["net_gain"], 1)
    _gross = round(_net + _hit, 1)
    _divc = round(_demo.get("diversify_credit", 0), 1)
    _tilt = round(_demo["league_gain"] - _demo["net_gain"] - _demo.get("diversify_credit", 0), 1)
    _score = round(_net + _divc + _tilt, 1)
    _n_trim = int(round(_demo.get("diversify_credit", 0) / config.CONCENTRATION_CREDIT))
    _extra = max(0, _demo["n_transfers"] - free)
    _moves = " + ".join(f"{viz_short(on)}→{viz_short(inn)}" for (on, _), (inn, _) in zip(_demo["outs"], _demo["ins"]))
    _rows = [
        ("Gross ΔEV — rest-of-cup best-XI value gained", f"{_gross:+.1f}"),
        (f"− transfer hits (−{config.EXTRA_TRANSFER_COST} × {_extra} beyond {free} free)",
         f"{-_hit:+.1f}" if _hit else "0.0"),
        ("**= net points gain**", f"**{_net:+.1f}**"),
        (f"+ diversification credit ({config.CONCENTRATION_CREDIT:g} × over-cap players trimmed)", f"{_divc:+.1f}"),
        (f"+ league tilt ({(_ls or {}).get('regime', 'coinflip')})", f"{_tilt:+.1f}"),
        ("**= plan score**", f"**{_score:+.1f}**"),
    ]
    if _demo.get("p_win") is not None:
        _rows.append(("**→ simulated win probability**", f"**{_demo['p_win'] * 100:.0f}%**"))
    _lbl = "the top plan" if _demo is best else "the best transfer plan (the model is keeping the squad this round)"
    st.caption(f"Worked example — {_lbl} ({_moves}):")
    st.markdown("| term | value |\n|:--|--:|\n" + "\n".join(f"| {t} | {v} |" for t, v in _rows))
    st.caption(f"Here it nets **{_net:+.1f}** rest-of-cup points"
               + (f" and **trims {_n_trim} over-cap player(s)** back inside the {_capn}-per-team limit."
                  if _n_trim > 0 else "."))
    # per-swap player-value deltas, so the gross ΔEV is legible at the player level
    _swaps = []
    for (on, ot), (inn, it) in zip(_demo["outs"], _demo["ins"]):
        _o, _i = row_of(on, ot), row_of(inn, it)
        _swaps.append(f"{viz_short(on)} → {viz_short(inn)} **{_i['xp_tournament'] - _o['xp_tournament']:+.1f}**")
    if _swaps:
        st.caption("Each swap's rest-of-cup value (whole-tournament xP, in − out):  " + "   ·   ".join(_swaps)
                   + ".  These roughly sum to the gross ΔEV; the exact figure re-picks your best XI after the "
                   "swaps, so it isn't a straight total.")

import plotly.graph_objects as go
st.subheader("All plans, ranked")
# plans arrive in the model's true order (win-probability, which folds in EV +
# diversification + variance). Plot that so the bars are monotonic and the order
# matches the move the model actually makes; show EV (and any stack-trim) as text.
_has_pw = any(p.get("p_win") is not None for p in plans[:8])
labels, vals, txt = [], [], []
for p in plans[:8]:
    lab = "Keep squad" if p["n_transfers"] == 0 else \
        " + ".join(f"{viz_short(on)}→{viz_short(inn)}" for (on, _), (inn, _) in zip(p["outs"], p["ins"]))
    labels.append(lab + (f"  [−{p['hit_cost']}]" if p["hit_cost"] else ""))
    trim = " · trims stack" if p.get("diversify_credit", 0) > 0 else ""
    if _has_pw:
        vals.append(round((p.get("p_win") or 0) * 100, 1))
        txt.append(f"{(p.get('p_win') or 0) * 100:.0f}% · {p['net_gain']:+.1f} pts{trim}")
    else:
        # plot the SAME quantity the list is sorted by (adj_gain / league_gain), so the
        # bars are monotonic; show the raw EV as the text annotation.
        vals.append(round(p.get("adj_gain", p.get("league_gain", p["net_gain"])), 1))
        txt.append(f"{p['net_gain']:+.1f} pts{trim}")
figp = go.Figure(go.Bar(
    x=vals[::-1], y=labels[::-1], orientation="h",
    marker_color=[viz_gain if p["net_gain"] >= 0 else viz_neutral for p in plans[:8]][::-1],
    text=txt[::-1], textposition="outside", cliponaxis=False))
figp.update_layout(height=90 + 36 * len(labels), margin=dict(l=10, r=10, t=10, b=10),
                   xaxis_title=("Win probability % — the objective (EV + diversification + variance)"
                                if _has_pw else "Plan value — EV + diversification + variance (text = raw EV)"))
st.plotly_chart(figp, width="stretch", config={"displayModeBar": False})
st.caption("Ranked by the model's true objective — **win probability** when rivals' squads are known, else raw "
           "points. The text shows each plan's raw EV gain (net of any −4 hit, over the rest of the cup) and "
           "flags when a plan **trims a 3-from-one-country stack** (group-stage diversification). The top plan "
           "isn't always the most points — it's the most likely to win you the round.")

a, b = st.columns(2)
with a:
    st.subheader(f"Captain picks (round {target})")
    _cap_regime = (_ls or {}).get("regime")
    _cap_fo = (analytics.field_effective_ownership((_ls or {}).get("rival_squads") or [],
                                                   (_ls or {}).get("rival_captains")) if _ls else None)
    st.dataframe(
        optimizer.captain_options(owned, regime=_cap_regime, field_own=_cap_fo),
        hide_index=True, width="stretch",
        column_config={
            "armband": st.column_config.TextColumn("", help="🟠 C = the captain the autopilot would set, "
                                                            "🔵 V = vice."),
            "opponent": st.column_config.TextColumn(f"opp R{target}"),
            "xp_next": st.column_config.NumberColumn(f"xP R{target}", format="%.2f"),
            "p_play": st.column_config.NumberColumn("plays %", format="percent"),
            "cap_ev": st.column_config.NumberColumn("cap EV", format="%.2f",
                                                    help="Availability-weighted EV (xP × P(plays)). The 🟠C/🔵V "
                                                         "is this PLUS a leader/chaser regime tilt, so under a "
                                                         "tilt the armband can sit just above a higher-EV row."),
        })
    st.caption("Ranked the way the **autopilot actually sets the armband** (availability-weighted, "
               "regime-aware) and limited to your starting XI — so 🟠 C is exactly what gets written and what "
               "the win-probability sim assumes, not a raw xP pick that could name a benched player.")
with b:
    st.subheader(f"Suggested starting XI (round {target})")
    xi = optimizer.best_xi(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)
    xi_df = owned.loc[[i for i in xi["xi_ids"] if i in owned.index]]
    xi_df = xi_df.sort_values("position", key=lambda s: s.map({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}))
    st.write(f"Formation **{xi['formation']}** — projected **{xi['total']:.1f}** pts for round {target}")
    st.dataframe(xi_df[["name", "team", "position", "xp_next"]], hide_index=True, width="stretch",
                 column_config={"xp_next": st.column_config.NumberColumn(f"xP R{target}", format="%.2f")})

# ---------------------------------------------------------------- formation finder
st.subheader(f"🔷 Which formation should I use? — round {target}")
_cur_xi = set(optimizer.best_xi(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)["xi_ids"])
_bench_cost = float(owned.loc[[i for i in owned.index if i not in _cur_xi], "price"].sum())
st.caption(f"💰 **Bench fodder:** **{_bench_cost:.1f}M** of your £100M is parked on the 4 bench players (they "
           "barely score). You can't field fewer than 15, but the model now **penalises dead bench money and "
           "routes it into your XI** — that's how it affords stars. Keep the bench the cheapest viable cover.")
_winf = services.get_formation_win_probs(my["squad"])
if _winf:
    _pick = _winf[0]                                   # the shape the model fields (p_win, EV-tiebroken)
    _disp = sorted(_winf, key=lambda f: f["p_win"])    # plotly draws bottom-up → highest p_win on top
    _ff = go.Figure(go.Bar(
        x=[f["p_win"] * 100 for f in _disp], y=[f["formation"] for f in _disp], orientation="h",
        marker_color=["#00b894" if f["formation"] == _pick["formation"] else viz_neutral for f in _disp],
        text=[f"{f['p_win'] * 100:.0f}%" for f in _disp], textposition="outside", cliponaxis=False))
    _ff.update_layout(height=80 + 32 * len(_disp), margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(title="P(finish 1st in the league) — simulated per formation",
                                 range=[0, max(f["p_win"] * 100 for f in _disp) * 1.18 + 0.5]))
    st.plotly_chart(_ff, width="stretch", config={"displayModeBar": False})
    st.caption(
        f"**Best formation: {_pick['formation']}** (green) — chosen to maximise **P(finishing 1st in the FINAL "
        "standings)**, Monte-Carlo'd across all 7 shapes vs your rivals' real squads (folding in your current "
        "points gap + the rest of the cup). The model fields it automatically; you set it on TV2 by which 11 you "
        "start. When several shapes are a **statistical tie** on title odds (as when you're far ahead or behind, "
        "like now), it takes the **highest expected-points** one — and leans to higher-ceiling attacking shapes "
        "only when extra variance actually lifts your title chances (close races).")
else:
    # rivals not known yet → rank by expected points instead
    _forms = optimizer.formation_options(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)
    if _forms:
        _bestf = _forms[0]
        _ff = go.Figure(go.Bar(
            x=[f["total"] for f in _forms][::-1], y=[f["formation"] for f in _forms][::-1], orientation="h",
            marker_color=["#00b894" if f["formation"] == _bestf["formation"] else viz_neutral
                          for f in _forms][::-1],
            text=[f"{f['total']:.1f}" for f in _forms][::-1], textposition="outside", cliponaxis=False))
        _ff.update_layout(height=80 + 32 * len(_forms), margin=dict(l=10, r=10, t=10, b=10),
                          xaxis=dict(title=f"Projected XI points (round {target}, captain ×2)",
                                     range=[0, max(f["total"] for f in _forms) * 1.12]))
        st.plotly_chart(_ff, width="stretch", config={"displayModeBar": False})
        st.caption(f"**Best formation: {_bestf['formation']}** ({_bestf['total']:.1f} projected pts). Ranked by "
                   "expected points until your rivals' squads unlock, then it switches to title probability.")
    else:
        st.caption("Not enough players to form a valid XI yet.")
