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
    f"Round {d['next_round']} projections from betting odds (Poisson model), adjusted for heat "
    "(apparent temperature at the venue vs the player's national-team climate class). "
    "xP horizon = next round + 0.6 × the round after, weighted by the team's survival odds."
)

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
        ["name", "team", "position", "price", "ownership_pct", "opponent", "venue",
         "apparent_temp", "heat_mult", "xp_next", "xp_after", "xp_horizon", "p_plays_after"]
    ],
    column_config={
        "ownership_pct": st.column_config.NumberColumn("owned %", format="%.1f"),
        "apparent_temp": st.column_config.NumberColumn("feels like °C", format="%.0f"),
        "heat_mult": st.column_config.NumberColumn("heat ×", format="%.2f"),
        "xp_next": st.column_config.NumberColumn("xP next", format="%.2f"),
        "xp_after": st.column_config.NumberColumn("xP after", format="%.2f"),
        "xp_horizon": st.column_config.NumberColumn("xP horizon", format="%.2f"),
        "p_plays_after": st.column_config.NumberColumn("P(plays next+1)", format="percent"),
    },
    hide_index=True, width="stretch", height=600,
)

st.subheader(f"Round {d['next_round']} fixtures — model inputs")
for fx in d["fixtures_next"]:
    heat_note = "🏟️ indoor (A/C) — no heat penalty" if fx.get("indoor_ac") else (
        f"🌡️ feels like {fx['apparent_temp']:.0f}°C" if fx.get("apparent_temp") is not None
        else "no forecast yet")
    with st.expander(f"{fx['home']} vs {fx['away']}  ·  {fx['venue_id']}  ·  {heat_note}"):
        st.write(f"Expected goals: **{fx['home']} {fx['mu_home']:.2f} — {fx['mu_away']:.2f} {fx['away']}** "
                 f"(source: {fx['source']})")
        st.write(f"Kickoff: {fx['kickoff_utc']}")
