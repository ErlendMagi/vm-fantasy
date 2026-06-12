import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="My League", page_icon="🏆", layout="wide")

from src import data_access, optimizer, services, viz

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

# ---------------------------------------------------------------- the points race (living)
st.subheader("📈 Points race — actual so far, then projected")
st.caption("Solid lines = points already scored. Dashed = where the model expects each team to be after the "
           "coming rounds, based on their current squads. Your line is the thick green one.")
have_squads = members["squad"].apply(len).gt(0).any()
fig = go.Figure()
for _, m in members.iterrows():
    sq = m["squad_name"]
    actual = cum_actual(m)
    start_round = len(actual)
    # projected forward from the current squad's next-round expected points
    proj_pts = None
    if proj is not None and m["squad"]:
        owned = proj.loc[[i for i in m["squad"] if i in proj.index]]
        proj_pts = optimizer.squad_xp(owned, "xp_next") if len(owned) >= 11 else float(owned["xp_next"].sum())
    width = 5 if m["is_me"] else 2
    if actual:
        fig.add_scatter(x=list(range(1, start_round + 1)), y=actual, mode="lines+markers",
                        name=sq, legendgroup=sq, line=dict(width=width, color=colour[sq]))
    if proj_pts is not None:
        x0 = start_round if actual else 0
        y0 = actual[-1] if actual else 0
        # project the next 3 rounds at a per-round expected rate
        xs = [x0 + k for k in range(0, 4)]
        ys = [y0 + proj_pts * k for k in range(0, 4)]
        fig.add_scatter(x=xs, y=ys, mode="lines", name=sq, legendgroup=sq, showlegend=not actual,
                        line=dict(width=width, color=colour[sq], dash="dash"), opacity=0.7)
fig.update_layout(xaxis_title="Round", yaxis_title="Cumulative points", height=440,
                  legend=dict(orientation="h", y=-0.2))
st.plotly_chart(fig, width="stretch")
if not any(cum_actual(m) for _, m in members.iterrows()):
    st.caption("No rounds scored yet — the solid lines start filling in after round 1 is played. "
               "Dashed projections use each manager's current squad.")

# ---------------------------------------------------------------- rivals' squads, ranked by projected pts
def squad_xp_safe(ids, col):
    owned = proj.loc[[i for i in ids if i in proj.index]]
    return optimizer.squad_xp(owned, col) if len(owned) >= 11 else float(owned[col].sum())

if proj is not None and have_squads:
    st.subheader("🔮 Projected this round — every manager's team, strongest first")
    st.caption("Each manager's starting XI projected for the coming round (captain doubled). "
               "Whoever the model expects to score most is on top.")
    rankrows = []
    for _, m in members.iterrows():
        if not m["squad"]:
            continue
        rankrows.append({"squad_name": m["squad_name"], "manager": m["manager"],
                         "is_me": m["is_me"], "proj_next": squad_xp_safe(m["squad"], "xp_next"),
                         "proj_tour": squad_xp_safe(m["squad"], "xp_tournament")})
    rk = pd.DataFrame(rankrows).sort_values("proj_next", ascending=False).reset_index(drop=True)
    rbar = go.Figure(go.Bar(
        x=rk["proj_next"], y=[f"{'🟢 ' if me else ''}{sn}" for sn, me in zip(rk["squad_name"], rk["is_me"])][::-1],
        orientation="h", marker_color=[colour.get(sn, viz.NEUTRAL) for sn in rk["squad_name"]][::-1],
        text=[f"{v:.1f}" for v in rk["proj_next"]][::-1], textposition="outside", cliponaxis=False))
    rbar.update_layout(height=90 + 34 * len(rk), xaxis_title="Projected points, next round (XI, captain ×2)",
                       margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(rbar, width="stretch", config={"displayModeBar": False})

    st.subheader("🔍 Open any manager's team")
    history = data_access.load_league_history().get("rounds", {})
    prev_round = str((league.get("current_round") or 2) - 1)
    prev_members = (history.get(prev_round) or {}).get("members", {})
    ordered = rk.merge(members, on=["squad_name", "manager", "is_me"])
    for _, m in ordered.iterrows():
        owned = proj.loc[[i for i in m["squad"] if i in proj.index]]
        xi = optimizer.best_xi(owned, "xp_next") if len(owned) >= 11 else None
        formation = m.get("formation") or (xi["formation"] if xi else "?")
        squad_cost = float(owned["price"].sum())
        title = f"{'🟢 ' if m['is_me'] else ''}**{m['manager']}** · {m['squad_name']} — {formation} · " \
                f"{m['proj_next']:.1f} proj pts · {m['total_points']} actual · {squad_cost:.0f}M"
        with st.expander(title):
            prev = prev_members.get(m["squad_name"])
            if prev:
                came, went = set(m["squad"]) - set(prev["squad"]), set(prev["squad"]) - set(m["squad"])
                if came or went:
                    ins = ", ".join(proj.loc[i, "name"] for i in came if i in proj.index) or "—"
                    outs = ", ".join(proj.loc[i, "name"] for i in went if i in proj.index) or "—"
                    st.markdown(f"**Changes since round {prev_round}:** OUT {outs} → IN {ins}"
                                + (f"  ·  {prev.get('formation')} → {formation}"
                                   if prev.get("formation") and prev.get("formation") != formation else ""))
            cap_id = m.get("captain_id") if m.get("captain_id") in owned.index else (xi["captain_id"] if xi else None)
            if xi:
                bench = m.get("bench_ids") or [i for i in m["squad"] if i not in xi["xi_ids"]]
                st.plotly_chart(viz.pitch_figure(owned, xi["xi_ids"], cap_id, "xp_next", bench),
                                width="stretch", config={"displayModeBar": False})
            tbl = owned.assign(
                flag=owned["team"].map(viz.flag),
                C=[("🅒" if i == cap_id else "") for i in owned.index],
                start=[("XI" if xi and i in xi["xi_ids"] else "bench") for i in owned.index])
            st.dataframe(
                tbl.sort_values(["start", "xp_next"], ascending=[True, False])[
                    ["flag", "name", "team", "position", "price", "xp_next", "xp_tournament", "C", "start"]],
                hide_index=True, width="stretch",
                column_config={"flag": "", "price": st.column_config.NumberColumn("price", format="%.1fM"),
                               "xp_next": st.column_config.NumberColumn("xP this round", format="%.2f"),
                               "xp_tournament": st.column_config.NumberColumn("xP cup", format="%.1f")})

    # ---- luck vs the field (z-score on round points) ----
    st.subheader("🎲 Luck so far — over/under-performing the field")
    st.caption("For each scored round we compare every manager's points to the whole league's spread. "
               "A score far above the field average is lucky/inspired; far below is unlucky/misjudged. "
               "Measured in standard deviations (σ) from the field — |σ|>2 is statistically notable.")
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
                       "😐 unlucky" if z < -0.7 else "➖ as expected")
            if z < -2:
                verdict = "💀 very unlucky"
            lr.append({"manager": m["manager"], "team": m["squad_name"], "points": p,
                       "σ vs field": round(z, 2), "verdict": verdict, "is_me": m["is_me"]})
        ld = pd.DataFrame(lr).sort_values("points", ascending=False)
        st.caption(f"Round {rnd}: field average {mu:.1f} pts (σ {sd:.1f}), {len(field)} managers.")
        lf = go.Figure(go.Bar(
            x=ld["σ vs field"], y=[f"{'🟢 ' if me else ''}{t}" for t, me in zip(ld['team'], ld['is_me'])][::-1],
            orientation="h", marker_color=["#00b894" if z > 0 else "#d63031" for z in ld["σ vs field"]][::-1],
            text=[f"{p} pts · {v}" for p, v in zip(ld["points"], ld["verdict"])][::-1],
            textposition="outside", cliponaxis=False))
        lf.update_layout(height=90 + 32 * len(ld), xaxis_title="σ from the field average (right = over-performed)",
                         margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(lf, width="stretch", config={"displayModeBar": False})

    # ---- whose games matter most next round (importance heatmap) ----
    if have_squads:
        st.subheader("🗓️ Whose games matter most next round")
        st.caption("How much expected points each manager has riding on each upcoming match — the brighter "
                   "the cell, the more that game decides their round.")
        rnd_no = d["next_round"]
        fixtures_r = [fx for fx in d["fixtures"] if fx.get("fantasy_round") == rnd_no]
        sq_members = ordered[ordered["squad"].apply(len) > 0]
        match_labels, z = [], []
        for fx in fixtures_r:
            teams = {fx["home"], fx["away"]}
            col = []
            for _, m in sq_members.iterrows():
                ow = proj.loc[[i for i in m["squad"] if i in proj.index]]
                col.append(float(ow[ow["team"].isin(teams)]["xp_next"].sum()))
            if sum(col) > 0.5:
                match_labels.append(f"{viz.flag(fx['home'])}{fx['home'][:3]}–{fx['away'][:3]}{viz.flag(fx['away'])}")
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
