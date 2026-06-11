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

### 3. TV 2 API — already discovered ✅
The game's backend (`vm-fantasyapi-production.up.railway.app`) was reverse-
engineered on 2026-06-11; `scraper/endpoints.json` is filled in, the real
scoring ruleset is in `src/config.py` (`SCORING_VERIFIED = True`), and your
login session is saved in `playwright-profile/`.

If your session ever expires (sync returns HTTP 401), just re-run the login:
```powershell
python scraper/discover_endpoints.py   # log in, then close the window
```

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

## Current state

The repo ships with a **real sync** already done (2026-06-11): 1,249 players
with live prices and ownership, and your actual squad "Erlend er best"
(Wiegele, Kobel / Muñoz, Nuno Mendes, Fonville, Kimmich, Robinson /
W. Pierre, Bruno Fernandes, Yamal, L. Pierre, Wirtz / Haaland, Providence,
Suárez), bank 2.5M. Run `python scraper/sync.py` to refresh before each
deadline. Projections become odds-aware once you add the Odds API key (step 2);
until then they rank on price, position and venue heat only.

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
