"""
Data Pipeline Orchestrator

Coordinates data collection from multiple sources with automatic fallback.
Handles database operations and data synchronization.

Usage:
    from data_pipeline import DataOrchestrator

    # Initialize with database connection
    orchestrator = DataOrchestrator(database_url="postgresql://...")

    # Sync all players
    orchestrator.sync_players()

    # Sync weekly stats
    orchestrator.sync_weekly_stats(season=2024, week=1)

    # Run full sync
    orchestrator.full_sync(season=2024, current_week=10)
"""

import logging
import os
from typing import Optional, Dict, List, Any
from datetime import datetime
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import execute_values, RealDictCursor

from .sleeper_client import SleeperClient, transform_player_data, transform_weekly_stats
from .espn_client import ESPNClient
from .scraper import ProFootballReferenceScraper, transform_pfr_fantasy_stats

logger = logging.getLogger(__name__)


class DataOrchestrator:
    """
    Orchestrates data collection from multiple sources.

    Priority order:
    1. Sleeper API (primary)
    2. ESPN API (secondary/validation)
    3. Pro Football Reference (fallback/scraping)
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize the orchestrator.

        Args:
            database_url: PostgreSQL connection string.
                         Defaults to DATABASE_URL env var or local docker setup.
        """
        self.database_url = database_url or os.getenv(
            'DATABASE_URL',
            'postgresql://postgres:postgres@localhost:5432/football_dev'
        )

        # Initialize clients (lazy loading)
        self._sleeper_client: Optional[SleeperClient] = None
        self._espn_client: Optional[ESPNClient] = None
        self._scraper: Optional[ProFootballReferenceScraper] = None

    @property
    def sleeper(self) -> SleeperClient:
        """Get or create Sleeper client."""
        if self._sleeper_client is None:
            self._sleeper_client = SleeperClient()
        return self._sleeper_client

    @property
    def espn(self) -> ESPNClient:
        """Get or create ESPN client."""
        if self._espn_client is None:
            self._espn_client = ESPNClient()
        return self._espn_client

    @property
    def scraper(self) -> ProFootballReferenceScraper:
        """Get or create PFR scraper."""
        if self._scraper is None:
            self._scraper = ProFootballReferenceScraper()
        return self._scraper

    @contextmanager
    def get_db_connection(self):
        """Get a database connection with automatic cleanup."""
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _log_ingestion(self, conn, source: str, data_type: str,
                      season: int = None, week: int = None,
                      records_processed: int = 0, records_inserted: int = 0,
                      records_updated: int = 0, status: str = 'started',
                      error_message: str = None) -> int:
        """Log an ingestion event to the database."""
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ingestion_log
            (source, data_type, season, week, records_processed,
             records_inserted, records_updated, status, error_message,
             completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s != 'started' THEN NOW() ELSE NULL END)
            RETURNING id
        """, (source, data_type, season, week, records_processed,
              records_inserted, records_updated, status, error_message, status))
        log_id = cursor.fetchone()[0]
        conn.commit()
        return log_id

    def _update_ingestion_log(self, conn, log_id: int,
                             records_processed: int, records_inserted: int,
                             records_updated: int, status: str,
                             error_message: str = None):
        """Update an existing ingestion log entry."""
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE ingestion_log
            SET records_processed = %s,
                records_inserted = %s,
                records_updated = %s,
                status = %s,
                error_message = %s,
                completed_at = NOW()
            WHERE id = %s
        """, (records_processed, records_inserted, records_updated,
              status, error_message, log_id))
        conn.commit()

    def sync_players(self, force: bool = False) -> Dict[str, int]:
        """
        Synchronize players from Sleeper API to database.

        Args:
            force: If True, update all players even if recently synced

        Returns:
            Dictionary with sync statistics
        """
        logger.info("Starting player sync...")
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'errors': 0}

        with self.get_db_connection() as conn:
            log_id = self._log_ingestion(conn, 'sleeper', 'players')

            try:
                # Fetch all players from Sleeper
                players_data = self.sleeper.get_all_players()

                if not players_data:
                    raise Exception("Failed to fetch players from Sleeper API")

                cursor = conn.cursor()

                # Filter to fantasy-relevant players (QB, RB, WR, TE, K)
                fantasy_positions = {'QB', 'RB', 'WR', 'TE', 'K'}

                for player_id, player_info in players_data.items():
                    position = player_info.get('position')
                    if position not in fantasy_positions:
                        continue

                    stats['processed'] += 1

                    try:
                        transformed = transform_player_data(player_info)

                        # Use savepoint to allow recovery from individual errors
                        cursor.execute("SAVEPOINT player_insert")

                        # Upsert player
                        cursor.execute("""
                            INSERT INTO players (
                                player_id, sleeper_id, full_name, first_name,
                                last_name, position, team, status, injury_status,
                                injury_body_part, years_exp, age, height, weight,
                                college, fantasy_positions
                            ) VALUES (
                                %(player_id)s, %(sleeper_id)s, %(full_name)s,
                                %(first_name)s, %(last_name)s, %(position)s,
                                %(team)s, %(status)s, %(injury_status)s,
                                %(injury_body_part)s, %(years_exp)s, %(age)s,
                                %(height)s, %(weight)s, %(college)s,
                                %(fantasy_positions)s
                            )
                            ON CONFLICT (player_id) DO UPDATE SET
                                full_name = EXCLUDED.full_name,
                                team = EXCLUDED.team,
                                status = EXCLUDED.status,
                                injury_status = EXCLUDED.injury_status,
                                injury_body_part = EXCLUDED.injury_body_part,
                                updated_at = NOW()
                        """, transformed)

                        cursor.execute("RELEASE SAVEPOINT player_insert")

                        if cursor.rowcount == 1:
                            stats['inserted'] += 1
                        else:
                            stats['updated'] += 1

                    except Exception as e:
                        # Rollback to savepoint to allow next insert to proceed
                        cursor.execute("ROLLBACK TO SAVEPOINT player_insert")
                        logger.warning(f"Error processing player {player_id}: {e}")
                        stats['errors'] += 1

                conn.commit()

                self._update_ingestion_log(
                    conn, log_id,
                    stats['processed'], stats['inserted'], stats['updated'],
                    'completed'
                )

                logger.info(f"Player sync completed: {stats}")

            except Exception as e:
                logger.error(f"Player sync failed: {e}")
                self._update_ingestion_log(
                    conn, log_id, stats['processed'], stats['inserted'],
                    stats['updated'], 'failed', str(e)
                )
                raise

        return stats

    def sync_weekly_stats(self, season: int, week: int,
                         use_fallback: bool = True) -> Dict[str, int]:
        """
        Synchronize weekly stats from API to database.

        Args:
            season: NFL season year
            week: Week number
            use_fallback: If True, try scraping if API fails

        Returns:
            Dictionary with sync statistics
        """
        logger.info(f"Starting stats sync for {season} week {week}...")
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'errors': 0}

        with self.get_db_connection() as conn:
            log_id = self._log_ingestion(conn, 'sleeper', 'stats', season, week)

            try:
                # Try Sleeper API first
                weekly_stats = self.sleeper.get_weekly_stats(season, week)

                if not weekly_stats and use_fallback:
                    logger.warning("Sleeper API failed, trying scraper fallback...")
                    self._update_ingestion_log(
                        conn, log_id, 0, 0, 0, 'failed',
                        'Sleeper API returned no data, falling back to scraper'
                    )

                    # Try scraping
                    log_id = self._log_ingestion(conn, 'scraped', 'stats', season, week)
                    df = self.scraper.get_weekly_fantasy_stats(season, week)

                    if df is not None:
                        scraped_stats = transform_pfr_fantasy_stats(df, season)
                        # Convert to dict format like Sleeper
                        weekly_stats = {s.get('full_name', ''): s for s in scraped_stats}
                    else:
                        raise Exception("Both API and scraper failed")

                if not weekly_stats:
                    raise Exception("No stats data available")

                cursor = conn.cursor()

                for player_id, player_stats in weekly_stats.items():
                    stats['processed'] += 1

                    try:
                        transformed = transform_weekly_stats(
                            player_id, player_stats, season, week
                        )

                        # Use savepoint to allow recovery from individual errors
                        cursor.execute("SAVEPOINT stats_insert")

                        cursor.execute("""
                            INSERT INTO player_weekly_stats (
                                player_id, season, week, fantasy_points,
                                fantasy_points_ppr, passing_attempts,
                                passing_completions, passing_yards, passing_tds,
                                interceptions, passing_2pt, rushing_attempts,
                                rushing_yards, rushing_tds, rushing_2pt,
                                targets, receptions, receiving_yards,
                                receiving_tds, receiving_2pt, fumbles,
                                fumbles_lost, source
                            ) VALUES (
                                %(player_id)s, %(season)s, %(week)s,
                                %(fantasy_points)s, %(fantasy_points_ppr)s,
                                %(passing_attempts)s, %(passing_completions)s,
                                %(passing_yards)s, %(passing_tds)s,
                                %(interceptions)s, %(passing_2pt)s,
                                %(rushing_attempts)s, %(rushing_yards)s,
                                %(rushing_tds)s, %(rushing_2pt)s,
                                %(targets)s, %(receptions)s, %(receiving_yards)s,
                                %(receiving_tds)s, %(receiving_2pt)s,
                                %(fumbles)s, %(fumbles_lost)s, %(source)s
                            )
                            ON CONFLICT (player_id, season, week) DO UPDATE SET
                                fantasy_points = EXCLUDED.fantasy_points,
                                fantasy_points_ppr = EXCLUDED.fantasy_points_ppr,
                                passing_yards = EXCLUDED.passing_yards,
                                passing_tds = EXCLUDED.passing_tds,
                                rushing_yards = EXCLUDED.rushing_yards,
                                rushing_tds = EXCLUDED.rushing_tds,
                                receiving_yards = EXCLUDED.receiving_yards,
                                receiving_tds = EXCLUDED.receiving_tds,
                                receptions = EXCLUDED.receptions,
                                targets = EXCLUDED.targets
                        """, transformed)

                        cursor.execute("RELEASE SAVEPOINT stats_insert")

                        if cursor.rowcount == 1:
                            stats['inserted'] += 1
                        else:
                            stats['updated'] += 1

                    except Exception as e:
                        # Rollback to savepoint to allow next insert to proceed
                        cursor.execute("ROLLBACK TO SAVEPOINT stats_insert")
                        logger.warning(f"Error processing stats for {player_id}: {e}")
                        stats['errors'] += 1

                conn.commit()

                self._update_ingestion_log(
                    conn, log_id,
                    stats['processed'], stats['inserted'], stats['updated'],
                    'completed'
                )

                logger.info(f"Stats sync completed for {season} week {week}: {stats}")

            except Exception as e:
                logger.error(f"Stats sync failed: {e}")
                self._update_ingestion_log(
                    conn, log_id, stats['processed'], stats['inserted'],
                    stats['updated'], 'failed', str(e)
                )
                raise

        return stats

    def sync_projections(self, season: int, week: int) -> Dict[str, int]:
        """
        Synchronize projections from Sleeper API.

        Args:
            season: NFL season year
            week: Week number

        Returns:
            Dictionary with sync statistics
        """
        logger.info(f"Starting projections sync for {season} week {week}...")
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'errors': 0}

        with self.get_db_connection() as conn:
            log_id = self._log_ingestion(conn, 'sleeper', 'projections', season, week)

            try:
                projections = self.sleeper.get_weekly_projections(season, week)

                if not projections:
                    raise Exception("No projections data available")

                cursor = conn.cursor()

                for player_id, proj in projections.items():
                    stats['processed'] += 1

                    try:
                        cursor.execute("""
                            INSERT INTO player_projections (
                                player_id, season, week, projected_points,
                                projected_points_ppr, proj_passing_yards,
                                proj_passing_tds, proj_rushing_yards,
                                proj_rushing_tds, proj_receiving_yards,
                                proj_receiving_tds, proj_receptions, source
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                            ON CONFLICT (player_id, season, week, source) DO UPDATE SET
                                projected_points = EXCLUDED.projected_points,
                                projected_points_ppr = EXCLUDED.projected_points_ppr
                        """, (
                            player_id, season, week,
                            proj.get('pts_std', 0),
                            proj.get('pts_ppr', 0),
                            proj.get('pass_yd', 0),
                            proj.get('pass_td', 0),
                            proj.get('rush_yd', 0),
                            proj.get('rush_td', 0),
                            proj.get('rec_yd', 0),
                            proj.get('rec_td', 0),
                            proj.get('rec', 0),
                            'sleeper'
                        ))

                        if cursor.rowcount == 1:
                            stats['inserted'] += 1
                        else:
                            stats['updated'] += 1

                    except Exception as e:
                        logger.warning(f"Error processing projection for {player_id}: {e}")
                        stats['errors'] += 1

                conn.commit()

                self._update_ingestion_log(
                    conn, log_id,
                    stats['processed'], stats['inserted'], stats['updated'],
                    'completed'
                )

                logger.info(f"Projections sync completed: {stats}")

            except Exception as e:
                logger.error(f"Projections sync failed: {e}")
                self._update_ingestion_log(
                    conn, log_id, stats['processed'], stats['inserted'],
                    stats['updated'], 'failed', str(e)
                )
                raise

        return stats

    def sync_matchups(self, season: int, week: int) -> Dict[str, int]:
        """
        Synchronize team matchup context for a prediction week.

        Matchup rows are stored per team so player feature computation can look
        up opponent, home/away, and game date by joining on player.team.
        """
        logger.info(f"Starting matchup sync for {season} week {week}...")
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'errors': 0}

        with self.get_db_connection() as conn:
            log_id = self._log_ingestion(conn, 'espn', 'matchups', season, week)

            try:
                matchups = self.espn.get_week_matchups(season, week)
                if not matchups:
                    raise Exception("No matchup data available")

                cursor = conn.cursor()
                for matchup in matchups:
                    stats['processed'] += 1
                    try:
                        cursor.execute("""
                            INSERT INTO team_weekly_matchups (
                                season, week, team, opponent, is_home, game_date, source
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (season, week, team) DO UPDATE SET
                                opponent = EXCLUDED.opponent,
                                is_home = EXCLUDED.is_home,
                                game_date = EXCLUDED.game_date,
                                source = EXCLUDED.source
                        """, (
                            season,
                            week,
                            matchup.get('team'),
                            matchup.get('opponent'),
                            matchup.get('is_home'),
                            matchup.get('game_date'),
                            matchup.get('source', 'espn'),
                        ))

                        if cursor.rowcount == 1:
                            stats['inserted'] += 1
                        else:
                            stats['updated'] += 1
                    except Exception as e:
                        logger.warning(f"Error processing matchup for {matchup.get('team')}: {e}")
                        stats['errors'] += 1

                conn.commit()
                self._update_ingestion_log(
                    conn, log_id,
                    stats['processed'], stats['inserted'], stats['updated'],
                    'completed'
                )
            except Exception as e:
                logger.error(f"Matchup sync failed: {e}")
                self._update_ingestion_log(
                    conn, log_id, stats['processed'], stats['inserted'],
                    stats['updated'], 'failed', str(e)
                )
                raise

        return stats

    def full_sync(self, season: int, prediction_week: Optional[int] = None,
                 current_week: Optional[int] = None,
                 sync_historical: bool = False) -> Dict[str, Any]:
        """
        Run a full data sync.

        Args:
            season: NFL season year
            prediction_week: Upcoming week being prepared for prediction
            current_week: Backward-compatible alias for prediction_week
            sync_historical: If True, sync all historical weeks

        Returns:
            Dictionary with overall sync results
        """
        prediction_week = prediction_week or current_week
        if prediction_week is None:
            raise ValueError("prediction_week is required")

        logger.info(f"Starting full sync for {season}, prediction week {prediction_week}")
        results = {
            'players': None,
            'stats': {},
            'matchups': None,
            'projections': None,
            'errors': []
        }

        # Sync players
        try:
            results['players'] = self.sync_players()
        except Exception as e:
            logger.error(f"Player sync error: {e}")
            results['errors'].append(f"Players: {e}")

        # Sync historical stats if requested
        completed_week = max(0, prediction_week - 1)
        start_week = 1 if sync_historical else max(1, completed_week - 1)

        for week in range(start_week, completed_week + 1):
            try:
                results['stats'][week] = self.sync_weekly_stats(season, week)
            except Exception as e:
                logger.error(f"Stats sync error for week {week}: {e}")
                results['errors'].append(f"Stats week {week}: {e}")

        try:
            results['matchups'] = self.sync_matchups(season, prediction_week)
        except Exception as e:
            logger.error(f"Matchup sync error: {e}")
            results['errors'].append(f"Matchups: {e}")

        # Sync projections for current/next week
        try:
            results['projections'] = self.sync_projections(season, prediction_week)
        except Exception as e:
            logger.error(f"Projections sync error: {e}")
            results['errors'].append(f"Projections: {e}")

        logger.info(f"Full sync completed with {len(results['errors'])} errors")
        return results

    def get_current_season_info(self) -> Dict[str, int]:
        """
        Get current NFL season and week from Sleeper.

        Returns:
            Dictionary with 'season' and 'week' keys
        """
        state = self.sleeper.get_nfl_state()
        if state:
            return {
                'season': state.get('season', datetime.now().year),
                'week': state.get('week', 1)
            }
        return {
            'season': datetime.now().year,
            'week': 1
        }

    def close(self):
        """Close all client connections."""
        if self._sleeper_client:
            self._sleeper_client.close()
        if self._espn_client:
            self._espn_client.close()
        if self._scraper:
            self._scraper.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == "__main__":
    # Quick test / manual sync
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Fantasy Football Data Pipeline")
    print("=" * 50)

    with DataOrchestrator() as orchestrator:
        # Get current season info
        info = orchestrator.get_current_season_info()
        print(f"\nCurrent NFL Season: {info['season']}, Week: {info['week']}")

        # Uncomment to run sync (requires database to be running)
        # print("\nSyncing players...")
        # orchestrator.sync_players()
        #
        # print(f"\nSyncing stats for week {info['week']}...")
        # orchestrator.sync_weekly_stats(info['season'], info['week'])

        print("\nOrchestrator initialized successfully!")
        print("Run 'docker-compose up -d' to start the database, then:")
        print("  orchestrator.sync_players()")
        print("  orchestrator.sync_weekly_stats(2024, 1)")
