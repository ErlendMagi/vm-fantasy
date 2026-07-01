import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="BPG League", page_icon="🏆", layout="wide")

from src import config, data_access, nav, optimizer, services, theme, viz

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

_SCOPE = st.radio(
    "Race view", [f"This round (R{live})", "Live + next round"],
    index=1, horizontal=True, label_visibility="collapsed",
    help="‘This round’ shows only the live round; ‘Live + next round’ also draws the round after it.")
_whole = False        # the 'projected finish' extension rode stale group-stage survival — retired
_max_r = live if _SCOPE.startswith("This round") else target

# per-manager per-round detail: lineup, this-round captain, and each player's
# ACTUAL points. The race steps per MATCH through the group stage (real team names), then adds ONE
# step per KNOCKOUT round from that round's total — TV2 scores the knockouts per round and the R32
# fixtures carry bracket placeholders, so a per-round step is the honest granularity AND fixes the bug
# that used to drop every R4+ match off the chart. Prefer the LIVE feed, fall back to the synced file.
synced = {}
for _src in (source, league):
    for _L in (_src or {}).get("leagues", []):
        for _mm in _L.get("members", []):
            _rounds = {r["number"]: r for r in (_mm.get("rounds") or []) if r.get("number")}
            if _rounds:
                synced.setdefault(_mm["squad_name"], _rounds)

_now = datetime.now(timezone.utc)


def _ko(fx):
    return datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00"))


# group matches (rounds 1-3, real teams) a manager owns a player in — one step each
owned_teams = {team_of.get(pid) for _, _m in members.iterrows()
               for pid in (_m.get("squad") or [])} - {None}
group_matches = sorted([fx for fx in d["fixtures"] if 0 < fx.get("fantasy_round", 0) <= min(_max_r, 3)],
                       key=lambda f: f["kickoff_utc"])
if owned_teams:
    group_matches = [fx for fx in group_matches if {fx["home"], fx["away"]} & owned_teams]

# knockout rounds that HAVE been scored (R32=4 … Final=8) — one per-round step each
_STAGE = {4: "R32", 5: "R16", 6: "Quarter", 7: "Semi", 8: "Final"}
ko_rounds = [r for r in range(4, _max_r + 1)
             if any((rd.get(r) or {}).get("points") is not None for rd in synced.values())]
steps = [("m", fx) for fx in group_matches] + [("r", r) for r in ko_rounds]

labels = [(f"{v['home']}–{v['away']} ({_ko(v).astimezone(OSLO).strftime('%a %d %b')})" if k == "m"
           else _STAGE.get(v, f"R{v}")) for k, v in steps]
played = [(_ko(v) < _now) if k == "m" else True for k, v in steps]      # a scored KO round counts as played
last_played = max([i for i, p in enumerate(played) if p], default=-1)

fig = go.Figure()
for _, m in members.iterrows():
    sq = m["squad_name"]
    rdata = synced.get(sq, {})
    xs, ys, run = [], [], 0.0
    for i, (kind, val) in enumerate(steps):
        if kind == "m":
            rd = rdata.get(val["fantasy_round"], {})
            _st = set(rd.get("starter_ids") or [])
            teams = {val["home"], val["away"]}
            run += sum(v for pid, v in (rd.get("scores") or {}).items()
                       if v and pid in _st and team_of.get(pid) in teams)
        else:
            run += float((rdata.get(val) or {}).get("points") or 0.0)     # knockout round total
        xs.append(i)
        ys.append(run)
    if xs:
        fig.add_scatter(x=xs, y=ys, customdata=[labels[i] for i in xs], mode="lines", name=sq,
                        legendgroup=sq, line=dict(width=5 if m["is_me"] else 2, color=colour[sq],
                                                  shape="spline", smoothing=0.5),
                        hovertemplate=f"%{{customdata}}<br>{sq}: %{{y:.0f}} pts<extra></extra>")

# round bands + a 'now' marker at the last scored step
for r in sorted({(v["fantasy_round"] if k == "m" else v) for k, v in steps}):
    idxs = [i for i, (k, v) in enumerate(steps) if (v["fantasy_round"] if k == "m" else v) == r]
    fig.add_vrect(x0=idxs[0] - 0.5, x1=idxs[-1] + 0.5,
                  fillcolor="rgba(255,255,255,0.03)" if r % 2 else "rgba(0,0,0,0)", line_width=0)
    fig.add_annotation(x=(idxs[0] + idxs[-1]) / 2, y=1.0, yref="paper",
                       text=(_STAGE.get(r) or f"Round {r}") if r > 3 else f"Round {r}",
                       showarrow=False, font=dict(size=12, color=theme.MUTED), yshift=8)
if last_played >= 0:
    fig.add_vline(x=last_played + 0.5, line=dict(color=theme.NEG, width=2),
                  annotation_text="▲ now", annotation_position="top right",
                  annotation_font=dict(color=theme.NEG, size=12))

fig.update_layout(
    xaxis=dict(title="Group matches → then each knockout round", tickmode="array",
               tickvals=list(range(len(steps))), ticktext=labels, tickangle=-55, tickfont=dict(size=9)),
    yaxis_title="Cumulative points", height=560, legend=dict(orientation="h", y=-0.62),
    margin=dict(l=10, r=10, t=22, b=150))
st.plotly_chart(fig, width="stretch")
st.caption("The group stage steps **match by match**; each **knockout round adds one step** (TV2 scores the "
           "knockouts per round). Your line is the thick one; the **red marker is now**.")

if last_played < 0:
    st.caption("No matches scored yet — the race fills in as results come in.")

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

# ---------------------------------------------------------------- watch guide (after standings)
# round {live} games that have NOT kicked off yet (played/in-progress dropped)
watch_rows = []
if proj_live is not None and have_squads:
    me_row = next((m for _, m in members.iterrows() if m["is_me"] and m["squad"]), None)
    if me_row is not None:
        my_owned = proj_live.loc[[i for i in me_row["squad"] if i in proj_live.index]]
        my_xi = optimizer.best_xi(my_owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR)  # my fielded XI floors playtime
        rival_xis = []
        for _, mm in members.iterrows():
            if mm["is_me"] or not mm["squad"]:
                continue
            ow = proj_live.loc[[i for i in mm["squad"] if i in proj_live.index]]
            if len(ow) >= 11:
                rival_xis.append((mm["squad_name"], ow, optimizer.best_xi(ow, "xp_next")))

        def stake(ow, xi_, teams):
            sel = ow[(ow["team"].isin(teams)) & (ow["id"].isin(xi_["xi_ids"]))]
            s = float(sel["xp_next"].sum())
            if xi_["captain_id"] in set(sel["id"]):
                s += float(ow.loc[xi_["captain_id"], "xp_next"])
            return s

        for fx in d["fixtures"]:
            if fx.get("fantasy_round") != live or _ko(fx) < _now:   # drop kicked-off games
                continue
            ko = datetime.fromisoformat(fx["kickoff_utc"].replace("Z", "+00:00")).astimezone(OSLO)
            teams = {fx["home"], fx["away"]}
            mine = stake(my_owned, my_xi, teams)
            threats = sorted(((stake(ow, xi_, teams) - mine, sn) for sn, ow, xi_ in rival_xis), reverse=True)
            danger, threat_name = (threats[0] if threats else (0.0, "-"))
            watch_rows.append({"ko": ko, "match": f"{viz.flag(fx['home'])} {fx['home']} – {fx['away']} {viz.flag(fx['away'])}",
                               "mine": round(mine, 1), "danger": round(max(danger, 0), 1), "threat": threat_name})

if watch_rows:
    st.markdown(f"#### 📺 Your watch guide — round {live} (still to kick off)")
    st.caption("Only round-{0} games that **haven't started yet** (played ones drop off). **Your stake** = "
               "expected points your XI has riding on the match (captain ×2). **Danger** = how many points the "
               "strongest rival gains on you there — the games that can hurt.".format(live))
    wg = pd.DataFrame(sorted(watch_rows, key=lambda r_: r_["ko"]))
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
elif proj_live is not None and have_squads:
    st.caption(f"📺 All your round-{live} games have kicked off — the watch guide refills when round "
               f"{live + 1}'s fixtures open.")

# ---------------------------------------------------------------- rivals' squads, ranked by SPI
if proj is not None and have_squads:
    from src import analytics
    ranks = d["ranks_live"]   # live tab → live-round ranks (match the pitch the cards draw)
    floors = dict(zip(proj.index, proj["floor"]))
    ceils = dict(zip(proj.index, proj["ceiling"]))
    managers = [{"squad_name": m["squad_name"], "manager": m["manager"], "is_me": m["is_me"],
                 "squad": m["squad"], "total_points": m["total_points"]}
                for _, m in members.iterrows() if m["squad"]]

    # each manager's ACTUAL fielded XI + captain (synced starters when a full 11, else
    # the model's best XI), so EVERY rank/rating/projection below — SPI, the card's
    # 'proj pts', team_rating and 'Avg XI rank' — describes the same XI the pitch draws.
    def _fielded(m):
        ow = proj.loc[[pid for pid in (m.get("squad") or []) if pid in proj.index]]
        if len(ow) < 11:
            return None
        best = optimizer.best_xi(ow, "xp_next")
        starters = [pid for pid in (m.get("starter_ids") or []) if pid in ow.index]
        xi_ids = starters if len(starters) == 11 else best["xi_ids"]
        cap_id = m.get("captain_id") if m.get("captain_id") in ow.index else best["captain_id"]
        return (xi_ids, cap_id)
    fielded_full = {m["squad_name"]: _fielded(m) for _, m in members.iterrows() if m["squad"]}
    fielded_xi = {k: (v[0] if v else []) for k, v in fielded_full.items()}
    spi = analytics.squad_power_index(proj, managers, fielded=fielded_full)

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
        tr = analytics.team_rating(proj, mgr["squad"], ranks, xi_ids=fielded_xi.get(mgr["squad_name"]))
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
                    "for the whole cup (faded). **Sorted by expected cup ROI**, so the solid 'actual' bars "
                    "needn't decrease in step.")
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

    if not spi.empty and not spi.iloc[0]["is_me"]:
        with st.expander("🤔 Why isn't my team #1 on the projection?"):
            st.markdown(
                f"This board ranks teams by the **Squad Power Index** — a blend of your projected round-{live} "
                "XI (60%), whole-cup durability (25%) and value-per-million (15%) — not who could build the "
                "best team today. Three reasons you can sit behind a rival here and it's still fine:\n\n"
                "1. **You're rules-locked.** Each round you only get **2 free transfers** (a 3rd "
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
            st.caption(f"**{m['manager']}** · SPI {m['SPI']:.0f} · {formation} · {m['proj_next']:.0f} proj pts · "
                       f"{m['total_points']} actual · {owned['price'].sum():.0f}M")
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
