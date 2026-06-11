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

c1, c2, c3, c4 = st.columns(4)
c1.metric("Next round", f"Round {d['next_round']}")
c2.metric("My total points", int(owned["total_points"].sum()))
c3.metric("Bank", f"{my.get('bank', 0):.1f}M")
c4.metric("Free transfers", my.get("free_transfers", 2))

# ---------------------------------------------------------------- my squad
st.subheader("My squad — next round outlook")
xi = optimizer.best_xi(owned, "xp_next")
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
