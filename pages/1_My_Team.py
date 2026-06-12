from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="My Team", page_icon="⚽", layout="wide")

from src import analytics, nav, optimizer, services, template_team, viz

nav.render("My Team")
d = services.get_data()
st.title("⚽ My team")
services.render_banners(d)
if d["players"] is None or d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my, ranks = d["proj"], d["my_team"], d["ranks"]
owned = proj.loc[[i for i in my["squad"] if i in proj.index]]
xi = optimizer.best_xi(owned, "xp_next")
cap_name = proj.loc[xi["captain_id"], "name"] if xi["captain_id"] else "-"
rating = analytics.team_rating(proj, my["squad"], ranks)
squad_rating = analytics.squad_quality(proj, my["squad"])  # all 15
history = {int(k): v for k, v in (my.get("round_history") or {}).items()}
points_so_far = sum(history.values()) if history else int(owned["total_points"].sum())

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("⭐ Squad rating", f"{squad_rating['rating']:.0f}/100",
          help="Average quality percentile across ALL 15 of your players (their rank within position). "
               "This is the number to push toward 100 by the end of the cup.")
c2.metric("Starting XI rating", f"{rating['rating']:.0f}/100",
          help="Same idea but only your 11 starters — the XI you actually field")
c3.metric("Expected next round", f"{xi['total']:.0f}", help=f"Captain: {cap_name} (doubled)")
c4.metric("Points so far", points_so_far)
c5.metric("Bank", f"{my.get('bank', 0):.1f}M")

# ---------------------------------------------------------------- pitch (always visible)
st.subheader("Your team on the pitch")
st.caption("Real player photos + flags. Each card: rank in position (#), price, expected points, and a "
           "floor→ceiling bar (how safe vs explosive). Captain ringed in orange.")
floors = dict(zip(owned.index, owned["floor"]))
ceils = dict(zip(owned.index, owned["ceiling"]))
bench = [p for p in my["squad"] if p not in xi["xi_ids"]]
st.markdown(viz.pitch_html(owned, xi["xi_ids"], xi["captain_id"], "xp_next", bench, ranks, floors, ceils),
            unsafe_allow_html=True)
st.caption(f"Formation **{xi['formation']}** — re-chosen every round to maximise points, so it can change "
           f"through the tournament. Average XI rank: GK #{rating['avg_pos_rank']['GK']}, "
           f"DEF #{rating['avg_pos_rank']['DEF']}, MID #{rating['avg_pos_rank']['MID']}, "
           f"FWD #{rating['avg_pos_rank']['FWD']}.")

# ---------------------------------------------------------------- rating over time
st.subheader("📈 Your ratings, day by day")
st.caption("Ratings move daily with odds, form and survival outlooks — the staff you want at the end of "
           "the cup is the highest-rated squad money can hold. Squad = all 15, XI = your starters, "
           "plus each position's strength (100 = best possible).")
import json as _json

from src import config as _cfg

_hist_file = _cfg.TV2_DIR / "rating_history.json"
if _hist_file.exists():
    _days = _json.loads(_hist_file.read_text(encoding="utf-8")).get("days", {})
else:
    _days = {}
if _days:
    hx = sorted(_days)
    rfig = go.Figure()
    series = [("Squad (all 15)", [_days[k]["squad_rating"] for k in hx], "#00b894", 5),
              ("Starting XI", [_days[k]["xi_rating"] for k in hx], "#0984e3", 3)]
    for pos, colr in [("GK", "#6c5ce7"), ("DEF", "#fdcb6e"), ("MID", "#74b9ff"), ("FWD", "#55efc4")]:
        vals = [(_days[k]["pos_rating"] or {}).get(pos) for k in hx]
        series.append((pos, vals, colr, 1.5))
    for nm, vals, colr, w in series:
        rfig.add_scatter(x=hx, y=vals, name=nm, mode="lines+markers",
                         line=dict(color=colr, width=w, shape="spline", smoothing=0.9),
                         marker=dict(size=5))
    rfig.update_layout(height=380, yaxis=dict(title="Rating (0–100)", range=[0, 102]),
                       legend=dict(orientation="h", y=-0.25), hovermode="x unified",
                       margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(rfig, width="stretch", config={"displayModeBar": False})
    if len(hx) < 3:
        st.caption(f"⏳ History started {hx[0]} — the lines get interesting as days accumulate "
                   "(one snapshot per day, recorded automatically in the cloud).")
else:
    st.info("Rating history starts recording today — the chart appears after the first daily snapshot.")

# ---------------------------------------------------------------- my upcoming matches
st.subheader("📅 Your upcoming matches")
my_teams = set(owned["team"])
fixtures = sorted([fx for fx in d["fixtures"]
                   if (fx.get("home") in my_teams or fx.get("away") in my_teams)
                   and fx.get("status") != "finished"], key=lambda f: f["kickoff_utc"])
if not fixtures:
    st.caption("No upcoming fixtures yet.")
else:
    rows = []
    for fx in fixtures[:14]:
        ko = datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=2)))
        for side in ("home", "away"):
            if fx[side] in my_teams:
                mh = owned[owned["team"] == fx[side]]
                rows.append({"When (Oslo)": ko.strftime("%a %d %b · %H:%M"),
                             "Match": f"{viz.flag(fx['home'])} {fx['home']} – {fx['away']} {viz.flag(fx['away'])}",
                             "Your players": ", ".join(viz.short_name(n) for n in mh["name"]),
                             "Their xP": round(float(mh["xp_next"].sum()), 1)})
    st.dataframe(rows, hide_index=True, width="stretch")

# ---------------------------------------------------------------- purchase report card
st.subheader("🧾 Your purchases — has each pick paid off?")
st.caption("Points returned per million spent. Until games are played everyone reads 'no points yet'.")
rep = owned.assign(
    flag=owned["team"].map(viz.flag),
    rank=[f"#{ranks.get(i, '?')}" for i in owned.index],
    verdict=[analytics.roi_label(r, p) for r, p in zip(owned["roi"], owned["total_points"])])
st.dataframe(
    rep.sort_values("roi", ascending=False)[
        ["flag", "name", "team", "position", "rank", "price", "total_points", "roi", "verdict"]],
    hide_index=True, width="stretch",
    column_config={"flag": "", "rank": "pos rank", "price": st.column_config.NumberColumn("price", format="%.1fM"),
                   "total_points": "points", "roi": st.column_config.NumberColumn("pts / M", format="%.2f"),
                   "verdict": "verdict"})

# ---------------------------------------------------------------- contributions chart
st.subheader("Top point sources this round")
contrib = owned[owned["id"].isin(xi["xi_ids"])].copy()
contrib["pts"] = contrib["xp_next"] * contrib["id"].map(lambda i: 2 if i == xi["captain_id"] else 1)
contrib = contrib.sort_values("pts").tail(8)
barf = go.Figure(go.Bar(
    x=contrib["pts"], y=[f"{viz.flag(t)} {viz.short_name(n)}" for n, t in zip(contrib["name"], contrib["team"])],
    orientation="h", marker_color=["#e17055" if i == xi["captain_id"] else "#00b894" for i in contrib["id"]],
    text=[f"{p:.1f}" for p in contrib["pts"]], textposition="outside", cliponaxis=False))
barf.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                   xaxis_title="Expected points (captain ×2 in orange)")
st.plotly_chart(barf, width="stretch", config={"displayModeBar": False})
