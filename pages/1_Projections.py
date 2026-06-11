import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Player Ratings", page_icon="📈", layout="wide")

from src import optimizer, services, viz

d = services.get_data()
st.title("📈 Player ratings & rankings")
services.render_banners(d)
if d["proj"] is None:
    st.stop()

proj = d["proj"]
my = d["my_team"] or {}
my_ids = set(my.get("squad", []))

st.caption(
    "A player's **rating = expected points**, summing every way they score: minutes, goals "
    "(from betting odds), assists, clean sheets, Man-of-the-Match, saves and set-piece duty — "
    "adjusted for opponent, venue heat, stage and form."
)

horizon = st.radio("Rate players by…", ["Next round", "Whole tournament"], horizontal=True,
                   help="Whole tournament weights every remaining round by the team's survival odds — "
                        "a star on a team likely to exit early rates lower here.")
value_col = "xp_next" if horizon == "Next round" else "xp_tournament"

# ---------------------------------------------------------------- rankings per position
st.subheader("Position rankings")
st.caption("Bars show each player as a % of the best player in that position. "
           "Green = in your squad. Hover for ownership.")
tabs = st.tabs([viz.POS_LABEL[p] for p in viz.POS_ORDER])
for tab, pos in zip(tabs, viz.POS_ORDER):
    with tab:
        st.plotly_chart(viz.position_ranking_figure(proj, pos, value_col, my_ids),
                        width="stretch", config={"displayModeBar": False})

with st.expander("How each position earns points (model averages)"):
    avg = proj[proj["xp_next"] > 0.5].groupby("position")[list(viz.COMP)].mean().reindex(viz.POS_ORDER)
    figc = go.Figure()
    for raw, label in viz.COMP.items():
        figc.add_bar(name=label, x=[viz.POS_LABEL[p] for p in avg.index], y=avg[raw],
                     marker_color=viz.COLORS[label])
    figc.update_layout(barmode="stack", height=360, yaxis_title="Avg expected points / match",
                       legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(figc, width="stretch", config={"displayModeBar": False})

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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rating next round", f"{r['xp_next']:.1f} pts", f"#{rank_next} of {viz.POS_LABEL[r['position']].lower()}")
    c2.metric("Rating whole cup", f"{r['xp_tournament']:.1f} pts", f"#{rank_tour} · {pct_tour:.0f}% of best")
    c3.metric("Price", f"{r['price']}M")
    c4.metric("Owned by", f"{(r['ownership_pct'] or 0):.0f}%" if r["ownership_pct"] == r["ownership_pct"] else "–")

    a, b = st.columns(2)
    with a:
        st.plotly_chart(viz.composition_figure(r, f"Where {viz.short_name(name)}'s points come from (next round)"),
                        width="stretch", config={"displayModeBar": False})
    with b:
        if r["id"] in my_ids:
            st.success(f"✅ **{name} is in your team.**")
        elif my_ids:
            owned = proj.loc[[i for i in my.get("squad", []) if i in proj.index]]
            base = optimizer.squad_xp(owned, "xp_tournament")
            bank = float(my.get("bank", 0))
            best_swap, best_gain = None, None
            for out_id, out_row in owned[owned["position"] == r["position"]].iterrows():
                if r["price"] > out_row["price"] + bank + 1e-9:
                    continue
                trial = owned.drop(index=out_id)
                counts = trial["team"].value_counts()
                if counts.get(r["team"], 0) + 1 > 3:
                    continue
                val = optimizer.squad_xp(pd.concat([trial, proj.loc[[r["id"]]]]), "xp_tournament")
                gain = val - base
                if best_gain is None or gain > best_gain:
                    best_swap, best_gain = out_row["name"], gain
            st.markdown(f"#### Why isn't {viz.short_name(name)} in the team?")
            if best_swap is None:
                st.warning(f"**He doesn't fit the budget/rules right now.** At {r['price']}M, no single "
                           f"same-position swap is affordable with {bank:.1f}M in the bank (or the "
                           "3-per-country cap blocks it).")
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
                    f"3-per-country cap — a star's price has to beat what the same money buys elsewhere."
                )
        else:
            st.caption("No squad loaded yet.")

# ---------------------------------------------------------------- fixtures + nerd table
st.subheader(f"Round {d['next_round']} fixtures the model sees")
for fx in d["fixtures_next"]:
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
            ["name", "team", "position", "price", "ownership_pct", "opponent",
             "pts_goals", "pts_assists", "pts_cs", "pts_motm", "pts_appear", "pts_duty", "form_mult",
             "xp_next", "xp_tournament", "p_plays_after"]
        ],
        column_config={
            "ownership_pct": st.column_config.NumberColumn("owned %", format="%.1f"),
            "pts_goals": st.column_config.NumberColumn("goals", format="%.2f"),
            "pts_assists": st.column_config.NumberColumn("assists", format="%.2f"),
            "pts_cs": st.column_config.NumberColumn("clean sheet", format="%.2f"),
            "pts_motm": st.column_config.NumberColumn("MotM", format="%.2f"),
            "pts_appear": st.column_config.NumberColumn("minutes", format="%.2f"),
            "pts_duty": st.column_config.NumberColumn("duty", format="%.2f"),
            "form_mult": st.column_config.NumberColumn("form ×", format="%.2f"),
            "xp_next": st.column_config.NumberColumn("xP next", format="%.2f"),
            "xp_tournament": st.column_config.NumberColumn("xP cup", format="%.1f"),
            "p_plays_after": st.column_config.NumberColumn("P(plays next+1)", format="percent"),
        },
        hide_index=True, width="stretch", height=520,
    )
