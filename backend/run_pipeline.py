#!/usr/bin/env python3
"""
Run the Fantasy Football Data Pipeline

Usage:
    python run_pipeline.py                    # Show current status
    python run_pipeline.py sync-players       # Sync all players
    python run_pipeline.py sync-stats 2024 1  # Sync stats for season/week
    python run_pipeline.py full-sync          # Full sync (players + recent stats)
    python run_pipeline.py compute-features 2024 10  # Compute features for week
    python run_pipeline.py compute-all-features      # Compute all historical features

Prerequisites:
    1. Start the database: docker-compose up -d
    2. Install dependencies: pip install -r requirements_data_pipeline.txt
"""

import sys
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_database():
    """Check if database is accessible."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            "postgresql://postgres:postgres@localhost:5432/football_dev"
        )
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.info("Make sure to run: docker-compose up -d")
        return False


def show_status():
    """Show current pipeline status."""
    from data_pipeline import DataOrchestrator

    print("\n" + "=" * 60)
    print("Fantasy Football Data Pipeline Status")
    print("=" * 60)

    with DataOrchestrator() as orchestrator:
        # Get NFL state
        info = orchestrator.get_current_season_info()
        print(f"\nNFL Season: {info['season']}")
        print(f"Current Week: {info['week']}")

        # Check database
        if check_database():
            print("\nDatabase: Connected")

            # Get record counts
            with orchestrator.get_db_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(*) FROM players")
                player_count = cursor.fetchone()[0]
                print(f"Players in DB: {player_count}")

                cursor.execute("SELECT COUNT(*) FROM player_weekly_stats")
                stats_count = cursor.fetchone()[0]
                print(f"Weekly Stats Records: {stats_count}")

                cursor.execute("""
                    SELECT source, data_type, status, COUNT(*)
                    FROM ingestion_log
                    GROUP BY source, data_type, status
                    ORDER BY source, data_type
                """)
                logs = cursor.fetchall()
                if logs:
                    print("\nRecent Ingestion Logs:")
                    for source, dtype, status, count in logs:
                        print(f"  {source}/{dtype}: {count} {status}")
        else:
            print("\nDatabase: Not Connected")
            print("Run: docker-compose up -d")

    print("\n" + "=" * 60)


def sync_players():
    """Sync all players from Sleeper API."""
    if not check_database():
        return

    from data_pipeline import DataOrchestrator

    print("\nSyncing players...")
    with DataOrchestrator() as orchestrator:
        stats = orchestrator.sync_players()
        print(f"\nResults:")
        print(f"  Processed: {stats['processed']}")
        print(f"  Inserted: {stats['inserted']}")
        print(f"  Updated: {stats['updated']}")
        print(f"  Errors: {stats['errors']}")


def sync_stats(season: int, week: int):
    """Sync weekly stats for a specific week."""
    if not check_database():
        return

    from data_pipeline import DataOrchestrator

    print(f"\nSyncing stats for {season} week {week}...")
    with DataOrchestrator() as orchestrator:
        stats = orchestrator.sync_weekly_stats(season, week)
        print(f"\nResults:")
        print(f"  Processed: {stats['processed']}")
        print(f"  Inserted: {stats['inserted']}")
        print(f"  Updated: {stats['updated']}")
        print(f"  Errors: {stats['errors']}")


def full_sync():
    """Run a full sync (players + recent weeks)."""
    if not check_database():
        return

    from data_pipeline import DataOrchestrator

    print("\nRunning full sync...")
    with DataOrchestrator() as orchestrator:
        info = orchestrator.get_current_season_info()
        results = orchestrator.full_sync(
            season=info['season'],
            current_week=info['week'],
            sync_historical=False
        )

        print(f"\nFull Sync Results:")
        print(f"  Players: {results['players']}")
        print(f"  Stats weeks synced: {list(results['stats'].keys())}")
        print(f"  Projections: {results['projections']}")
        if results['errors']:
            print(f"  Errors: {results['errors']}")


def test_api():
    """Test API connectivity without database."""
    from data_pipeline import SleeperClient

    print("\nTesting Sleeper API...")
    with SleeperClient() as client:
        state = client.get_nfl_state()
        if state:
            print(f"  Connected! Season: {state.get('season')}, Week: {state.get('week')}")

        trending = client.get_trending_players(limit=5)
        print(f"  Trending players retrieved: {len(trending)}")

        print("\nSleeper API is working!")


def compute_features(season: int, week: int):
    """Compute features for a specific season/week."""
    if not check_database():
        return

    import psycopg2
    from data_pipeline.features import FeatureEngineer

    print(f"\nComputing features for {season} week {week}...")

    conn = psycopg2.connect(
        "postgresql://postgres:postgres@localhost:5432/football_dev"
    )

    try:
        with FeatureEngineer(conn) as engineer:
            stats = engineer.compute_all_features(season, week, positions=['QB', 'RB', 'WR', 'TE'])

            print(f"\nResults:")
            print(f"  Total players: {stats['total']}")
            print(f"  Inserted: {stats['inserted']}")
            print(f"  Updated: {stats['updated']}")
            print(f"  Errors: {stats['errors']}")
    finally:
        conn.close()


def compute_all_features():
    """Compute features for all historical data."""
    if not check_database():
        return

    import psycopg2
    from data_pipeline.features import FeatureEngineer

    print("\nComputing features for all historical data...")
    print("This may take several minutes...\n")

    conn = psycopg2.connect(
        "postgresql://postgres:postgres@localhost:5432/football_dev"
    )

    try:
        with FeatureEngineer(conn) as engineer:
            # Get available seasons
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT season FROM player_weekly_stats ORDER BY season")
            seasons = [row[0] for row in cursor.fetchall()]
            cursor.close()

            print(f"Found seasons: {seasons}")

            stats = engineer.compute_historical_features(
                seasons=seasons,
                positions=['QB', 'RB', 'WR', 'TE']
            )

            print(f"\nFinal Results:")
            print(f"  Total players processed: {stats['total']}")
            print(f"  Inserted: {stats['inserted']}")
            print(f"  Updated: {stats['updated']}")
            print(f"  Errors: {stats['errors']}")

            # Show summary
            summary = engineer.get_feature_summary()
            print(f"\nFeature Table Summary:")
            print(f"  Total records: {summary['total_records']}")
            print(f"  Unique players: {summary['unique_players']}")
            print(f"  Seasons covered: {summary['min_season']} - {summary['max_season']}")
    finally:
        conn.close()


def show_feature_status():
    """Show feature computation status."""
    if not check_database():
        return

    import psycopg2

    conn = psycopg2.connect(
        "postgresql://postgres:postgres@localhost:5432/football_dev"
    )

    try:
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'player_features'
            )
        """)
        table_exists = cursor.fetchone()[0]

        print("\n" + "=" * 60)
        print("Feature Engineering Status")
        print("=" * 60)

        if not table_exists:
            print("\nFeature table not created yet.")
            print("Run the migration: psql -f migrations/001_add_player_features.sql")
            return

        cursor.execute("SELECT COUNT(*) FROM player_features")
        count = cursor.fetchone()[0]
        print(f"\nFeature records: {count}")

        if count > 0:
            cursor.execute("""
                SELECT season, COUNT(*) as records, COUNT(DISTINCT player_id) as players
                FROM player_features
                GROUP BY season
                ORDER BY season
            """)
            rows = cursor.fetchall()
            print("\nBy Season:")
            for season, records, players in rows:
                print(f"  {season}: {records} records, {players} players")

            cursor.execute("""
                SELECT MIN(computed_at), MAX(computed_at)
                FROM player_features
            """)
            oldest, newest = cursor.fetchone()
            print(f"\nOldest computation: {oldest}")
            print(f"Newest computation: {newest}")

        cursor.close()
        print("=" * 60)
    finally:
        conn.close()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_status()
        print("\nCommands:")
        print("  python run_pipeline.py status              # Show status")
        print("  python run_pipeline.py test-api            # Test API (no DB needed)")
        print("  python run_pipeline.py sync-players        # Sync players")
        print("  python run_pipeline.py sync-stats 2024 1   # Sync week stats")
        print("  python run_pipeline.py full-sync           # Full sync")
        print("\nFeature Engineering:")
        print("  python run_pipeline.py feature-status          # Show feature status")
        print("  python run_pipeline.py compute-features 2024 10  # Compute for week")
        print("  python run_pipeline.py compute-all-features    # Compute all historical")
        return

    command = sys.argv[1].lower()

    if command == 'status':
        show_status()
    elif command == 'test-api':
        test_api()
    elif command == 'sync-players':
        sync_players()
    elif command == 'sync-stats':
        if len(sys.argv) < 4:
            print("Usage: python run_pipeline.py sync-stats <season> <week>")
            print("Example: python run_pipeline.py sync-stats 2024 1")
            return
        season = int(sys.argv[2])
        week = int(sys.argv[3])
        sync_stats(season, week)
    elif command == 'full-sync':
        full_sync()
    elif command == 'feature-status':
        show_feature_status()
    elif command == 'compute-features':
        if len(sys.argv) < 4:
            print("Usage: python run_pipeline.py compute-features <season> <week>")
            print("Example: python run_pipeline.py compute-features 2024 10")
            return
        season = int(sys.argv[2])
        week = int(sys.argv[3])
        compute_features(season, week)
    elif command == 'compute-all-features':
        compute_all_features()
    else:
        print(f"Unknown command: {command}")
        print("Use: status, test-api, sync-players, sync-stats, full-sync")
        print("     feature-status, compute-features, compute-all-features")


if __name__ == "__main__":
    main()
