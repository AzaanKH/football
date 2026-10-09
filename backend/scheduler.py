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
from datetime import datetime, timezone
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


def _context_to_dict(context) -> dict:
    completed = context.completed_weeks
    return {
        'season': context.season,
        'season_type': context.season_type,
        'nfl_week': context.week,
        'prediction_week': context.prediction_week,
        'completed_week': context.last_completed_week,
        # Re-sync the last two finished weeks to pick up stat corrections
        'weeks_to_refresh': completed[-2:],
        'is_offseason': context.is_offseason,
        'source': context.source,
    }


def resolve_pipeline_context(season: Optional[int] = None, nfl_week: Optional[int] = None) -> dict:
    """
    Resolve the season, finished weeks and prediction week for automation.

    With no arguments this follows the real calendar (Sleeper's NFL state,
    falling back to the date) and counts the current week as finished once
    its last game is over, using the synced schedule. Explicit season/week
    treat that week as the upcoming one (weeks before it are finished).
    """
    from data_pipeline.season import build_context, current_context, schedule_week_end

    if season is not None and nfl_week is not None:
        state = {'season': season, 'week': nfl_week,
                 'season_type': 'regular' if nfl_week >= 1 else 'off'}
        context = build_context(state, datetime.now(timezone.utc), 'explicit')
        return _context_to_dict(context)

    conn = None
    try:
        conn = get_db_connection()
        context = current_context(week_end_lookup=schedule_week_end(conn))
    except Exception as e:
        logger.warning(f"Schedule unavailable ({e}); resolving the week without it")
        context = current_context()
    finally:
        if conn is not None:
            conn.close()
    return _context_to_dict(context)


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

        # Independent feeds: a matchup failure must not block projections,
        # which are the point estimate
        results = {}
        with DataOrchestrator() as orchestrator:
            for name, sync in (('matchups', orchestrator.sync_matchups),
                               ('projections', orchestrator.sync_projections)):
                try:
                    results[name] = sync(season, prediction_week)
                except Exception as e:
                    logger.error(f"{name} sync failed for {season} Week {prediction_week}: {e}")
                    results[name] = {'status': 'failed', 'error': str(e)}

        if all(r.get('status') == 'failed' for r in results.values()):
            raise RuntimeError(f"Prediction-context sync failed: {results}")
        return results
    except Exception as e:
        logger.error(f"Prediction-context sync failed: {e}")
        raise


def job_refresh_projections():
    """
    Scheduled job: re-sync Sleeper projections for the upcoming week.

    Sleeper revises projections through the week as injury and depth-chart
    news lands; they are the point estimate, so keep them current.
    """
    try:
        from data_pipeline import DataOrchestrator

        context = resolve_pipeline_context()
        season = context['season']
        prediction_week = context['prediction_week']
        if _is_offseason(context):
            return _skipped("Offseason detected; no projections to refresh",
                            season=season, prediction_week=prediction_week)

        with DataOrchestrator() as orchestrator:
            stats = orchestrator.sync_projections(season, prediction_week)
        logger.info(f"Refreshed projections for {season} Week {prediction_week}: {stats}")
        return stats
    except Exception as e:
        logger.error(f"Projection refresh failed: {e}")
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


# NFL timezone. Each CronTrigger needs it explicitly: a trigger constructed
# outside add_job() uses the host's local zone, not the scheduler's.
SCHEDULER_TIMEZONE = 'America/New_York'


def _cron(**fields):
    """CronTrigger evaluated in Eastern time, whatever the host's zone."""
    return CronTrigger(timezone=SCHEDULER_TIMEZONE, **fields)


class FantasyScheduler:
    """Fantasy Football Data Scheduler."""

    def __init__(self):
        if not SCHEDULER_AVAILABLE:
            raise ImportError("APScheduler not installed. Run: pip install apscheduler")

        self.scheduler = BackgroundScheduler(timezone=SCHEDULER_TIMEZONE)
        self.scheduler.add_listener(job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
        self._setup_jobs()

    def _setup_jobs(self):
        """Configure scheduled jobs."""

        # Daily player sync at 6:00 AM ET
        self.scheduler.add_job(
            job_sync_players,
            _cron(hour=6, minute=0),
            id='sync_players',
            name='Daily Player Sync',
            replace_existing=True,
            max_instances=1
        )

        # Tuesday stats sync at 6:00 AM ET (after Monday Night Football)
        self.scheduler.add_job(
            job_sync_weekly_stats,
            _cron(day_of_week='tue', hour=6, minute=0),
            id='sync_stats',
            name='Weekly Stats Sync',
            replace_existing=True,
            max_instances=1
        )

        # Tuesday matchup/projection sync at 6:30 AM ET
        self.scheduler.add_job(
            job_sync_prediction_context,
            _cron(day_of_week='tue', hour=6, minute=30),
            id='sync_prediction_context',
            name='Weekly Prediction Context Sync',
            replace_existing=True,
            max_instances=1
        )

        # Daily projection refresh at 10:00 AM ET (injury/depth-chart news)
        self.scheduler.add_job(
            job_refresh_projections,
            _cron(hour=10, minute=0),
            id='refresh_projections',
            name='Daily Projection Refresh',
            replace_existing=True,
            max_instances=1
        )

        # Sunday 11:45 AM ET: after inactives are announced, before 1 PM kickoffs
        self.scheduler.add_job(
            job_refresh_projections,
            _cron(day_of_week='sun', hour=11, minute=45),
            id='refresh_projections_gameday',
            name='Gameday Projection Refresh',
            replace_existing=True,
            max_instances=1
        )

        # Tuesday feature computation at 7:00 AM ET
        self.scheduler.add_job(
            job_compute_features,
            _cron(day_of_week='tue', hour=7, minute=0),
            id='compute_features',
            name='Weekly Feature Computation',
            replace_existing=True,
            max_instances=1
        )

        # Tuesday model retraining at 8:00 AM ET
        self.scheduler.add_job(
            job_retrain_model,
            _cron(day_of_week='tue', hour=8, minute=0),
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
