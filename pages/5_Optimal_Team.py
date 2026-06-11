import pandas as pd
import streamlit as st

st.set_page_config(page_title="Optimal Team", page_icon="⭐", layout="wide")

from src import config, optimizer, services

d = services.get_data()
st.title("⭐ The model's optimal team")
services.render_banners(d)
if d["proj"] is None:
    st.stop()

proj = d["proj"]
horizon = st.toggle("Optimise for the two-round horizon (off = just the next round)", value=True)
res = services.get_optimal_squad("xp_horizon" if horizon else "xp_next")
if not res:
    st.stop()

squad = proj.loc[res["squad_ids"]]
xi = optimizer.best_xi(squad, "xp_next")  # lineup + captain for the imminent round
vice_pool = squad.loc[xi["xi_ids"]].sort_values("xp_next", ascending=False)
captain_name = proj.loc[xi["captain_id"], "name"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Squad cost", f"{res['price']}/{config.BUDGET:.0f}M")
c2.metric("Formation", xi["formation"])
c3.metric("Captain", captain_name)
c4.metric("Model squad value", res["value"])

order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
squad = squad.assign(role=squad["id"].map(
    lambda i: "🅒 captain" if i == xi["captain_id"]
    else ("Ⓥ vice" if i == vice_pool.index[1] else ("XI" if i in xi["xi_ids"] else "bench"))))
squad = squad.sort_values(
    ["role", "position"],
    key=lambda s: s.map({"🅒 captain": 0, "Ⓥ vice": 1, "XI": 2, "bench": 3}) if s.name == "role"
    else s.map(order), ascending=True)
st.dataframe(
    squad[["role", "name", "team", "position", "price", "ownership_pct", "opponent",
           "heat_mult", "xp_next", "xp_horizon"]],
    column_config={
        "ownership_pct": st.column_config.NumberColumn("owned %", format="%.1f"),
        "heat_mult": st.column_config.NumberColumn("heat ×", format="%.2f"),
        "xp_next": st.column_config.NumberColumn("xP next", format="%.2f"),
        "xp_horizon": st.column_config.NumberColumn("xP horizon", format="%.2f"),
    },
    hide_index=True, width="stretch",
)

st.warning(
    "⚠️ **Read before copying this.** This is the squad that maximises the odds-and-heat model's "
    "projected points within the 100M budget. It deliberately ignores ownership, so it will often "
    "be a low-owned, high-variance team that loads players from the biggest mismatches "
    "(e.g. Germany vs Curaçao, Spain vs Cape Verde). For a small money league that's a legitimate "
    "way to *win* (you beat the field with differentials), but it can swing hard round to round. "
    "It is a model output, not certainty."
)

# transfers to get from the current team to this one
if d["my_team"] is not None:
    mine = set(d["my_team"]["squad"])
    target = set(res["squad_ids"])
    out_ids, in_ids = mine - target, target - mine
    st.subheader(f"To move from your team to this one: {len(out_ids)} changes")
    a, b = st.columns(2)
    with a:
        st.caption("OUT")
        st.dataframe(proj.loc[list(out_ids)][["name", "team", "position", "price", "xp_horizon"]]
                     if out_ids else proj.head(0)[["name"]], hide_index=True, width="stretch")
    with b:
        st.caption("IN")
        st.dataframe(proj.loc[list(in_ids)][["name", "team", "position", "price", "xp_horizon"]]
                     if in_ids else proj.head(0)[["name"]], hide_index=True, width="stretch")
    st.caption("Before the tournament locks, transfers are free and unlimited, so you can apply all of "
               "these at no cost. After round 1 each change beyond your 2 free transfers costs −4 points.")
