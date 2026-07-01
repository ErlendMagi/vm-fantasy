"""Top/bottom navigation bar + the site-wide "Pitch Dark" design system.

nav.render("<Active Label>") is the first line of every page body. It injects the
whole CSS design system (fonts, colour tokens, card/metric styling, section rhythm)
plus the responsive nav bar — sticky on top for desktop, fixed to the bottom thumb
zone on phones. Importing this module also applies the shared Plotly chart template
(via src.theme), so every chart matches the palette.
"""
import streamlit as st

from src import theme  # noqa: F401  — importing applies the shared Plotly template on every page

# (label, url-slug, emoji, low_priority). Slugs match Streamlit's page URLs.
PAGES = [
    ("League", "/", "🏆", False),
    ("Players", "/Projections", "📈", False),
    ("Matches", "/Match_Center", "📰", False),
]

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&display=swap');
:root{--bg:#0B0F14;--surf:#141A22;--surf2:#1B232D;--line:#263039;--text:#E6EDF3;--muted:#93A1B0;
  --accent:#10D9A3;--info:#3B9EFF;--pos:#2FE0A6;--neg:#FF5D6C;--gold:#FFC24B;--pitch1:#12633A;--pitch2:#16794A}

/* ---- base ---- */
html,body,[class*="css"],.stApp{background:var(--bg);color:var(--text);
  font-family:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif}
.block-container{max-width:1120px;padding-top:1.1rem}
a{color:var(--accent)}

/* ---- typography ---- */
h1,h2,h3,[data-testid="stHeading"]{font-family:'Space Grotesk','Inter',sans-serif;
  letter-spacing:-.01em;color:var(--text)}
h1{font-size:1.9rem;font-weight:800}
h2,[data-testid="stSubheader"]{font-size:1.35rem;font-weight:700;margin-top:2rem;
  padding-bottom:.35rem;border-bottom:1px solid var(--line)}
h3{font-size:1.1rem;font-weight:700}
[data-testid="stCaptionContainer"],.stCaption{color:var(--muted);font-size:.8rem}

/* ---- metric as an accented card ---- */
[data-testid="stMetric"]{background:var(--surf);border:1px solid var(--line);
  border-left:3px solid var(--accent);border-radius:14px;padding:12px 16px}
[data-testid="stMetricLabel"]{color:var(--muted);text-transform:uppercase;letter-spacing:.04em;font-size:.74rem}
[data-testid="stMetricValue"]{font-size:1.7rem;font-weight:800;font-variant-numeric:tabular-nums}
[data-testid="stMetricDelta"]{font-weight:600}

/* ---- tables, alerts, misc ---- */
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:14px;overflow:hidden}
.stAlert{border-radius:12px;border:1px solid var(--line)}
.stTabs [data-baseweb="tab-list"]{gap:4px}
.stTabs [aria-selected="true"]{color:var(--accent)}
hr{border-color:var(--line)}
.bpg-card{background:var(--surf);border:1px solid var(--line);border-radius:16px;
  padding:16px 18px;box-shadow:0 2px 10px rgba(0,0,0,.28);margin-bottom:14px}

/* ---- nav bar ---- */
[data-testid="stSidebarNav"],[data-testid="stSidebarCollapseButton"]{display:none!important}
section[data-testid="stSidebar"]{display:none!important}
.vmnav{display:flex;gap:6px;justify-content:center;flex-wrap:nowrap;overflow-x:auto;
  background:var(--surf);border:1px solid var(--line);border-radius:14px;padding:7px 8px;margin:0 0 16px;
  position:sticky;top:8px;z-index:1000;box-shadow:0 4px 16px rgba(0,0,0,.4)}
.vmnav a{flex:0 0 auto;display:flex;flex-direction:column;align-items:center;gap:1px;
  text-decoration:none;color:var(--muted);font-size:12.5px;font-weight:600;
  padding:7px 15px;border-radius:10px;white-space:nowrap;transition:.12s}
.vmnav a .ic{font-size:17px;line-height:1}
.vmnav a:hover{background:var(--surf2);color:var(--text)}
.vmnav a.act{background:var(--accent);color:#04120C}
@media (max-width:820px){
  .block-container{max-width:100%;padding-inline:14px;padding-bottom:96px!important}
  h1{font-size:1.55rem}
  .vmnav{position:fixed;left:6px;right:108px;bottom:6px;top:auto;margin:0;border-radius:16px;
    justify-content:space-between;padding:7px 6px;gap:2px}
  .vmnav a{font-size:10px;padding:5px 8px;gap:0}
  .vmnav a.lo{display:none}
  .vmnav a .lbl{max-width:56px;overflow:hidden;text-overflow:ellipsis}
  .vmnav a .ic{font-size:19px}
}
</style>
"""


def render(active: str = "") -> None:
    links = "".join(
        f'<a class="{"act" if label == active else ""}{" lo" if lo else ""}" target="_self" href="{url}">'
        f'<span class="ic">{icon}</span><span class="lbl">{label}</span></a>'
        for label, url, icon, lo in PAGES)
    st.markdown(_CSS + f'<div class="vmnav">{links}</div>', unsafe_allow_html=True)
