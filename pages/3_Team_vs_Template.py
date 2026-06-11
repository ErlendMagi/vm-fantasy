import pandas as pd
import streamlit as st

st.set_page_config(page_title="Team vs Template", page_icon="⚔️", layout="wide")

from src import services, template_team

d = services.get_data()
st.title("⚔️ My team vs the template")
services.render_banners(d)
if d["proj"] is None or d["my_team"] is None:
    st.stop()

proj, my, completed = d["proj"], d["my_team"], d["completed"]
template = template_team.template_squad(proj)
if template is None:
    st.info("The template team is built from ownership percentages, which arrive with the first "
            "real TV 2 sync. Run `python scraper/sync.py` once the scraper is configured.")
    st.stop()

st.caption("Template = most-owned squad right now, respecting the per-country cap (budget not "
           "enforced; today's ownership snapshot applied to past rounds — a small bias, documented "
           "on purpose). Captain = most-owned XI player.")


def round_matrix(squad: pd.DataFrame) -> pd.DataFrame:
    out = squad[["name", "team", "position", "ownership_pct", "total_points"]].copy()
    for r in completed:
        out[f"R{r}"] = squad["round_points"].apply(lambda rp: rp.get(r, 0))
    return out


a, b = st.columns(2)
with a:
    st.subheader("My squad, round by round")
    mine = proj.loc[[i for i in my["squad"] if i in proj.index]]
    st.dataframe(round_matrix(mine), hide_index=True, width="stretch")
with b:
    st.subheader("Template squad, round by round")
    st.dataframe(round_matrix(template), hide_index=True, width="stretch")

cmp = template_team.comparison_frame(proj, my, completed)
if cmp is not None:
    st.subheader("Round-by-round margin")
    cmp["margin"] = cmp["mine"] - cmp["template"]
    st.bar_chart(cmp.set_index("round")["margin"])
    total = int(cmp["mine"].sum() - cmp["template"].sum())
    st.metric("Total margin vs template", f"{total:+d} pts")
else:
    st.info("Charts appear once the first round completes.")
