"""Shared plotly figures: the pitch view, position rankings, point composition."""
import pandas as pd
import plotly.graph_objects as go

COMP = {"pts_appear": "Minutes on pitch", "pts_goals": "Goals", "pts_assists": "Assists",
        "pts_cs": "Clean sheet", "pts_motm": "Man of the Match", "pts_saves": "Saves",
        "pts_duty": "Set-piece/penalty duty", "pts_concede": "Goals conceded"}
COLORS = {"Minutes on pitch": "#b2bec3", "Goals": "#00b894", "Assists": "#0984e3",
          "Clean sheet": "#fdcb6e", "Man of the Match": "#e17055", "Saves": "#a29bfe",
          "Set-piece/penalty duty": "#fd79a8", "Goals conceded": "#d63031"}
# distinct accents so a colour never means two things on one screen
MINE_GREEN = "#00b894"      # reserved: "in your squad"
GAIN_BLUE = "#0984e3"       # reserved: "positive transfer gain"
NEUTRAL = "#636e72"
POS_ORDER = ["GK", "DEF", "MID", "FWD"]
POS_LABEL = {"GK": "Keepers", "DEF": "Defenders", "MID": "Midfielders", "FWD": "Forwards"}
POS_COLOR = {"GK": "#6c5ce7", "DEF": "#fdcb6e", "MID": "#74b9ff", "FWD": "#55efc4"}
ROW_Y = {"GK": 0.7, "DEF": 2.1, "MID": 3.7, "FWD": 5.2}

# national-team flag emoji (by canonical team name; FIFA code as fallback)
FLAGS = {
    "Mexico": "🇲🇽", "South Africa": "🇿🇦", "Czech Republic": "🇨🇿", "South Korea": "🇰🇷",
    "Canada": "🇨🇦", "Switzerland": "🇨🇭", "Qatar": "🇶🇦", "Bosnia & Herzegovina": "🇧🇦",
    "Brazil": "🇧🇷", "Morocco": "🇲🇦", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Haiti": "🇭🇹", "USA": "🇺🇸",
    "Turkey": "🇹🇷", "Australia": "🇦🇺", "Paraguay": "🇵🇾", "Germany": "🇩🇪", "Ecuador": "🇪🇨",
    "Ivory Coast": "🇨🇮", "Curacao": "🇨🇼", "Netherlands": "🇳🇱", "Japan": "🇯🇵", "Sweden": "🇸🇪",
    "Tunisia": "🇹🇳", "Belgium": "🇧🇪", "Egypt": "🇪🇬", "Iran": "🇮🇷", "New Zealand": "🇳🇿",
    "Spain": "🇪🇸", "Uruguay": "🇺🇾", "Saudi Arabia": "🇸🇦", "Cape Verde": "🇨🇻", "France": "🇫🇷",
    "Norway": "🇳🇴", "Senegal": "🇸🇳", "Iraq": "🇮🇶", "Argentina": "🇦🇷", "Austria": "🇦🇹",
    "Algeria": "🇩🇿", "Jordan": "🇯🇴", "Portugal": "🇵🇹", "Colombia": "🇨🇴", "Uzbekistan": "🇺🇿",
    "DR Congo": "🇨🇩", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Croatia": "🇭🇷", "Ghana": "🇬🇭", "Panama": "🇵🇦",
}
_CODE_FLAGS = {  # FIFA 3-letter code -> flag, for the rival feed which gives codes
    "SUI": "🇨🇭", "GER": "🇩🇪", "ESP": "🇪🇸", "FRA": "🇫🇷", "BRA": "🇧🇷", "POR": "🇵🇹", "ARG": "🇦🇷",
    "ENG": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "NED": "🇳🇱", "BEL": "🇧🇪", "CRO": "🇭🇷", "URU": "🇺🇾", "COL": "🇨🇴", "MEX": "🇲🇽",
    "USA": "🇺🇸", "CAN": "🇨🇦", "NOR": "🇳🇴", "MAR": "🇲🇦", "SEN": "🇸🇳", "JPN": "🇯🇵", "AUT": "🇦🇹",
    "SWE": "🇸🇪", "RSA": "🇿🇦", "CZE": "🇨🇿", "KOR": "🇰🇷", "QAT": "🇶🇦", "BIH": "🇧🇦", "SCO": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "HAI": "🇭🇹", "TUR": "🇹🇷", "AUS": "🇦🇺", "PAR": "🇵🇾", "ECU": "🇪🇨", "CIV": "🇨🇮", "CUW": "🇨🇼",
    "TUN": "🇹🇳", "EGY": "🇪🇬", "IRN": "🇮🇷", "NZL": "🇳🇿", "KSA": "🇸🇦", "CPV": "🇨🇻", "IRQ": "🇮🇶",
    "ALG": "🇩🇿", "JOR": "🇯🇴", "UZB": "🇺🇿", "COD": "🇨🇩", "GHA": "🇬🇭", "PAN": "🇵🇦",
}


def flag(team: str = "", code: str = "") -> str:
    return FLAGS.get(team) or _CODE_FLAGS.get(code, "🏳️")


def short_name(full: str) -> str:
    parts = str(full).split()
    return parts[-1] if len(parts) > 1 else str(full)


def pitch_figure(squad: pd.DataFrame, xi_ids: list, captain_id, value_col: str = "xp_next",
                 bench_order: list | None = None) -> go.Figure:
    """The starting XI on a football pitch, marker size = expected points,
    captain in orange. Bench drawn below the pitch."""
    fig = go.Figure()
    line_col = "rgba(255,255,255,0.45)"
    # pitch: two-tone halves + markings
    for y0, y1 in [(0, 3.05), (3.05, 6.1)]:
        fig.add_shape(type="rect", x0=0, y0=y0, x1=8, y1=y1, line=dict(width=0),
                      fillcolor="#157f3d" if y0 == 0 else "#1d8a46", layer="below")
    fig.add_shape(type="rect", x0=0, y0=0, x1=8, y1=6.1, line=dict(color=line_col, width=2))
    fig.add_shape(type="line", x0=0, y0=3.05, x1=8, y1=3.05, line=dict(color=line_col, width=2))
    fig.add_shape(type="circle", x0=3.2, y0=2.25, x1=4.8, y1=3.85, line=dict(color=line_col, width=2))
    fig.add_shape(type="rect", x0=2.2, y0=0, x1=5.8, y1=1.0, line=dict(color=line_col, width=2))
    fig.add_shape(type="rect", x0=2.2, y0=5.1, x1=5.8, y1=6.1, line=dict(color=line_col, width=2))

    xi = squad.loc[[i for i in xi_ids if i in squad.index]]
    vmax = max(float(xi[value_col].max()), 0.1)
    for pos, y in ROW_Y.items():
        row = xi[xi["position"] == pos].sort_values(value_col, ascending=False)
        n = len(row)
        xs = [8 * (k + 1) / (n + 1) for k in range(n)]
        for x, (idx, r) in zip(xs, row.iterrows()):
            cap = idx == captain_id
            fl = flag(r["team"])
            price = f"{r['price']:.1f}M" if "price" in r and r["price"] == r["price"] else ""
            fig.add_scatter(
                x=[x], y=[y], mode="markers+text", cliponaxis=False,
                marker=dict(size=30 + 26 * float(r[value_col]) / vmax,
                            color="#e17055" if cap else "#ffffff",
                            line=dict(color="#2d3436", width=2)),
                text=f"{fl} <b>{short_name(r['name'])}{' (C)' if cap else ''}</b><br>"
                     f"{price} · {r[value_col]:.1f} pts",
                textposition="bottom center", textfont=dict(color="white", size=12),
                hovertemplate=(f"{fl} <b>{r['name']}</b> ({r['team']})<br>"
                               f"Price: {price}<br>vs {r.get('opponent', '?')}<br>"
                               f"Expected points: {r[value_col]:.2f}<extra></extra>"),
                showlegend=False)
    # bench strip
    bench_ids = bench_order or [i for i in squad.index if i not in set(xi_ids)]
    bench = squad.loc[[i for i in bench_ids if i in squad.index]]
    n = max(len(bench), 1)
    for k, (idx, r) in enumerate(bench.iterrows()):
        x = 8 * (k + 1) / (n + 1)
        fl = flag(r["team"])
        price = f"{r['price']:.1f}M" if "price" in r and r["price"] == r["price"] else ""
        fig.add_scatter(
            x=[x], y=[-0.9], mode="markers+text", cliponaxis=False,
            marker=dict(size=22, color="#636e72", line=dict(color="#2d3436", width=1)),
            text=f"{fl} {short_name(r['name'])}<br>{price} · {r[value_col]:.1f}",
            textposition="bottom center", textfont=dict(color="#b2bec3", size=10),
            hovertemplate=f"{fl} <b>{r['name']}</b> (bench)<br>{price} · xP {r[value_col]:.2f}<extra></extra>",
            showlegend=False)
    fig.add_annotation(x=0.1, y=-0.9, text="BENCH", showarrow=False,
                       font=dict(color="#b2bec3", size=11), xanchor="left")
    fig.update_layout(
        xaxis=dict(visible=False, range=[-0.3, 8.3], fixedrange=True),
        yaxis=dict(visible=False, range=[-1.9, 6.5], fixedrange=True),
        height=620, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def position_ranking_figure(proj: pd.DataFrame, pos: str, value_col: str,
                            my_ids: set, top_n: int = 15) -> go.Figure:
    """Top players of a position as horizontal bars on a 0-100% scale
    (% of the best player's rating). Green = in your squad."""
    sub = proj[proj["position"] == pos].nlargest(top_n, value_col).iloc[::-1]
    n_rows = len(sub)
    best = max(float(sub[value_col].max()), 0.01)
    pct = sub[value_col] / best * 100
    mine = sub["id"].isin(my_ids)
    labels = [f"#{n_rows - k}  {flag(t)} {n}" for k, (n, t) in enumerate(zip(sub["name"], sub["team"]))]
    own = ["unknown" if o != o else f"{o:.1f}%" for o in sub["ownership_pct"]]  # o!=o -> NaN
    fig = go.Figure(go.Bar(
        x=pct, y=labels, orientation="h",
        marker_color=[MINE_GREEN if m else NEUTRAL for m in mine],
        text=[f"{pr:.1f}M · {v:.1f} pts" + ("  ✓ yours" if m else "")
              for v, pr, m in zip(sub[value_col], sub["price"], mine)],
        textposition="outside", cliponaxis=False, customdata=own,
        hovertemplate="%{y}<br>%{text}<br>Ownership: %{customdata}<extra></extra>"))
    fig.update_layout(
        xaxis=dict(title="% of the position's best player", range=[0, 118]),
        height=80 + 30 * len(sub), margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False)
    return fig


def composition_figure(row: pd.Series, title: str | None = None, height: int = 300) -> go.Figure:
    parts = {label: float(row[raw]) for raw, label in COMP.items()
             if raw in row and abs(float(row[raw])) > 0.01}
    fig = go.Figure(go.Bar(
        x=list(parts.values()), y=list(parts.keys()), orientation="h",
        marker_color=[COLORS[k] for k in parts],
        text=[f"{v:.2f}" for v in parts.values()], textposition="outside", cliponaxis=False))
    fig.update_layout(height=height, margin=dict(l=10, r=30, t=30, b=10),
                      title=title, xaxis_title="Expected points")
    return fig


def position_totals_figure(squad: pd.DataFrame, xi_ids: list, value_col: str = "xp_next") -> go.Figure:
    """Expected points per position for the starting XI."""
    xi = squad.loc[[i for i in xi_ids if i in squad.index]]
    sums = xi.groupby("position")[value_col].sum().reindex(POS_ORDER).fillna(0)
    counts = xi.groupby("position")[value_col].count().reindex(POS_ORDER).fillna(0).astype(int)
    fig = go.Figure(go.Bar(
        x=[f"{POS_LABEL[p]} ({counts[p]})" for p in POS_ORDER],
        y=sums.values, marker_color=[POS_COLOR[p] for p in POS_ORDER],
        text=[f"{v:.1f}" for v in sums.values], textposition="outside", cliponaxis=False))
    fig.update_layout(height=300, yaxis_title="Expected points (XI)",
                      margin=dict(l=10, r=10, t=10, b=10))
    return fig
