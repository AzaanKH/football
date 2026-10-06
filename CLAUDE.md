# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Start/Sit**: a fantasy football app for weekly start/sit decisions (QB, RB,
WR; PPR scoring). Users pick the players they're choosing between; the app
names the decision ("Start X" / "Close call"), shows each player's projected
points with a calibrated 80% range, the matchup, byes, injury status, and how
fresh the data is.

The point estimate is **Sleeper's own weekly projection**, plus a learned
correction only where it measurably helps (currently QB). Our engineered
features did not beat Sleeper on their own; any model change must clear that
bar in `backend/evaluation.py` (see "Changing the model").

## Repository layout

The git repo is `football/` (GitHub `AzaanKH/football`, default branch
`main`). The parent folder `football-website/` is *not* the repo; it only
holds local tooling (`.mcp.json`, Playwright `node_modules`) and a CLAUDE.md
that imports this file.

```
football/
├── backend/                     Python 3.13, Flask, PostgreSQL
│   ├── app.py                   REST API (port 5001)
│   ├── weekly_predictor.py      Training + inference (WeeklyPredictor)
│   ├── metrics.py               start/sit accuracy, coverage, conformal helpers
│   ├── evaluation.py            Baseline comparison on held-out weeks
│   ├── model_store.py           Reloads the model when the pickle changes
│   ├── scheduler.py             APScheduler jobs (sync, features, retrain)
│   ├── setup_season.py          Incremental catch-up to the current season
│   ├── run_pipeline.py          Ad-hoc pipeline CLI
│   ├── data_pipeline/
│   │   ├── season.py            NFL calendar: current season/week, finished weeks
│   │   ├── sleeper_client.py    Players, stats, projections, NFL state
│   │   ├── espn_client.py       NFL schedule (scoreboard); maps WSH -> WAS
│   │   ├── orchestrator.py      sync_players/stats/projections/matchups -> DB
│   │   ├── player_ids.py        Name -> Sleeper ID matching (scraper fallback)
│   │   ├── scraper.py           Pro Football Reference (blocked: HTTP 403; off by default)
│   │   └── features/            Rolling averages, efficiency, consistency, trends, matchups
│   ├── init_db.sql              Schema for a fresh volume
│   ├── migrations/              001-004, applied manually to existing DBs
│   ├── models/                  weekly_predictor.pkl (+ local backups; gitignored)
│   └── tests/                   pytest: unit / integration / e2e
├── frontend/fantasy-football/   React 18 + Vite, Tailwind 4, shadcn/ui (Radix, cmdk)
│   ├── index.html, vite.config.mjs  Entry page; Vite + Vitest config
│   └── src/
│       ├── main.jsx             Entry point
│       ├── App.jsx              Page, state, request lifecycle
│       ├── lib/api.js           All HTTP calls (base URL: VITE_API_BASE)
│       ├── lib/predictionState.js  Request identity / stale-result logic
│       └── components/range-field.jsx  The yard-line range chart
└── .claude/skills/frontend-design/  Design skill (use for UI work)
```

Untracked local scripts may exist in `backend/` (e.g. `sync_historical.py`,
`visualize_data.py`); they are personal tools, not part of the app.

## Commands

Windows + Git Bash. The venv is `backend/venv` (call
`./venv/Scripts/python.exe` directly).

```bash
# Database (Docker Desktop must be running)
cd football/backend && docker-compose up -d
docker exec -it football-db psql -U postgres -d football_dev

# Catch up to the current NFL season (incremental; safe to re-run)
python setup_season.py --dry-run      # what's missing
python setup_season.py                # sync, features, retrain
#   --history N  --season YYYY  --weeks 1-10  --force  --sync  --train

# API and scheduler
python app.py                         # 127.0.0.1:5001 (FLASK_DEBUG/FLASK_HOST opt-in)
python scheduler.py start | run-now | status | dry-run

# Model
python weekly_predictor.py train      # measures on held-out weeks, refits on all, saves
python evaluation.py [qb rb wr]       # model vs 3/5-game avg vs Sleeper

# Tests
python -m pytest -m unit              # fast, no DB/network
python run_tests.py e2e               # real Sleeper + football_test DB

# Frontend
cd football/frontend/fantasy-football
npm start                             # Vite dev server, :3000
npm test                              # Vitest (jsdom)
npm run build                         # -> build/
npm run preview
```

Dependencies are pinned in `backend/requirements*.txt`
(`requirements_test.txt` includes the others).

## Architecture

### Data flow

1. **Sync** (`orchestrator`): Sleeper players, weekly stats and projections;
   ESPN schedule. Only players in the `players` table are stored (team
   defenses / IDP are skipped).
2. **Features** (`data_pipeline/features`): per player per week, computed only
   from games *before* that week, across season boundaries.
3. **Train** (`WeeklyPredictor.fit`): per position, picks the point strategy
   (`sleeper`, `sleeper+model`, or `model` when no projection), fits
   10th/90th-percentile models, and applies a split-conformal adjustment so
   the 80% range covers ~80%.
4. **Serve** (`app.py`): `/predict_week` returns every requested player as a
   prediction or an `unavailable` reason (`unknown_player`,
   `position_mismatch`, `bye`, `unsupported_position`, `features_unavailable`,
   `no_history`), with game context and data freshness.

### Season calendar

`data_pipeline/season.py` is the single source of truth: Sleeper's
`/state/nfl`, else a date estimate (season opens the Thursday after Labor
Day). A week is *finished* once its last kickoff (from the synced schedule)
plus 4 hours has passed. Never hard-code a season; use `current_context()`.

### Database

PostgreSQL in Docker (TimescaleDB image, but plain tables: no hypertables).
Key tables: `players`, `player_weekly_stats` (generated column `played`),
`player_projections`, `team_weekly_matchups`, `player_features`,
`ingestion_log`. `team_defense_stats` exists but is never populated.

### API endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /seasons` | Seasons with data, default, current NFL week |
| `GET /available_weeks?season=` | Weeks with computed features |
| `GET /players?position=&season=&week=&search=&limit=` | Search; with season+week, predictable players ranked by recent scoring |
| `POST /predict_week` | `{position, player_ids[], week, season}` -> predictions, unavailable, freshness, current_week |
| `GET /player_features/<id>` | Stored features |
| `GET /model_status` | DB/model availability, metrics |

## Rules and gotchas

**Data and tests**
- Never run destructive tests against `football_dev`. E2E tests use
  `football_test` (auto-created); a guard refuses any DB without "test" in its
  name or equal to `DB_NAME`.
- Features and training use only rows where `played` is true (any attempt,
  carry, target, reception or fantasy points). Inactive weeks are not games.
- In write loops, wrap each row in a `SAVEPOINT`: one failed statement aborts
  the whole PostgreSQL transaction. Count inserts vs updates with
  `RETURNING (xmax = 0)`, not `cursor.rowcount`.
- psycopg2 returns `Decimal`; convert (`_to_float`) before JSON or math.
- Feature recompute is an upsert: after changing feature logic, rows it no
  longer produces stay stale; delete them (back up first).
- Unit tests fit models single-threaded (`tests/conftest.py` sets
  `PREDICTOR_N_JOBS=1`, `OMP_NUM_THREADS=1`): on tiny data, thread start-up
  dominated and pushed tests past pytest's 60 s timeout on a busy machine.
- Back up before destructive data operations
  (`pg_dump -t <table> -Fc` into `backend/backups/`, gitignored).

**Model**
- Judge every model change with `evaluation.py` on identical held-out played
  games, against Sleeper's projection. Report start/sit accuracy, MAE and
  80% coverage, not training metrics. Real per-game error is ~4.5-6 points.
- Missing features stay NaN (models handle them); don't `fillna(0)`.
- `WeeklyPredictor.save` writes atomically; the running API reloads the
  pickle on change. Old pickles load with legacy defaults.

**API**
- Borrow DB connections with `with db_connection() as conn:` (pooled,
  request-scoped); use `predictor.with_connection(conn)`, never assign a
  connection to the shared predictor.
- Validate inputs with the `_int_param` / `_position_param` helpers; raise
  `BadRequest` for a 400. Don't return exception text in 500s.

**Frontend**
- All requests go through `src/lib/api.js`. Results are stored with the request
  that produced them; outdated requests are cancelled with `AbortController`.
- Design: turf palette in the `@theme` block of `src/index.css` (Tailwind 4,
  CSS-first config; no tailwind.config.js), validated with the dataviz
  palette checker. Scrimmage blue `#3D8EF0` is the only data color; pylon
  orange is only the primary button; flag yellow / out red are injury status
  only, always with an icon and label. Use the `frontend-design` skill for UI
  work.
- cmdk v1 always renders `data-disabled="false"`: style disabled items with
  `data-[disabled=true]:`, not `data-[disabled]:`.
- Tests use Vitest (config in `vite.config.mjs`: jsdom, `pool: 'threads'`
  because forked workers time out on this Windows machine, `mockReset`).
  Use `vi.mock`/`vi.fn` and user-event 14 (`const user = userEvent.setup()`,
  `await user.click(...)`). In jsdom, Radix returns focus to a trigger a tick
  late; `await` the next element (`findBy*`) before opening another popover.
- Files containing JSX must use `.jsx` (Vite requirement). Env vars must be
  prefixed `VITE_` (or `REACT_APP_`, kept for compatibility).

**Environment**
- In this Git Bash setup, heredocs containing apostrophes fail to parse; write
  multi-line scripts to a file instead.
- Prefix `docker exec`/`docker cp` with `MSYS_NO_PATHCONV=1` when passing
  container paths like `/tmp/...`.

## Changing the model

1. Add the feature or change, then run `python evaluation.py`.
2. Keep it only if the model beats Sleeper's projection on start/sit accuracy
   (and doesn't worsen MAE) on the held-out weeks.
3. Retrain (`python weekly_predictor.py train`) and note results in the PR.

## Known limitations

- Opponent-defense features are empty (`team_defense_stats` unpopulated);
  snap counts are not stored. Both are candidate features to test.
- Player team for opponent/bye is the *current* team (`players.team`), so
  traded players can show the wrong matchup for past weeks.
- Injury status is current-only; the UI shows it only for the current week.
- QB range coverage is ~76% vs the 80% target (calibration drift).
