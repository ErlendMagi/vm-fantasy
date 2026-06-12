from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Match Center", page_icon="📰", layout="wide")

from src import data_access, nav, narrative, services, viz

nav.render("Match Center")
d = services.get_data()
st.title("📰 Match Center")
services.render_banners(d)
if d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my = d["proj"], d["my_team"]
owned = proj.loc[[i for i in my["squad"] if i in proj.index]]

league = data_access.load_league()
live = services.get_live_league()
rivals = []
src = live or league
if src and src.get("leagues"):
    syn = (league or {}).get("leagues", [{}])[0]
    extra = {m["squad_name"]: m for m in syn.get("members", [])}
    for m in src["leagues"][0]["members"]:
        sq = (extra.get(m["squad_name"]) or m).get("squad", [])
        if sq and m["squad_name"] != (my.get("squad_name")):
            rivals.append((m["squad_name"], proj.loc[[i for i in sq if i in proj.index]]))

# the live round's games still to be played — the ones actually worth watching
fixtures = sorted([f for f in d["fixtures_next"] if f.get("status") != "finished"],
                  key=lambda f: f["kickoff_utc"])
st.caption(f"Auto-written analysis for the {len(fixtures)} upcoming round-{d['next_round']} matches — "
           "implied probabilities, expected goals, heat, key men, your exposure and rival threats. "
           "Refreshes with the odds.")
OSLO = timezone(timedelta(hours=2))
if not fixtures:
    st.info(f"All round-{d['next_round']} matches have kicked off. The next round's previews appear once "
            "its fixtures are scheduled.")
    st.stop()

# quick filter
only_mine = st.toggle("Only games my players feature in", value=False)
my_teams = set(owned["team"])

for fx in fixtures:
    if only_mine and not ({fx["home"], fx["away"]} & my_teams):
        continue
    brief = narrative.match_brief(fx, proj, owned, rivals)
    ko = datetime.fromisoformat(brief["kickoff_utc"].replace("Z", "+00:00")).astimezone(OSLO)
    with st.container(border=True):
        h1, h2 = st.columns([3, 2])
        with h1:
            st.markdown(
                f"### {viz.flag_img(fx['home'], h=22)} {fx['home']} "
                f"<span style='color:#888'>vs</span> {fx['away']} {viz.flag_img(fx['away'], h=22)}",
                unsafe_allow_html=True)
            st.caption(f"🗓️ {ko.strftime('%a %d %b · %H:%M')} (Oslo) · {fx.get('venue_id', '')}")
        with h2:
            m1, m2, m3 = st.columns(3)
            m1.metric("Your stake", f"{brief['my_stake']:.1f}", help="Expected points your XI has here")
            m2.metric("Danger", f"{brief['danger']:.1f}" if brief["danger"] > 0 else "—",
                      help=f"Pts the top rival ({brief['danger_name']}) gains on you" if brief["danger_name"] else "")
            m3.metric("Goals", f"{brief['mu_h']:.1f}–{brief['mu_a']:.1f}")
        # win-probability bar
        seg = go.Figure()
        for lbl, val, col in [(fx["home"], brief["ph"], "#00b894"), ("Draw", brief["pd"], "#636e72"),
                              (fx["away"], brief["pa"], "#0984e3")]:
            seg.add_bar(x=[val], y=["odds"], orientation="h", name=lbl, marker_color=col,
                        text=f"{lbl} {val:.0%}", textposition="inside", insidetextanchor="middle")
        seg.update_layout(barmode="stack", height=70, showlegend=False,
                          margin=dict(l=6, r=6, t=4, b=4), xaxis=dict(visible=False, range=[0, 1]),
                          yaxis=dict(visible=False))
        st.plotly_chart(seg, width="stretch", config={"displayModeBar": False})
        for para in brief["paragraphs"]:
            st.markdown(para)
