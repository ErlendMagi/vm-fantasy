import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="My Fund vs The Index", page_icon="📊", layout="wide")

from src import nav, optimizer, services, template_team, viz

nav.render("vs Index")
d = services.get_data()
st.title("📊 My team vs the People's Index")
services.render_banners(d)
if d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my, completed = d["proj"], d["my_team"], d["completed"]
owned = proj.loc[[i for i in my["squad"] if i in proj.index]]

st.info("Think of your team as an **actively managed fund** and the **People's Index** as the market "
        "it's measured against. The index isn't the most-owned dream team (nobody can afford that) — it's "
        "the *ownership-weighted average* player at each position, i.e. what the average krone in the game "
        "earns. Beating it round after round is your **alpha**.")

if proj["ownership_pct"].isna().all():
    st.warning("Ownership data isn't in yet — the index needs it. It appears after the next sync.")
    st.stop()

# ---- projection for the next round ----
my_next = optimizer.best_xi(owned, "xp_next")["total"]
idx_next = template_team.index_next_projection(proj)
history = {int(k): v for k, v in (my.get("round_history") or {}).items()}

# ---- cumulative actual (and projected) series ----
rows, mine_cum, idx_cum = [], 0.0, 0.0
for r in completed:
    mine_r = history.get(r)
    if mine_r is None:  # estimate from my current XI's actual points that round
        xi_ids = my.get("starting_xi") or my["squad"][:11]
        cap = my.get("captain_id")
        mine_r = sum(proj.loc[i, "round_points"].get(r, 0) for i in xi_ids if i in proj.index)
        mine_r += proj.loc[cap, "round_points"].get(r, 0) if cap in proj.index else 0
    idx_r = template_team.index_round_actual(proj, r)
    mine_cum += mine_r
    idx_cum += idx_r
    rows.append({"round": r, "mine": mine_r, "index": idx_r,
                 "mine_cum": mine_cum, "index_cum": idx_cum})
df = pd.DataFrame(rows)

c1, c2, c3 = st.columns(3)
if not df.empty:
    alpha = df["mine_cum"].iloc[-1] - df["index_cum"].iloc[-1]
    c1.metric("Your points so far", f"{df['mine_cum'].iloc[-1]:.0f}")
    c2.metric("The Index", f"{df['index_cum'].iloc[-1]:.0f}")
    c3.metric("Your alpha", f"{alpha:+.1f}", help="Points above (or below) the market benchmark")
else:
    c1.metric("Projected next round (you)", f"{my_next:.0f}")
    c2.metric("Projected next round (Index)", f"{idx_next:.0f}")
    c3.metric("Projected edge", f"{my_next - idx_next:+.1f}")

# ---- the fund-vs-index chart ----
st.subheader("Cumulative return")
fig = go.Figure()
nxt = (completed[-1] + 1) if completed else 1
if not df.empty:
    fig.add_scatter(x=df["round"], y=df["mine_cum"], name="My team", mode="lines+markers",
                    line=dict(width=5, color=viz.MINE_GREEN))
    fig.add_scatter(x=df["round"], y=df["index_cum"], name="People's Index", mode="lines+markers",
                    line=dict(width=3, color=viz.NEUTRAL))
    # one projected step forward (dashed)
    fig.add_scatter(x=[df["round"].iloc[-1], nxt], y=[df["mine_cum"].iloc[-1], df["mine_cum"].iloc[-1] + my_next],
                    name="My team (proj)", mode="lines", line=dict(width=5, color=viz.MINE_GREEN, dash="dash"), showlegend=False)
    fig.add_scatter(x=[df["round"].iloc[-1], nxt], y=[df["index_cum"].iloc[-1], df["index_cum"].iloc[-1] + idx_next],
                    name="Index (proj)", mode="lines", line=dict(width=3, color=viz.NEUTRAL, dash="dash"), showlegend=False)
else:
    fig.add_scatter(x=[0, 1], y=[0, my_next], name="My team (proj)", mode="lines+markers",
                    line=dict(width=5, color=viz.MINE_GREEN, dash="dash"))
    fig.add_scatter(x=[0, 1], y=[0, idx_next], name="Index (proj)", mode="lines+markers",
                    line=dict(width=3, color=viz.NEUTRAL, dash="dash"))
fig.update_layout(xaxis_title="Round", yaxis_title="Cumulative points", height=420)
st.plotly_chart(fig, width="stretch")

# ---- where you're over/under-weight vs the market ----
st.subheader("Your bets vs the market — expected points per position (next round)")
st.caption("Green = your starting XI's expected points at each position; grey = the index. Taller-than-grey "
           "means you're overweight there and expect to beat the market; shorter means you're underweight.")
my_xi = owned.loc[[i for i in optimizer.best_xi(owned, 'xp_next')['xi_ids'] if i in owned.index]]
cats, mine_v, idx_v = [], [], []
for pos in viz.POS_ORDER:
    mine_v.append(float(my_xi[my_xi["position"] == pos]["xp_next"].sum()))
    sub = proj[proj["position"] == pos]
    idx_avg = template_team._own_weighted_avg(sub, sub["xp_next"])
    idx_v.append(idx_avg * template_team.INDEX_XI[pos])
    cats.append(viz.POS_LABEL[pos])
posfig = go.Figure()
posfig.add_bar(name="My XI", x=cats, y=mine_v, marker_color=viz.MINE_GREEN)
posfig.add_bar(name="People's Index", x=cats, y=idx_v, marker_color=viz.NEUTRAL)
posfig.update_layout(barmode="group", height=340, yaxis_title="Expected points (next round)")
st.plotly_chart(posfig, width="stretch")

with st.expander("Round-by-round detail"):
    if not df.empty:
        st.dataframe(df.assign(alpha=df["mine_cum"] - df["index_cum"]),
                     hide_index=True, width="stretch",
                     column_config={"mine": "You", "index": "Index", "mine_cum": "You (cum)",
                                    "index_cum": "Index (cum)", "alpha": "Alpha"})
    else:
        st.caption("Fills in once round 1 is scored.")
