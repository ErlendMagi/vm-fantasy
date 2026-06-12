import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="My League", page_icon="🏆", layout="wide")

from src import data_access, nav, optimizer, services, viz

nav.render("League")
d = services.get_data()
st.title("🏆 My league — BPG")
services.render_banners(d)

league = data_access.load_league()
live = services.get_live_league()
is_live = live is not None
if is_live:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=120_000, key="league_live_refresh")
    except ImportError:
        pass

if not is_live and (not league or not league.get("leagues")):
    st.info("League standings appear after the next data sync. Rival squads are hidden by TV 2 until "
            "each round's deadline passes, then they fill in here automatically.")
    st.stop()

proj = d["proj"]
source = live if is_live else league
lg = source["leagues"][0]
if len(source["leagues"]) > 1:
    lg = next(l for l in source["leagues"]
              if l["name"] == st.selectbox("League", [l["name"] for l in source["leagues"]]))

members = pd.DataFrame(lg["members"])
# live mode carries fresh scores but no rosters - merge squads/formation from the synced file
if is_live and league and league.get("leagues"):
    synced = next((l for l in league["leagues"] if l.get("league_id") == lg.get("league_id")),
                  league["leagues"][0])
    extra = {m["squad_name"]: m for m in synced["members"]}
    for col, default in [("squad", []), ("starter_ids", []), ("bench_ids", []),
                         ("captain_id", None), ("formation", None)]:
        members[col] = members["squad_name"].map(
            lambda sq, c=col, dft=default: (extra.get(sq) or {}).get(c, dft))
elif "squad" not in members.columns:
    members["squad"] = [[] for _ in range(len(members))]

if is_live:
    st.success("🔴 **LIVE** — scores update during matches (refreshes every 2 minutes).")
else:
    st.caption("Showing the last synced snapshot. For live in-match scores, add your TV2_TOKEN to the "
               "Streamlit app's Secrets (see README).")
me_name = (d["my_team"] or {}).get("squad_name")
members["is_me"] = members["squad_name"] == me_name
PALETTE = ["#00b894", "#0984e3", "#e17055", "#fdcb6e", "#a29bfe", "#fd79a8", "#55efc4", "#ff7675"]
colour = {sq: (("#00b894") if sq == me_name else PALETTE[(i + 1) % len(PALETTE)])
          for i, sq in enumerate(members["squad_name"])}


def cum_actual(m):
    run, out = 0, []
    for x in (m.get("round_scores") or []):
        run += (x.get("points", x) if isinstance(x, dict) else x) or 0
        out.append(run)
    return out


# ---------------------------------------------------------------- standings
st.subheader("Standings")
standings = members.sort_values(["total_points", "latest_round_points"], ascending=False).reset_index(drop=True)
standings.insert(0, "pos", standings.index + 1)
st.dataframe(
    standings[["pos", "manager", "squad_name", "total_points", "latest_round_points", "is_me"]],
    hide_index=True, width="stretch",
    column_config={"pos": "#", "manager": "Manager", "squad_name": "Team",
                   "total_points": "Total", "latest_round_points": "Last round",
                   "is_me": st.column_config.CheckboxColumn("You")})

# ---------------------------------------------------------------- the points race (day by day)
st.subheader("📈 Points race — day by day")
st.caption("Solid = points actually scored. Dashed = expected cumulative points, day by day: the line "
           "jumps on days a manager's players play (a Spain-heavy team jumps on Spain days) and stays "
           "flat on rest days. Projections stop after the last round with a confirmed schedule — no "
           "guessing about knockout pairings. Your line is the thick green one.")
have_squads = members["squad"].apply(len).gt(0).any()

from collections import defaultdict
from datetime import datetime, timedelta, timezone

OSLO = timezone(timedelta(hours=2))
today = datetime.now(OSLO).date()


def fixture_date(team, rnd):
    for fx in d["fixtures"]:
        if fx.get("fantasy_round") == rnd and team in (fx.get("home"), fx.get("away")):
            return datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).astimezone(OSLO).date()
    return None


def round_end_date(rnd):
    dates = [datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).astimezone(OSLO).date()
             for fx in d["fixtures"] if fx.get("fantasy_round") == rnd]
    return max(dates) if dates else None


fig = go.Figure()
for _, m in members.iterrows():
    sq = m["squad_name"]
    width = 5 if m["is_me"] else 2
    # actual: cumulative per completed round, placed on each round's final matchday
    actual_pts = cum_actual(m)
    ax, ay = [], []
    for r_idx, total in enumerate(actual_pts, start=1):
        rd = round_end_date(r_idx)
        if rd and rd <= today:
            ax.append(rd)
            ay.append(total)
    base = ay[-1] if ay else (m.get("total_points") or 0)
    if ax:
        fig.add_scatter(x=ax, y=ay, mode="lines+markers", name=sq, legendgroup=sq,
                        line=dict(width=width, color=colour[sq], shape="spline", smoothing=0.8))
    # expected: per-DAY steps for every scheduled round the model can price
    if proj is not None and m["squad"]:
        owned = proj.loc[[i for i in m["squad"] if i in proj.index]]
        if len(owned) >= 11:
            daily = defaultdict(float)
            for rnd, xpcol in [(d["next_round"], "xp_next"), (d["next_round"] + 1, "xp_after")]:
                if rnd > 3:          # knockout pairings not scheduled yet -> no projection
                    continue
                xi = optimizer.best_xi(owned, xpcol)
                for pid in xi["xi_ids"]:
                    fd = fixture_date(owned.loc[pid, "team"], rnd)
                    if fd and fd >= today:
                        daily[fd] += float(owned.loc[pid, xpcol]) * (2 if pid == xi["captain_id"] else 1)
            if daily:
                run = float(base)
                xs, ys = [max(ax[-1] if ax else today, today)], [run]
                for day in sorted(daily):
                    run += daily[day]
                    xs.append(day)
                    ys.append(run)
                fig.add_scatter(x=xs, y=ys, mode="lines+markers", name=sq, legendgroup=sq,
                                showlegend=not ax, marker=dict(size=5),
                                line=dict(width=width, color=colour[sq], dash="dash", shape="spline",
                                          smoothing=0.8),
                                opacity=0.8)

# shaded bands + end-markers so every round's span is obvious
for r in (1, 2, 3):
    dts = [datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).astimezone(OSLO).date()
           for fx in d["fixtures"] if fx.get("fantasy_round") == r]
    if not dts:
        continue
    fig.add_vrect(x0=str(min(dts)), x1=str(max(dts) + timedelta(days=1)),
                  fillcolor="#ffffff" if r % 2 else "#000000", opacity=0.04, line_width=0)
    fig.add_vline(x=str(max(dts) + timedelta(days=1)), line=dict(color="#777", dash="dot", width=1))
    fig.add_annotation(x=str(max(dts) + timedelta(days=1)), y=1.0, yref="paper",
                       text=f"🏁 Round {r} ends", showarrow=False, xanchor="right",
                       font=dict(size=11, color="#999"), yshift=10)

# 📺 / ⚠️ watch markers: my biggest games and the most dangerous rival games
watch_rows = []
if proj is not None and have_squads:
    me_row = next((m for _, m in members.iterrows() if m["is_me"] and m["squad"]), None)
    if me_row is not None:
        my_owned = proj.loc[[i for i in me_row["squad"] if i in proj.index]]
        my_xi = optimizer.best_xi(my_owned, "xp_next")
        rivals = [(m["squad_name"], proj.loc[[i for i in m["squad"] if i in proj.index]])
                  for _, m in members.iterrows() if not m["is_me"] and m["squad"]]
        rival_xis = [(sn, ow, optimizer.best_xi(ow, "xp_next")) for sn, ow in rivals if len(ow) >= 11]

        def stake(owned_df, xi_info, teams):
            sel = owned_df[(owned_df["team"].isin(teams)) & (owned_df["id"].isin(xi_info["xi_ids"]))]
            s = float(sel["xp_next"].sum())
            if xi_info["captain_id"] in set(sel["id"]):
                s += float(owned_df.loc[xi_info["captain_id"], "xp_next"])
            return s

        for fx in d["fixtures"]:
            if fx.get("fantasy_round") != d["next_round"] or fx.get("status") == "finished":
                continue
            ko = datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).astimezone(OSLO)
            if ko.date() < today:
                continue
            teams = {fx["home"], fx["away"]}
            mine = stake(my_owned, my_xi, teams)
            threats = sorted(((stake(ow, xi, teams) - mine, sn) for sn, ow, xi in rival_xis), reverse=True)
            danger, threat_name = (threats[0] if threats else (0.0, "-"))
            watch_rows.append({"ko": ko, "date": ko.date(),
                               "match": f"{viz.flag(fx['home'])} {fx['home']} – {fx['away']} {viz.flag(fx['away'])}",
                               "mine": round(mine, 1), "danger": round(max(danger, 0), 1),
                               "threat": threat_name})
        top_watch = sorted(watch_rows, key=lambda r_: -r_["mine"])[:2]
        top_danger = sorted(watch_rows, key=lambda r_: -r_["danger"])[:2]
        for w in top_watch:
            fig.add_annotation(x=str(w["date"]), y=0.05, yref="paper", text="📺", showarrow=False,
                               font=dict(size=16), hovertext=f"Watch: {w['match']} — {w['mine']} of your pts at stake")
        for w in top_danger:
            if w["danger"] > 0:
                fig.add_annotation(x=str(w["date"]), y=0.13, yref="paper", text="⚠️", showarrow=False,
                                   font=dict(size=15),
                                   hovertext=f"Danger: {w['match']} — {w['threat']} gains {w['danger']} on you")

fig.update_layout(xaxis_title="Date", yaxis_title="Cumulative points", height=470,
                  legend=dict(orientation="h", y=-0.25), hovermode="x unified")
st.plotly_chart(fig, width="stretch")

if watch_rows:
    st.markdown("#### 📺 Your watch guide — next round")
    st.caption("**Your stake** = expected points your XI has riding on the match (captain ×2). "
               "**Danger** = how many points the strongest rival gains on you in that match — "
               "those are the games that can hurt.")
    wg = pd.DataFrame(sorted(watch_rows, key=lambda r_: -r_["mine"]))
    wg["When (Oslo)"] = wg["ko"].apply(lambda k: k.strftime("%a %d %b · %H:%M"))
    wg["verdict"] = ["📺 must-watch" if m_ >= wg["mine"].quantile(0.7) and m_ > 0
                     else ("⚠️ danger" if dg > 2 else "—")
                     for m_, dg in zip(wg["mine"], wg["danger"])]
    st.dataframe(
        wg[["When (Oslo)", "match", "mine", "danger", "threat", "verdict"]],
        hide_index=True, width="stretch",
        column_config={"match": "Match", "mine": st.column_config.NumberColumn("Your stake", format="%.1f"),
                       "danger": st.column_config.NumberColumn("Danger", format="%.1f"),
                       "threat": "Biggest threat", "verdict": ""})
if not any(cum_actual(m) for _, m in members.iterrows()):
    st.caption("No rounds scored yet — solid lines fill in as TV 2 finalises each round. Dashed lines "
               "show each manager's expected path through the scheduled group games.")

# ---------------------------------------------------------------- rivals' squads, ranked by SPI
if proj is not None and have_squads:
    from src import analytics
    ranks = d["ranks"]
    floors = dict(zip(proj.index, proj["floor"]))
    ceils = dict(zip(proj.index, proj["ceiling"]))
    managers = [{"squad_name": m["squad_name"], "manager": m["manager"], "is_me": m["is_me"],
                 "squad": m["squad"], "total_points": m["total_points"]}
                for _, m in members.iterrows() if m["squad"]]
    spi = analytics.squad_power_index(proj, managers)

    st.subheader("🏅 Squad Power Index — every manager's team, strongest first")
    st.caption("A 0–100 rating blending this round's projected XI (60%), whole-cup durability (25%) and "
               "value-per-million (15%), graded across your league.")
    rev = spi.iloc[::-1]  # plotly draws horizontal bars bottom-up
    sbar = go.Figure(go.Bar(
        x=rev["SPI"], y=[f"{'🟢 ' if me else ''}{sn}" for sn, me in zip(rev["squad_name"], rev["is_me"])],
        orientation="h", marker_color=[colour.get(sn, viz.NEUTRAL) for sn in rev["squad_name"]],
        text=[f"{v:.0f}" for v in rev["SPI"]], textposition="outside", cliponaxis=False))
    sbar.update_layout(height=90 + 34 * len(spi), xaxis=dict(title="Squad Power Index", range=[0, 108]),
                       margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(sbar, width="stretch", config={"displayModeBar": False})

    # ---- overall player-quality + ROI, one number each, you vs rivals ----
    a, b = st.columns(2)
    qual_rows = []
    for mgr in managers:
        tr = analytics.team_rating(proj, mgr["squad"], ranks)
        owned_m = proj.loc[[i for i in mgr["squad"] if i in proj.index]]
        cost = max(float(owned_m["price"].sum()), 0.1)
        qual_rows.append({"squad_name": mgr["squad_name"], "is_me": mgr["is_me"],
                          "avg_rank": tr["avg_rank_overall"],
                          "actual_roi": round(mgr["total_points"] / cost, 2),
                          "proj_roi": round(float(spi.set_index("squad_name").loc[mgr["squad_name"], "proj_tour"]) / cost, 2)
                          if mgr["squad_name"] in set(spi["squad_name"]) else 0.0})
    qd = pd.DataFrame(qual_rows)
    with a:
        st.markdown("**🎖️ Overall player quality** — average rank of each XI across *all* positions "
                    "(lower = better players)")
        q = qd.sort_values("avg_rank", ascending=False)  # plotly bottom-up: best ends on top
        qf = go.Figure(go.Bar(
            x=q["avg_rank"], y=[f"{'🟢 ' if me else ''}{s}" for s, me in zip(q["squad_name"], q["is_me"])],
            orientation="h", marker_color=[colour.get(s, viz.NEUTRAL) for s in q["squad_name"]],
            text=[f"#{v:.0f}" for v in q["avg_rank"]], textposition="outside", cliponaxis=False))
        qf.update_layout(height=70 + 32 * len(q), xaxis_title="Avg player rank in XI (lower = better)",
                         margin=dict(l=10, r=10, t=6, b=10))
        st.plotly_chart(qf, width="stretch", config={"displayModeBar": False})
    with b:
        st.markdown("**💸 Squad ROI** — points per million spent: actual so far (solid) and expected "
                    "for the whole cup (faded)")
        r = qd.sort_values("proj_roi")
        labels = [f"{'🟢 ' if me else ''}{s}" for s, me in zip(r["squad_name"], r["is_me"])]
        rf = go.Figure()
        rf.add_bar(x=r["proj_roi"], y=labels, orientation="h", name="expected (cup)",
                   marker_color=[colour.get(s, viz.NEUTRAL) for s in r["squad_name"]], opacity=0.35,
                   text=[f"{v:.2f}" for v in r["proj_roi"]], textposition="outside", cliponaxis=False)
        rf.add_bar(x=r["actual_roi"], y=labels, orientation="h", name="actual so far",
                   marker_color=[colour.get(s, viz.NEUTRAL) for s in r["squad_name"]])
        rf.update_layout(barmode="overlay", height=70 + 32 * len(r), xaxis_title="points per million",
                         legend=dict(orientation="h", y=-0.3), margin=dict(l=10, r=10, t=6, b=10))
        st.plotly_chart(rf, width="stretch", config={"displayModeBar": False})

    if not spi.empty and not spi.iloc[0]["is_me"]:
        with st.expander("🤔 Why isn't my team #1 on the projection?"):
            st.markdown(
                "This board ranks **the points your already-locked round-1 team is projected to score on the "
                "next round's fixtures** — not who could build the best team today. Three reasons you can sit "
                "behind a rival here and it's still fine:\n\n"
                "1. **You're rules-locked.** After round 1 you only get **2 free transfers per round** (a 3rd "
                "costs −4 pts), so you can't rebuild to the current optimum in one week — a small gap is often "
                "less than a single −4 hit.\n"
                "2. **You're built for the whole cup, not one week.** The autopilot maximises rest-of-tournament "
                "value; a rival can have softer fixtures *this specific round*.\n"
                "3. **The autopilot re-optimises right before each deadline** on the freshest odds and makes the "
                "best transfers/captain within your free transfers — so your team climbs toward the top over the "
                "tournament rather than leading every single week.")

    # ---- rival pitches, always visible, in columns ----
    st.subheader("🔍 Everyone's team")
    st.caption("Each manager's XI on the pitch with photos, flags, price, rank and expected points. "
               "Sorted by Squad Power Index.")
    history = data_access.load_league_history().get("rounds", {})
    prev_round = str((league.get("current_round") or 2) - 1)
    prev_members = (history.get(prev_round) or {}).get("members", {})
    ordered = spi.merge(members, on=["squad_name", "manager", "is_me"], suffixes=("", "_m"))
    cols = st.columns(2)
    for i, (_, m) in enumerate(ordered.iterrows()):
        owned = proj.loc[[pid for pid in m["squad"] if pid in proj.index]]
        starter_ids = [pid for pid in (m.get("starter_ids") or []) if pid in owned.index]
        xi = optimizer.best_xi(owned, "xp_next") if len(owned) >= 11 else None
        xi_ids = starter_ids if len(starter_ids) == 11 else (xi["xi_ids"] if xi else [])
        cap_id = m.get("captain_id") if m.get("captain_id") in owned.index else (xi["captain_id"] if xi else None)
        bench = m.get("bench_ids") or [pid for pid in m["squad"] if pid not in xi_ids]
        formation = m.get("formation") or (xi["formation"] if xi else "?")
        rating = analytics.team_rating(proj, m["squad"], ranks)
        with cols[i % 2]:
            st.markdown(f"### {'🟢 ' if m['is_me'] else ''}{m['squad_name']}")
            st.caption(f"**{m['manager']}** · SPI {m['SPI']:.0f} · {formation} · {m['proj_next']:.0f} proj pts · "
                       f"{m['total_points']} actual · {owned['price'].sum():.0f}M")
            st.caption(f"Avg XI rank: GK #{rating['avg_pos_rank']['GK']} · DEF #{rating['avg_pos_rank']['DEF']} · "
                       f"MID #{rating['avg_pos_rank']['MID']} · FWD #{rating['avg_pos_rank']['FWD']}")
            prev = prev_members.get(m["squad_name"])
            if prev:
                came, went = set(m["squad"]) - set(prev["squad"]), set(prev["squad"]) - set(m["squad"])
                if came or went:
                    ins = ", ".join(viz.short_name(proj.loc[x, "name"]) for x in came if x in proj.index) or "—"
                    outs = ", ".join(viz.short_name(proj.loc[x, "name"]) for x in went if x in proj.index) or "—"
                    st.caption(f"↔️ since R{prev_round}: OUT {outs} · IN {ins}")
            if xi_ids:
                st.markdown(viz.pitch_html(owned, xi_ids, cap_id, "xp_next", bench, ranks, floors, ceils),
                            unsafe_allow_html=True)

    # ---- luck vs the field ----
    st.subheader("🎲 Luck so far — over/under-performing the field")
    st.caption("Each scored round, every manager vs the whole league's spread, in standard deviations (σ). "
               "Far right = rode their luck / nailed it; far left = unlucky or misjudged. |σ|>2 is notable.")
    import numpy as np
    scored_rounds = sorted({s.get("roundNumber") for _, m in members.iterrows()
                            for s in (m.get("round_scores") or [])
                            if isinstance(s, dict) and s.get("roundNumber")})
    if scored_rounds:
        rnd = st.selectbox("Round", scored_rounds, index=len(scored_rounds) - 1)

        def pts_in(m, r):
            return next((s.get("points", 0) for s in (m.get("round_scores") or [])
                         if s.get("roundNumber") == r), None)
        field = [p for p in (pts_in(m, rnd) for _, m in members.iterrows()) if p is not None]
        mu, sd = (float(np.mean(field)), float(np.std(field))) if field else (0.0, 1.0)
        sd = sd or 1.0
        lr = []
        for _, m in members.iterrows():
            p = pts_in(m, rnd)
            if p is None:
                continue
            z = (p - mu) / sd
            verdict = ("🍀 very lucky" if z > 2 else "🙂 lucky" if z > 0.7 else
                       "💀 very unlucky" if z < -2 else "😐 unlucky" if z < -0.7 else "➖ as expected")
            lr.append({"label": f"{'🟢 ' if m['is_me'] else ''}{m['squad_name']} · {p}p {verdict}",
                       "z": round(z, 2)})
        ld = pd.DataFrame(lr).sort_values("z")
        st.caption(f"Round {rnd}: field average {mu:.1f} pts (σ {sd:.1f}), {len(field)} managers.")
        lf = go.Figure(go.Bar(
            x=ld["z"], y=ld["label"], orientation="h",
            marker_color=["#00b894" if z > 0 else "#d63031" for z in ld["z"]],
            hovertemplate="%{y}<br>%{x:.2f}σ from field<extra></extra>"))
        lf.update_layout(height=110 + 34 * len(ld), bargap=0.35,
                         xaxis=dict(title="σ from field average (→ over-performed)", zeroline=True,
                                    zerolinecolor="#888", zerolinewidth=2),
                         yaxis=dict(automargin=True), margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(lf, width="stretch", config={"displayModeBar": False})

    # ---- whose games matter most next round (importance heatmap) ----
    if have_squads:
        st.subheader("🗓️ Whose games matter most next round")
        st.caption("How much expected points each manager has riding on each upcoming match — the brighter "
                   "the cell, the more that game decides their round.")
        rnd_no = d["next_round"]
        from datetime import datetime, timedelta, timezone
        fixtures_r = sorted([fx for fx in d["fixtures"] if fx.get("fantasy_round") == rnd_no],
                            key=lambda f: f["kickoff_utc"])
        sq_members = ordered[ordered["squad"].apply(len) > 0]
        match_labels, z = [], []
        for fx in fixtures_r:
            teams = {fx["home"], fx["away"]}
            col = []
            for _, m in sq_members.iterrows():
                ow = proj.loc[[i for i in m["squad"] if i in proj.index]]
                col.append(float(ow[ow["team"].isin(teams)]["xp_next"].sum()))
            if sum(col) > 0.5:
                ko = datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).astimezone(
                    timezone(timedelta(hours=2)))
                match_labels.append(f"{ko.strftime('%a %d')} {fx['home'][:3]}–{fx['away'][:3]}")
                z.append(col)
        if z:
            zt = list(map(list, zip(*z)))  # transpose -> rows=members
            hm = go.Figure(go.Heatmap(
                z=zt, x=match_labels, y=[f"{'🟢 ' if me else ''}{t}" for t, me in zip(sq_members['squad_name'], sq_members['is_me'])],
                colorscale="YlGn", colorbar=dict(title="xP"),
                hovertemplate="%{y}<br>%{x}<br>%{z:.1f} expected points<extra></extra>"))
            hm.update_layout(height=120 + 34 * len(zt), margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(hm, width="stretch", config={"displayModeBar": False})

    st.subheader("⚔️ What you win & lose on (vs each rival)")
    mine = set((d["my_team"] or {}).get("squad", []))
    cols = ["name", "team", "position", "price", "xp_next", "xp_tournament"]
    for _, m in ordered[~ordered["is_me"]].iterrows():
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
    st.caption("🔒 Rival squads are hidden by TV 2 until each round's deadline passes. Once they unlock "
               "they appear here — every manager's team on a pitch, their prices, projected points, "
               "formation, and what they changed each round.")
