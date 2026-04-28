# Fantasy Football Predictor

A machine learning-powered fantasy football prediction application for weekly start/sit decisions. The current backend uses separate XGBoost models by position and trains on historical NFL data with rolling features, reliability flags, and matchup context.

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
- **Database**: PostgreSQL + TimescaleDB in Docker Desktop
- **Data Pipeline**: Sleeper + ESPN integrations in `backend/data_pipeline/`
- **Models**: Position-specific XGBoost weekly predictor in `backend/weekly_predictor.py`

## Backend Overview

The current backend has a newer weekly prediction system alongside older legacy model code.

- The current weekly prediction API is `POST /predict_week`
- The newer pipeline stores player data, stats, projections, features, and matchup context in Postgres
- Feature engineering now includes reliability-aware early-season handling
- Training now uses temporal splits and supports walk-forward backtesting

## Quick Start

### Prerequisites

- Python 3.8+
- Node.js 16+
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
```

### 4. Run initial setup

```bash
cd backend
python setup_2025_season.py
```

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

## Offseason Behavior

The weekly scheduler now distinguishes between:

- `completed_week`: the latest finalized stat week
- `prediction_week`: the upcoming week being prepared for prediction

During the NFL offseason, Sleeper may return `week = 0`. In that case:

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

The current weekly predictor:

- trains separate models for `qb`, `rb`, and `wr`
- uses temporal train/test splitting instead of random row splitting
- supports walk-forward backtesting
- saves trained artifacts to `backend/models/weekly_predictor.pkl`

## Development

### Run unit tests

```bash
cd backend
python run_tests.py unit
```

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
│   ├── setup_2025_season.py
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
