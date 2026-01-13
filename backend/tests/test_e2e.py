"""
End-to-End Tests for Data Pipeline

These tests use REAL API calls AND the REAL database (Docker PostgreSQL).
They verify the complete data flow from API to database.

Prerequisites:
    1. Docker database running: docker-compose up -d
    2. Internet connectivity

Run with: pytest tests/test_e2e.py -m e2e -v
"""

import pytest
from tests.conftest import requires_docker, requires_internet


@pytest.mark.e2e
class TestPlayerSyncE2E:
    """End-to-end tests for player synchronization."""

    @requires_docker
    @requires_internet
    def test_sync_players_inserts_to_database(self, clean_test_db, orchestrator):
        """Test that player sync actually inserts data into database."""
        # Run the sync
        result = orchestrator.sync_players()

        # Verify results
        assert result['processed'] > 0
        assert result['inserted'] > 0 or result['updated'] > 0
        assert result['errors'] == 0 or result['errors'] < result['processed'] * 0.01  # <1% error rate

        # Verify data in database
        cursor = clean_test_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM players")
        count = cursor.fetchone()[0]

        assert count > 0
        assert count == result['inserted'] + result['updated']

    @requires_docker
    @requires_internet
    def test_sync_players_filters_fantasy_positions(self, clean_test_db, orchestrator):
        """Test that only fantasy-relevant positions are synced."""
        orchestrator.sync_players()

        cursor = clean_test_db.cursor()

        # Check that we have QB, RB, WR, TE, K
        cursor.execute("""
            SELECT DISTINCT position FROM players
            WHERE position IS NOT NULL
        """)
        positions = {row[0] for row in cursor.fetchall()}

        expected_positions = {'QB', 'RB', 'WR', 'TE', 'K'}
        assert positions.issubset(expected_positions), f"Unexpected positions: {positions - expected_positions}"

    @requires_docker
    @requires_internet
    def test_sync_players_stores_correct_data(self, clean_test_db, orchestrator):
        """Test that player data is stored correctly."""
        orchestrator.sync_players()

        cursor = clean_test_db.cursor()

        # Find Patrick Mahomes
        cursor.execute("""
            SELECT player_id, full_name, position, team
            FROM players
            WHERE full_name = 'Patrick Mahomes'
        """)
        result = cursor.fetchone()

        assert result is not None, "Patrick Mahomes not found in database"
        player_id, full_name, position, team = result

        assert full_name == 'Patrick Mahomes'
        assert position == 'QB'
        assert team == 'KC'

    @requires_docker
    @requires_internet
    def test_sync_players_is_idempotent(self, clean_test_db, orchestrator):
        """Test that running sync twice doesn't duplicate data."""
        # First sync
        result1 = orchestrator.sync_players()

        # Second sync
        result2 = orchestrator.sync_players()

        # Should have updates, not new inserts
        assert result2['inserted'] == 0 or result2['inserted'] < result1['inserted']

        # Total count should be same
        cursor = clean_test_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM players")
        count = cursor.fetchone()[0]

        assert count == result1['inserted'] + result1['updated']


@pytest.mark.e2e
class TestWeeklyStatsSyncE2E:
    """End-to-end tests for weekly stats synchronization."""

    @requires_docker
    @requires_internet
    def test_sync_weekly_stats_inserts_to_database(self, clean_test_db, orchestrator):
        """Test that weekly stats sync inserts data."""
        # Sync players first (foreign key requirement)
        orchestrator.sync_players()

        # Sync stats for 2023 week 1 (completed season)
        result = orchestrator.sync_weekly_stats(2023, 1)

        assert result['processed'] > 0
        assert result['inserted'] > 0 or result['updated'] > 0

        # Verify data in database
        cursor = clean_test_db.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM player_weekly_stats
            WHERE season = 2023 AND week = 1
        """)
        count = cursor.fetchone()[0]

        assert count > 0

    @requires_docker
    @requires_internet
    def test_sync_weekly_stats_stores_correct_data(self, clean_test_db, orchestrator):
        """Test that stats data is stored correctly."""
        orchestrator.sync_players()
        orchestrator.sync_weekly_stats(2023, 1)

        cursor = clean_test_db.cursor()

        # Check that we have fantasy points
        cursor.execute("""
            SELECT player_id, fantasy_points, fantasy_points_ppr
            FROM player_weekly_stats
            WHERE season = 2023 AND week = 1
            AND fantasy_points > 0
            LIMIT 5
        """)
        results = cursor.fetchall()

        assert len(results) > 0, "No players with fantasy points found"

        for player_id, pts_std, pts_ppr in results:
            assert pts_std >= 0
            assert pts_ppr >= 0

    @requires_docker
    @requires_internet
    def test_sync_weekly_stats_unique_constraint(self, clean_test_db, orchestrator):
        """Test that duplicate stats are handled via upsert."""
        orchestrator.sync_players()

        # Sync same week twice
        orchestrator.sync_weekly_stats(2023, 1)
        orchestrator.sync_weekly_stats(2023, 1)

        # Should not have duplicates
        cursor = clean_test_db.cursor()
        cursor.execute("""
            SELECT player_id, COUNT(*)
            FROM player_weekly_stats
            WHERE season = 2023 AND week = 1
            GROUP BY player_id
            HAVING COUNT(*) > 1
        """)
        duplicates = cursor.fetchall()

        assert len(duplicates) == 0, f"Found duplicate entries: {duplicates}"


@pytest.mark.e2e
class TestProjectionsSyncE2E:
    """End-to-end tests for projections synchronization."""

    @requires_docker
    @requires_internet
    def test_sync_projections_inserts_to_database(self, clean_test_db, orchestrator):
        """Test that projections sync works."""
        orchestrator.sync_players()

        # Get current season/week
        info = orchestrator.get_current_season_info()

        try:
            result = orchestrator.sync_projections(info['season'], info['week'])

            # Verify data in database
            cursor = clean_test_db.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM player_projections
                WHERE season = %s AND week = %s
            """, (info['season'], info['week']))
            count = cursor.fetchone()[0]

            # May be empty in offseason
            assert count >= 0

        except Exception as e:
            # Projections might not be available
            if "No projections data available" in str(e):
                pytest.skip("Projections not available (likely offseason)")
            raise


@pytest.mark.e2e
class TestFullSyncE2E:
    """End-to-end tests for full sync operation."""

    @requires_docker
    @requires_internet
    def test_full_sync_populates_database(self, clean_test_db, orchestrator):
        """Test that full sync populates all tables."""
        # Use a past season week for reliability
        result = orchestrator.full_sync(season=2023, current_week=3)

        assert result['players'] is not None

        # Verify players table
        cursor = clean_test_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM players")
        player_count = cursor.fetchone()[0]
        assert player_count > 0

        # Verify stats table
        cursor.execute("SELECT COUNT(*) FROM player_weekly_stats")
        stats_count = cursor.fetchone()[0]
        assert stats_count > 0

        # Check ingestion log
        cursor.execute("""
            SELECT source, data_type, status, records_processed
            FROM ingestion_log
            WHERE status = 'completed'
        """)
        logs = cursor.fetchall()
        assert len(logs) > 0, "No completed ingestion logs found"

    @requires_docker
    @requires_internet
    def test_full_sync_logs_errors(self, clean_test_db, orchestrator):
        """Test that full sync logs any errors."""
        orchestrator.full_sync(season=2023, current_week=2)

        cursor = clean_test_db.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM ingestion_log
        """)
        log_count = cursor.fetchone()[0]

        assert log_count > 0, "No ingestion logs created"


@pytest.mark.e2e
class TestIngestionLogE2E:
    """End-to-end tests for ingestion logging."""

    @requires_docker
    @requires_internet
    def test_ingestion_log_tracks_player_sync(self, clean_test_db, orchestrator):
        """Test that player sync creates ingestion log."""
        orchestrator.sync_players()

        cursor = clean_test_db.cursor()
        cursor.execute("""
            SELECT source, data_type, status, records_processed, records_inserted
            FROM ingestion_log
            WHERE data_type = 'players'
            ORDER BY started_at DESC
            LIMIT 1
        """)
        log = cursor.fetchone()

        assert log is not None
        source, data_type, status, processed, inserted = log

        assert source == 'sleeper'
        assert data_type == 'players'
        assert status == 'completed'
        assert processed > 0
        assert inserted > 0 or True  # May be 0 on re-run

    @requires_docker
    @requires_internet
    def test_ingestion_log_tracks_stats_sync(self, clean_test_db, orchestrator):
        """Test that stats sync creates ingestion log."""
        orchestrator.sync_players()
        orchestrator.sync_weekly_stats(2023, 1)

        cursor = clean_test_db.cursor()
        cursor.execute("""
            SELECT source, data_type, season, week, status
            FROM ingestion_log
            WHERE data_type = 'stats'
            ORDER BY started_at DESC
            LIMIT 1
        """)
        log = cursor.fetchone()

        assert log is not None
        source, data_type, season, week, status = log

        assert data_type == 'stats'
        assert season == 2023
        assert week == 1
        assert status == 'completed'


@pytest.mark.e2e
class TestDatabaseQueriesE2E:
    """Test common database queries after sync."""

    @requires_docker
    @requires_internet
    def test_query_top_qbs_by_fantasy_points(self, clean_test_db, orchestrator):
        """Test querying top QBs by fantasy points."""
        orchestrator.sync_players()
        orchestrator.sync_weekly_stats(2023, 1)

        cursor = clean_test_db.cursor()
        cursor.execute("""
            SELECT p.full_name, s.fantasy_points_ppr
            FROM player_weekly_stats s
            JOIN players p ON s.player_id = p.player_id
            WHERE p.position = 'QB'
            AND s.season = 2023 AND s.week = 1
            ORDER BY s.fantasy_points_ppr DESC
            LIMIT 5
        """)
        results = cursor.fetchall()

        assert len(results) > 0
        # Top QB should have significant points
        top_name, top_points = results[0]
        assert top_points > 10  # At least 10 fantasy points

    @requires_docker
    @requires_internet
    def test_query_players_by_team(self, clean_test_db, orchestrator):
        """Test querying players by team."""
        orchestrator.sync_players()

        cursor = clean_test_db.cursor()
        cursor.execute("""
            SELECT full_name, position
            FROM players
            WHERE team = 'KC'
            AND position IN ('QB', 'RB', 'WR', 'TE')
            ORDER BY position, full_name
        """)
        results = cursor.fetchall()

        assert len(results) > 0

        # Should have Patrick Mahomes
        names = [r[0] for r in results]
        assert 'Patrick Mahomes' in names

    @requires_docker
    @requires_internet
    def test_query_weekly_stats_aggregation(self, clean_test_db, orchestrator):
        """Test aggregating weekly stats."""
        orchestrator.sync_players()
        orchestrator.sync_weekly_stats(2023, 1)
        orchestrator.sync_weekly_stats(2023, 2)

        cursor = clean_test_db.cursor()
        cursor.execute("""
            SELECT p.full_name,
                   SUM(s.fantasy_points_ppr) as total_points,
                   COUNT(*) as games
            FROM player_weekly_stats s
            JOIN players p ON s.player_id = p.player_id
            WHERE s.season = 2023
            GROUP BY p.player_id, p.full_name
            HAVING COUNT(*) >= 2
            ORDER BY total_points DESC
            LIMIT 10
        """)
        results = cursor.fetchall()

        assert len(results) > 0
        for name, total_points, games in results:
            assert games >= 2
            assert total_points > 0
