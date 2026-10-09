#!/usr/bin/env python3
"""
Season Setup / Catch-up

Brings the database up to date with the real NFL calendar: works out the
current season and week (Sleeper, falling back to the date), then syncs only
what is missing for the current season plus --history previous seasons:

  1. players (always)
  2. schedule (team_weekly_matchups) for every week of each season
  3. weekly stats for finished weeks
  4. Sleeper projections for finished weeks and the week being predicted
  5. features from the earliest changed week onward (rolling windows cross
     season boundaries, so later weeks are recomputed too)
  6. model retraining, if any features changed

Safe to re-run any time; already-synced weeks are skipped. The current
season's last two finished weeks are always re-synced for stat corrections.

Usage:
    python setup_season.py                  # catch up current + 3 past seasons
    python setup_season.py --dry-run        # show the plan only
    python setup_season.py --history 1      # current + 1 past season
    python setup_season.py --season 2025    # one season only
    python setup_season.py --weeks 1-10     # limit weeks (with --season)
    python setup_season.py --force          # re-sync everything in range
    python setup_season.py --sync           # sync data, skip training
    python setup_season.py --train          # retrain only
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REGULAR_SEASON_WEEKS = 18
DEFAULT_HISTORY = 3
MODEL_PATH = 'models/weekly_predictor.pkl'


def print_banner(text: str) -> None:
    print("\n" + "=" * 60)
    print(f" {text}")
    print("=" * 60)


def get_db_connection():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=os.environ.get('DB_PORT', 5432),
        database=os.environ.get('DB_NAME', 'football_dev'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASSWORD', 'postgres'),
    )


def ensure_database() -> bool:
    """Connect to PostgreSQL, starting the Docker container if needed."""
    try:
        get_db_connection().close()
        return True
    except Exception:
        logger.info("Database not reachable; starting it with docker-compose up -d")
    try:
        subprocess.run(['docker-compose', 'up', '-d'], check=True, timeout=120,
                       cwd=os.path.dirname(os.path.abspath(__file__)))
    except Exception as e:
        logger.error(f"Could not start the database: {e}")
        return False
    for _ in range(30):
        try:
            get_db_connection().close()
            return True
        except Exception:
            time.sleep(2)
    logger.error("Database did not become ready")
    return False


def parse_weeks(spec: str) -> List[int]:
    """'1-10' or '5,6,7' -> week list."""
    if '-' in spec:
        start, end = map(int, spec.split('-'))
        return list(range(start, end + 1))
    return [int(w) for w in spec.split(',')]


def _weeks_present(conn, table: str, season: int, extra: str = '') -> Set[int]:
    cursor = conn.cursor()
    cursor.execute(f"SELECT DISTINCT week FROM {table} WHERE season = %s {extra}", (season,))
    return {row[0] for row in cursor.fetchall()}


def build_plan(context, conn, seasons: List[int], weeks_filter: Optional[List[int]],
               force: bool) -> Dict[int, Dict[str, List[int]]]:
    """
    Per season: which weeks need schedule, stats and projections synced.

    Finished weeks: all 18 for past seasons; the context's completed weeks
    for the current one. The prediction week always gets fresh projections.
    """
    plan = {}
    for season in seasons:
        if season < context.season:
            finished = list(range(1, REGULAR_SEASON_WEEKS + 1))
        elif season == context.season:
            finished = list(context.completed_weeks)
        else:
            finished = []
        all_weeks = list(range(1, REGULAR_SEASON_WEEKS + 1))
        if weeks_filter:
            finished = [w for w in finished if w in weeks_filter]
            all_weeks = [w for w in all_weeks if w in weeks_filter]

        have_schedule = set() if force else _weeks_present(conn, 'team_weekly_matchups', season)
        have_stats = set() if force else _weeks_present(conn, 'player_weekly_stats', season)
        have_projections = set() if force else _weeks_present(
            conn, 'player_projections', season, "AND source = 'sleeper'")

        refresh = set(finished[-2:]) if season == context.season else set()
        stats = [w for w in finished if w not in have_stats or w in refresh]

        projection_weeks = [w for w in finished if w not in have_projections]
        prediction_week = context.prediction_week if season == context.season else None
        if prediction_week and (not weeks_filter or prediction_week in weeks_filter):
            projection_weeks.append(prediction_week)

        plan[season] = {
            'schedule': [w for w in all_weeks if w not in have_schedule],
            'stats': stats,
            'projections': sorted(set(projection_weeks)),
            'prediction_week': [prediction_week] if prediction_week else [],
        }
    return plan


def feature_weeks(context, plan, seasons: List[int]) -> List[Tuple[int, int]]:
    """
    (season, week) pairs whose features need computing: every finished week
    from the earliest changed one onward, plus the prediction week.
    """
    changed = [(s, w) for s in seasons for w in plan[s]['stats']]
    pairs = []
    if changed:
        start = min(changed)
        for season in seasons:
            finished = (list(range(1, REGULAR_SEASON_WEEKS + 1)) if season < context.season
                        else list(context.completed_weeks) if season == context.season else [])
            pairs += [(season, w) for w in finished if (season, w) >= start]
    for season in seasons:
        pairs += [(season, w) for w in plan[season]['prediction_week']]
    return sorted(set(pairs))


def run_sync(plan) -> Dict[str, int]:
    from data_pipeline import DataOrchestrator

    totals = {'schedule': 0, 'stats': 0, 'projections': 0, 'failed': 0}
    with DataOrchestrator() as orchestrator:
        print_banner("Players")
        result = orchestrator.sync_players()
        logger.info(f"Players: {result['processed']} processed")

        for season, steps in plan.items():
            for step, sync in (('schedule', orchestrator.sync_matchups),
                               ('stats', orchestrator.sync_weekly_stats),
                               ('projections', orchestrator.sync_projections)):
                if not steps[step]:
                    continue
                print_banner(f"{season} {step}: weeks {steps[step]}")
                for week in steps[step]:
                    try:
                        sync(season, week)
                        totals[step] += 1
                    except Exception as e:
                        # Future weeks often have no projections/schedule yet
                        logger.warning(f"{season} week {week} {step} failed: {e}")
                        totals['failed'] += 1
    return totals


def run_features(pairs: List[Tuple[int, int]]) -> int:
    from data_pipeline.features import FeatureEngineer

    print_banner(f"Features: {len(pairs)} weeks")
    conn = get_db_connection()
    computed = 0
    try:
        with FeatureEngineer(conn) as engineer:
            for season, week in pairs:
                try:
                    engineer.compute_all_features(season, week, positions=['QB', 'RB', 'WR', 'TE'])
                    computed += 1
                except Exception as e:
                    conn.rollback()
                    logger.warning(f"Features for {season} week {week} failed: {e}")
    finally:
        conn.close()
    return computed


def run_training() -> Optional[Dict]:
    from weekly_predictor import WeeklyPredictor

    print_banner("Training")
    conn = get_db_connection()
    try:
        predictor = WeeklyPredictor(db_connection=conn)
        metrics = predictor.train_all_positions()
        if not metrics:
            logger.error("No position trained successfully")
            return None
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        predictor.save(MODEL_PATH)
        for position, m in metrics.items():
            logger.info(f"{position.upper()}: MAE={m['mae']:.2f}, strategy={m['point_strategy']}")
        return metrics
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Bring NFL data up to date with the current season')
    parser.add_argument('--season', type=int, help='Only this season')
    parser.add_argument('--history', type=int, default=DEFAULT_HISTORY,
                        help=f'Previous seasons to include (default {DEFAULT_HISTORY})')
    parser.add_argument('--weeks', type=str, help='Limit weeks, e.g. "1-10" or "5,6,7"')
    parser.add_argument('--force', action='store_true', help='Re-sync weeks that already have data')
    parser.add_argument('--dry-run', action='store_true', help='Print the plan without syncing')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--sync', action='store_true', help='Sync data only (no training)')
    mode.add_argument('--train', action='store_true', help='Retrain only')
    args = parser.parse_args(argv)

    if not ensure_database():
        return 1

    from data_pipeline.season import current_context, schedule_week_end

    conn = get_db_connection()
    try:
        context = current_context(week_end_lookup=schedule_week_end(conn))
        seasons = [args.season] if args.season else context.history_seasons(args.history)
        weeks_filter = parse_weeks(args.weeks) if args.weeks else None
        plan = build_plan(context, conn, seasons, weeks_filter, args.force)
    finally:
        conn.close()
    pairs = feature_weeks(context, plan, seasons)

    print_banner(f"NFL {context.season}: {context.season_type}, week {context.week} "
                 f"(via {context.source})")
    print(f"Finished weeks this season: {context.completed_weeks or 'none'}")
    print(f"Prediction week: {context.prediction_week or 'none (offseason)'}")
    for season in seasons:
        steps = plan[season]
        print(f"{season}: schedule {len(steps['schedule'])}, stats {steps['stats'] or '-'}, "
              f"projections {steps['projections'] or '-'}")
    print(f"Feature weeks to compute: {len(pairs)}")

    if args.dry_run:
        return 0

    if not args.train:
        totals = run_sync(plan)
        logger.info(f"Synced: {totals}")
        computed = run_features(pairs) if pairs else 0
        logger.info(f"Feature weeks computed: {computed}")
        if args.sync or (computed == 0 and os.path.exists(MODEL_PATH)):
            if computed == 0:
                logger.info("No features changed; model left as is")
            return 0

    return 0 if run_training() else 1


if __name__ == '__main__':
    sys.exit(main())
