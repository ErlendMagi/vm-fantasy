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


# ISO-2 (flagcdn) codes so we can use real flag IMAGES (emoji don't render on
# Windows/Chrome). gb-eng / gb-sct are flagcdn subdivision slugs.
ISO2 = {
    "Mexico": "mx", "South Africa": "za", "Czech Republic": "cz", "South Korea": "kr",
    "Canada": "ca", "Switzerland": "ch", "Qatar": "qa", "Bosnia & Herzegovina": "ba",
    "Brazil": "br", "Morocco": "ma", "Scotland": "gb-sct", "Haiti": "ht", "USA": "us",
    "Turkey": "tr", "Australia": "au", "Paraguay": "py", "Germany": "de", "Ecuador": "ec",
    "Ivory Coast": "ci", "Curacao": "cw", "Netherlands": "nl", "Japan": "jp", "Sweden": "se",
    "Tunisia": "tn", "Belgium": "be", "Egypt": "eg", "Iran": "ir", "New Zealand": "nz",
    "Spain": "es", "Uruguay": "uy", "Saudi Arabia": "sa", "Cape Verde": "cv", "France": "fr",
    "Norway": "no", "Senegal": "sn", "Iraq": "iq", "Argentina": "ar", "Austria": "at",
    "Algeria": "dz", "Jordan": "jo", "Portugal": "pt", "Colombia": "co", "Uzbekistan": "uz",
    "DR Congo": "cd", "England": "gb-eng", "Croatia": "hr", "Ghana": "gh", "Panama": "pa",
}
_CODE_ISO2 = {
    "SUI": "ch", "GER": "de", "ESP": "es", "FRA": "fr", "BRA": "br", "POR": "pt", "ARG": "ar",
    "ENG": "gb-eng", "NED": "nl", "BEL": "be", "CRO": "hr", "URU": "uy", "COL": "co", "MEX": "mx",
    "USA": "us", "CAN": "ca", "NOR": "no", "MAR": "ma", "SEN": "sn", "JPN": "jp", "AUT": "at",
    "SWE": "se", "RSA": "za", "CZE": "cz", "KOR": "kr", "QAT": "qa", "BIH": "ba", "SCO": "gb-sct",
    "HAI": "ht", "TUR": "tr", "AUS": "au", "PAR": "py", "ECU": "ec", "CIV": "ci", "CUW": "cw",
    "TUN": "tn", "EGY": "eg", "IRN": "ir", "NZL": "nz", "KSA": "sa", "CPV": "cv", "IRQ": "iq",
    "ALG": "dz", "JOR": "jo", "UZB": "uz", "COD": "cd", "GHA": "gh", "PAN": "pa",
}


def flag_img(team: str = "", code: str = "", h: int = 14) -> str:
    iso = ISO2.get(team) or _CODE_ISO2.get(code)
    if not iso:
        return ""
    return (f'<img src="https://flagcdn.com/h20/{iso}.png" '
            f'style="height:{h}px;border-radius:2px;vertical-align:middle" alt="{team}">')


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


PITCH_CSS = """
<style>
.vmpitch{background:linear-gradient(#1d8a46,#157f3d);border:2px solid rgba(255,255,255,.25);
 border-radius:14px;padding:14px 6px;display:flex;flex-direction:column;gap:6px}
.vmrow{display:flex;justify-content:space-around;align-items:flex-start;gap:4px}
.vmp{width:78px;text-align:center;color:#fff;font-size:11px;line-height:1.15}
.vmpic{position:relative;width:46px;height:46px;margin:0 auto 3px}
.vmpic img.face{width:46px;height:46px;border-radius:50%;object-fit:cover;border:2px solid #fff;background:#2d3436}
.vmpic .fl{position:absolute;bottom:-2px;right:-4px;border:1px solid #2d3436}
.vmp.cap .vmpic img.face{border-color:#e17055;box-shadow:0 0 0 2px #e17055}
.vmp .nm{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.vmp .meta{opacity:.92;font-size:10px}
.vmp .rk{display:inline-block;background:rgba(0,0,0,.45);border-radius:6px;padding:0 4px;font-size:10px}
.vmbar{height:5px;border-radius:3px;background:rgba(0,0,0,.35);margin:3px 2px 0;position:relative;overflow:hidden}
.vmbar>span{position:absolute;height:100%;background:#fdcb6e;border-radius:3px}
.vmbench{display:flex;justify-content:center;gap:10px;margin-top:8px;padding-top:8px;border-top:1px dashed rgba(255,255,255,.25)}
.vmcapbadge{position:absolute;top:-4px;left:-4px;background:#e17055;color:#fff;border-radius:50%;
 width:16px;height:16px;font-size:10px;font-weight:700;line-height:16px}
.vmp.vice .vmpic img.face{border-color:#0984e3;box-shadow:0 0 0 2px #0984e3}
.vmvicebadge{position:absolute;top:-4px;right:-4px;background:#0984e3;color:#fff;border-radius:50%;
 width:16px;height:16px;font-size:10px;font-weight:700;line-height:16px;z-index:2}
</style>
"""


def _initials_face(name: str) -> str:
    ini = "".join(p[0] for p in str(name).split()[:2]).upper()
    return (f'<div class="face" style="display:flex;align-items:center;justify-content:center;'
            f'font-weight:700;font-size:14px;color:#fff">{ini}</div>')


def _player_card(r, value_col, captain, rank=None, floor=None, ceil=None, vice=False):
    photo = r.get("photo")
    face = (f'<img class="face" src="{photo}" referrerpolicy="no-referrer" '
            f'onerror="this.style.display=\'none\'">' if isinstance(photo, str) and photo else "") \
        + (_initials_face(r["name"]) if not (isinstance(photo, str) and photo) else "")
    fl = flag_img(r.get("team", ""), r.get("team_code", ""), h=13)
    cap_badge = '<div class="vmcapbadge">C</div>' if captain else ""
    vice_badge = '<div class="vmvicebadge">V</div>' if vice else ""
    price = f"{r['price']:.1f}M" if r.get("price") == r.get("price") else ""
    rk = f'<span class="rk">#{rank}</span> ' if rank else ""
    rng = ""
    if floor is not None and ceil is not None and ceil > 0:
        lo = 100 * floor / ceil
        rng = (f'<div class="vmbar" title="floor {floor:.1f} → ceiling {ceil:.1f}">'
               f'<span style="left:{lo:.0f}%;width:{100 - lo:.0f}%"></span></div>')
    cls = "cap" if captain else ("vice" if vice else "")
    return (f'<div class="vmp {cls}">'
            f'<div class="vmpic">{cap_badge}{vice_badge}{face}<span class="fl">{fl}</span></div>'
            f'<div class="nm">{short_name(r["name"])}</div>'
            f'<div class="meta">{rk}{price}</div>'
            f'<div class="meta"><b>{r[value_col]:.1f}</b> pts</div>{rng}</div>')


def pitch_html(squad: pd.DataFrame, xi_ids: list, captain_id, value_col: str = "xp_next",
               bench_order: list | None = None, ranks: dict | None = None,
               floors: dict | None = None, ceils: dict | None = None, vice_id=None) -> str:
    """A full pitch as HTML: real player photos, flag badges, rank, price, xP
    and a floor→ceiling bar. Captain ringed orange (C), vice ringed blue (V)."""
    ranks, floors, ceils = ranks or {}, floors or {}, ceils or {}
    xi = squad.loc[[i for i in xi_ids if i in squad.index]]
    rows_html = []
    for pos in POS_ORDER:
        row = xi[xi["position"] == pos].sort_values(value_col, ascending=False)
        cards = "".join(_player_card(r, value_col, idx == captain_id, ranks.get(idx),
                                     floors.get(idx), ceils.get(idx), vice=idx == vice_id)
                        for idx, r in row.iterrows())
        if cards:
            rows_html.append(f'<div class="vmrow">{cards}</div>')
    bench_ids = bench_order or [i for i in squad.index if i not in set(xi_ids)]
    bench = squad.loc[[i for i in bench_ids if i in squad.index]]
    bench_html = "".join(_player_card(r, value_col, False, ranks.get(idx)) for idx, r in bench.iterrows())
    bench_block = f'<div class="vmbench">{bench_html}</div>' if bench_html else ""
    return PITCH_CSS + f'<div class="vmpitch">{"".join(rows_html)}{bench_block}</div>'


LIVE_CSS = """
<style>
@keyframes vlpulse{0%{opacity:1;transform:scale(1)}50%{opacity:.3;transform:scale(1.35)}100%{opacity:1;transform:scale(1)}}
@keyframes vlpop{0%{transform:translateY(7px) scale(.96);opacity:0}100%{transform:none;opacity:1}}
@keyframes vlshim{0%{background-position:-220px 0}100%{background-position:220px 0}}
.vl-wrap{background:linear-gradient(160deg,#1b2430,#11161d);border:1px solid #2a3340;border-radius:14px;
 padding:10px 14px 12px;margin:6px 0 12px}
.vl-live{display:inline-block;width:11px;height:11px;border-radius:50%;background:#d63031;
 box-shadow:0 0 9px #d63031;animation:vlpulse 1.1s infinite;margin-right:7px;vertical-align:middle}
.vl-h{font-size:1.02rem;font-weight:800;margin:2px 0 4px}
.vl-score{font-weight:800;color:#fdcb6e}
.vl-clock{font-size:.8rem;color:#9aa7b4;margin-left:6px}
.vl-row{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 2px}
.vl-card{flex:1 1 150px;min-width:148px;max-width:210px;background:#0e131a;border:1px solid #283143;
 border-radius:12px;padding:10px 10px 8px;animation:vlpop .45s ease both;position:relative;overflow:hidden}
.vl-card.gold{border-color:#fdcb6e;box-shadow:0 0 0 1px #fdcb6e55}
.vl-card.mine{border-color:#00b894;box-shadow:0 0 0 1px #00b89455}
.vl-rank{position:absolute;top:5px;left:8px;font-size:1.15rem}
.vl-face{width:56px;height:56px;border-radius:50%;overflow:hidden;margin:2px auto 6px;background:#1c2530;
 position:relative;border:2px solid #2a3340}
.vl-face img{width:100%;height:100%;object-fit:cover}
.vl-fl{position:absolute;bottom:-1px;right:-3px}
.vl-nm{font-weight:700;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:.9rem}
.vl-tm{text-align:center;font-size:.71rem;color:#9aa7b4;margin-bottom:5px}
.vl-big{text-align:center;font-size:1.4rem;font-weight:800;color:#fdcb6e;line-height:1.05}
.vl-lab{text-align:center;font-size:.62rem;color:#9aa7b4;letter-spacing:.05em;text-transform:uppercase}
.vl-bar{height:7px;border-radius:5px;background:rgba(255,255,255,.1);overflow:hidden;margin:5px 1px}
.vl-bar>span{display:block;height:100%;border-radius:5px;background:linear-gradient(90deg,#e17055,#fdcb6e);
 width:0;transition:width 1s cubic-bezier(.2,.8,.2,1)}
.vl-card.gold .vl-bar>span{background-image:linear-gradient(90deg,#fdcb6e,#ffeaa7,#fdcb6e);
 background-size:220px 100%;animation:vlshim 1.6s linear infinite}
.vl-sub{text-align:center;font-size:.72rem;color:#cbd5e1}
.vl-own{text-align:center;font-size:.72rem;margin-top:4px;font-weight:700}
.vl-stats{text-align:center;font-size:.72rem;color:#dfe6ee;margin-top:5px;border-top:1px solid #222b36;padding-top:5px}
.vl-pts{color:#00b894;font-weight:800}
</style>
"""


def trend_arrow(delta: float | None) -> str:
    """Green ▲ rising / red ▼ falling / grey ▬ flat — change in MVP odds since
    the last refresh. Empty when there's no prior reading yet."""
    if delta is None:
        return ""
    if delta > 0.012:
        return "<span style='color:#00b894'>▲</span>"
    if delta < -0.012:
        return "<span style='color:#d63031'>▼</span>"
    return "<span style='color:#9aa7b4'>▬</span>"


def live_card(row, probs, owner_html="", klass="", rank="", live_pts=None, stats=None, trend="") -> str:
    """One animated card: photo + flag, P(MVP) headline (with a trend arrow) and
    an animated bar, 2nd/3rd odds, owner tag and the live stats that actually
    decide MVP (rating, goals, assists, shots)."""
    photo = row.get("photo")
    img = (f'<img src="{photo}" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">'
           if isinstance(photo, str) and photo else _initials_face(row["name"]))
    fl = flag_img(row.get("team", ""), row.get("team_code", ""), h=15)
    p1, p2, p3 = probs.get("p1", 0.0), probs.get("p2", 0.0), probs.get("p3", 0.0)
    bits = []
    if stats:
        if stats.get("rating"):
            bits.append(f"⭐{stats['rating']:.1f}")
        if stats.get("goals"):
            bits.append(f"⚽{int(stats['goals'])}")
        if stats.get("assists"):
            bits.append(f"🅰{int(stats['assists'])}")
        if stats.get("shots"):
            bits.append(f"{int(stats['shots'])}sh")
        if stats.get("xg") is not None:
            bits.append(f"{stats['xg']:.1f}xG")
        if stats.get("is_potm"):
            bits.append("🏅POTM")
    if live_pts is not None:
        bits.append(f"<span class='vl-pts'>{live_pts:g} pts</span>")
    statline = f'<div class="vl-stats">{" · ".join(bits)}</div>' if bits else ""
    rk = f'<div class="vl-rank">{rank}</div>' if rank else ""
    return (f'<div class="vl-card {klass}">{rk}'
            f'<div class="vl-face">{img}<span class="vl-fl">{fl}</span></div>'
            f'<div class="vl-nm">{short_name(row["name"])}</div>'
            f'<div class="vl-tm">{row.get("team", "")} · {row.get("position", "")}</div>'
            f'<div class="vl-big">{p1 * 100:.0f}% {trend}</div><div class="vl-lab">MVP odds</div>'
            f'<div class="vl-bar"><span style="width:{min(p1 * 100, 100):.0f}%"></span></div>'
            f'<div class="vl-sub">2nd {p2 * 100:.0f}% · 3rd {p3 * 100:.0f}%</div>'
            f'{owner_html}{statline}</div>')


def _mini_player(r, tone):
    photo = r.get("photo")
    face = (f'<img class="face" src="{photo}" referrerpolicy="no-referrer" onerror="this.style.opacity=0">'
            if isinstance(photo, str) and photo else _initials_face(r["name"]))
    fl = flag_img(r.get("team", ""), r.get("team_code", ""), h=12)
    return (f'<div class="tcp {tone}"><div class="vmpic" style="width:42px;height:42px">{face}'
            f'<span class="fl">{fl}</span></div>'
            f'<div class="tnm">{short_name(r["name"])}</div>'
            f'<div class="tmeta">{r["position"]} · {r["price"]:.1f}M</div>'
            f'<div class="tmeta"><b>{r["xp_next"]:.1f}</b> xP · #{int(r.get("pos_rank", 0))}</div></div>')


def transfer_card_html(out_row, in_row, gain, reasons, hit=0) -> str:
    chips = "".join(f'<span class="chip {"up" if up else "dn"}">{txt}</span>' for txt, up in reasons[:5]) \
        or '<span class="chip neutral">marginal upgrade</span>'
    hit_txt = f' · <span style="color:#e17055">−{hit} hit</span>' if hit else ""
    css = """
<style>
.tcard{background:#11161c;border:1px solid #2b333d;border-radius:14px;padding:12px 14px;margin-bottom:10px}
.trow{display:flex;align-items:center;gap:10px}
.tcp{flex:1;text-align:center;color:#e6edf3;font-size:11px}
.tcp.face img.face,.tcp .face{width:42px;height:42px;border-radius:50%;object-fit:cover;border:2px solid #3a4450;background:#222;margin:0 auto}
.tcp.out{opacity:.75}.tcp.in .vmpic .face,.tcp.in img.face{border-color:#00b894}
.tcp .tnm{font-weight:700;margin-top:3px}.tcp .tmeta{font-size:10px;opacity:.85}
.tarrow{font-size:22px;color:#00b894;flex:0 0 auto}
.tgain{margin-left:auto;text-align:right;flex:0 0 auto}
.tgain b{font-size:20px;color:#00b894}
.tchips{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px}
.chip{font-size:10.5px;padding:2px 8px;border-radius:20px;font-weight:600}
.chip.up{background:rgba(0,184,148,.18);color:#3ddc97;border:1px solid #145c45}
.chip.dn{background:rgba(214,48,49,.16);color:#ff8a8a;border:1px solid #5c1d1d}
.chip.neutral{background:#222a33;color:#9aa7b4}
.vmpic{position:relative}.vmpic .fl{position:absolute;bottom:-2px;right:-4px}
</style>"""
    return css + (f'<div class="tcard"><div class="trow">'
                  f'{_mini_player(out_row, "out")}<div class="tarrow">➜</div>{_mini_player(in_row, "in")}'
                  f'<div class="tgain"><b>+{gain:.1f}</b><br><span style="font-size:10px;color:#9aa7b4">'
                  f'pts/cup{hit_txt}</span></div></div>'
                  f'<div class="tchips">{chips}</div></div>')


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
