import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="BPG League", page_icon="🏆", layout="wide")

from src import analytics, config, data_access, nav, optimizer, services, theme, viz

nav.render("League")
d = services.get_data()
st.title("🏆 BPG — the league")
services.render_banners(d)

league = data_access.load_league()
live = services.get_live_league()
is_live = live is not None
if is_live:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=60_000, key="league_live_refresh")
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
    # prefer the LIVE per-squad detail when present (small leagues now fetch it
    # live), fall back to the synced file only for what live didn't carry
    for col, default in [("squad", []), ("starter_ids", []), ("bench_ids", []), ("captain_id", None),
                         ("vice_captain_id", None), ("formation", None), ("rounds", [])]:
        live_col = members[col] if col in members.columns else [None] * len(members)
        members[col] = [lv if lv not in (None, [], "") else (extra.get(sq) or {}).get(c2, dft)
                        for lv, sq, c2, dft in
                        zip(live_col, members["squad_name"], [col] * len(members), [default] * len(members))]
elif "squad" not in members.columns:
    members["squad"] = [[] for _ in range(len(members))]

if is_live:
    st.success("🔴 **LIVE** — scores update during matches (refreshes every 2 minutes).")
else:
    st.caption("Showing the last synced snapshot. For live in-match scores, add your TV2_TOKEN to the "
               "Streamlit app's Secrets (see README).")
me_name = (d["my_team"] or {}).get("squad_name")
members["is_me"] = members["squad_name"] == me_name
PALETTE = theme.CAT
colour = {sq: (theme.ACCENT if sq == me_name else PALETTE[(i + 1) % len(PALETTE)])
          for i, sq in enumerate(members["squad_name"])}


def cum_actual(m):
    run, out = 0, []
    for x in (m.get("round_scores") or []):
        run += (x.get("points", x) if isinstance(x, dict) else x) or 0
        out.append(run)
    return out


# ================================================================ LIVE: your players are playing now
from datetime import datetime as _dtL, timedelta as _tdL, timezone as _tzL

from src import analytics as _an

_nowL = _dtL.now(_tzL.utc)


def _koL(fx):
    return _dtL.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00"))


_liveR = d["next_round"]
# ownership + live fantasy points across the whole league (from members' live rounds)
owner_of, live_pts = {}, {}
for _, _m in members.iterrows():
    _mrd = next((r for r in (_m.get("rounds") or []) if r.get("number") == _liveR), {})
    for _pid, _v in (_mrd.get("scores") or {}).items():
        live_pts[_pid] = _v
    for _pid in (_m.get("squad") or []):
        owner_of.setdefault(_pid, _m["squad_name"])
my_squad = set((d["my_team"] or {}).get("squad", []))


def _match_pids(fx):
    return list(proj.index[proj["team"].isin({fx["home"], fx["away"]})]) if proj is not None else []


# candidate live games: kicked off in the last ~2.2h, not flagged finished, and I have a player in them
_cand = ([fx for fx in d["fixtures"]
          if fx.get("fantasy_round") == _liveR and fx.get("status") != "finished"
          and _koL(fx) <= _nowL < _koL(fx) + _tdL(hours=2.2)
          and my_squad & set(_match_pids(fx))] if proj is not None else [])
live_stats = services.get_live_stats(_cand)
# FotMob is the source of truth for 'finished' — drop games that are actually over
_games = sorted([fx for fx in _cand if not live_stats.get(fx["match_id"], {}).get("finished")], key=_koL)

if _games:
    st.markdown(viz.LIVE_CSS, unsafe_allow_html=True)
    st.markdown(f'### <span class="vl-live"></span> Live now — your players are playing (round {_liveR})',
                unsafe_allow_html=True)
    _prev = st.session_state.get("motm_prev", {})
    _cur = {}

    def _own_html(pid):
        o = owner_of.get(pid)
        if o == me_name:
            return '<div class="vl-own" style="color:#00b894">🟢 You</div>'
        if o:
            return f'<div class="vl-own" style="color:#74b9ff">👤 {o[:16]}</div>'
        return '<div class="vl-own" style="color:#7f8c9b">unowned</div>'

    def _playing(p, stats_map, have_fm):
        s = stats_map.get(p)
        return (not have_fm) or bool(s and (s.get("rating") is not None or (s.get("minutes") or 0) > 0))

    for fx in _games:
        ls = live_stats.get(fx["match_id"], {})
        stats_map = ls.get("players", {})
        have_fm = bool(stats_map)
        pids = _match_pids(fx)
        if not pids:
            continue
        sub = proj.loc[pids]
        if have_fm:                                  # LIVE odds: who's actually performing on the pitch
            weights = {p: _an.live_motm_weight(stats_map.get(p)) for p in pids}
        else:                                        # pre-match estimate, down-weighted by P(play)
            weights = {p: float(sub.loc[p, "pts_motm"]) * float(sub.loc[p].get("p_play") or 0.8) for p in pids}
        probs = _an.motm_probabilities(weights)
        for p in pids:
            _cur[p] = probs[p]["p1"]

        def _tr(p):
            return viz.trend_arrow(None if p not in _prev else probs[p]["p1"] - _prev[p])

        sc = ls.get("score")
        score = (f'<span class="vl-score">{fx["home"]} {sc[0]}–{sc[1]} {fx["away"]}</span>'
                 if sc else f'{fx["home"]} vs {fx["away"]}')
        mins = int((_nowL - _koL(fx)).total_seconds() // 60)
        clock = (f"~{min(mins, 90)}′" + ("+" if mins > 90 else "")) if have_fm else "LIVE"
        src = "" if have_fm else " · pre-match estimate (live stats unavailable)"
        st.markdown(f'<div class="vl-wrap"><div class="vl-h"><span class="vl-live"></span>{score}'
                    f'<span class="vl-clock">{clock}{src}</span></div>', unsafe_allow_html=True)

        left, right = st.columns([1.05, 1])
        with left:
            st.markdown('<div style="font-weight:700">⚽ Owned players on the pitch '
                        '<span style="font-weight:400;color:#9aa7b4;font-size:.82rem">(you & rivals)</span></div>',
                        unsafe_allow_html=True)
            owned_here = [p for p in pids if p in owner_of and _playing(p, stats_map, have_fm)]
            owned_here.sort(key=lambda p: (0 if p in my_squad else 1, -probs[p]["p1"]))
            if owned_here:
                cards = "".join(viz.live_card(sub.loc[p], probs[p], _own_html(p),
                                              "mine" if p in my_squad else "", live_pts=live_pts.get(p),
                                              stats=stats_map.get(p), trend=_tr(p)) for p in owned_here)
                st.markdown(f'<div class="vl-row">{cards}</div>', unsafe_allow_html=True)
            else:
                st.caption("No owned players on the pitch in this match yet.")
        with right:
            st.markdown('<div style="font-weight:700">🏅 MVP race '
                        '<span style="font-weight:400;color:#9aa7b4;font-size:.82rem">(odds to be best on '
                        'the pitch)</span></div>', unsafe_allow_html=True)
            ranked = [p for p in sorted(pids, key=lambda p: -probs[p]["p1"]) if weights[p] > 0][:3]
            if ranked:
                cards = "".join(viz.live_card(sub.loc[p], probs[p], _own_html(p), "gold" if i == 0 else "",
                                              "①②③"[i], live_pts=live_pts.get(p), stats=stats_map.get(p),
                                              trend=_tr(p)) for i, p in enumerate(ranked))
                st.markdown(f'<div class="vl-row">{cards}</div>', unsafe_allow_html=True)
            else:
                st.caption("Waiting for live ratings…")
        st.markdown("</div>", unsafe_allow_html=True)

    st.session_state["motm_prev"] = _cur
    st.caption("Live from FotMob: real score, ⭐rating, ⚽goals, 🅰assists, shots — and **MVP odds** computed "
               "from who's *actually performing* (Plackett-Luce on live ratings; players not on the pitch are "
               "excluded). 🟢▲ rising / 🔴▼ falling tracks who's climbing the MVP race since the last refresh. "
               "**pts** = live fantasy points. This panel vanishes the moment the game ends.")
    st.divider()


# ---------------------------------------------------------------- the points race (match by match)
st.subheader("📈 Points race — match by match")
st.caption("Every step is a match — and only matches where **someone in the league owns a player** "
           "appear (the only games any of us can score in). Solid lines use the points your players "
           "**actually** scored in finished matches; dashed lines project the upcoming ones. A manager's "
           "line only rises on a match their players feature in. Your line is the thick green one.")
have_squads = members["squad"].apply(len).gt(0).any()

from datetime import datetime, timedelta, timezone

OSLO = timezone(timedelta(hours=2))
live, target = d["next_round"], d["target_round"]
proj_live, proj_plan = d["proj"], d["proj_plan"]
team_of = proj_live["team"]   # player id -> team (every player)

_now = datetime.now(timezone.utc)


def _ko(fx):
    return datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00"))


# every manager's round-by-round scores (LIVE feed first, else the synced file)
synced = {}
for _src in (source, league):
    for _L in (_src or {}).get("leagues", []):
        for _mm in _L.get("members", []):
            _rounds = {r["number"]: r for r in (_mm.get("rounds") or []) if r.get("number")}
            if _rounds:
                synced.setdefault(_mm["squad_name"], _rounds)

# We step per ROUND, not per match: each manager's cumulative is the running sum of their OFFICIAL
# round totals, which equal the standings exactly. (A per-match accrual silently dropped eliminated-
# team players' historical points — once a team is knocked out its players leave the pool — which is
# why the old chart under-counted everyone and mis-ranked the race.)
_STAGE = {1: "Round 1", 2: "Round 2", 3: "Round 3", 4: "R32", 5: "R16", 6: "Quarters", 7: "Semis", 8: "Final"}
scored_rounds = sorted({r for rd in synced.values() for r, e in rd.items()
                        if (e or {}).get("points") is not None})
labels = [_STAGE.get(r, f"R{r}") for r in scored_rounds]

fig = go.Figure()
for _, m in members.iterrows():
    sq = m["squad_name"]
    rdata = synced.get(sq, {})
    run, ys = 0.0, []
    for r in scored_rounds:
        run += float((rdata.get(r) or {}).get("points") or 0.0)
        ys.append(run)
    if ys:
        fig.add_scatter(x=list(range(len(scored_rounds))), y=ys, customdata=labels,
                        mode="lines+markers", name=sq, legendgroup=sq,
                        line=dict(width=5 if m["is_me"] else 2.5, color=colour[sq], shape="spline", smoothing=0.4),
                        marker=dict(size=7 if m["is_me"] else 4),
                        hovertemplate=f"%{{customdata}}<br>{sq}: %{{y:.0f}} pts<extra></extra>")

for i in range(0, len(scored_rounds), 2):                 # faint alternating round bands
    fig.add_vrect(x0=i - 0.5, x1=i + 0.5, fillcolor="rgba(255,255,255,0.03)", line_width=0)

fig.update_layout(
    xaxis=dict(title="Round", tickmode="array", tickvals=list(range(len(scored_rounds))), ticktext=labels),
    yaxis_title="Cumulative points", height=470, legend=dict(orientation="h", y=-0.3),
    margin=dict(l=10, r=10, t=16, b=10))
st.plotly_chart(fig, width="stretch")
st.caption("**Cumulative points by round.** Each line's endpoint is that manager's exact total in the "
           "standings below — your line is the thick one.")

if not scored_rounds:
    st.caption("No rounds scored yet — the race fills in as results come in.")

# ---------------------------------------------------------------- standings (right under the race)
st.subheader("🏆 Standings")
# expected points each manager still has TO COME in the live round: their starters
# whose match hasn't kicked off yet (captain ×2). Drops as games kick off.
_future_teams = set()
for _fx in d["fixtures"]:
    if _fx.get("fantasy_round") == live and _ko(_fx) >= _now:
        _future_teams.update((_fx["home"], _fx["away"]))


def _exp_left(sq):
    rd = synced.get(sq, {}).get(live, {})
    starters = rd.get("starter_ids") or []
    capid = rd.get("captain_id")
    if not starters:
        return None
    return round(sum(float(proj_live.loc[pid, "xp_next"]) * (2 if pid == capid else 1)
                     for pid in starters
                     if pid in proj_live.index and team_of.get(pid) in _future_teams), 1)


standings = members.sort_values(["total_points", "latest_round_points"], ascending=False).reset_index(drop=True)
standings.insert(0, "pos", standings.index + 1)
standings["exp_left"] = standings["squad_name"].map(_exp_left)
st.caption(f"**Exp. left R{live}** = expected points each manager still has to come this round (from players "
           "whose match hasn't kicked off yet, captain ×2). It ticks down as games play.")
st.dataframe(
    standings[["pos", "manager", "squad_name", "total_points", "latest_round_points", "exp_left", "is_me"]],
    hide_index=True, width="stretch",
    column_config={"pos": "#", "manager": "Manager", "squad_name": "Team",
                   "total_points": "Total", "latest_round_points": "Last round",
                   "exp_left": st.column_config.NumberColumn(f"Exp. left R{live}", format="%.1f"),
                   "is_me": st.column_config.CheckboxColumn("You")})

# ---------------------------------------------------------------- rivals' squads + luck + pitches
if proj is not None and have_squads:
    ranks = d["ranks_live"]   # live-round ranks (match the pitch the cards draw)
    floors = dict(zip(proj.index, proj["floor"]))
    ceils = dict(zip(proj.index, proj["ceiling"]))

    # ---- luck over time: cumulative over/under-performance vs the field ----
    st.subheader("🎲 Luck — cumulative over/under-performance vs the field")
    st.caption("Each round, how many points above (lucky / clinical) or below (unlucky / misjudged) the "
               "league average a manager scored, **added up over the tournament**. Above 0 = riding luck so "
               "far; below 0 = due a bounce. Your line is the thick green one — it updates every round.")
    import numpy as np

    def _pts_in(m, r):
        return next((s.get("points", 0) for s in (m.get("round_scores") or [])
                     if isinstance(s, dict) and s.get("roundNumber") == r), None)
    scored_rounds = sorted({s.get("roundNumber") for _, m in members.iterrows()
                            for s in (m.get("round_scores") or [])
                            if isinstance(s, dict) and s.get("roundNumber")})
    if scored_rounds:
        means = {}
        for r in scored_rounds:
            fld = [p for p in (_pts_in(m, r) for _, m in members.iterrows()) if p is not None]
            means[r] = float(np.mean(fld)) if fld else 0.0
        lf = go.Figure()
        for _, m in members.iterrows():
            run, xs_, ys_ = 0.0, [], []
            for r in scored_rounds:
                p = _pts_in(m, r)
                if p is None:
                    continue
                run += (p - means[r])
                xs_.append(r)
                ys_.append(round(run, 1))
            if xs_:
                sq = m["squad_name"]
                lf.add_scatter(x=xs_, y=ys_, mode="lines+markers", name=("🟢 " if m["is_me"] else "") + sq,
                               line=dict(color=colour.get(sq, viz.NEUTRAL), width=5 if m["is_me"] else 2,
                                         shape="spline", smoothing=0.5),
                               marker=dict(size=8 if m["is_me"] else 5),
                               hovertemplate="%{fullData.name}<br>after R%{x}: %{y:+.1f} vs field<extra></extra>")
        lf.add_hline(y=0, line=dict(color="#888", width=1, dash="dot"))
        lf.update_layout(height=430, xaxis=dict(title="Round", dtick=1),
                         yaxis_title="Cumulative luck (points vs field average)",
                         legend=dict(orientation="h", y=-0.3), hovermode="x unified",
                         margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(lf, width="stretch", config={"displayModeBar": False})
        if len(scored_rounds) < 2:
            st.caption("Only one scored round so far — the lines fan out as more rounds complete.")
    else:
        st.caption("Luck lines appear once the first round has been scored.")

    # ---- rival pitches, always visible, in columns ----
    st.subheader("🔍 Everyone's team")
    st.caption("Each manager's XI on the pitch — photos, flags, price and points. Sorted by total points.")
    history = data_access.load_league_history().get("rounds", {})
    prev_round = str((league.get("current_round") or 2) - 1)
    prev_members = (history.get(prev_round) or {}).get("members", {})
    ordered = members[members["squad"].apply(len) > 0].sort_values("total_points", ascending=False)
    cols = st.columns(2)
    for i, (_, m) in enumerate(ordered.iterrows()):
        owned = proj.loc[[pid for pid in m["squad"] if pid in proj.index]]
        starter_ids = [pid for pid in (m.get("starter_ids") or []) if pid in owned.index]
        xi = optimizer.best_xi(owned, "xp_next") if len(owned) >= 11 else None
        xi_ids = starter_ids if len(starter_ids) == 11 else (xi["xi_ids"] if xi else [])
        cap_id = m.get("captain_id") if m.get("captain_id") in owned.index else (xi["captain_id"] if xi else None)
        # vice: real one from TV2 if present, else the 2nd-best starter as fallback
        vice_id = m.get("vice_captain_id") if m.get("vice_captain_id") in owned.index else None
        if vice_id is None and xi_ids:
            _cand = owned.loc[[p for p in xi_ids if p != cap_id and p in owned.index]].sort_values(
                "xp_next", ascending=False)
            vice_id = _cand.index[0] if len(_cand) else None
        bench = m.get("bench_ids") or [pid for pid in m["squad"] if pid not in xi_ids]
        formation = m.get("formation") or (xi["formation"] if xi else "?")
        rating = analytics.team_rating(proj, m["squad"], ranks, xi_ids=xi_ids)
        with cols[i % 2]:
            st.markdown(f"### {'🟢 ' if m['is_me'] else ''}{m['squad_name']}")
            st.caption(f"**{m['manager']}** · {formation} · {m['total_points']} pts · {owned['price'].sum():.0f}M")
            cap_nm = viz.short_name(owned.loc[cap_id, "name"]) if cap_id in owned.index else "—"
            vice_nm = viz.short_name(owned.loc[vice_id, "name"]) if vice_id in owned.index else "—"
            st.caption(f"🟠 **C** {cap_nm}  ·  🔵 **V** {vice_nm}")
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
                st.markdown(viz.pitch_html(owned, xi_ids, cap_id, "xp_next", bench, ranks, floors, ceils,
                                           vice_id=vice_id), unsafe_allow_html=True)

else:
    st.caption("🔒 Rival squads are hidden by TV 2 until each round's deadline passes. Once they unlock "
               "they appear here — every manager's team on a pitch, their prices, projected points, "
               "formation, and what they changed each round.")
