#!/usr/bin/env python3
"""
2025 NFL Season Setup Script

This script automates the complete setup of the fantasy football prediction system:
1. Verifies database connectivity
2. Syncs all players from Sleeper API
3. Syncs weekly stats for all available 2025 weeks
4. Computes predictive features for each week
5. Trains the weekly predictor model

Usage:
    python setup_2025_season.py           # Full setup
    python setup_2025_season.py --sync    # Only sync data (no training)
    python setup_2025_season.py --train   # Only train model (assumes data exists)

Prerequisites:
    - Docker Desktop running
    - Run: docker-compose up -d
"""

import sys
import os
import time
import logging
import argparse
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
SEASON = 2025
MAX_WEEKS = 18  # Regular season weeks


def print_banner(text):
    """Print a formatted banner."""
    print("\n" + "=" * 60)
    print(f" {text}")
    print("=" * 60)


def check_docker():
    """Check if Docker container is running."""
    import subprocess

    try:
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'name=football-db', '--format', '{{.Names}}'],
            capture_output=True, text=True, timeout=10
        )
        if 'football-db' in result.stdout:
            logger.info("Docker container 'football-db' is running")
            return True
        else:
            logger.warning("Docker container 'football-db' is not running")
            return False
    except Exception as e:
        logger.error(f"Docker check failed: {e}")
        return False


def start_docker():
    """Start Docker container."""
    import subprocess

    logger.info("Starting Docker container...")
    try:
        result = subprocess.run(
            ['docker-compose', 'up', '-d'],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        if result.returncode == 0:
            logger.info("Docker container started successfully")
            time.sleep(5)  # Wait for DB to be ready
            return True
        else:
            logger.error(f"Failed to start Docker: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Docker start failed: {e}")
        return False


def check_database():
    """Check database connectivity."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=os.environ.get('DB_PORT', 5432),
            database=os.environ.get('DB_NAME', 'football_dev'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'postgres')
        )
        conn.close()
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


def get_current_nfl_week():
    """Get current NFL week from Sleeper API."""
    try:
        from data_pipeline import SleeperClient

        with SleeperClient() as client:
            state = client.get_nfl_state()
            if state:
                return state.get('season', SEASON), state.get('week', 1)
    except Exception as e:
        logger.warning(f"Could not get NFL state: {e}")

    return SEASON, 1


def sync_players():
    """Sync all players from Sleeper API."""
    print_banner("Syncing Players")

    try:
        from data_pipeline import DataOrchestrator

        with DataOrchestrator() as orchestrator:
            stats = orchestrator.sync_players()
            logger.info(f"Players synced: {stats['processed']} processed, "
                       f"{stats['inserted']} inserted, {stats['updated']} updated")
            return stats
    except Exception as e:
        logger.error(f"Player sync failed: {e}")
        return None


def sync_weekly_stats(season, weeks):
    """Sync weekly stats for specified weeks."""
    print_banner(f"Syncing Weekly Stats ({season})")

    try:
        from data_pipeline import DataOrchestrator

        results = {}
        with DataOrchestrator() as orchestrator:
            for week in weeks:
                logger.info(f"Syncing week {week}...")
                try:
                    stats = orchestrator.sync_weekly_stats(season, week)
                    results[week] = stats
                    logger.info(f"  Week {week}: {stats['processed']} processed, "
                               f"{stats['inserted']} inserted")
                except Exception as e:
                    logger.warning(f"  Week {week} failed: {e}")
                    results[week] = {'error': str(e)}

                # Rate limiting
                time.sleep(0.5)

        return results
    except Exception as e:
        logger.error(f"Stats sync failed: {e}")
        return None


def compute_features(season, weeks):
    """Compute features for all weeks."""
    print_banner(f"Computing Features ({season})")

    try:
        import psycopg2
        from data_pipeline.features import FeatureEngineer

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=os.environ.get('DB_PORT', 5432),
            database=os.environ.get('DB_NAME', 'football_dev'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'postgres')
        )

        results = {}
        try:
            with FeatureEngineer(conn) as engineer:
                for week in weeks:
                    logger.info(f"Computing features for week {week}...")
                    try:
                        stats = engineer.compute_all_features(
                            season, week,
                            positions=['QB', 'RB', 'WR', 'TE']
                        )
                        results[week] = stats
                        logger.info(f"  Week {week}: {stats['total']} players, "
                                   f"{stats['inserted']} inserted")
                    except Exception as e:
                        logger.warning(f"  Week {week} failed: {e}")
                        results[week] = {'error': str(e)}
        finally:
            conn.close()

        return results
    except ImportError as e:
        logger.error(f"Feature engineer import failed: {e}")
        logger.info("Make sure to install: pip install -r requirements_data_pipeline.txt")
        return None
    except Exception as e:
        logger.error(f"Feature computation failed: {e}")
        return None


def train_weekly_predictor():
    """Train the weekly prediction model."""
    print_banner("Training Weekly Predictor")

    try:
        import psycopg2
        from weekly_predictor import WeeklyPredictor

        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=os.environ.get('DB_PORT', 5432),
            database=os.environ.get('DB_NAME', 'football_dev'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'postgres')
        )

        try:
            predictor = WeeklyPredictor(db_connection=conn)

            all_metrics = {}
            for position in ['qb', 'rb', 'wr']:
                logger.info(f"Training {position.upper()} model...")
                try:
                    metrics = predictor.train(position)
                    all_metrics[position] = metrics
                    logger.info(f"  {position.upper()}: MAE={metrics['mae']:.2f}, "
                               f"R²={metrics['r2']:.3f}, Samples={metrics['samples']}")
                except Exception as e:
                    logger.warning(f"  {position.upper()} training failed: {e}")

            if all_metrics:
                # Save model
                os.makedirs('models', exist_ok=True)
                predictor.save('models/weekly_predictor.pkl')
                logger.info("Model saved to models/weekly_predictor.pkl")
                return all_metrics
            else:
                logger.error("No models trained successfully")
                return None

        finally:
            conn.close()

    except ImportError as e:
        logger.error(f"Weekly predictor import failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Training failed: {e}")
        return None


def show_summary(player_stats, sync_results, feature_results, training_metrics):
    """Show setup summary."""
    print_banner("Setup Summary")

    print(f"\nSeason: {SEASON}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if player_stats:
        print(f"\nPlayers:")
        print(f"  Total synced: {player_stats['processed']}")
        print(f"  New players: {player_stats['inserted']}")

    if sync_results:
        success_weeks = [w for w, r in sync_results.items() if 'error' not in r]
        print(f"\nWeekly Stats:")
        print(f"  Weeks synced: {len(success_weeks)}")
        print(f"  Weeks: {success_weeks if success_weeks else 'None'}")

    if feature_results:
        success_weeks = [w for w, r in feature_results.items() if 'error' not in r]
        total_features = sum(r.get('total', 0) for r in feature_results.values() if 'error' not in r)
        print(f"\nFeatures:")
        print(f"  Weeks computed: {len(success_weeks)}")
        print(f"  Total feature records: {total_features}")

    if training_metrics:
        print(f"\nModel Training:")
        for pos, metrics in training_metrics.items():
            print(f"  {pos.upper()}: MAE={metrics['mae']:.2f}, R²={metrics['r2']:.3f}")

    print("\n" + "=" * 60)

    # Next steps
    print("\nNext Steps:")
    if training_metrics:
        print("  1. Start the backend: python app.py")
        print("  2. Start the frontend: cd ../frontend/fantasy-football && npm start")
        print("  3. Open http://localhost:3000")
    else:
        print("  - Fix any errors above and re-run the script")

    print("\nTo update data weekly:")
    print("  python scheduler.py start")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Setup 2025 NFL Season Data')
    parser.add_argument('--sync', action='store_true', help='Only sync data (no training)')
    parser.add_argument('--train', action='store_true', help='Only train model')
    parser.add_argument('--weeks', type=str, help='Specific weeks to sync (e.g., "1-10" or "5,6,7")')
    args = parser.parse_args()

    print_banner("2025 NFL Season Setup")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Determine weeks to process
    current_season, current_week = get_current_nfl_week()
    logger.info(f"Current NFL state: {current_season} Week {current_week}")

    if args.weeks:
        if '-' in args.weeks:
            start, end = map(int, args.weeks.split('-'))
            weeks_to_sync = list(range(start, end + 1))
        else:
            weeks_to_sync = [int(w) for w in args.weeks.split(',')]
    else:
        # Sync all weeks up to current
        weeks_to_sync = list(range(1, min(current_week + 1, MAX_WEEKS + 1)))

    logger.info(f"Weeks to process: {weeks_to_sync}")

    # Check Docker
    if not check_docker():
        logger.info("Attempting to start Docker...")
        if not start_docker():
            logger.error("Could not start Docker. Please run: docker-compose up -d")
            sys.exit(1)

    # Check database
    if not check_database():
        logger.error("Database not accessible. Make sure Docker is running.")
        sys.exit(1)

    player_stats = None
    sync_results = None
    feature_results = None
    training_metrics = None

    if not args.train:
        # Sync data
        player_stats = sync_players()
        if not player_stats:
            logger.error("Player sync failed. Aborting.")
            sys.exit(1)

        sync_results = sync_weekly_stats(SEASON, weeks_to_sync)
        if not sync_results:
            logger.warning("Stats sync had issues, but continuing...")

        # Compute features
        feature_results = compute_features(SEASON, weeks_to_sync)
        if not feature_results:
            logger.warning("Feature computation had issues, but continuing...")

    if not args.sync:
        # Train model
        training_metrics = train_weekly_predictor()

    # Show summary
    show_summary(player_stats, sync_results, feature_results, training_metrics)

    print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == '__main__':
    main()
