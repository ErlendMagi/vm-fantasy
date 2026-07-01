import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Players", page_icon="📈", layout="wide")

from src import nav, services, viz

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
    "player below). The model learns it from **observed minutes** (a 17-min cameo is "
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

# ---------------------------------------------------------------- who was a good pick (value)
import numpy as _np

st.subheader("💰 Who was a good pick — real points vs price")
st.caption("Every player's **actual fantasy points banked so far** against their **price**. The dashed line is the "
           "**going rate** (what a player of that price typically returns) — dots **above it are bargains** that beat "
           "their cost, dots **below are flops**. Bigger 🟢 dots are owned by someone in the league. Hover for names.")
_pl = proj[proj["total_points"].fillna(0) > 0].copy()
if len(_pl) >= 6:
    _owned_league = set()
    if _bpg:
        for _m in _bpg["members"]:
            _owned_league.update(_m.get("squad") or [])
    _px = _pl["price"].to_numpy(dtype=float)
    _py = _pl["total_points"].to_numpy(dtype=float)
    _slope, _icpt = _np.polyfit(_px, _py, 1)                       # going rate: points ~ price
    _pl["expected"] = _slope * _pl["price"] + _icpt
    _pl["surprise"] = _pl["total_points"] - _pl["expected"]        # + = beat its price, − = flop
    _pl["value"] = _pl["total_points"] / _pl["price"].clip(lower=0.1)
    _pl["owned"] = _pl.index.isin(_owned_league)

    fig = go.Figure()
    _xs = _np.linspace(_px.min(), _px.max(), 40)
    fig.add_trace(go.Scatter(x=_xs, y=_slope * _xs + _icpt, mode="lines", name="going rate",
                             line=dict(dash="dash", color="#8a94a0"), hoverinfo="skip"))
    for _lab, _mask, _col in [("bargain (beat its price)", _pl["surprise"] >= 0, "#00b894"),
                              ("flop (under its price)", _pl["surprise"] < 0, "#e17055")]:
        _s = _pl[_mask]
        fig.add_trace(go.Scatter(
            x=_s["price"], y=_s["total_points"], mode="markers", name=_lab,
            marker=dict(color=_col, size=[11 if o else 6 for o in _s["owned"]],
                        line=dict(width=[1.6 if o else 0 for o in _s["owned"]], color="#fff")),
            text=[f"{viz.flag(t)} {n}" for n, t in zip(_s["name"], _s["team"])],
            customdata=_np.stack([_s["price"], _s["total_points"], _s["ownership_pct"].fillna(0)], axis=-1),
            hovertemplate="%{text}<br>%{customdata[0]}M · %{customdata[1]:.0f} pts · owned %{customdata[2]:.0f}%<extra></extra>"))
    fig.update_layout(height=470, xaxis_title="price (M)", yaxis_title="real points banked so far",
                      legend=dict(orientation="h", y=-0.16), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    _num = {"total_points": st.column_config.NumberColumn("pts", format="%d"),
            "price": st.column_config.NumberColumn("M", format="%.1f"),
            "ownership_pct": st.column_config.NumberColumn("owned %", format="%.0f")}
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🤑 Best value — most points per M**")
        st.dataframe(_pl.sort_values("value", ascending=False).head(12)[
                         ["name", "team", "price", "total_points", "value", "ownership_pct"]],
                     hide_index=True, width="stretch",
                     column_config={**_num, "value": st.column_config.NumberColumn("pts/M", format="%.1f")})
    with c2:
        st.markdown("**🥶 Biggest flops — priciest under-deliverers**")
        _flop = _pl[_pl["price"] >= _pl["price"].median()].sort_values("surprise").head(12)
        st.dataframe(_flop[["name", "team", "price", "total_points", "surprise", "ownership_pct"]],
                     hide_index=True, width="stretch",
                     column_config={**_num, "surprise": st.column_config.NumberColumn("vs price", format="%+.0f")})
else:
    st.caption("The value chart fills in once players have banked some points.")

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
