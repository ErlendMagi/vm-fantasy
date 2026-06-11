import streamlit as st

st.set_page_config(page_title="Transfers", page_icon="🔁", layout="wide")

from src import config, optimizer, services

d = services.get_data()
st.title("🔁 Transfer suggestions")
services.render_banners(d)
if d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my = d["proj"], d["my_team"]
owned = proj.loc[[i for i in my["squad"] if i in proj.index]]

st.subheader("Current squad health")
st.caption("P(plays next+1) is the odds-derived chance the team is still in the tournament — "
           "low values mean the player is about to stop scoring points (elimination risk).")
sq = owned.sort_values("xp_horizon", ascending=False)
st.dataframe(
    sq[["name", "team", "position", "price", "opponent", "heat_mult", "xp_next", "xp_horizon", "p_plays_after"]],
    column_config={
        "heat_mult": st.column_config.NumberColumn("heat ×", format="%.2f"),
        "xp_next": st.column_config.NumberColumn("xP next", format="%.2f"),
        "xp_horizon": st.column_config.NumberColumn("xP horizon", format="%.2f"),
        "p_plays_after": st.column_config.ProgressColumn("P(plays next+1)", min_value=0, max_value=1, format="%.2f"),
    },
    hide_index=True, width="stretch",
)

st.subheader("Best transfer plans")
default_free = int(my.get("free_transfers", 2))
unlimited = default_free >= config.SQUAD_SIZE
if unlimited:
    st.info("Transfers are currently **unlimited** (the squad isn't locked yet) — no −4 hits apply. "
            "After round 1 locks this becomes 2 free per round.")
c1, c2 = st.columns(2)
free = c1.number_input("Free transfers", 0, max(5, default_free),
                       5 if unlimited else default_free)
bank = c2.number_input("Bank (M)", 0.0, 50.0, float(my.get("bank", 0.0)), 0.1)

plans = services.get_transfer_plans(my["squad"], bank, free)
rows = []
for p in plans:
    rows.append({
        "out": ", ".join(f"{n} ({t})" for n, t in p["outs"]) or "—",
        "in": ", ".join(f"{n} ({t})" for n, t in p["ins"]) or "—",
        "transfers": p["n_transfers"],
        "hit": -p["hit_cost"] if p["hit_cost"] else 0,
        "net xP gain": p["net_gain"],
        "bank after": p["new_bank"],
    })
st.dataframe(rows, hide_index=True, width="stretch")
st.caption(f"Net gain = projected horizon points gained minus hit cost, vs keeping the squad. "
           f"A -{4} hit is only suggested when it clears the cost by a safety margin. "
           "Players from teams likely to be eliminated lose horizon value automatically.")

a, b = st.columns(2)
with a:
    st.subheader("Captain picks (next round)")
    st.dataframe(optimizer.captain_options(owned), hide_index=True, width="stretch")
with b:
    st.subheader("Suggested starting XI")
    xi = optimizer.best_xi(owned, "xp_next")
    xi_df = owned.loc[[i for i in xi["xi_ids"] if i in owned.index]]
    xi_df = xi_df.sort_values("position", key=lambda s: s.map({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}))
    st.write(f"Formation **{xi['formation']}** — projected **{xi['total']:.1f}** pts")
    st.dataframe(xi_df[["name", "team", "position", "xp_next"]], hide_index=True, width="stretch")
