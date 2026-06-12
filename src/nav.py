"""Responsive top/bottom navigation bar.

Replaces Streamlit's left sidebar page list with a horizontal bar that sticks to
the TOP on desktop and is fixed to the BOTTOM (thumb zone) on phones/tablets.
Call nav.render("<Active Label>") as the first line of every page body.
"""
import streamlit as st

# (label, url-slug, emoji). Slugs match Streamlit's page URLs.
PAGES = [
    ("Home", "/", "⚽"),
    ("Projections", "/Projections", "📈"),
    ("Transfers", "/Transfers", "🔁"),
    ("Team vs Template", "/Team_vs_Template", "⚔️"),
    ("Data Status", "/Data_Status", "🧰"),
    ("League", "/League", "🏆"),
]

_CSS = """
<style>
/* hide Streamlit's default sidebar page nav and collapse the sidebar */
[data-testid="stSidebarNav"], [data-testid="stSidebarCollapseButton"]{display:none!important}
section[data-testid="stSidebar"]{display:none!important}
.vmnav{display:flex;gap:6px;justify-content:center;flex-wrap:nowrap;overflow-x:auto;
  background:#11161c;border:1px solid #2b333d;border-radius:14px;padding:7px 8px;margin:0 0 14px;
  position:sticky;top:8px;z-index:1000;box-shadow:0 4px 14px rgba(0,0,0,.35)}
.vmnav a{flex:0 0 auto;display:flex;flex-direction:column;align-items:center;gap:1px;
  text-decoration:none;color:#cfd6de;font-size:12.5px;font-weight:600;
  padding:7px 13px;border-radius:10px;white-space:nowrap;transition:.12s}
.vmnav a .ic{font-size:17px;line-height:1}
.vmnav a:hover{background:#1d2530;color:#fff}
.vmnav a.act{background:#00b894;color:#06281f}
/* keep the floating Streamlit badge clear of the bottom bar on phones */
@media (max-width:820px){
  .block-container{padding-bottom:96px!important}
  .vmnav{position:fixed;left:6px;right:6px;bottom:6px;top:auto;margin:0;border-radius:16px;
    justify-content:space-between;padding:7px 60px 7px 6px;gap:2px}
  .vmnav a{font-size:10px;padding:5px 6px;gap:0}
  .vmnav a .lbl{max-width:54px;overflow:hidden;text-overflow:ellipsis}
  .vmnav a .ic{font-size:19px}
}
</style>
"""


def render(active: str = "") -> None:
    links = "".join(
        f'<a class="{"act" if label == active else ""}" target="_self" href="{url}">'
        f'<span class="ic">{icon}</span><span class="lbl">{label}</span></a>'
        for label, url, icon in PAGES)
    st.markdown(_CSS + f'<div class="vmnav">{links}</div>', unsafe_allow_html=True)
