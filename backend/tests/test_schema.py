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
