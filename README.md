# VM Fantasy Companion — World Cup 2026

Personal dashboard for TV 2's VM Fantasy: tracks your team vs. the most-owned
"template" team, projects player points from **betting odds adjusted for heat**,
and suggests transfers each round (elimination-risk aware).

**How it works:** a sync script on your PC scrapes vmfantasy.tv2.no with your
logged-in browser session + pulls odds, commits the JSON to this repo and
pushes. The deployed Streamlit app just reads the repo — it holds no
credentials and spends no API credits.

```
[your PC]  sync.py ──> data/*.json ──git push──> [GitHub] ──auto deploy──> [Streamlit Cloud]
            │  TV 2 scrape (Playwright, your login)                            │
            │  The Odds API (free key, ~2 credits/day)                  phone / browser
            └─ Open-Meteo weather is fetched by the app itself (free, keyless)
```

## One-time setup (~20 min)

### 1. Local Python deps
```powershell
cd C:\Users\erlen\vm-fantasy
pip install -r requirements.txt
pip install -r scraper/requirements-local.txt
playwright install chromium
```

### 2. Odds API key (free)
Sign up at https://the-odds-api.com (free tier, 500 credits/month — daily sync
uses ~60/month). Create a file `.env` in the repo root:
```
ODDS_API_KEY=your-key-here
```
Then fetch the first snapshot (uses 3 credits):
```powershell
python scraper/refresh_odds.py --outrights
```

### 3. Discover TV 2's internal API (needs you at the keyboard once)
```powershell
python scraper/discover_endpoints.py
```
A browser opens on vmfantasy.tv2.no. **Log in**, then click through: your squad,
the player list, one player's point details, the transfers page. Press Enter in
the terminal when done. Open the `scrape_dumps/` folder, find the JSON responses
holding (a) all players with prices/ownership, (b) your squad, (c) fixtures —
and paste their URLs into `scraper/endpoints.json`.

Also check the dumps for the game's **scoring rules** and update
`src/config.py` (`SCORING`, `SQUAD_SHAPE`, `MAX_PER_TEAM`), then set
`SCORING_VERIFIED = True`.

> If a payload doesn't normalize, run `python scraper/sync.py --dry-run` and
> adjust `FIELD_MAP` / `normalize_my_team` in `scraper/tv2_client.py` to match.

### 4. GitHub + Streamlit Cloud (free)
1. Create a **private** repo on https://github.com/new (e.g. `vm-fantasy`), then:
   ```powershell
   git remote add origin https://github.com/<you>/vm-fantasy.git
   git push -u origin master
   ```
2. Go to https://share.streamlit.io → New app → pick the repo, main file
   `Home.py` → Deploy. Open the app URL on your phone and bookmark it.

## During the tournament

**Daily (or at least before every transfer deadline):**
```powershell
python scraper/sync.py
```
That's it — scrapes TV 2, refreshes odds, validates, commits, pushes; the site
updates itself within a minute. Add `--outrights` once before the knockouts.
If validation fails it commits **nothing** and the site keeps the last good data.

**If the scraper breaks mid-tournament** (TV 2 changed something):
`python scraper/manual_entry.py` rebuilds your team by hand; projections and
transfer suggestions keep working from odds + weather alone. Fixtures fall back
to `data/static/fixtures_fallback.json` (refresh it with
`python scraper/build_static.py` after re-downloading the openfootball JSON).

## Current state / what's seeded

The repo ships with **seed data**: your actual 15-man squad (Rangel, Vargas,
Kimmich, Brown, Meunier, Tagliafico, Douglas, Raphinha, Bruno Fernandes,
De Bruyne, James, Baena, Mbappé, Oyarzabal (C), Jiménez) plus ~45 star players
with *estimated* prices and **no ownership data**. The app works in this mode
(flagged with a yellow banner) but the template-team comparison needs the first
real sync.

## Model in one paragraph

Match odds → de-vigged 1X2 + over/under → Poisson expected goals per team →
distributed to players by position/price/form/start-probability → multiplied by
a heat factor (apparent temperature at the venue from Open-Meteo vs. the
player's national-team climate class: −3%/°C above 28°C for cool-climate teams,
−1.5%/°C for warm; zero penalty in the A/C stadiums in Dallas, Houston and
Atlanta) → clean-sheet odds for defenders → summed over a 2-round horizon
weighted by P(team still alive) from a 10,000-run group-stage Monte Carlo.
Transfers: exhaustive single+double swap search under budget/squad rules; a
−4 hit is only suggested when it beats the best free plan by >6 projected pts.
Heat evidence: Chmura et al. 2017; PMC11436032.

## Tests
```powershell
python -m pytest tests -q       # unit tests (no network)
python tests/smoke_pages.py     # renders all pages headlessly (live weather)
```
