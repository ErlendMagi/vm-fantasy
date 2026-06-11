import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="VM Fantasy Companion", page_icon="⚽", layout="wide")

from src import optimizer, services, template_team, viz

d = services.get_data()
st.title("⚽ VM Fantasy Companion")
services.render_banners(d)
if d["players"] is None or d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my = d["proj"], d["my_team"]
owned = proj.loc[[i for i in my["squad"] if i in proj.index]]
xi = optimizer.best_xi(owned, "xp_next")
cap_name = proj.loc[xi["captain_id"], "name"] if xi["captain_id"] else "-"
squad_tournament = float(optimizer.squad_xp(owned, "xp_tournament"))

history = {int(k): v for k, v in (my.get("round_history") or {}).items()}
points_so_far = sum(history.values()) if history else None

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Next round", f"Round {d['next_round']}",
          help="The round the team below is set up for")
c2.metric("Expected points, next round", f"{xi['total']:.0f}",
          help="Best XI for the next round, captain counted twice")
c3.metric("Expected points, whole cup", f"{squad_tournament:.0f}",
          help="Best XI (captain doubled) projected over every remaining round, weighted by each team's survival odds")
c4.metric("Captain", cap_name)
if points_so_far is not None:
    c5.metric("Points so far", points_so_far, help="Your actual TV 2 fantasy score")
else:
    c5.metric("Points so far", "0", help="No completed rounds yet")

# ---------------------------------------------------------------- pitch
st.subheader("Your team on the pitch")
st.caption("Marker size = expected points next round. Orange = captain (scores double). "
           "Numbers under each player are their expected points.")
bench = [p for p in my["squad"] if p not in xi["xi_ids"]]
st.plotly_chart(viz.pitch_figure(owned, xi["xi_ids"], xi["captain_id"], "xp_next", bench),
                width="stretch", config={"displayModeBar": False})
st.caption(f"Formation **{xi['formation']}** — chosen because it maximises total expected points "
           "across all 7 legal formations.")

# ---------------------------------------------------------------- per-position + contributions
a, b = st.columns(2)
with a:
    st.subheader("Expected points by position")
    st.plotly_chart(viz.position_totals_figure(owned, xi["xi_ids"], "xp_next"),
                    width="stretch", config={"displayModeBar": False})
with b:
    st.subheader("Top point sources this round")
    contrib = owned[owned["id"].isin(xi["xi_ids"])].copy()
    contrib["pts"] = contrib["xp_next"] * contrib["id"].map(lambda i: 2 if i == xi["captain_id"] else 1)
    contrib = contrib.sort_values("pts").tail(8)
    barf = go.Figure(go.Bar(
        x=contrib["pts"], y=[viz.short_name(n) for n in contrib["name"]], orientation="h",
        marker_color=["#e17055" if i == xi["captain_id"] else "#00b894" for i in contrib["id"]],
        text=[f"{p:.1f}" for p in contrib["pts"]], textposition="outside", cliponaxis=False))
    barf.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                       xaxis_title="Expected points (captain ×2 in orange)")
    st.plotly_chart(barf, width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------- vs template
st.subheader("You vs the crowd")
cmp = template_team.comparison_frame(proj, my, d["completed"])
if cmp is None:
    st.info("📊 The points race against the most-owned 'template' team appears here after the first "
            "round is scored.")
else:
    fig = go.Figure()
    fig.add_scatter(x=cmp["round"], y=cmp["mine_cum"], name="My team", mode="lines+markers",
                    line=dict(width=4, color="#00b894"))
    fig.add_scatter(x=cmp["round"], y=cmp["template_cum"], name="Most-owned team", mode="lines+markers",
                    line=dict(width=2, color="#636e72"))
    fig.update_layout(xaxis_title="Round", yaxis_title="Cumulative points", height=380)
    st.plotly_chart(fig, width="stretch")
    if cmp["mine_estimated"].any():
        st.caption("⚠️ Rounds without scraped history are estimated from your current XI; the most-owned "
                   "team is scored from today's ownership snapshot.")

diff = template_team.differentials(proj, my["squad"])
if diff is not None:
    mine_only, tmpl_only = diff
    with st.expander("Details: where your team differs from the most-owned team"):
        a, b = st.columns(2)
        with a:
            st.caption("You own — the crowd doesn't (your potential edge)")
            st.dataframe(mine_only, hide_index=True, width="stretch")
        with b:
            st.caption("The crowd owns — you don't (their potential edge)")
            st.dataframe(tmpl_only, hide_index=True, width="stretch")
