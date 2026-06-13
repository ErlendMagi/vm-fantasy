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

# This tab focuses on the LIVE round (the one being played). Round-{target}
# PLANNING (XI/captain/transfers) lives on the Transfers tab.
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60_000, key="myteam_live_refresh")   # live scores flow in
except ImportError:
    pass

from src import data_access as _da

proj = proj_live = d["proj"]                  # LIVE round — this page's focus
proj_plan = d["proj_plan"]                    # editable round (used only for the planning pointer)
my, ranks = d["my_team"], d["ranks"]
target, live = d["target_round"], d["next_round"]

# my live-league member: live scores during matches if a token is set, else the synced file
_league = services.get_live_league() or _da.load_league()
_me = next((mm for L in (_league or {}).get("leagues", []) for mm in L.get("members", [])
            if mm.get("squad_name") == my.get("squad_name")), None)
_rd = next((r for r in ((_me or {}).get("rounds") or []) if r.get("number") == live), {})
_starters = _rd.get("starter_ids") or []
_capid = _rd.get("captain_id")
_scores = _rd.get("scores") or {}
_my_total = (_me or {}).get("total_points")

owned = proj.loc[[i for i in my["squad"] if i in proj.index]]
_best = optimizer.best_xi(owned, "xp_next")
xi_ids = [p for p in _starters if p in owned.index]
if len(xi_ids) != 11:                          # fall back to the model's XI if the sync lineup isn't 11
    xi_ids = _best["xi_ids"]
cap_id = _capid if _capid in owned.index else _best["captain_id"]
vice_id = _rd.get("vice_captain_id") if _rd.get("vice_captain_id") in owned.index else None
if vice_id is None:
    _vc = owned.loc[[p for p in xi_ids if p != cap_id and p in owned.index]].sort_values("xp_next", ascending=False)
    vice_id = _vc.index[0] if len(_vc) else None
_formation = _rd.get("formation") or _best["formation"]
xi = {"xi_ids": xi_ids, "captain_id": cap_id, "formation": _formation}   # downstream compatibility

rating_live = analytics.team_rating(proj, my["squad"], ranks)
squad_rating_live = analytics.squad_quality(proj, my["squad"])
points_so_far = int(_my_total) if _my_total is not None else int(owned["total_points"].sum())

# expected points still TO COME this round (your starters not yet kicked off, captain ×2)
_now0 = datetime.now(timezone.utc)
_future_teams = {t for fx in d["fixtures"] if fx.get("fantasy_round") == live
                 and datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")) >= _now0
                 for t in (fx["home"], fx["away"])}
exp_left = sum(float(proj.loc[p, "xp_next"]) * (2 if p == cap_id else 1)
               for p in xi_ids if p in proj.index and proj.loc[p, "team"] in _future_teams)

if target != live:
    st.info(f"**This tab shows round {live} (live)** — the round being played, locked and scoring now. "
            f"**Planning round {target}?** Go to the **Transfers** tab — that's where you set next round's "
            "XI, captain and transfers.")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("⭐ Squad rating", f"{squad_rating_live['rating']:.0f}/100",
          help="Average quality percentile across ALL 15 of your players (their rank within position), for "
               "the live round — it matches the history chart below. Push it toward 100 by the cup's end.")
c2.metric("Starting XI rating", f"{rating_live['rating']:.0f}/100",
          help="Same idea but only your 11 live-round starters.")
c3.metric(f"Expected left R{live}", f"{exp_left:.0f}",
          help="Expected points your XI still has to come this round — players whose match hasn't kicked "
               "off yet (captain ×2). Ticks down as your games play.")
c4.metric("Points so far", points_so_far, help="Your real total points in the league.")
c5.metric("Bank", f"{my.get('bank', 0):.1f}M")

# ---------------------------------------------------------------- pitch (live round)
st.subheader(f"Your round {live} XI (live)")
st.caption(f"The XI **scoring for you right now in round {live}**. Each card: rank (#), price, expected "
           "points, floor→ceiling bar. **Captain ringed orange (C), vice ringed blue (V).** "
           f"(Setting up round {target}? See the **Transfers** tab.)")
floors = dict(zip(owned.index, owned["floor"]))
ceils = dict(zip(owned.index, owned["ceiling"]))
bench = [p for p in my["squad"] if p not in xi_ids]
st.markdown(viz.pitch_html(owned, xi_ids, cap_id, "xp_next", bench, ranks, floors, ceils, vice_id=vice_id),
            unsafe_allow_html=True)
st.caption(f"Formation **{_formation}**. Average XI rank: GK #{rating_live['avg_pos_rank']['GK']}, "
           f"DEF #{rating_live['avg_pos_rank']['DEF']}, MID #{rating_live['avg_pos_rank']['MID']}, "
           f"FWD #{rating_live['avg_pos_rank']['FWD']}.")

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
    rfig.add_vline(x=hx[-1], line=dict(color="#d63031", width=2),
                   annotation_text="▲ today", annotation_position="top right",
                   annotation_font=dict(color="#d63031", size=11))
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
st.caption("The honest scoreboard for the projections: your **actual** cumulative points (real results) "
           "against what the **model expected**, match by match. When green sits below blue the model was "
           "optimistic; above, it was conservative. Calibrated projections make the two lines hug.")

if not _starters:
    st.info("Your fielded XI for the live round isn't available yet — this fills in once the round locks "
            "and your players start playing.")
else:
    _now = datetime.now(timezone.utc)

    def _ko(fx):
        return datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00"))

    # per-round lineup + projection: the live round uses my fielded XI and real
    # scores; the planning round uses the model's best XI (expected only).
    rounds_info = {live: {"starters": _starters, "cap": _capid, "scores": _scores, "proj": proj_live}}
    if target != live and proj_plan is not None:
        _po = proj_plan.loc[[i for i in my["squad"] if i in proj_plan.index]]
        _pxi = optimizer.best_xi(_po, "xp_next")
        rounds_info[target] = {"starters": _pxi["xi_ids"], "cap": _pxi["captain_id"],
                               "scores": {}, "proj": proj_plan}

    # one row per match any of my starters feature in, chronological. expected =
    # sum of my players' xP in that match (captain doubled); actual = real points.
    mymatches = []
    for r, info in rounds_info.items():
        pr = info["proj"]
        team_of = {pid: pr.loc[pid, "team"] for pid in info["starters"] if pid in pr.index}
        for fx in _da.round_fixtures(d["fixtures"], r):
            mine = [pid for pid in info["starters"] if team_of.get(pid) in (fx["home"], fx["away"])]
            if not mine:
                continue
            exp = sum(float(pr.loc[pid, "xp_next"]) * (2 if pid == info["cap"] else 1)
                      for pid in mine if pid in pr.index)
            finished = _ko(fx) < _now
            act = sum((info["scores"].get(pid) or 0) for pid in mine) if finished else None
            mymatches.append({"r": r, "ko": fx["kickoff_utc"], "finished": finished,
                              "label": f"R{r} · {fx['home']}–{fx['away']}", "exp": exp, "act": act})
    mymatches.sort(key=lambda m: m["ko"])

    # cumulative series: expected over every match, actual over finished ones
    exp_cum, act_cum, last_played = 0.0, 0.0, -1
    xs, exp_y, act_x, act_y = [], [], [], []
    for i, m in enumerate(mymatches):
        exp_cum += m["exp"]
        xs.append(i)
        exp_y.append(exp_cum)
        if m["finished"]:
            act_cum += (m["act"] or 0)
            act_x.append(i)
            act_y.append(act_cum)
            last_played = i

    # headline numbers framed on the LIVE round (apples-to-apples on finished games)
    live_exp_full = sum(m["exp"] for m in mymatches if m["r"] == live)
    live_exp_done = sum(m["exp"] for m in mymatches if m["r"] == live and m["finished"])
    live_act_done = sum((m["act"] or 0) for m in mymatches if m["r"] == live and m["finished"])
    n_done = sum(1 for m in mymatches if m["r"] == live and m["finished"])
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Actual so far ({n_done} matches in)", f"{live_act_done:.0f}",
              delta=(f"{live_act_done - live_exp_done:+.1f} vs model" if n_done else None),
              help="Real points from your round-{0} matches that have finished.".format(live))
    c2.metric("Model expected (same matches)", f"{live_exp_done:.1f}",
              help="What the model projected for exactly those finished matches — the fair test.")
    c3.metric(f"On pace this round (R{live})", f"{live_act_done + (live_exp_full - live_exp_done):.0f}",
              help=f"Real points so far + the model's projection for your round-{live} players still to play "
                   f"(it expected the full round to score {live_exp_full:.0f}).")

    gfig = go.Figure()
    _se = last_played if last_played >= 0 else 0
    gfig.add_scatter(x=xs[:_se + 1], y=exp_y[:_se + 1], name="Model expected", mode="lines",
                     line=dict(color="#0984e3", width=3, shape="spline", smoothing=0.5),
                     customdata=[mymatches[i]["label"] for i in xs[:_se + 1]],
                     hovertemplate="%{customdata}<br>expected: %{y:.1f}<extra></extra>")
    if _se < len(xs) - 1:
        gfig.add_scatter(x=xs[_se:], y=exp_y[_se:], name="Expected (projected)", mode="lines",
                         line=dict(color="#0984e3", width=3, dash="dash", shape="spline", smoothing=0.5),
                         opacity=0.8, showlegend=False,
                         customdata=[mymatches[i]["label"] for i in xs[_se:]],
                         hovertemplate="%{customdata}<br>expected: %{y:.1f}<extra></extra>")
    if act_x:
        gfig.add_scatter(x=act_x, y=act_y, name="Actually scored", mode="lines+markers",
                         line=dict(color="#00b894", width=5, shape="spline", smoothing=0.5),
                         marker=dict(size=7), customdata=[mymatches[i]["label"] for i in act_x],
                         hovertemplate="%{customdata}<br>actual: %{y:.0f}<extra></extra>")
    for r in sorted(rounds_info):
        idxs = [i for i, m in enumerate(mymatches) if m["r"] == r]
        if idxs:
            gfig.add_vrect(x0=idxs[0] - 0.5, x1=idxs[-1] + 0.5, fillcolor="#ffffff" if r % 2 else "#000000",
                           opacity=0.04, line_width=0)
            gfig.add_annotation(x=(idxs[0] + idxs[-1]) / 2, y=1.0, yref="paper", text=f"Round {r}",
                                showarrow=False, font=dict(size=12, color="#aaa"), yshift=8)
    if last_played >= 0:
        gfig.add_vline(x=last_played + 0.5, line=dict(color="#d63031", width=2),
                       annotation_text="▲ now", annotation_position="top right",
                       annotation_font=dict(color="#d63031", size=11))
    _step = max(1, len(mymatches) // 10)
    gfig.update_layout(height=420, yaxis_title="Cumulative points",
                       xaxis=dict(title="Your matches (chronological →)", tickmode="array",
                                  tickvals=list(range(0, len(mymatches), _step)),
                                  ticktext=[mymatches[i]["label"].split("· ")[-1]
                                            for i in range(0, len(mymatches), _step)], tickangle=-35),
                       legend=dict(orientation="h", y=-0.35), margin=dict(l=10, r=10, t=22, b=10),
                       hovermode="x unified")
    st.plotly_chart(gfig, width="stretch", config={"displayModeBar": False})

    if n_done < 3:
        st.caption(f"⏳ Only {n_done} of your round-{live} matches have finished — too small a sample to judge "
                   "the model yet. The gap between the lines becomes meaningful as the round fills out. "
                   "(Tip: an early gap usually means a favourite your defenders backed didn't keep the clean "
                   "sheet the odds implied — variance, not a broken model.)")
    else:
        ratio = live_act_done / live_exp_done if live_exp_done else 1.0
        if ratio >= 1.10:
            st.success(f"✅ **Over-performing the model** — {live_act_done:.0f} actual vs {live_exp_done:.1f} "
                       f"expected ({(ratio - 1) * 100:+.0f}%).")
        elif ratio <= 0.90:
            st.warning(f"⚠️ **Under the model** — {live_act_done:.0f} actual vs {live_exp_done:.1f} expected "
                       f"({(ratio - 1) * 100:+.0f}%). Early variance, or the model is optimistic for these picks.")
        else:
            st.info(f"🎯 **Tracking reality well** — {live_act_done:.0f} actual vs {live_exp_done:.1f} expected "
                    f"({(ratio - 1) * 100:+.0f}%). The projections look calibrated.")

# ---------------------------------------------------------------- squad risk (live round)
st.subheader("🧯 Squad risk — how exposed is your round?")
st.caption(f"Diversification check on your **round {live} (live)** XI: how many independent 'bets' you really "
           "have, how much rides on a single match, and — given the league table — whether you should spread "
           "risk or chase variance. One bad game shouldn't tank your whole round.")
_my_total = next((mm.get("total_points", 0) for L in (_league or {}).get("leagues", [])
                  for mm in L.get("members", []) if mm.get("squad_name") == my.get("squad_name")), 0)
_rivals = [mm.get("total_points", 0) for L in (_league or {}).get("leagues", [])
           for mm in L.get("members", [])
           if mm.get("squad_name") != my.get("squad_name") and mm.get("total_points") is not None
           and (mm.get("squad") or mm.get("rounds"))]
_gap = (_my_total - max(_rivals)) if _rivals else None
risk = analytics.squad_risk(proj_live, my["squad"], _capid, "xp_next",
                            gap_to_field=_gap, rounds_left=max(1, 9 - live))
if not risk:
    st.caption("Risk metrics appear once your full XI is set.")
else:
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("🎲 Effective bets", f"{risk['enb_match']:.1f}",
               help="How many independent matches your points are really spread across (Herfindahl on "
                    "expected points by match). Higher = more diversified; under ~4 is fragile.")
    rc2.metric("⚠️ Biggest single match", f"{risk['max_match_share'] * 100:.0f}%",
               help=f"Share of your round riding on {risk['top_match']}. Over 30% is a lot of eggs in one basket.")
    rc3.metric("Round floor → ceiling", f"{risk['floor']:.0f}–{risk['ceiling']:.0f}",
               help=f"Expected {risk['expected']:.0f}, std ±{risk['sd_round']:.0f} — the spread of plausible totals.")
    bm = risk["by_match"]
    rkfig = go.Figure(go.Bar(
        x=[v * 100 for v in bm.values][::-1], y=list(bm.index)[::-1], orientation="h",
        marker_color=["#d63031" if v > 0.30 else ("#fdcb6e" if v > 0.20 else "#0984e3")
                      for v in bm.values][::-1],
        text=[f"{v * 100:.0f}%" for v in bm.values][::-1], textposition="outside", cliponaxis=False))
    rkfig.update_layout(height=80 + 30 * len(bm), xaxis_title="% of your round riding on this match",
                        margin=dict(l=10, r=10, t=10, b=10),
                        xaxis=dict(range=[0, max(bm.values) * 100 + 14]))
    st.plotly_chart(rkfig, width="stretch", config={"displayModeBar": False})
    for f in risk["flags"]:
        st.markdown(f"- {f}")
    if risk["regime_msg"]:
        st.info("📐 **League-state call:** " + risk["regime_msg"])

# ---------------------------------------------------------------- my upcoming matches
st.subheader("📅 Your upcoming matches")
my_teams = set(owned["team"])
_now_um = datetime.now(timezone.utc)
fixtures = sorted([fx for fx in d["fixtures"]
                   if (fx.get("home") in my_teams or fx.get("away") in my_teams)
                   and datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")) >= _now_um],
                  key=lambda f: f["kickoff_utc"])
if not fixtures:
    st.caption("No upcoming fixtures yet.")
else:
    st.caption(f"xP is shown for round {live} (the live round); later rounds show '—' because the projection "
               "re-computes each round. Played games drop off the list.")
    rows = []
    for fx in fixtures[:14]:
        ko = datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=2)))
        in_live = fx.get("fantasy_round") == live
        for side in ("home", "away"):
            if fx[side] in my_teams:
                mh = owned[owned["team"] == fx[side]]
                rows.append({"When (Oslo)": ko.strftime("%a %d %b · %H:%M"),
                             "R": fx.get("fantasy_round"),
                             "Match": f"{viz.flag(fx['home'])} {fx['home']} – {fx['away']} {viz.flag(fx['away'])}",
                             "Your players": ", ".join(viz.short_name(n) for n in mh["name"]),
                             f"xP R{live}": (round(float(mh["xp_next"].sum()), 1) if in_live else None)})
    st.dataframe(rows, hide_index=True, width="stretch")

# ---------------------------------------------------------------- per-player expected vs actual
st.subheader(f"🧾 Each player: expected vs actual — round {live}")
st.caption(f"What the model expected each of your players to score in round {live} versus what they've "
           "**actually** scored. **Δ** is the over/under-performance. '— to play' means their match hasn't "
           "kicked off yet. 'Total' is their real points across every round so far. Updates as games finish.")


def _player_total(pid):
    return sum((r.get("scores") or {}).get(pid, 0) for r in ((_me or {}).get("rounds") or []))


prep = []
for pid, r in owned.iterrows():
    played = pid in _scores
    exp = float(r["xp_next"]) * (2 if pid == cap_id else 1)
    act = _scores.get(pid)
    tag = " (C)" if pid == cap_id else (" (V)" if pid == vice_id else "")
    prep.append({"flag": viz.flag(r["team"]), "name": r["name"] + tag, "pos": r["position"],
                 "price": float(r["price"]), "expected": round(exp, 1),
                 "actual": (f"{act:.0f}" if played else "— to play"),
                 "Δ": (f"{(act or 0) - exp:+.1f}" if played else ""),
                 "total": int(_player_total(pid)), "_sort": ((act or 0) - exp if played else -99)})
prep.sort(key=lambda x: (-x["_sort"], -x["expected"]))
st.dataframe(
    [{k: v for k, v in row.items() if k != "_sort"} for row in prep],
    hide_index=True, width="stretch",
    column_config={"flag": "", "pos": "pos", "price": st.column_config.NumberColumn("price", format="%.1fM"),
                   "expected": st.column_config.NumberColumn(f"expected R{live}", format="%.1f"),
                   "actual": f"actual R{live}", "Δ": "Δ", "total": "total (all rounds)"})

# ---------------------------------------------------------------- contributions chart
st.subheader(f"Top point sources — round {live} (live)")
st.caption(f"Where your round-{live} points are expected to come from across your live XI (captain ×2 in orange).")
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
    ifig.add_vline(x=(completed[-1] if completed else 0), line=dict(color="#d63031", width=2),
                   annotation_text="▲ now", annotation_position="top left",
                   annotation_font=dict(color="#d63031", size=11))
    ifig.update_layout(xaxis_title="Round", yaxis_title="Cumulative points", height=400,
                       legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(ifig, width="stretch", config={"displayModeBar": False})

    st.markdown(f"**Your bets vs the market** — expected points per position (round {live}). "
                "Taller-than-grey = overweight, expecting to beat the market there.")
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
    posfig.update_layout(barmode="group", height=320, yaxis_title=f"Expected points (round {live})",
                         legend=dict(orientation="h", y=-0.25), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(posfig, width="stretch", config={"displayModeBar": False})
