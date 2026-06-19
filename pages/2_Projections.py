import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Player Ratings", page_icon="📈", layout="wide")

from src import config, nav, optimizer, services, viz

nav.render("Players")
d = services.get_data()
st.title("📈 Player ratings & rankings")
services.render_banners(d)
if d["proj"] is None:
    st.stop()

proj = d["proj_plan"]  # rate players for the round you're planning (editable)
my = d["my_team"] or {}
my_ids = set(my.get("squad", []))
target, live = d["target_round"], d["next_round"]
if target != live:
    st.info(f"These ratings plan your team for the **next editable round — round {target}** (the upcoming "
            f"TV2 transfer deadline). Round {live} is still being played; see **Match Center** for the live "
            "round. Every 'round {0}' label below means the round you can still change.".format(target))

st.caption(
    "A player's **rating = expected points**, summing every way they score: minutes, goals "
    "(from betting odds), assists, clean sheets, Man-of-the-Match, saves and set-piece duty — "
    "adjusted for opponent, venue heat, stage and form."
)
st.caption(
    "▶️ **Playtime drives everything** — each rating is scaled by the player's **start chance** (shown per "
    "player below and on My Team). The model learns it from **observed minutes** (a 17-min cameo is "
    "downweighted automatically) and from **FotMob's published XIs** near kickoff. No free API gives a clean "
    "start-probability days ahead, so to eyeball predicted lineups yourself check "
    "[FotMob](https://www.fotmob.com/), [RotoWire](https://www.rotowire.com/soccer/lineups.php?league=WOC) or "
    "[TheFantasyTool](https://thefantasytool.com/predicted-lineups-wc) — but the app already folds the live "
    "lineup feed in for you."
)

horizon = st.radio("Rate players by…", [f"Round {target} (planning)", "Whole tournament"], horizontal=True,
                   help="Whole tournament weights every remaining round by the team's survival odds — "
                        "a star on a team likely to exit early rates lower here.")
value_col = "xp_next" if horizon.startswith("Round") else "xp_tournament"

# ---------------------------------------------------------------- rankings per position
_is_round = horizon.startswith("Round")           # the chart follows value_col; the heading must too
st.subheader(f"Position rankings — {f'planning round {target}' if _is_round else 'whole tournament'}")
st.caption("Bars show each player as a % of the best player in that position, rated for "
           + (f"the upcoming editable round (R{target})." if _is_round else
              "the whole tournament (survival-weighted — a star on a team likely to exit early rates lower).")
           + " Green = in your squad. Hover for ownership.")
tabs = st.tabs([viz.POS_LABEL[p] for p in viz.POS_ORDER])
for tab, pos in zip(tabs, viz.POS_ORDER):
    with tab:
        st.plotly_chart(viz.position_ranking_figure(proj, pos, value_col, my_ids),
                        width="stretch", config={"displayModeBar": False})

with st.expander(f"How each position earns points (round {target} averages)"):
    avg = proj[proj["xp_next"] > 0.5].groupby("position")[list(viz.COMP)].mean().reindex(viz.POS_ORDER)
    figc = go.Figure()
    for raw, label in viz.COMP.items():
        figc.add_bar(name=label, x=[viz.POS_LABEL[p] for p in avg.index], y=avg[raw],
                     marker_color=viz.COLORS[label])
    figc.update_layout(barmode="stack", height=360, yaxis_title="Avg expected points / match",
                       legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(figc, width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------- player points across the BPG league
from collections import defaultdict

from src import data_access as _da

_league = services.get_live_league() or _da.load_league()
_myname = my.get("squad_name")
_bpg = next((L for L in (_league or {}).get("leagues", [])
             if any(m.get("squad_name") == _myname for m in L.get("members", []))
             and any(m.get("rounds") for m in L.get("members", []))), None)
if _bpg:
    st.subheader("🏅 Who's cashed in — actual player points across your league")
    st.caption(f"Real fantasy points each player has banked **for each manager who owns them** in "
               f"**{_bpg['name']}**. **Captaincy counts double**, so the same player can show twice the points "
               "for whoever armbanded him. It's the differential map — who held the hauls, who missed them. "
               "Your column is highlighted 🟢.")
    _mgrs = sorted([m for m in _bpg["members"] if m.get("rounds") or m.get("squad")],
                   key=lambda m: -(m.get("total_points") or 0))
    _mnames = [m["squad_name"] for m in _mgrs]
    _pts = defaultdict(lambda: defaultdict(float))
    for _m in _mgrs:
        for _r in (_m.get("rounds") or []):
            # only points that were actually BANKED count — the starting XI (TV2 folds
            # auto-subs into starter_ids). The raw scores dict also carries bench players,
            # whose points were never earned, so summing them would inflate the totals
            # past each manager's real standings figure.
            _st = set(_r.get("starter_ids") or [])
            for _pid, _v in (_r.get("scores") or {}).items():
                if _st and _pid not in _st:
                    continue
                _pts[_pid][_m["squad_name"]] += (_v or 0)
    if _pts:
        def _pname(pid):
            return proj.loc[pid, "name"] if pid in proj.index else str(pid)[:8]

        def _pteam(pid):
            return proj.loc[pid, "team"] if pid in proj.index else ""
        _ordered = sorted(_pts.items(), key=lambda kv: -sum(kv[1].values()))   # most league impact first
        _top = _ordered[:24]
        _ynames = [f"{viz.flag(_pteam(p))} {viz.short_name(_pname(p))}" for p, _ in _top][::-1]
        _z = [[row.get(mn, 0) for mn in _mnames] for _, row in _top][::-1]
        _xlab = [(f"🟢 {mn}" if mn == _myname else mn) for mn in _mnames]
        hm = go.Figure(go.Heatmap(
            z=_z, x=_xlab, y=_ynames, colorscale="YlGn", colorbar=dict(title="pts"),
            text=[[(f"{v:.0f}" if v else "") for v in r] for r in _z], texttemplate="%{text}",
            textfont=dict(size=10), hovertemplate="%{y}<br>%{x}<br>%{z:.0f} pts<extra></extra>"))
        hm.update_layout(height=140 + 26 * len(_top), margin=dict(l=10, r=10, t=10, b=10),
                         xaxis=dict(side="top", tickangle=-25))
        st.plotly_chart(hm, width="stretch", config={"displayModeBar": False})
        # reconcile the columns to the official standings: a manager's column sums to
        # their GROSS banked player points; standings then net out −4/transfer hits.
        _hits = defaultdict(float)
        for _m in _mgrs:
            for _r in (_m.get("rounds") or []):
                _hits[_m["squad_name"]] += (_r.get("transfer_hit", 0) or 0)
        _hit_mgrs = [f"{mn} ({int(h)})" for mn in _mnames if (h := _hits.get(mn, 0))]
        if _hit_mgrs:
            st.caption("Each column sums to that manager's **gross** player points; the official "
                       "standings then net out transfer-hit penalties — " + ", ".join(_hit_mgrs) + ".")
        if len(_ordered) > len(_top):
            st.caption(f"Showing the **{len(_top)}** highest-impact players; the other "
                       f"**{len(_ordered) - len(_top)}** are in the full table below.")
        with st.expander("Full table — every owned player, points delivered to each manager"):
            _tbl = []
            for _p, _row in _ordered:
                _rec = {"flag": viz.flag(_pteam(_p)), "player": _pname(_p), "team": _pteam(_p),
                        "Σ league": int(sum(_row.values()))}
                for mn in _mnames:
                    _rec[mn] = int(_row.get(mn, 0))
                _tbl.append(_rec)
            st.dataframe(_tbl, hide_index=True, width="stretch", column_config={"flag": ""})
        st.caption("A bright cell only **one** manager has is a haul nobody else caught (a winning differential); "
                   "a full bright row is a **template** player everyone owns. A column that's mostly dark is a "
                   "manager whose picks haven't paid yet.")
    else:
        st.caption("Per-player league scores appear here once a round has been scored.")

# ---------------------------------------------------------------- why (not) this player
st.subheader("🔍 Player check: why is he (not) in my team?")
pick_list = proj.sort_values("xp_next", ascending=False)
who = st.selectbox("Pick any player", pick_list["name"] + "  ·  " + pick_list["team"])
if who:
    name, team = [s.strip() for s in who.split("·")]
    r = proj[(proj["name"] == name) & (proj["team"] == team)].iloc[0]
    pos_peers = proj[proj["position"] == r["position"]]
    rank_next = int((pos_peers["xp_next"] > r["xp_next"]).sum()) + 1
    rank_tour = int((pos_peers["xp_tournament"] > r["xp_tournament"]).sum()) + 1
    pct_tour = 100 * r["xp_tournament"] / max(float(pos_peers["xp_tournament"].max()), 0.01)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(f"Rating round {target}", f"{r['xp_next']:.1f} pts",
              f"#{rank_next} of {viz.POS_LABEL[r['position']].lower()} this round")
    c2.metric("Rating whole cup", f"{r['xp_tournament']:.1f} pts", f"#{rank_tour} · {pct_tour:.0f}% of best")
    _srcmap = {"lineup✓": "confirmed XI", "lineup~": "predicted XI", "minutes": "observed minutes",
               "prior": "pre-game estimate"}
    c3.metric("▶️ Start chance", f"{r['p_start'] * 100:.0f}%",
              help="Probability this player STARTS — it scales his whole projection (no minutes, no points). "
                   f"Source: {_srcmap.get(r.get('p_start_src', 'prior'), 'estimate')}.")
    c4.metric("Price", f"{r['price']}M")
    c5.metric("Owned by", f"{(r['ownership_pct'] or 0):.0f}%" if r["ownership_pct"] == r["ownership_pct"] else "–")

    a, b = st.columns(2)
    with a:
        st.plotly_chart(viz.composition_figure(r, f"Where {viz.short_name(name)}'s points come from (round {target})"),
                        width="stretch", config={"displayModeBar": False})
        if r.get("rotation_risk", 0) > 0.03:
            st.caption(f"🔄 **Rotation risk ~{r['rotation_risk'] * 100:.0f}%** — {viz.short_name(name)} is a "
                       "nailed starter in a lopsided game, so there's a real chance of being rested (the "
                       "projection already shaves this off).")
    with b:
        if r["id"] in my_ids:
            st.success(f"✅ **{name} is in your team.**")
        elif my_ids:
            owned = proj.loc[[i for i in my.get("squad", []) if i in proj.index]]
            base = optimizer.squad_xp(owned, "xp_tournament")
            bank = float(my.get("bank", 0))
            best_swap, best_gain = None, None
            _cap = config.soft_team_cap(target)
            _own_t = int((owned["team"] == r["team"]).sum())     # grandfather an existing stack
            for out_id, out_row in owned[owned["position"] == r["position"]].iterrows():
                if r["price"] > out_row["price"] + bank + 1e-9:
                    continue
                trial = owned.drop(index=out_id)
                counts = trial["team"].value_counts()
                if counts.get(r["team"], 0) + 1 > max(_cap, _own_t):
                    continue
                val = optimizer.squad_xp(pd.concat([trial, proj.loc[[r["id"]]]]), "xp_tournament")
                gain = val - base
                if best_gain is None or gain > best_gain:
                    best_swap, best_gain = out_row["name"], gain
            st.markdown(f"#### Why isn't {viz.short_name(name)} in the team?")
            if best_swap is None:
                st.warning(f"**He doesn't fit the budget/rules right now.** At {r['price']}M, no single "
                           f"same-position swap is affordable with {bank:.1f}M in the bank (or the "
                           f"{_cap}-per-country cap blocks it{' — group-stage diversification' if _cap < config.MAX_PER_TEAM else ''}).")
            elif best_gain > 0.05:
                st.info(f"**He actually would help.** Best swap: {best_swap} → {name}, "
                        f"worth **+{best_gain:.1f}** team points over the rest of the tournament. "
                        "The autopilot ranks every move on this same whole-tournament value before each "
                        "deadline and applies the best ROI swaps within your free transfers (taking a −4 "
                        "hit only when it clearly pays off) — so a clear upgrade like this gets made.")
            else:
                st.success(
                    f"**The team is better without him.** Best possible swap ({best_swap} → {name}) "
                    f"would change the TEAM's expected total by **{best_gain:+.1f}** points. "
                    f"The optimiser maximises the *team's* total under the 100M budget and "
                    f"{_cap}-per-country cap — a star's price has to beat what the same money buys elsewhere."
                )
        else:
            st.caption("No squad loaded yet.")

# ---------------------------------------------------------------- fixtures + nerd table
st.subheader(f"Round {d['target_round']} fixtures the model sees")
for fx in d["fixtures_plan"]:
    heat_note = "🏟️ indoor (A/C)" if fx.get("indoor_ac") else (
        f"🌡️ {fx['apparent_temp']:.0f}°C feels-like" if fx.get("apparent_temp") is not None else "no forecast yet")
    p_h = fx.get("p_home_win")
    odds_note = f" · win odds {p_h:.0%}/{fx.get('p_away_win', 0):.0%}" if p_h is not None else ""
    with st.expander(f"{fx['home']} vs {fx['away']}  ·  {fx['venue_id']}  ·  {heat_note}{odds_note}"):
        st.write(f"Expected goals: **{fx['home']} {fx['mu_home']:.2f} — {fx['mu_away']:.2f} {fx['away']}** "
                 f"(source: {fx['source']})")
        st.write(f"Kickoff: {fx['kickoff_utc']}")

with st.expander("🤓 Full data table (all players, all columns)"):
    f1, f2, f3 = st.columns(3)
    positions = f1.multiselect("Position", viz.POS_ORDER)
    teams = f2.multiselect("Team", sorted(proj["team"].unique()))
    search = f3.text_input("Search player")
    view = proj.copy()
    if positions:
        view = view[view["position"].isin(positions)]
    if teams:
        view = view[view["team"].isin(teams)]
    if search:
        view = view[view["name"].str.contains(search, case=False, na=False)]
    st.dataframe(
        view.sort_values(value_col, ascending=False)[
            ["name", "team", "position", "price", "ownership_pct", "p_start", "opponent",
             "pts_goals", "pts_assists", "pts_cs", "pts_motm", "pts_appear", "pts_duty", "form_mult",
             "rotation_risk", "xp_next", "xp_tournament", "p_plays_after"]
        ],
        column_config={
            "ownership_pct": st.column_config.NumberColumn("owned %", format="%.1f"),
            "p_start": st.column_config.NumberColumn("start %", format="percent",
                                                     help="Probability of starting — scales the whole "
                                                          "projection (observed minutes + published lineups)."),
            "pts_goals": st.column_config.NumberColumn("goals", format="%.2f"),
            "pts_assists": st.column_config.NumberColumn("assists", format="%.2f"),
            "pts_cs": st.column_config.NumberColumn("clean sheet", format="%.2f"),
            "pts_motm": st.column_config.NumberColumn("MotM", format="%.2f"),
            "pts_appear": st.column_config.NumberColumn("minutes", format="%.2f"),
            "pts_duty": st.column_config.NumberColumn("duty", format="%.2f"),
            "form_mult": st.column_config.NumberColumn("form ×", format="%.2f"),
            "rotation_risk": st.column_config.NumberColumn("rot risk", format="percent",
                                                           help="Chance a nailed starter is rested in a "
                                                                "lopsided game (blowout rotation)."),
            "opponent": st.column_config.TextColumn(f"opp R{target}"),
            "xp_next": st.column_config.NumberColumn(f"xP R{target}", format="%.2f"),
            "xp_tournament": st.column_config.NumberColumn("xP cup", format="%.1f"),
            "p_plays_after": st.column_config.NumberColumn(f"P(plays R{target + 1})", format="percent"),
        },
        hide_index=True, width="stretch", height=520,
    )
