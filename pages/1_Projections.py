import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Projections", page_icon="📈", layout="wide")

from src import services

d = services.get_data()
st.title("📈 Player projections")
services.render_banners(d)
if d["proj"] is None:
    st.stop()

proj = d["proj"]
st.caption(
    f"Round {d['next_round']} expected points = the sum of EVERY scoring component (appearance, "
    "goals, assists, clean sheets, Man-of-the-Match, saves), not just goals. Goals come from "
    "player-level betting odds; clean sheets from match odds; all adjusted for venue heat and "
    "each player's recent form. xP horizon weights the next two rounds by survival odds."
)

# ---- where points come from, by position ----
COMP = {"pts_appear": "Appearance/minutes", "pts_goals": "Goals", "pts_assists": "Assists",
        "pts_cs": "Clean sheet", "pts_motm": "Man of the Match", "pts_saves": "Saves",
        "pts_duty": "Set-piece/penalty duty"}
COLORS = {"Appearance/minutes": "#b2bec3", "Goals": "#00b894", "Assists": "#0984e3",
          "Clean sheet": "#fdcb6e", "Man of the Match": "#e17055", "Saves": "#6c5ce7",
          "Set-piece/penalty duty": "#fd79a8"}
st.subheader("Where points come from, by position")
st.caption("Different positions earn points very differently — defenders live on clean sheets, "
           "attackers on goals. The model values each player on their own full mix.")
avg = proj[proj["xp_next"] > 0.5].groupby("position")[list(COMP)].mean().reindex(["GK", "DEF", "MID", "FWD"])
fig = go.Figure()
for raw, label in COMP.items():
    fig.add_bar(name=label, x=avg.index, y=avg[raw], marker_color=COLORS[label])
fig.update_layout(barmode="stack", height=380, yaxis_title="Avg expected points / match",
                  legend=dict(orientation="h", y=-0.15))
st.plotly_chart(fig, width="stretch")

f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
positions = f1.multiselect("Position", ["GK", "DEF", "MID", "FWD"])
teams = f2.multiselect("Team", sorted(proj["team"].unique()))
max_price = f3.number_input("Max price", 3.0, 15.0, 15.0, 0.5)
search = f4.text_input("Search player")

view = proj.copy()
if positions:
    view = view[view["position"].isin(positions)]
if teams:
    view = view[view["team"].isin(teams)]
view = view[view["price"] <= max_price]
if search:
    view = view[view["name"].str.contains(search, case=False, na=False)]

st.dataframe(
    view.sort_values("xp_next", ascending=False)[
        ["name", "team", "position", "price", "ownership_pct", "opponent",
         "pts_goals", "pts_assists", "pts_cs", "pts_motm", "pts_appear", "form_mult",
         "xp_next", "xp_horizon", "xp_tournament", "p_plays_after"]
    ],
    column_config={
        "ownership_pct": st.column_config.NumberColumn("owned %", format="%.1f"),
        "pts_goals": st.column_config.NumberColumn("goals", format="%.2f"),
        "pts_assists": st.column_config.NumberColumn("assists", format="%.2f"),
        "pts_cs": st.column_config.NumberColumn("clean sheet", format="%.2f"),
        "pts_motm": st.column_config.NumberColumn("MotM", format="%.2f"),
        "pts_appear": st.column_config.NumberColumn("minutes", format="%.2f"),
        "form_mult": st.column_config.NumberColumn("form ×", format="%.2f", help="recent-form adjustment; 1.00 until games are played"),
        "xp_next": st.column_config.NumberColumn("xP next", format="%.2f"),
        "xp_horizon": st.column_config.NumberColumn("xP horizon", format="%.2f"),
        "xp_tournament": st.column_config.NumberColumn("xP tournament", format="%.1f"),
        "p_plays_after": st.column_config.NumberColumn("P(plays next+1)", format="percent"),
    },
    hide_index=True, width="stretch", height=560,
)

# ---- per-player composition breakdown ----
st.subheader("Break down a player's points")
who = st.selectbox("Player", view.sort_values("xp_next", ascending=False)["name"].tolist())
if who:
    r = proj[proj["name"] == who].iloc[0]
    parts = {label: float(r[raw]) for raw, label in COMP.items() if abs(r[raw]) > 0.01}
    bd = go.Figure(go.Bar(x=list(parts.values()), y=list(parts.keys()), orientation="h",
                          marker_color=[COLORS[k] for k in parts],
                          text=[f"{v:.2f}" for v in parts.values()], textposition="outside"))
    bd.update_layout(height=300, xaxis_title=f"{who} — expected points next round (total {r['xp_next']:.2f})",
                     margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(bd, width="stretch")

st.subheader(f"Round {d['next_round']} fixtures — model inputs")
for fx in d["fixtures_next"]:
    heat_note = "🏟️ indoor (A/C) — no heat penalty" if fx.get("indoor_ac") else (
        f"🌡️ feels like {fx['apparent_temp']:.0f}°C" if fx.get("apparent_temp") is not None
        else "no forecast yet")
    with st.expander(f"{fx['home']} vs {fx['away']}  ·  {fx['venue_id']}  ·  {heat_note}"):
        st.write(f"Expected goals: **{fx['home']} {fx['mu_home']:.2f} — {fx['mu_away']:.2f} {fx['away']}** "
                 f"(source: {fx['source']})")
        st.write(f"Kickoff: {fx['kickoff_utc']}")
