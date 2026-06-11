# VM Fantasy Companion — World Cup 2026

Personal dashboard for TV 2's VM Fantasy: tracks your team vs. the most-owned
"template" team, projects player points from **betting odds adjusted for heat**,
and suggests transfers each round (elimination-risk aware).

**How it works:** a sync job pulls your TV 2 squad/players + betting odds and
commits the JSON to this repo; the deployed Streamlit app reads the repo and
recomputes projections. The sync can run **two ways**:

- **Locally** (`python scraper/sync.py`) using your saved browser login, or
- **Fully in the cloud, computer off** — GitHub Actions runs the sync on a
  schedule using your TV 2 token + odds key (see "Hands-off automation" below).
  TV 2's backend is a plain REST API and your token lasts 120 days, so no
  browser is needed on the server.

```
[GitHub Actions, every 6h]  sync ──> data/*.json ──commit──> [GitHub] ──auto deploy──> [Streamlit Cloud]
   TV 2 REST API (bearer token)                                              │
   The Odds API (free key)                                            phone / browser
   Open-Meteo weather is fetched by the app itself (free, keyless)
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

### 5. Hands-off automation (runs with your computer OFF)
The sync can run entirely on GitHub's servers (`.github/workflows/sync.yml`,
every 6 hours). Add two repository secrets so it can log in to TV 2 and the
odds API — **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name    | Value |
|----------------|-------|
| `TV2_TOKEN`    | your TV 2 bearer token (the JWT — valid ~120 days, re-paste if it expires) |
| `ODDS_API_KEY` | your the-odds-api.com key |

To grab a fresh `TV2_TOKEN`: open vmfantasy.tv2.no logged in → DevTools (F12) →
Application → Local Storage → copy the JWT value; or run
`python scraper/print_token.py` locally. Once the secrets are set the workflow
self-runs; the Actions tab shows each run. This is the only part that needs
your accounts — I can't create GitHub/Streamlit logins for you.

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

## The model's optimal team & applying it

The **⭐ Optimal Team** page shows the squad that maximises the odds+heat model's
projected points within the 100M budget (2 GK / 5 DEF / 5 MID / 3 FWD, ≤3 per
country), plus the exact transfers to get there from your team. It ignores
ownership, so it is deliberately a high-variance, low-owned, differential team —
a reasonable way to *win* a small money league, but it swings round to round.

To push that team onto your TV 2 account automatically:
```powershell
python scraper/apply_team.py            # DRY RUN: prints the team, sends nothing
python scraper/apply_team.py --confirm  # actually sets it (verifies afterwards)
```
The write uses the game's own `PUT /squad/update`. One field (`formation`) isn't
verified against the game, so the script aborts cleanly if the API rejects it
rather than leaving a half-applied squad — the first `--confirm` is worth doing
while you can watch the result. Transfers are free & unlimited until round 1
locks, so applying it pre-deadline costs nothing and is reversible.

## Current state

The repo ships with a **real, odds-aware sync** (2026-06-11): 1,249 players with
live prices/ownership, your actual squad "Erlend er best" (bank 2.5M), live
match + outright odds, and the verified TV 2 scoring ruleset. The Optimal Team
page is live. Refresh anytime with `python scraper/sync.py`, or let the GitHub
Action do it.

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
