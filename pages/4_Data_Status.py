import json
from datetime import datetime, timezone

import streamlit as st

st.set_page_config(page_title="Data Status", page_icon="🧰", layout="wide")

from src import config, nav, services

nav.render("Data Status")
d = services.get_data()
st.title("🧰 Data status")
services.render_banners(d)

meta = d["meta"]
c1, c2, c3 = st.columns(3)
c1.metric("Last synced", meta.get("last_synced", "never")[:16].replace("T", " "))
c2.metric("Scraper mode", meta.get("scraper_mode", "?"))
odds = d["match_odds"]
c3.metric("Odds credits left", (odds or {}).get("credits_remaining") or "?")

st.subheader("Data files")
rows = []
for folder in (config.TV2_DIR, config.ODDS_DIR, config.STATIC_DIR):
    for f in sorted(folder.glob("*.json")):
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        rows.append({"file": f"{folder.name}/{f.name}", "modified (UTC)": f"{mtime:%Y-%m-%d %H:%M}",
                     "size (KB)": round(f.stat().st_size / 1024, 1)})
st.dataframe(rows, hide_index=True, width="stretch")

if odds:
    st.subheader("Odds snapshot")
    st.write(f"{len(odds.get('matches', []))} matches with h2h odds, fetched {odds.get('fetched_at', '?')[:16]}")
else:
    st.warning("No match odds yet — run `python scraper/refresh_odds.py` locally (needs free ODDS_API_KEY, "
               "see README). Until then projections use outright strengths or league-average defaults.")
if not d["outrights"]:
    st.warning("No outright (tournament winner) odds yet — advancement probabilities fall back to "
               "Monte Carlo on match odds only. Run `python scraper/refresh_odds.py --outrights` once.")

if d["adv"] is not None:
    st.subheader("Advancement probabilities (all 48 teams)")
    st.caption("P(team plays in each knockout round), from 10,000 group-stage simulations + "
               "strength propagation. Used to discount future points of at-risk players.")
    adv = d["adv"].sort_values("R32", ascending=False)
    st.dataframe(
        adv.style.format("{:.0%}"),
        width="stretch", height=600,
    )

st.subheader("Download raw data")
for name, payload in [("players.json", config.TV2_DIR / "players.json"),
                      ("my_team.json", config.TV2_DIR / "my_team.json"),
                      ("match_odds.json", config.ODDS_DIR / "match_odds.json")]:
    if payload.exists():
        st.download_button(name, payload.read_text(encoding="utf-8"), file_name=name, mime="application/json")
