import pandas as pd
import streamlit as st

st.set_page_config(page_title="Optimal Team", page_icon="⭐", layout="wide")

from src import config, optimizer, services, viz

d = services.get_data()
st.title("⭐ Dream team (unlimited transfers)")
services.render_banners(d)
if d["proj"] is None:
    st.stop()

proj = d["proj"]
my_squad = set((d["my_team"] or {}).get("squad", []))
st.info("**Why isn't this just my team?** Before the tournament started you had unlimited transfers, so the "
        "autopilot built your team to match this exactly. But once a round locks you only get **2 free "
        "transfers per round** (extra ones cost −4). This page shows the team you'd pick if you could "
        "rebuild from scratch today — the target your real team moves *toward* a couple of transfers at a "
        "time, not something you can jump to in one round without burning points.")
horizon = st.toggle("Optimise for the whole tournament (off = just the next round)", value=True)
res = services.get_optimal_squad("xp_tournament" if horizon else "xp_next")
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
c4.metric("Expected points (whole cup)" if horizon else "Expected points (next round)", f"{res['value']:.0f}")

st.caption("Lineup, captain and marker sizes below are for the **next round**; the squad itself is "
           f"optimised for {'the whole tournament' if horizon else 'the next round'}.")
bench_ids = [p for p in res["squad_ids"] if p not in xi["xi_ids"]]
st.plotly_chart(viz.pitch_figure(squad, xi["xi_ids"], xi["captain_id"], "xp_next", bench_ids),
                width="stretch", config={"displayModeBar": False})

a, b = st.columns(2)
with a:
    st.subheader("Expected points by position")
    st.plotly_chart(viz.position_totals_figure(squad, xi["xi_ids"], "xp_next"),
                    width="stretch", config={"displayModeBar": False})
with b:
    st.subheader("Squad value over the whole cup")
    bysum = squad.groupby("position")["xp_tournament"].sum().reindex(viz.POS_ORDER).fillna(0)
    import plotly.graph_objects as go
    figt = go.Figure(go.Bar(x=[viz.POS_LABEL[p] for p in viz.POS_ORDER], y=bysum.values,
                            marker_color=[viz.POS_COLOR[p] for p in viz.POS_ORDER],
                            text=[f"{v:.0f}" for v in bysum.values], textposition="outside",
                            cliponaxis=False))
    figt.update_layout(height=300, yaxis_title="Expected points, all remaining rounds",
                       margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(figt, width="stretch", config={"displayModeBar": False})

with st.expander("Full squad table"):
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
               "heat_mult", "xp_next", "xp_tournament"]],
        column_config={
            "ownership_pct": st.column_config.NumberColumn("owned %", format="%.1f"),
            "heat_mult": st.column_config.NumberColumn("heat ×", format="%.2f"),
            "xp_next": st.column_config.NumberColumn("xP next", format="%.2f"),
            "xp_tournament": st.column_config.NumberColumn("xP cup", format="%.1f"),
        },
        hide_index=True, width="stretch",
    )

st.info("This is the squad that maximises the model's expected points within the 100M budget and "
        "3-per-country cap. **While transfers are unlimited (before round 1) the autopilot rebuilds your "
        "team to match this.** After that it makes the best 1–2 transfers per round (the Transfers page), "
        "so your real team moves toward this rather than matching it exactly. It's a model output, not certainty.")

# transfers to get from the current team to this one
if d["my_team"] is not None:
    mine = set(d["my_team"]["squad"])
    target = set(res["squad_ids"])
    out_ids = [i for i in (mine - target) if i in proj.index]
    in_ids = [i for i in (target - mine) if i in proj.index]
    cols = ["name", "team", "position", "price", "xp_tournament"]
    n = len(out_ids)
    rounds_needed = (n + 1) // 2  # ~2 free transfers per round
    st.subheader(f"Your team is {n} change{'s' if n != 1 else ''} away "
                 f"(~{rounds_needed} round{'s' if rounds_needed != 1 else ''} of free transfers)")
    a, b = st.columns(2)
    with a:
        st.caption("OUT")
        st.dataframe(proj.loc[out_ids][cols] if out_ids else proj.head(0)[cols],
                     hide_index=True, width="stretch")
    with b:
        st.caption("IN")
        st.dataframe(proj.loc[in_ids][cols] if in_ids else proj.head(0)[cols],
                     hide_index=True, width="stretch")
