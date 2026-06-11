import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="My League", page_icon="🏆", layout="wide")

from src import data_access, services

d = services.get_data()
st.title("🏆 My league")
services.render_banners(d)

league = data_access.load_league()
if not league or not league.get("leagues"):
    st.info("League standings appear after the next data sync. The cloud job pulls them automatically; "
            "rival squads are usually hidden by TV 2 until each round's deadline passes.")
    st.stop()

proj = d["proj"]
players = d["players"]
lg = league["leagues"][0]
if len(league["leagues"]) > 1:
    names = [l["name"] for l in league["leagues"]]
    pick = st.selectbox("League", names)
    lg = next(l for l in league["leagues"] if l["name"] == pick)

members = pd.DataFrame(lg["members"])
me_name = (d["my_team"] or {}).get("squad_name")
members["is_me"] = members["squad_name"] == me_name

st.subheader(f"{lg['name']} — {len(members)} managers")

# ---- standings ----
standings = members.sort_values(["total_points", "latest_round_points"], ascending=False).reset_index(drop=True)
standings.insert(0, "pos", standings.index + 1)
show = standings[["pos", "manager", "squad_name", "total_points", "latest_round_points", "is_me"]]
st.dataframe(
    show, hide_index=True, width="stretch",
    column_config={
        "pos": "#", "manager": "Manager", "squad_name": "Team",
        "total_points": "Total", "latest_round_points": "Last round",
        "is_me": st.column_config.CheckboxColumn("You"),
    },
)

# ---- cumulative points over rounds ----
def cum_series(m):
    rs = m.get("round_scores") or []
    vals, run = [], 0
    for x in rs:
        run += (x.get("points", x) if isinstance(x, dict) else x) or 0
        vals.append(run)
    return vals

has_history = any(m.get("round_scores") for _, m in members.iterrows())
if has_history:
    st.subheader("Points race")
    fig = go.Figure()
    for _, m in members.iterrows():
        ys = cum_series(m)
        fig.add_scatter(x=list(range(1, len(ys) + 1)), y=ys, mode="lines+markers",
                        name=m["squad_name"], line=dict(width=4 if m["is_me"] else 2))
    fig.update_layout(xaxis_title="Round", yaxis_title="Cumulative points", height=420)
    st.plotly_chart(fig, width="stretch")
else:
    st.caption("📈 The points race chart fills in once round 1 is scored.")

# ---- projected next round + differentials (need rival squads, revealed at lock) ----
if proj is not None and members["squad"].apply(len).gt(0).any():
    st.subheader("Projected next round")
    rows = []
    for _, m in members.iterrows():
        owned = proj.loc[[i for i in m["squad"] if i in proj.index]] if m["squad"] else proj.head(0)
        from src import optimizer
        proj_pts = optimizer.squad_xp(owned, "xp_next") if len(owned) >= 11 else owned["xp_next"].sum()
        rows.append({"manager": m["manager"], "team": m["squad_name"],
                     "projected": round(proj_pts, 1), "is_me": m["is_me"]})
    pr = pd.DataFrame(rows).sort_values("projected", ascending=False)
    fig2 = go.Figure(go.Bar(x=pr["team"], y=pr["projected"],
                            marker_color=["#00b894" if me else "#636e72" for me in pr["is_me"]]))
    fig2.update_layout(yaxis_title="Projected points (next round)", height=360)
    st.plotly_chart(fig2, width="stretch")

    # head-to-head differentials vs each rival
    st.subheader("What you win & lose on")
    me_row = members[members["is_me"]]
    mine = set(me_row.iloc[0]["squad"]) if len(me_row) and me_row.iloc[0]["squad"] else set(
        (d["my_team"] or {}).get("squad", []))
    cols = ["name", "team", "position", "xp_next", "xp_tournament"]
    for _, m in members[~members["is_me"]].iterrows():
        if not m["squad"]:
            continue
        theirs = set(m["squad"])
        only_me = [i for i in mine - theirs if i in proj.index]
        only_them = [i for i in theirs - mine if i in proj.index]
        with st.expander(f"vs {m['manager']} ({m['squad_name']})"):
            a, b = st.columns(2)
            with a:
                st.caption("Your edge — you own, they don't")
                st.dataframe(proj.loc[only_me].sort_values("xp_tournament", ascending=False)[cols]
                             if only_me else proj.head(0)[cols], hide_index=True, width="stretch")
            with b:
                st.caption("Their edge — they own, you don't")
                st.dataframe(proj.loc[only_them].sort_values("xp_tournament", ascending=False)[cols]
                             if only_them else proj.head(0)[cols], hide_index=True, width="stretch")
else:
    st.caption("🔒 Rival squads are hidden by TV 2 until each round locks — differentials and the projected-points "
               "race will appear here right after the round 1 deadline.")
