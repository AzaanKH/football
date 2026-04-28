#!/usr/bin/env python3
"""
Fantasy Football Data Scheduler

Automated weekly updates for the fantasy football prediction system.
Uses APScheduler to run data sync and feature computation on a schedule.

Schedule:
- Player sync: Daily at 6:00 AM
- Completed-week stats sync: Tuesday 6:00 AM (after Monday Night Football)
- Upcoming-week context sync: Tuesday 6:30 AM
- Feature computation: Tuesday 7:00 AM
- Model retraining: Tuesday 8:00 AM (optional)

Usage:
    python scheduler.py start              # Start scheduler daemon
    python scheduler.py run-now            # Run all jobs immediately
    python scheduler.py run-now --sync     # Only run sync jobs
    python scheduler.py run-now --features # Only compute features
    python scheduler.py run-now --train    # Only retrain model
    python scheduler.py status             # Show scheduler status

Prerequisites:
    pip install apscheduler
"""

import sys
import os
import time
import logging
import signal
from datetime import datetime
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('scheduler')

# Try to import APScheduler
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.warning("APScheduler not installed. Run: pip install apscheduler")


# Configuration
SEASON = 2025
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', 5432)),
    'database': os.environ.get('DB_NAME', 'football_dev'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', 'postgres'),
}


def get_db_connection():
    """Get PostgreSQL connection."""
    import psycopg2
    return psycopg2.connect(**DB_CONFIG)


def get_current_nfl_week() -> tuple:
    """Get current NFL season and week."""
    try:
        from data_pipeline import SleeperClient

        with SleeperClient() as client:
            state = client.get_nfl_state()
            if state:
                return state.get('season', SEASON), state.get('week', 1)
    except Exception as e:
        logger.warning(f"Could not get NFL state: {e}")

    return SEASON, 1


def resolve_pipeline_context(season: Optional[int] = None, nfl_week: Optional[int] = None) -> dict:
    """
    Resolve explicit completed and prediction weeks for weekly automation.

    The scheduler runs on Tuesday morning, so Sleeper's current week is treated
    as the upcoming prediction week and the completed stats week is one prior.
    """
    if season is None or nfl_week is None:
        season, nfl_week = get_current_nfl_week()

    prediction_week = max(1, nfl_week)
    completed_week = max(0, prediction_week - 1)
    weeks_to_refresh = [w for w in {completed_week - 1, completed_week} if w >= 1]

    return {
        'season': season,
        'nfl_week': nfl_week,
        'prediction_week': prediction_week,
        'completed_week': completed_week,
        'weeks_to_refresh': sorted(weeks_to_refresh),
        'is_offseason': nfl_week == 0,
    }


def _skipped(reason: str, **extra) -> dict:
    """Standardize skipped job responses for run-now reporting."""
    payload = {'skipped': True, 'reason': reason}
    payload.update(extra)
    return payload


def _is_offseason(context: dict) -> bool:
    """Handle older or mocked contexts that may not include the new flag."""
    return context.get('is_offseason', context.get('nfl_week', 1) == 0)


def job_sync_players():
    """Scheduled job: Sync players from Sleeper API."""
    logger.info("Starting scheduled player sync...")

    try:
        from data_pipeline import DataOrchestrator

        with DataOrchestrator() as orchestrator:
            stats = orchestrator.sync_players()
            logger.info(f"Player sync complete: {stats['processed']} processed, "
                       f"{stats['inserted']} new, {stats['updated']} updated")
            return stats
    except Exception as e:
        logger.error(f"Player sync failed: {e}")
        raise


def job_sync_weekly_stats():
    """Scheduled job: Sync current week's stats."""
    logger.info("Starting scheduled stats sync...")

    try:
        from data_pipeline import DataOrchestrator

        context = resolve_pipeline_context()
        season = context['season']
        completed_week = context['completed_week']
        if not context['weeks_to_refresh']:
            logger.info(
                f"No completed weeks to refresh for {season} "
                f"(nfl_week={context['nfl_week']}, offseason={_is_offseason(context)})"
            )
            return _skipped(
                "No completed NFL weeks are available to sync yet",
                season=season,
                completed_week=completed_week,
            )

        logger.info(
            f"Syncing finalized stats for {season}: completed week {completed_week}, "
            f"refresh weeks {context['weeks_to_refresh']}"
        )

        with DataOrchestrator() as orchestrator:
            results = {}
            for w in context['weeks_to_refresh']:
                try:
                    stats = orchestrator.sync_weekly_stats(season, w)
                    results[w] = stats
                    logger.info(f"Week {w}: {stats['processed']} processed, "
                               f"{stats['inserted']} inserted")
                except Exception as e:
                    logger.warning(f"Week {w} sync failed: {e}")

            return results
    except Exception as e:
        logger.error(f"Stats sync failed: {e}")
        raise


def job_sync_prediction_context():
    """Scheduled job: Sync matchups and projections for the upcoming prediction week."""
    logger.info("Starting scheduled prediction-context sync...")

    try:
        from data_pipeline import DataOrchestrator

        context = resolve_pipeline_context()
        season = context['season']
        prediction_week = context['prediction_week']
        if _is_offseason(context):
            logger.info(f"Skipping matchup/projection sync for {season}: offseason")
            return _skipped(
                "Offseason detected; matchup and projection feeds are not available",
                season=season,
                prediction_week=prediction_week,
            )
        logger.info(f"Syncing matchups and projections for {season} Week {prediction_week}")

        with DataOrchestrator() as orchestrator:
            return {
                'matchups': orchestrator.sync_matchups(season, prediction_week),
                'projections': orchestrator.sync_projections(season, prediction_week),
            }
    except Exception as e:
        logger.error(f"Prediction-context sync failed: {e}")
        raise


def job_compute_features():
    """Scheduled job: Compute features for current week."""
    logger.info("Starting scheduled feature computation...")

    try:
        from data_pipeline.features import FeatureEngineer

        context = resolve_pipeline_context()
        season = context['season']
        prediction_week = context['prediction_week']
        if _is_offseason(context):
            logger.info(f"Skipping feature computation for {season}: offseason")
            return _skipped(
                "Offseason detected; no prediction week feature build is needed",
                season=season,
                prediction_week=prediction_week,
            )
        logger.info(f"Computing features for {season} Week {prediction_week}")

        conn = get_db_connection()
        try:
            with FeatureEngineer(conn) as engineer:
                stats = engineer.compute_all_features(
                    season, prediction_week,
                    positions=['QB', 'RB', 'WR', 'TE']
                )
                logger.info(f"Features computed: {stats['total']} players, "
                           f"{stats['inserted']} inserted, {stats['updated']} updated")
                return stats
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Feature computation failed: {e}")
        raise


def job_retrain_model():
    """Scheduled job: Retrain the weekly predictor model."""
    logger.info("Starting scheduled model retraining...")

    try:
        from weekly_predictor import WeeklyPredictor

        conn = get_db_connection()
        try:
            predictor = WeeklyPredictor(db_connection=conn)

            all_metrics = {}
            for position in ['qb', 'rb', 'wr']:
                try:
                    metrics = predictor.train(position)
                    all_metrics[position] = metrics
                    logger.info(f"{position.upper()}: MAE={metrics['mae']:.2f}, "
                               f"R²={metrics['r2']:.3f}")
                except Exception as e:
                    logger.warning(f"{position.upper()} training failed: {e}")

            if all_metrics:
                os.makedirs('models', exist_ok=True)
                predictor.save('models/weekly_predictor.pkl')
                logger.info("Model saved successfully")
                return all_metrics

        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Model retraining failed: {e}")
        raise


def job_listener(event):
    """Log job execution events."""
    if event.exception:
        logger.error(f"Job {event.job_id} failed: {event.exception}")
    else:
        logger.info(f"Job {event.job_id} completed successfully")


class FantasyScheduler:
    """Fantasy Football Data Scheduler."""

    def __init__(self):
        if not SCHEDULER_AVAILABLE:
            raise ImportError("APScheduler not installed. Run: pip install apscheduler")

        self.scheduler = BackgroundScheduler(
            timezone='America/New_York'  # NFL timezone
        )
        self.scheduler.add_listener(job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
        self._setup_jobs()

    def _setup_jobs(self):
        """Configure scheduled jobs."""

        # Daily player sync at 6:00 AM ET
        self.scheduler.add_job(
            job_sync_players,
            CronTrigger(hour=6, minute=0),
            id='sync_players',
            name='Daily Player Sync',
            replace_existing=True,
            max_instances=1
        )

        # Tuesday stats sync at 6:00 AM ET (after Monday Night Football)
        self.scheduler.add_job(
            job_sync_weekly_stats,
            CronTrigger(day_of_week='tue', hour=6, minute=0),
            id='sync_stats',
            name='Weekly Stats Sync',
            replace_existing=True,
            max_instances=1
        )

        # Tuesday matchup/projection sync at 6:30 AM ET
        self.scheduler.add_job(
            job_sync_prediction_context,
            CronTrigger(day_of_week='tue', hour=6, minute=30),
            id='sync_prediction_context',
            name='Weekly Prediction Context Sync',
            replace_existing=True,
            max_instances=1
        )

        # Tuesday feature computation at 7:00 AM ET
        self.scheduler.add_job(
            job_compute_features,
            CronTrigger(day_of_week='tue', hour=7, minute=0),
            id='compute_features',
            name='Weekly Feature Computation',
            replace_existing=True,
            max_instances=1
        )

        # Tuesday model retraining at 8:00 AM ET
        self.scheduler.add_job(
            job_retrain_model,
            CronTrigger(day_of_week='tue', hour=8, minute=0),
            id='retrain_model',
            name='Weekly Model Retraining',
            replace_existing=True,
            max_instances=1
        )

        logger.info("Scheduled jobs configured:")
        for job in self.scheduler.get_jobs():
            logger.info(f"  - {job.name}: {job.trigger}")

    def start(self):
        """Start the scheduler."""
        logger.info("Starting Fantasy Football Scheduler...")
        self.scheduler.start()

        # Handle shutdown signals
        def shutdown(signum, frame):
            logger.info("Shutting down scheduler...")
            self.scheduler.shutdown(wait=True)
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        # Keep alive
        print("\nScheduler is running. Press Ctrl+C to stop.\n")
        print("Scheduled jobs:")
        for job in self.scheduler.get_jobs():
            print(f"  - {job.name}: Next run at {job.next_run_time}")
        print()

        try:
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            self.scheduler.shutdown(wait=True)

    def run_job(self, job_id: str):
        """Run a specific job immediately."""
        job = self.scheduler.get_job(job_id)
        if job:
            logger.info(f"Running job: {job.name}")
            job.func()
        else:
            logger.error(f"Job not found: {job_id}")

    def get_status(self):
        """Get scheduler status."""
        jobs = self.scheduler.get_jobs()
        return {
            'running': self.scheduler.running,
            'jobs': [
                {
                    'id': job.id,
                    'name': job.name,
                    'next_run': str(job.next_run_time) if job.next_run_time else None,
                    'trigger': str(job.trigger)
                }
                for job in jobs
            ]
        }


def run_all_jobs_now(sync_only=False, features_only=False, train_only=False):
    """Run all jobs immediately."""
    print("\n" + "=" * 60)
    print(" Running Jobs Now")
    print("=" * 60 + "\n")

    if not sync_only and not features_only and not train_only:
        # Run all
        sync_only = features_only = train_only = True

    results = {}

    if sync_only:
        print("1. Syncing players...")
        try:
            results['players'] = job_sync_players()
        except Exception as e:
            results['players'] = {'error': str(e)}

        print("\n2. Syncing weekly stats...")
        try:
            results['stats'] = job_sync_weekly_stats()
        except Exception as e:
            results['stats'] = {'error': str(e)}

        print("\n2b. Syncing upcoming-week context...")
        try:
            results['prediction_context'] = job_sync_prediction_context()
        except Exception as e:
            results['prediction_context'] = {'error': str(e)}

    if features_only:
        print("\n3. Computing features...")
        try:
            results['features'] = job_compute_features()
        except Exception as e:
            results['features'] = {'error': str(e)}

    if train_only:
        print("\n4. Retraining model...")
        try:
            results['training'] = job_retrain_model()
        except Exception as e:
            results['training'] = {'error': str(e)}

    print("\n" + "=" * 60)
    print(" Results Summary")
    print("=" * 60)

    for job, result in results.items():
        if result and result.get('skipped'):
            print(f"  {job}: Skipped - {result.get('reason', 'No action needed')}")
        elif result and 'error' not in result:
            print(f"  {job}: Success")
        else:
            print(f"  {job}: Failed - {result.get('error', 'Unknown error')}")

    return results


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCommands:")
        print("  python scheduler.py start              # Start scheduler daemon")
        print("  python scheduler.py run-now            # Run all jobs immediately")
        print("  python scheduler.py run-now --sync     # Only run sync jobs")
        print("  python scheduler.py run-now --features # Only compute features")
        print("  python scheduler.py run-now --train    # Only retrain model")
        print("  python scheduler.py status             # Show scheduler status")
        print("  python scheduler.py dry-run            # Show resolved weekly trigger context")
        return

    command = sys.argv[1].lower()

    if not SCHEDULER_AVAILABLE and command == 'start':
        print("ERROR: APScheduler not installed.")
        print("Install with: pip install apscheduler")
        sys.exit(1)

    if command == 'start':
        scheduler = FantasyScheduler()
        scheduler.start()

    elif command == 'run-now':
        sync_only = '--sync' in sys.argv
        features_only = '--features' in sys.argv
        train_only = '--train' in sys.argv

        run_all_jobs_now(
            sync_only=sync_only and not features_only and not train_only,
            features_only=features_only and not sync_only and not train_only,
            train_only=train_only and not sync_only and not features_only
        )

    elif command == 'status':
        if SCHEDULER_AVAILABLE:
            scheduler = FantasyScheduler()
            status = scheduler.get_status()
            print("\nScheduler Status:")
            print(f"  Running: {status['running']}")
            print("\nConfigured Jobs:")
            for job in status['jobs']:
                print(f"  - {job['name']}")
                print(f"    ID: {job['id']}")
                print(f"    Trigger: {job['trigger']}")
                print(f"    Next Run: {job['next_run'] or 'Not scheduled'}")
        else:
            print("APScheduler not installed")

    elif command == 'dry-run':
        context = resolve_pipeline_context()
        print("\nWeekly Trigger Context:")
        for key, value in context.items():
            print(f"  {key}: {value}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == '__main__':
    main()
