from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Match Center", page_icon="📰", layout="wide")

from src import config, data_access, nav, narrative, optimizer, services, viz

nav.render("Match Center")
d = services.get_data()
st.title("📰 Match Center")
services.render_banners(d)
if d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my = d["proj"], d["my_team"]
owned = proj.loc[[i for i in my["squad"] if i in proj.index]]
# your starting XI + captain, so 'Your stake' matches the League watch guide (XI, captain ×2)
my_xi = (optimizer.best_xi(owned, "xp_next", p_start_floor=config.XI_PSTART_FLOOR) if len(owned) >= 11
         else {"xi_ids": list(owned.index), "captain_id": None})

league = data_access.load_league()
live = services.get_live_league()
rivals = []   # (squad_name, owned_df, xi_ids, captain_id) — each rival's best XI, same basis as yours
src = live or league
if src and src.get("leagues"):
    syn = (league or {}).get("leagues", [{}])[0]
    extra = {m["squad_name"]: m for m in syn.get("members", [])}
    for m in src["leagues"][0]["members"]:
        sq = (extra.get(m["squad_name"]) or m).get("squad", [])
        if sq and m["squad_name"] != (my.get("squad_name")):
            ow = proj.loc[[i for i in sq if i in proj.index]]
            if len(ow) >= 11:
                rxi = optimizer.best_xi(ow, "xp_next")
                rivals.append((m["squad_name"], ow, rxi["xi_ids"], rxi["captain_id"]))

# the live round's games still to be played — the ones actually worth watching
_now = datetime.now(timezone.utc)


def _koff(f):
    return datetime.fromisoformat(f["kickoff_utc"].replace("Z", "+00:00"))


OSLO = timezone(timedelta(hours=2))
all_fx = sorted([f for f in d["fixtures_next"] if f.get("status") != "finished"], key=_koff)
if not all_fx:
    st.info(f"All round-{d['next_round']} matches have kicked off. The next round's previews appear once "
            "its fixtures are scheduled.")
    st.stop()

# quick filter — applied FIRST, so the header counts match the cards actually shown
only_mine = st.toggle("Only games my players feature in", value=False)
my_teams = set(owned["team"])
shown = [fx for fx in all_fx if not (only_mine and not ({fx["home"], fx["away"]} & my_teams))]

# live score + finished flag for games that have kicked off (FotMob); drop the finished ones
_kicked = [fx for fx in shown if _koff(fx) < _now]
live_stats = services.get_live_stats(_kicked) if _kicked else {}
shown = [fx for fx in shown if not live_stats.get(fx["match_id"], {}).get("finished")]

n_live = sum(1 for f in shown if _koff(f) < _now)
n_up = len(shown) - n_live
st.caption(f"Auto-written analysis for round-{d['next_round']} matches — **{n_live} in progress, {n_up} still "
           "to come**" + (" (your games only)" if only_mine else "") + " — implied probabilities, expected "
           "goals, heat, key men, your exposure and rival threats. **In-progress games show the live score**; "
           "the written read stays the pre-match model until the final whistle.")
if not shown:
    st.info("No matches to show" + (" with your players in them" if only_mine else " — all have finished") + ".")
    st.stop()

_divider_shown = _rendered_live = False
for fx in shown:
    is_live_game = _koff(fx) < _now
    if not _divider_shown and not is_live_game and _rendered_live:
        st.markdown("<div style='border-top:2px solid #d63031;margin:6px 0 2px;color:#d63031;"
                    "font-weight:700;font-size:0.9em'>▲ NOW — matches above have kicked off · "
                    "below are still to come</div>", unsafe_allow_html=True)
        _divider_shown = True
    brief = narrative.match_brief(fx, proj, owned, rivals,
                                  my_xi_ids=my_xi["xi_ids"], my_cap=my_xi["captain_id"])
    ko = datetime.fromisoformat(brief["kickoff_utc"].replace("Z", "+00:00")).astimezone(OSLO)
    sc = live_stats.get(fx["match_id"], {}).get("score")
    with st.container(border=True):
        h1, h2 = st.columns([3, 2])
        with h1:
            _mid = (f"<b>{sc[0]}–{sc[1]}</b>" if sc else "<span style='color:#888'>vs</span>")
            _badge = " <span style='color:#d63031;font-weight:700'>🔴 LIVE</span>" if is_live_game else ""
            st.markdown(
                f"### {viz.flag_img(fx['home'], h=22)} {fx['home']} {_mid} "
                f"{fx['away']} {viz.flag_img(fx['away'], h=22)}{_badge}",
                unsafe_allow_html=True)
            st.caption(f"🗓️ {ko.strftime('%a %d %b · %H:%M')} (Oslo) · {fx.get('venue_id', '')}"
                       + (" · kicked off" if is_live_game else ""))
        with h2:
            m1, m2, m3 = st.columns(3)
            m1.metric("Your stake", f"{brief['my_stake']:.1f}",
                      help="Expected points your starting XI has here (captain ×2)")
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
    if is_live_game:
        _rendered_live = True
