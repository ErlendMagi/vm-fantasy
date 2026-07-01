"""One design system for the whole site — "Pitch Dark".

Importing this module (done by src/nav.py and src/viz.py, so it loads on every
page) sets a single Plotly template as the default, so every chart renders with
the same transparent background, faint gridlines, muted axes, dark hover cards
and one categorical colour ramp — instead of Plotly's default light theme fighting
the dark page. The CSS half of the system lives in src/nav.py (_CSS), injected on
every page via nav.render().
"""
import plotly.graph_objects as go
import plotly.io as pio

# ── palette tokens (mirror the CSS :root variables in nav.py) ──────────────────
BG = "#0B0F14"          # deep-ink canvas
SURF = "#141A22"        # card surface
SURF2 = "#1B232D"       # raised / hover
LINE = "#263039"        # single hairline / border token
TEXT = "#E6EDF3"        # primary text
MUTED = "#93A1B0"       # secondary / captions / axes
ACCENT = "#10D9A3"      # brand emerald — "you"
INFO = "#3B9EFF"        # info / vice / rivals
POS = "#2FE0A6"         # positive
NEG = "#FF5D6C"         # negative / "now" line
GOLD = "#FFC24B"        # captain / gold / warn
PITCH1 = "#12633A"      # branded pitch green (dark)
PITCH2 = "#16794A"      # branded pitch green (light)

# categorical ramp — use IN ORDER, one stable meaning each
CAT = ["#10D9A3", "#3B9EFF", "#FFC24B", "#B892FF", "#FF8FA3", "#5AD1FF", "#FF9E6D", "#7EE787"]

# scoring-component colours (semantic), resnapped to the palette
COMPOSITION = {
    "Minutes on pitch": MUTED, "Goals": ACCENT, "Assists": INFO, "Clean sheet": GOLD,
    "Man of the Match": "#FF9E6D", "Saves": "#B892FF", "Set-piece/penalty duty": "#FF8FA3",
    "Goals conceded": NEG,
}

_GRID = "rgba(255,255,255,0.06)"
_ZERO = "rgba(255,255,255,0.12)"

pio.templates["bpg"] = go.layout.Template(layout=dict(
    font=dict(family="Inter, 'Segoe UI', sans-serif", size=13, color=TEXT),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    colorway=CAT,
    title=dict(font=dict(family="'Space Grotesk', Inter, sans-serif", size=16, color=TEXT),
               x=0.01, xanchor="left"),
    xaxis=dict(gridcolor=_GRID, zerolinecolor=_ZERO, linecolor=LINE,
               tickfont=dict(color=MUTED, size=11), title_font=dict(color=MUTED, size=12)),
    yaxis=dict(gridcolor=_GRID, zerolinecolor=_ZERO, linecolor=LINE,
               tickfont=dict(color=MUTED, size=11), title_font=dict(color=MUTED, size=12)),
    legend=dict(font=dict(color=MUTED, size=11), bgcolor="rgba(0,0,0,0)"),
    margin=dict(l=8, r=8, t=36, b=8),
    hoverlabel=dict(bgcolor=SURF, bordercolor=LINE,
                    font=dict(family="Inter, sans-serif", size=12, color=TEXT)),
    hovermode="closest",
))
pio.templates.default = "bpg"
