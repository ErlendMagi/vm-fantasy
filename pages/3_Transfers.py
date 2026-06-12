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
if d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my = d["proj_plan"], d["my_team"]
if d["target_round"] != d["next_round"]:
    st.caption(f"Planning **round {d['target_round']}** (the next editable round). "
               f"Round {d['next_round']} is locked and scoring live.")
owned = proj.loc[[i for i in my["squad"] if i in proj.index]]

st.subheader("Current squad health")
st.caption("P(plays next+1) is the odds-derived chance the team is still in the tournament — "
           "low values mean the player is about to stop scoring points (elimination risk).")
sq = owned.sort_values("xp_horizon", ascending=False)
st.dataframe(
    sq[["name", "team", "position", "price", "opponent", "heat_mult", "xp_next", "xp_horizon", "p_plays_after"]],
    column_config={
        "heat_mult": st.column_config.NumberColumn("heat ×", format="%.2f"),
        "xp_next": st.column_config.NumberColumn("xP next", format="%.2f"),
        "xp_horizon": st.column_config.NumberColumn("xP horizon", format="%.2f"),
        "p_plays_after": st.column_config.ProgressColumn("P(plays next+1)", min_value=0, max_value=1, format="%.2f"),
    },
    hide_index=True, width="stretch",
)

st.subheader("Best transfer plans")
default_free = int(my.get("free_transfers", 2))
unlimited = default_free >= config.SQUAD_SIZE
if unlimited:
    st.info("Transfers are currently **unlimited** (the squad isn't locked yet) — no −4 hits apply. "
            "After round 1 locks this becomes 2 free per round.")
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


if best and best["n_transfers"] > 0:
    st.caption(f"Best plan: **+{best['net_gain']:.1f}** points over the rest of the cup"
               + (f" after a −{best['hit_cost']} hit." if best["hit_cost"] else ".") + f" {auto_note}")
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
            f.update_layout(barmode="group", height=300, yaxis_title="Expected pts (next round)",
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
    st.subheader("Captain picks (next round)")
    st.dataframe(optimizer.captain_options(owned), hide_index=True, width="stretch")
with b:
    st.subheader("Suggested starting XI")
    xi = optimizer.best_xi(owned, "xp_next")
    xi_df = owned.loc[[i for i in xi["xi_ids"] if i in owned.index]]
    xi_df = xi_df.sort_values("position", key=lambda s: s.map({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}))
    st.write(f"Formation **{xi['formation']}** — projected **{xi['total']:.1f}** pts")
    st.dataframe(xi_df[["name", "team", "position", "xp_next"]], hide_index=True, width="stretch")
