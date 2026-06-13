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

proj, my, ranks = d["proj_plan"], d["my_team"], d["ranks"]
target, live = d["target_round"], d["next_round"]
if target != live:
    st.info(f"**Round {live} is live & locked** — your team is scoring now (captain can't change). "
            f"Everything below is your plan for **round {target}**, the next editable round, which the "
            f"autopilot finalises before its deadline.")
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

# ---------------------------------------------------------------- model check: expected vs actual
st.subheader("🔬 Is the model working? Expected vs actual")
st.caption("The honest scoreboard for the projections. For every player who's *already played* this round, "
           "this compares what the model expected them to score against what they really scored — so you "
           "can see if the projections are calibrated or just optimistic.")

from src import data_access as _da

_league = _da.load_league()
proj_live = d["proj"]
_me = None
for _L in (_league or {}).get("leagues", []):
    for _mm in _L.get("members", []):
        if _mm.get("squad_name") == my.get("squad_name"):
            _me = _mm
_rd = next((r for r in (_me.get("rounds") or []) if r.get("number") == live), {}) if _me else {}
_starters = _rd.get("starter_ids") or []
_capid = _rd.get("captain_id")
_scores = _rd.get("scores") or {}


def _xp_live(pid):
    return float(proj_live.loc[pid, "xp_next"]) if pid in proj_live.index else 0.0


if not _starters:
    st.info("Your fielded XI for the live round isn't available yet — this fills in once the round locks "
            "and your players start playing.")
else:
    rows = []
    for pid in _starters:
        nm = (proj_live.loc[pid, "name"] if pid in proj_live.index else pid)
        exp = round(_xp_live(pid) * (2 if pid == _capid else 1), 1)   # points-as-they-count (capt doubled)
        played = pid in _scores
        act = _scores.get(pid) if played else None
        rows.append({"Player": nm + (" (C)" if pid == _capid else ""),
                     "Pos": (proj_live.loc[pid, "position"] if pid in proj_live.index else ""),
                     "Expected": exp, "Actual": act, "played": played,
                     "Δ": (round((act or 0) - exp, 1) if played else None)})
    played_rows = [r for r in rows if r["played"]]
    exp_played = sum(r["Expected"] for r in played_rows)
    act_played = sum((r["Actual"] or 0) for r in played_rows)
    exp_full = sum(r["Expected"] for r in rows)
    projected_final = act_played + (exp_full - exp_played)   # real so far + model for the rest

    m1, m2, m3 = st.columns(3)
    m1.metric(f"Actual so far ({len(played_rows)}/{len(rows)} played)", f"{act_played:.0f}",
              delta=(f"{act_played - exp_played:+.1f} vs model" if played_rows else None),
              help="Real points from your players whose match has finished this round.")
    m2.metric("Model expected (same players)", f"{exp_played:.1f}",
              help="What the model projected for exactly those finished players — the apples-to-apples test.")
    m3.metric("On pace for", f"{projected_final:.0f}",
              help=f"Real points so far + the model's projection for your {len(rows) - len(played_rows)} "
                   "players still to play. Model expected the full XI to score "
                   f"{exp_full:.0f}.")

    if len(played_rows) < 3:
        st.caption(f"⏳ Only {len(played_rows)} of your players have played round {live} so far — too small "
                   "a sample to judge the model yet. The verdict sharpens as the round fills out.")
    else:
        ratio = act_played / exp_played if exp_played else 1.0
        if ratio >= 1.10:
            st.success(f"✅ **Your XI is over-performing the model** — {act_played:.0f} actual vs "
                       f"{exp_played:.1f} expected ({(ratio - 1) * 100:+.0f}%). Either variance is in your "
                       "favour or the projections are a touch conservative.")
        elif ratio <= 0.90:
            st.warning(f"⚠️ **Your XI is under the model** — {act_played:.0f} actual vs {exp_played:.1f} "
                       f"expected ({(ratio - 1) * 100:+.0f}%). Early bad luck, or the model is optimistic "
                       "for these picks.")
        else:
            st.info(f"🎯 **The model is tracking reality well** — {act_played:.0f} actual vs "
                    f"{exp_played:.1f} expected ({(ratio - 1) * 100:+.0f}%). Projections look calibrated.")

    _df = pd.DataFrame(
        sorted([r for r in rows if r["played"]], key=lambda r: r["Δ"], reverse=True)
        + sorted([r for r in rows if not r["played"]], key=lambda r: r["Expected"], reverse=True)
    )
    _df["Actual"] = _df.apply(lambda r: f"{r['Actual']:.0f}" if r["played"] else "— to play", axis=1)
    _df["Δ"] = _df["Δ"].apply(lambda v: (f"{v:+.1f}" if v is not None else ""))
    st.dataframe(_df[["Player", "Pos", "Expected", "Actual", "Δ"]], hide_index=True, width="stretch")

    # round-by-round trend - only completed rounds are a fair test
    _acc = _da.load_model_accuracy().get("rounds", {})
    done = {int(k): v for k, v in _acc.items()
            if v.get("starters") and v.get("played", 0) >= v["starters"]}
    if done:
        ks = sorted(done)
        tfig = go.Figure()
        tfig.add_bar(x=[f"R{k}" for k in ks], y=[done[k]["expected"] for k in ks],
                     name="Model expected", marker_color="#0984e3")
        tfig.add_bar(x=[f"R{k}" for k in ks], y=[done[k]["actual"] for k in ks],
                     name="Actually scored", marker_color="#00b894")
        tfig.update_layout(barmode="group", height=300, yaxis_title="Round points",
                           legend=dict(orientation="h", y=-0.2), margin=dict(l=10, r=10, t=10, b=10))
        st.markdown("**Round-by-round: expected vs actual** (completed rounds only)")
        st.plotly_chart(tfig, width="stretch", config={"displayModeBar": False})
    else:
        st.caption("📊 A round-by-round expected-vs-actual chart appears here once round "
                   f"{live} finishes — then every round adds a bar so you can watch the model's accuracy "
                   "over the whole tournament.")

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

# ---------------------------------------------------------------- vs the People's Index (the fund analogy)
st.divider()
st.header("📊 You vs the People's Index")
st.caption("Think of your team as an **actively managed fund** and the **People's Index** as the market: "
           "the ownership-weighted average player at each position — what the average krone in the game earns. "
           "Beating it round after round is your **alpha**.")
completed = d["completed"]
if proj["ownership_pct"].isna().all():
    st.warning("Ownership data isn't in yet — the index needs it. It appears after the next sync.")
else:
    my_next_idx = optimizer.best_xi(owned, "xp_next")["total"]
    idx_next = template_team.index_next_projection(proj)
    histr = {int(k): v for k, v in (my.get("round_history") or {}).items()}
    rows, mine_cum, idx_cum = [], 0.0, 0.0
    for r in completed:
        mine_r = histr.get(r)
        if mine_r is None:
            xi_ids = my.get("starting_xi") or my["squad"][:11]
            cap = my.get("captain_id")
            mine_r = sum(proj.loc[i, "round_points"].get(r, 0) for i in xi_ids if i in proj.index)
            mine_r += proj.loc[cap, "round_points"].get(r, 0) if cap in proj.index else 0
        idx_r = template_team.index_round_actual(proj, r)
        mine_cum += mine_r
        idx_cum += idx_r
        rows.append({"round": r, "mine": mine_r, "index": idx_r, "mine_cum": mine_cum, "index_cum": idx_cum})
    idf = pd.DataFrame(rows)

    k1, k2, k3 = st.columns(3)
    if not idf.empty:
        alpha = idf["mine_cum"].iloc[-1] - idf["index_cum"].iloc[-1]
        k1.metric("Your points", f"{idf['mine_cum'].iloc[-1]:.0f}")
        k2.metric("The Index", f"{idf['index_cum'].iloc[-1]:.0f}")
        k3.metric("Your alpha", f"{alpha:+.1f}", help="Points above/below the market benchmark")
    else:
        k1.metric("Projected next (you)", f"{my_next_idx:.0f}")
        k2.metric("Projected next (Index)", f"{idx_next:.0f}")
        k3.metric("Projected edge", f"{my_next_idx - idx_next:+.1f}")

    nxt = (completed[-1] + 1) if completed else 1
    ifig = go.Figure()
    if not idf.empty:
        ifig.add_scatter(x=idf["round"], y=idf["mine_cum"], name="My team", mode="lines+markers",
                         line=dict(width=5, color=viz.MINE_GREEN, shape="spline", smoothing=0.8))
        ifig.add_scatter(x=idf["round"], y=idf["index_cum"], name="People's Index", mode="lines+markers",
                         line=dict(width=3, color=viz.NEUTRAL, shape="spline", smoothing=0.8))
        ifig.add_scatter(x=[idf["round"].iloc[-1], nxt],
                         y=[idf["mine_cum"].iloc[-1], idf["mine_cum"].iloc[-1] + my_next_idx],
                         mode="lines", line=dict(width=5, color=viz.MINE_GREEN, dash="dash", shape="spline"),
                         showlegend=False)
        ifig.add_scatter(x=[idf["round"].iloc[-1], nxt],
                         y=[idf["index_cum"].iloc[-1], idf["index_cum"].iloc[-1] + idx_next],
                         mode="lines", line=dict(width=3, color=viz.NEUTRAL, dash="dash", shape="spline"),
                         showlegend=False)
    else:
        ifig.add_scatter(x=[0, 1], y=[0, my_next_idx], name="My team (proj)", mode="lines+markers",
                         line=dict(width=5, color=viz.MINE_GREEN, dash="dash", shape="spline", smoothing=0.8))
        ifig.add_scatter(x=[0, 1], y=[0, idx_next], name="Index (proj)", mode="lines+markers",
                         line=dict(width=3, color=viz.NEUTRAL, dash="dash", shape="spline", smoothing=0.8))
    ifig.update_layout(xaxis_title="Round", yaxis_title="Cumulative points", height=400,
                       legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(ifig, width="stretch", config={"displayModeBar": False})

    st.markdown("**Your bets vs the market** — expected points per position (next round). Taller-than-grey = "
                "overweight, expecting to beat the market there.")
    my_xi = owned.loc[[i for i in xi["xi_ids"] if i in owned.index]]
    cats, mine_v, idx_v = [], [], []
    for pos in viz.POS_ORDER:
        mine_v.append(float(my_xi[my_xi["position"] == pos]["xp_next"].sum()))
        sub = proj[proj["position"] == pos]
        idx_v.append(template_team._own_weighted_avg(sub, sub["xp_next"]) * template_team.INDEX_XI[pos])
        cats.append(viz.POS_LABEL[pos])
    posfig = go.Figure()
    posfig.add_bar(name="My XI", x=cats, y=mine_v, marker_color=viz.MINE_GREEN)
    posfig.add_bar(name="People's Index", x=cats, y=idx_v, marker_color=viz.NEUTRAL)
    posfig.update_layout(barmode="group", height=320, yaxis_title="Expected points (next round)",
                         legend=dict(orientation="h", y=-0.25), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(posfig, width="stretch", config={"displayModeBar": False})
