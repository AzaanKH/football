# Fantasy Football Predictor

A fantasy football prediction application for weekly start/sit decisions. Point estimates are anchored on Sleeper's weekly projections (with a learned correction only where it measurably helps); the app adds calibrated 80% ranges, explanations, and a comparison UI. Every modeling choice is checked against baselines with `backend/evaluation.py`.

## Features

- **Position-based predictions** for Quarterbacks, Running Backs, and Wide Receivers
- **Position-specific models** so QB/RB/WR data stays separated
- **Confidence intervals** for weekly predictions
- **Early-season aware features** with reliability flags and prior-season blending
- **Weekly matchup context** sourced from ESPN scoreboard data
- **Searchable player dropdown** in the frontend
- **Local-first workflow** with Docker Desktop + TimescaleDB/Postgres

## Screenshots

### Homepage

Select your prediction week and position to get started.

![Homepage](docs/images/homepage.png)

### Player Search

Search through 800+ players with instant filtering.

![Player Search](docs/images/player-search.png)

### Prediction Results

Compare players with predicted points, confidence ranges, and 3-game averages.

![Predictions](docs/images/predictions-3players.png)

## Architecture

- **Frontend**: React + shadcn/ui in `frontend/fantasy-football/`
- **API**: Flask backend in `backend/app.py`
- **Database**: PostgreSQL in Docker Desktop (TimescaleDB image, plain tables)
- **Data Pipeline**: Sleeper + ESPN integrations in `backend/data_pipeline/`
- **Models**: Position-specific weekly predictor in `backend/weekly_predictor.py`; evaluation in `backend/evaluation.py`

## Backend Overview

The backend serves a single weekly prediction system built on Postgres feature engineering, Sleeper projections, and position-specific models.

- The current weekly prediction API is `POST /predict_week`
- The newer pipeline stores player data, stats, projections, features, and matchup context in Postgres
- Feature engineering now includes reliability-aware early-season handling
- Training now uses temporal splits and supports walk-forward backtesting

## Quick Start

### Prerequisites

- Python 3.11+ (the pinned NumPy and scikit-learn require it; CI uses 3.13)
- Node.js 18+ (CI uses 22.12)
- Docker Desktop

### 1. Start the database

```bash
cd backend
docker-compose up -d
```

### 2. Setup the backend

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on Mac/Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements_data_pipeline.txt
```

### 3. Apply migrations if your database already existed

If your `football_dev` database was created before the newer feature and matchup changes, apply the migrations manually.

PowerShell:

```powershell
Get-Content .\migrations\002_add_matchups_and_reliability_features.sql | docker exec -i football-db psql -U postgres -d football_dev
Get-Content .\migrations\003_expand_player_status_columns.sql | docker exec -i football-db psql -U postgres -d football_dev
Get-Content .\migrations\004_add_played_flag.sql | docker exec -i football-db psql -U postgres -d football_dev
```

After applying `004`, recompute features (`python run_pipeline.py compute-all-features`)
and retrain: features and training now ignore weeks a player didn't play.

### 4. Catch up to the current season

```bash
cd backend
python setup_season.py --dry-run   # show what's missing
python setup_season.py             # sync it, compute features, retrain
```

`setup_season.py` reads the current NFL season and week from Sleeper (falling
back to the calendar) and syncs only what is missing for the current season
plus three previous ones: schedule, stats for finished weeks, Sleeper
projections, then features and retraining. Re-run it any time; it is
incremental. Options: `--history N`, `--season YYYY`, `--weeks 1-10`,
`--force`, `--sync`, `--train`.

### 5. Start the backend API

```bash
cd backend
python app.py
```

### 6. Start the frontend

```bash
cd frontend/fantasy-football
npm install
npm start
```

The frontend calls `http://localhost:5001` by default. To point it elsewhere,
set `REACT_APP_API_BASE` (e.g. in `frontend/fantasy-football/.env.local`).
The season and weeks shown come from the data the backend has.

Frontend tests: `CI=true npm test`.

### 7. Open the app

Navigate to <http://localhost:3000>

## Local Workflow

This project is designed to run fully locally.

- Docker Desktop runs PostgreSQL + TimescaleDB
- the Flask backend runs locally
- the React frontend runs locally
- `scheduler.py` can be run locally to automate weekly sync/training

You do not need to host the app for the scheduler to work.

## Scheduler

The scheduler in `backend/scheduler.py` supports two local modes:

### Manual run

```bash
cd backend
python scheduler.py run-now
```

This runs the jobs immediately and exits.

### Long-running local scheduler

```bash
cd backend
python scheduler.py start
```

This starts a local long-lived Python process that waits for scheduled job times. If you close the terminal, the scheduler stops.

### Useful scheduler commands

```bash
python scheduler.py dry-run
python scheduler.py run-now
python scheduler.py run-now --sync
python scheduler.py run-now --features
python scheduler.py run-now --train
python scheduler.py status
```

`python scheduler.py start` requires `APScheduler` to be installed in the Python environment you are using.

## Season Calendar

Nothing is tied to a fixed season. `backend/data_pipeline/season.py` resolves
where the NFL calendar is right now (Sleeper's state, or the date if Sleeper
is unreachable: the regular season opens the Thursday after Labor Day):

- `completed_weeks`: weeks with final stats. The current week counts as
  finished once its last game is over (last kickoff in the synced schedule
  plus four hours), so it flips Monday night, not on a fixed weekday.
- `prediction_week`: the week being predicted; `None` in the offseason.

The scheduler, `setup_season.py`, the API's default season and the predictor
CLI all use it. Set `DEFAULT_SEASON` only to pin the API to a season.

## Offseason Behavior

During the NFL offseason (no prediction week):

- player sync still runs
- stats sync is skipped cleanly
- matchup/projection sync is skipped cleanly
- feature computation is skipped cleanly
- retraining can still run on historical data

This means `python scheduler.py run-now` is safe to run locally year-round, even when there is no live NFL week to ingest.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/players` | GET | Get players by position |
| `/predict_week` | POST | Get weekly predictions with confidence intervals |
| `/available_weeks` | GET | Get weeks with computed features |
| `/model_status` | GET | Check model availability |

### Example prediction request

```bash
curl -X POST http://localhost:5001/predict_week \
  -H "Content-Type: application/json" \
  -d '{
    "position": "rb",
    "player_ids": ["4034", "6794"],
    "week": 18,
    "season": 2025
  }'
```

## Predictive Features

- **Rolling Averages**: Fantasy points, rushing/receiving/passing yards over 3, 5, and 10 game views
- **Reliability Features**: Games played, full-window flags, previous-season availability, blended baseline
- **Efficiency**: Yards per carry, yards per target, catch rate, touchdown efficiency
- **Consistency**: Standard deviation, boom rate, bust rate, floor score
- **Trends**: Short-term fantasy point and usage slopes
- **Matchup Context**: Opponent, home/away, rest days, opponent defensive context when available

## Model Training

Per position (`qb`, `rb`, `wr`), the weekly predictor:

- **Point estimate**: Sleeper's pre-game PPR projection. A shallow correction
  model (actual − projection) is kept only if it lowers MAE without hurting
  start/sit accuracy on the latest calibration weeks; otherwise Sleeper's
  projection is used as-is. Players without a projection fall back to a
  standalone XGBoost model on the engineered features.
- **80% range**: 10th/90th percentile models, conformally calibrated
  (CQR) on the latest weeks so the range actually covers ~80% of outcomes.
- **Training**: temporal splits only; measures on held-out weeks, then refits
  on all weeks before saving to `backend/models/weekly_predictor.pkl`.
- Targets and features use only games the player actually played (see
  migration `004`).

### Evaluation (held-out 2025 weeks 5-18, played games)

| Position | Method | MAE | Start/sit accuracy | 80% range coverage |
|----------|--------|-----|--------------------|--------------------|
| QB | 3-game average | 6.82 | 59.7% | |
| QB | Previous standalone model | 6.35 | 61.2% | 70.5% |
| QB | **Current** | **5.83** | **62.2%** | 76.4% |
| RB | 3-game average | 5.35 | 68.3% | |
| RB | Previous standalone model | 5.02 | 70.4% | 75.0% |
| RB | **Current** | **4.69** | **74.3%** | 77.8% |
| WR | 3-game average | 5.05 | 65.6% | |
| WR | Previous standalone model | 4.74 | 67.9% | 74.1% |
| WR | **Current** | **4.54** | **70.9%** | 81.0% |

Start/sit accuracy: among startable players (Sleeper projection >= 5) in the
same week and position, the share of pairs whose actual scores differ by at
least 3 points where the higher scorer was ranked first. Engineered features
did not measurably beat Sleeper's projection on their own; see
`backend/evaluation.py` to test new features against this bar:

```bash
cd backend
python evaluation.py          # all positions
python evaluation.py rb wr    # selected positions
```

## Development

### Run unit tests

```bash
cd backend
python run_tests.py unit
```

### Run end-to-end tests

E2E tests truncate tables, so they run against a dedicated `football_test`
database (created and initialized from `init_db.sql` automatically). They refuse
to run against `football_dev` or any database whose name lacks `test`.

```bash
cd backend
docker-compose up -d
python run_tests.py e2e
# Custom target: TEST_DATABASE_URL=postgresql://user:pass@host:5432/my_test_db
```

### Backend server options

`python app.py` binds to `127.0.0.1` with the debugger off. Opt in with
`FLASK_DEBUG=1` (never on a network-reachable host) or `FLASK_HOST=0.0.0.0`.

The API reloads `models/weekly_predictor.pkl` automatically when it changes
(e.g. after the scheduler's Tuesday retrain), so no restart is needed. The
database is checked per request: if PostgreSQL is down, endpoints return 503
and recover on their own once it is back.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MODEL_PATH` | `models/weekly_predictor.pkl` | Model file to serve |
| `DEFAULT_SEASON` | `2025` | Season when a request omits it |
| `DB_POOL_MAX` | `10` | Max pooled database connections |
| `DB_POOL_WAIT_SECONDS` | `10` | How long a request waits for a free connection before a 503 |

### Backtest a position model

```bash
cd backend
python weekly_predictor.py backtest qb
```

### Retrain the weekly models

```bash
cd backend
python weekly_predictor.py train
```

### Manual pipeline commands

```bash
cd backend
python run_pipeline.py sync-players
python run_pipeline.py sync-stats 2025 18
python run_pipeline.py compute-features 2025 18
python scheduler.py run-now
```

## Project Structure

```text
football/
├── backend/
│   ├── app.py
│   ├── weekly_predictor.py
│   ├── scheduler.py
│   ├── setup_season.py
│   ├── migrations/
│   ├── data_pipeline/
│   │   ├── sleeper_client.py
│   │   ├── espn_client.py
│   │   └── features/
│   └── tests/
├── frontend/fantasy-football/
└── docs/images/
```

## Tech Stack

### Backend

- Python
- Flask + Flask-CORS
- PostgreSQL + TimescaleDB
- XGBoost
- pandas / numpy / scikit-learn
- APScheduler

### Frontend

- React 18
- Tailwind CSS
- shadcn/ui
- Axios

## License

MIT
