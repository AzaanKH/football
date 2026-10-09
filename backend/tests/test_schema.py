"""
Fresh-database schema test.

Applies init_db.sql to a brand-new, throwaway database exactly as Docker does
on a fresh volume, so schema errors surface here instead of for new clones.

Run with: pytest tests/test_schema.py -m e2e -v   (needs: docker-compose up -d)
"""

import uuid

import pytest

from tests.conftest import (
    SCHEMA_FILE,
    _server_url,
    get_test_database_url,
    requires_docker,
)

EXPECTED_TABLES = {
    'players',
    'player_weekly_stats',
    'team_defense_stats',
    'team_weekly_matchups',
    'player_projections',
    'ingestion_log',
    'player_features',
}


@pytest.fixture
def fresh_schema_db():
    """Create an empty database, apply init_db.sql, drop it afterwards."""
    import psycopg2
    from psycopg2.extensions import parse_dsn, make_dsn

    dbname = f"football_schema_test_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(_server_url(get_test_database_url()))
    admin.autocommit = True
    admin.cursor().execute(f'CREATE DATABASE "{dbname}"')

    params = parse_dsn(get_test_database_url())
    params['dbname'] = dbname
    conn = psycopg2.connect(make_dsn(**params))
    try:
        with open(SCHEMA_FILE, encoding='utf-8') as f:
            conn.cursor().execute(f.read())
        conn.commit()
        yield conn
    finally:
        conn.close()
        admin.cursor().execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        admin.close()


@pytest.mark.e2e
class TestFreshSchema:
    @requires_docker
    def test_init_db_creates_all_tables(self, fresh_schema_db):
        cursor = fresh_schema_db.cursor()
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        tables = {row[0] for row in cursor.fetchall()}

        assert EXPECTED_TABLES <= tables

    @requires_docker
    def test_weekly_stats_upsert_on_player_week_key(self, fresh_schema_db):
        """The pipeline upserts on (player_id, season, week); that key must be enforceable."""
        cursor = fresh_schema_db.cursor()
        upsert = """
            INSERT INTO player_weekly_stats (player_id, season, week, fantasy_points_ppr)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (player_id, season, week)
            DO UPDATE SET fantasy_points_ppr = EXCLUDED.fantasy_points_ppr
        """
        cursor.execute(upsert, ('4034', 2025, 5, 12.5))
        cursor.execute(upsert, ('4034', 2025, 5, 18.0))
        fresh_schema_db.commit()

        cursor.execute("""
            SELECT COUNT(*), MAX(fantasy_points_ppr) FROM player_weekly_stats
            WHERE player_id = '4034' AND season = 2025 AND week = 5
        """)
        assert cursor.fetchone() == (1, 18.0)

    @requires_docker
    def test_resync_without_game_context_keeps_stored_context(self, fresh_schema_db):
        """Stat corrections apply; a failed or partial enrichment never erases context."""
        from data_pipeline.orchestrator import DataOrchestrator as Orchestrator

        cursor = fresh_schema_db.cursor()
        cursor.execute("INSERT INTO players (player_id, full_name, position) VALUES ('p1', 'Test', 'WR')")
        upsert = Orchestrator.weekly_stats_upsert_sql()
        stats = dict.fromkeys(Orchestrator.WEEKLY_STAT_COLUMNS, 0)
        stats.update(player_id='p1', season=2025, week=5, targets=8, source='sleeper')

        context = dict(team='PHI', opponent='DAL', game_date='2025-10-05',
                       off_snaps=50, team_off_snaps=65)
        cursor.execute(upsert, {**stats, 'fantasy_points_ppr': 12.5, **context})
        # Enrichment failed: every context field NULL, stats corrected
        cursor.execute(upsert, {**stats, 'fantasy_points_ppr': 14.0,
                                **dict.fromkeys(Orchestrator.GAME_CONTEXT_COLUMNS)})
        # Partial enrichment: snaps updated, the rest missing
        cursor.execute(upsert, {**stats, 'fantasy_points_ppr': 14.0,
                                **dict.fromkeys(Orchestrator.GAME_CONTEXT_COLUMNS), 'off_snaps': 52})
        fresh_schema_db.commit()

        cursor.execute("""
            SELECT fantasy_points_ppr, team, opponent, game_date::text, off_snaps, team_off_snaps
            FROM player_weekly_stats WHERE player_id = 'p1'
        """)
        assert cursor.fetchone() == (14.0, 'PHI', 'DAL', '2025-10-05', 52, 65)

    @requires_docker
    def test_played_flag_requires_an_opportunity(self, fresh_schema_db):
        """Inactive weeks (0 points, 0 opportunities) must not count as games."""
        cursor = fresh_schema_db.cursor()
        cursor.executemany("""
            INSERT INTO player_weekly_stats
                (player_id, season, week, passing_attempts, rushing_attempts, targets, receptions,
                 fantasy_points_ppr)
            VALUES (%s, 2025, %s, %s, %s, %s, %s, %s)
        """, [
            ('p1', 1, 0, 0, 0, 0, 0),                 # inactive
            ('p1', 2, None, None, None, None, None),  # missing stats
            ('p1', 3, 0, 0, 1, 0, 0),                 # one target, no catch
            ('p1', 4, 0, 1, 0, 0, 0.3),               # one carry
            ('p1', 5, 30, 0, 0, 0, 18.2),             # QB passing only
            ('p1', 6, 0, 0, 0, 0, 9.0),               # kicker / return TD: points, no touches
        ])
        fresh_schema_db.commit()

        cursor.execute("SELECT week, played FROM player_weekly_stats ORDER BY week")
        assert cursor.fetchall() == [
            (1, False), (2, False), (3, True), (4, True), (5, True), (6, True)
        ]
