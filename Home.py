import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="VM Fantasy Companion", page_icon="⚽", layout="wide")

from src import optimizer, services, template_team

d = services.get_data()
st.title("⚽ VM Fantasy Companion")
services.render_banners(d)
if d["players"] is None or d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my = d["proj"], d["my_team"]
owned = proj.loc[[i for i in my["squad"] if i in proj.index]]
xi = optimizer.best_xi(owned, "xp_next")
cap_name = proj.loc[xi["captain_id"], "name"] if xi["captain_id"] else "-"

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Next round", f"Round {d['next_round']}")
c2.metric("Projected XI", f"{xi['total']:.0f} pts", help="Best starting XI for the next round, captain doubled")
c3.metric("Captain", cap_name)
c4.metric("My total points", int(owned["total_points"].sum()))
c5.metric("Bank", f"{my.get('bank', 0):.1f}M")

# ---------------------------------------------------------------- contributions
st.subheader("Where your next-round points come from")
contrib = owned[owned["id"].isin(xi["xi_ids"])].copy()
contrib["pts"] = contrib["xp_next"] * contrib["id"].map(lambda i: 2 if i == xi["captain_id"] else 1)
contrib = contrib.sort_values("pts")
bar = go.Figure(go.Bar(
    x=contrib["pts"], y=contrib["name"] + "  (" + contrib["team"] + ")", orientation="h",
    marker_color=["#e17055" if i == xi["captain_id"] else "#00b894" for i in contrib["id"]],
    text=[f"{p:.1f}" for p in contrib["pts"]], textposition="outside"))
bar.update_layout(height=460, xaxis_title="Projected points (captain ×2 in red)",
                  margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(bar, width="stretch")

# ---------------------------------------------------------------- my squad
st.subheader("Full squad — next round outlook")
view = owned.copy()
view["suggested XI"] = view["id"].isin(xi["xi_ids"])
view["C"] = view["id"] == xi["captain_id"]
view = view.sort_values(["position", "xp_next"],
                        key=lambda s: s.map({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}) if s.name == "position" else s,
                        ascending=[True, False])
st.dataframe(
    view[["name", "team", "position", "price", "opponent", "venue", "apparent_temp",
          "heat_mult", "xp_next", "xp_horizon", "suggested XI", "C"]],
    column_config={
        "apparent_temp": st.column_config.NumberColumn("feels like °C", format="%.0f"),
        "heat_mult": st.column_config.NumberColumn("heat ×", format="%.2f"),
        "xp_next": st.column_config.NumberColumn("xP next", format="%.2f"),
        "xp_horizon": st.column_config.NumberColumn("xP horizon", format="%.2f"),
        "C": st.column_config.CheckboxColumn("captain"),
    },
    hide_index=True, width="stretch",
)
st.caption(f"Suggested formation {xi['formation']}, projected XI total **{xi['total']:.1f}** pts "
           f"(captain doubled). Heat × applies to attacking output only; 1.00 = no penalty.")

# ---------------------------------------------------------------- chart
st.subheader("Me vs the template (most-owned) team")
cmp = template_team.comparison_frame(proj, my, d["completed"])
if cmp is None:
    if proj["ownership_pct"].isna().all():
        st.info("Ownership data arrives with the first real TV 2 sync — the template team needs it.")
    else:
        st.info("No completed rounds yet — the comparison chart appears after the first matchday.")
else:
    fig = go.Figure()
    fig.add_scatter(x=cmp["round"], y=cmp["mine_cum"], name="My team", mode="lines+markers")
    fig.add_scatter(x=cmp["round"], y=cmp["template_cum"], name="Template team", mode="lines+markers")
    fig.update_layout(xaxis_title="Round", yaxis_title="Cumulative points", height=380)
    st.plotly_chart(fig, width="stretch")
    if cmp["mine_estimated"].any():
        st.caption("⚠️ Rounds marked estimated use your current XI retroactively — synced history replaces this.")

# ---------------------------------------------------------------- differentials
diff = template_team.differentials(proj, my["squad"])
if diff is not None:
    mine_only, tmpl_only = diff
    a, b = st.columns(2)
    with a:
        st.subheader("My differentials")
        st.caption("I own, template doesn't — where I win or lose vs the crowd")
        st.dataframe(mine_only, hide_index=True, width="stretch")
    with b:
        st.subheader("Template's edge")
        st.caption("Template owns, I don't — their points here hurt me")
        st.dataframe(tmpl_only, hide_index=True, width="stretch")
