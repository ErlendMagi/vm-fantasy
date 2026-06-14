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
    sq[["name", "team", "position", "price", "opponent", "heat_mult", "rotation_risk",
        "xp_next", "xp_horizon", "p_plays_after"]],
    column_config={
        "opponent": st.column_config.TextColumn(f"opp R{target}"),
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
is_live = (free == default_free) and abs(bank - float(my.get("bank", 0.0))) < 1e-6
best = plans[0] if plans else None
auto_note = ("The autopilot runs this exact search with your live transfers and bank before the deadline."
             if is_live else "What-if with your edited inputs — the autopilot uses your real values.")

st.subheader("💡 The move the model would make")
from src import analytics, viz
id_by_name = {(proj.loc[i, "name"], proj.loc[i, "team"]): i for i in proj.index}


def row_of(name, team):
    return proj.loc[id_by_name[(name, team)]]


_keep_pw = next((p.get("p_win") for p in plans if p["n_transfers"] == 0), None)
if best and best["n_transfers"] > 0:
    _pw = (f" It lifts your **win probability to {best['p_win'] * 100:.0f}%**"
           + (f" (from {_keep_pw * 100:.0f}% if you keep)." if _keep_pw is not None else ".")
           if best.get("p_win") is not None else "")
    st.caption(f"Best plan: **+{best['net_gain']:.1f}** points over the rest of the cup"
               + (f" after a −{best['hit_cost']} hit." if best["hit_cost"] else ".") + _pw + f" {auto_note}")
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

import plotly.graph_objects as go
st.subheader("All plans, ranked")
labels, gains = [], []
for p in plans[:8]:
    if p["n_transfers"] == 0:
        labels.append("Keep squad (baseline)")
    else:
        labels.append(" + ".join(f"{viz_short(on)}→{viz_short(inn)}" for (on, _), (inn, _) in zip(p["outs"], p["ins"]))
                      + (f"  [−{p['hit_cost']}]" if p["hit_cost"] else ""))
    gains.append(p["net_gain"])
figp = go.Figure(go.Bar(
    x=gains[::-1], y=labels[::-1], orientation="h",
    marker_color=[viz_gain if g > 0 else viz_neutral for g in gains[::-1]],
    text=[f"{g:+.1f}" for g in gains[::-1]], textposition="outside", cliponaxis=False))
figp.update_layout(height=90 + 36 * len(labels), xaxis_title="Expected points gained vs keeping the squad",
                   margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(figp, width="stretch", config={"displayModeBar": False})
st.caption("Gains are net of any −4 hit, valued over the rest of the tournament (so swapping out a player "
           "whose country is likely eliminated counts their lost future games). A hit is only proposed "
           "when it clearly pays for itself.")

a, b = st.columns(2)
with a:
    st.subheader(f"Captain picks (round {target})")
    st.dataframe(optimizer.captain_options(owned), hide_index=True, width="stretch")
with b:
    st.subheader(f"Suggested starting XI (round {target})")
    xi = optimizer.best_xi(owned, "xp_next")
    xi_df = owned.loc[[i for i in xi["xi_ids"] if i in owned.index]]
    xi_df = xi_df.sort_values("position", key=lambda s: s.map({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}))
    st.write(f"Formation **{xi['formation']}** — projected **{xi['total']:.1f}** pts for round {target}")
    st.dataframe(xi_df[["name", "team", "position", "xp_next"]], hide_index=True, width="stretch",
                 column_config={"xp_next": st.column_config.NumberColumn(f"xP R{target}", format="%.2f")})
