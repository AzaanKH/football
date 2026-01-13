"""
Pytest Configuration and Shared Fixtures

This file contains fixtures used across all test types:
- Unit tests (mocked dependencies)
- Integration tests (real API, mocked DB)
- End-to-end tests (real API + real DB)
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any, Generator

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Sample Data Fixtures
# =============================================================================

@pytest.fixture
def sample_sleeper_player() -> Dict[str, Any]:
    """Sample player data as returned by Sleeper API."""
    return {
        "player_id": "4046",
        "full_name": "Patrick Mahomes",
        "first_name": "Patrick",
        "last_name": "Mahomes",
        "position": "QB",
        "team": "KC",
        "status": "Active",
        "injury_status": None,
        "injury_body_part": None,
        "years_exp": 7,
        "age": 28,
        "height": "6'2\"",
        "weight": 225,
        "college": "Texas Tech",
        "fantasy_positions": ["QB"]
    }


@pytest.fixture
def sample_sleeper_players() -> Dict[str, Dict]:
    """Sample players dictionary from Sleeper API."""
    return {
        "4046": {
            "player_id": "4046",
            "full_name": "Patrick Mahomes",
            "first_name": "Patrick",
            "last_name": "Mahomes",
            "position": "QB",
            "team": "KC",
            "status": "Active",
            "injury_status": None,
            "years_exp": 7,
            "age": 28,
            "fantasy_positions": ["QB"]
        },
        "4199": {
            "player_id": "4199",
            "full_name": "Josh Allen",
            "first_name": "Josh",
            "last_name": "Allen",
            "position": "QB",
            "team": "BUF",
            "status": "Active",
            "injury_status": None,
            "years_exp": 6,
            "age": 27,
            "fantasy_positions": ["QB"]
        },
        "5850": {
            "player_id": "5850",
            "full_name": "Saquon Barkley",
            "first_name": "Saquon",
            "last_name": "Barkley",
            "position": "RB",
            "team": "PHI",
            "status": "Active",
            "injury_status": None,
            "years_exp": 6,
            "age": 27,
            "fantasy_positions": ["RB"]
        },
        "DEF_KC": {
            "player_id": "DEF_KC",
            "full_name": "Kansas City Chiefs",
            "position": "DEF",  # Should be filtered out
            "team": "KC",
            "fantasy_positions": ["DEF"]
        }
    }


@pytest.fixture
def sample_weekly_stats() -> Dict[str, Dict]:
    """Sample weekly stats from Sleeper API."""
    return {
        "4046": {
            "pts_std": 25.5,
            "pts_ppr": 25.5,
            "pass_att": 35,
            "pass_cmp": 28,
            "pass_yd": 312,
            "pass_td": 3,
            "pass_int": 1,
            "rush_att": 4,
            "rush_yd": 28,
            "rush_td": 0,
            "fum": 0,
            "fum_lost": 0
        },
        "5850": {
            "pts_std": 18.2,
            "pts_ppr": 22.2,
            "rush_att": 22,
            "rush_yd": 112,
            "rush_td": 1,
            "rec_tgt": 6,
            "rec": 4,
            "rec_yd": 30,
            "rec_td": 0,
            "fum": 0,
            "fum_lost": 0
        }
    }


@pytest.fixture
def sample_projections() -> Dict[str, Dict]:
    """Sample projections from Sleeper API."""
    return {
        "4046": {
            "pts_std": 22.0,
            "pts_ppr": 22.0,
            "pass_yd": 285,
            "pass_td": 2,
            "rush_yd": 15,
            "rush_td": 0
        },
        "5850": {
            "pts_std": 15.0,
            "pts_ppr": 18.5,
            "rush_yd": 85,
            "rush_td": 0.8,
            "rec": 3.5,
            "rec_yd": 25,
            "rec_td": 0.2
        }
    }


@pytest.fixture
def sample_nfl_state() -> Dict[str, Any]:
    """Sample NFL state from Sleeper API."""
    return {
        "season": 2024,
        "week": 10,
        "season_type": "regular",
        "display_week": 10,
        "leg": 10
    }


# =============================================================================
# Mock Fixtures for Unit Tests
# =============================================================================

@pytest.fixture
def mock_httpx_client():
    """Mock httpx.Client for unit tests."""
    with patch('httpx.Client') as mock:
        client_instance = MagicMock()
        mock.return_value = client_instance
        yield client_instance


@pytest.fixture
def mock_requests_session():
    """Mock requests.Session for scraper unit tests."""
    with patch('requests.Session') as mock:
        session_instance = MagicMock()
        mock.return_value = session_instance
        yield session_instance


@pytest.fixture
def mock_db_connection():
    """Mock database connection for unit tests."""
    with patch('psycopg2.connect') as mock:
        conn_instance = MagicMock()
        cursor_instance = MagicMock()
        conn_instance.cursor.return_value = cursor_instance
        conn_instance.__enter__ = MagicMock(return_value=conn_instance)
        conn_instance.__exit__ = MagicMock(return_value=False)
        mock.return_value = conn_instance
        yield {
            'connect': mock,
            'connection': conn_instance,
            'cursor': cursor_instance
        }


# =============================================================================
# Database Fixtures for E2E Tests
# =============================================================================

@pytest.fixture(scope="session")
def docker_db_url() -> str:
    """Database URL for Docker PostgreSQL."""
    return os.getenv(
        'TEST_DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/football_dev'
    )


@pytest.fixture(scope="function")
def clean_test_db(docker_db_url):
    """
    Provide a clean database for each E2E test.
    Truncates all tables before and after each test.
    """
    import psycopg2

    conn = None
    try:
        conn = psycopg2.connect(docker_db_url)
        cursor = conn.cursor()

        # Truncate all tables before test
        tables = [
            'player_weekly_stats',
            'player_projections',
            'team_defense_stats',
            'ingestion_log',
            'players'
        ]
        for table in tables:
            cursor.execute(f"TRUNCATE TABLE {table} CASCADE")
        conn.commit()

        yield conn

        # Truncate after test
        for table in tables:
            cursor.execute(f"TRUNCATE TABLE {table} CASCADE")
        conn.commit()

    finally:
        if conn:
            conn.close()


@pytest.fixture
def db_connection(docker_db_url):
    """
    Provide a database connection for tests.
    Does NOT clean the database (for inspection).
    """
    import psycopg2

    conn = psycopg2.connect(docker_db_url)
    yield conn
    conn.close()


# =============================================================================
# Client Fixtures
# =============================================================================

@pytest.fixture
def sleeper_client():
    """
    Create a real SleeperClient for integration tests.
    """
    from data_pipeline import SleeperClient
    client = SleeperClient()
    yield client
    client.close()


@pytest.fixture
def espn_client():
    """
    Create a real ESPNClient for integration tests.
    """
    from data_pipeline import ESPNClient
    client = ESPNClient()
    yield client
    client.close()


@pytest.fixture
def scraper():
    """
    Create a real ProFootballReferenceScraper for integration tests.
    Note: Use sparingly due to rate limits.
    """
    from data_pipeline import ProFootballReferenceScraper
    scraper = ProFootballReferenceScraper(delay=3.0)
    yield scraper
    scraper.close()


@pytest.fixture
def orchestrator(docker_db_url):
    """
    Create a DataOrchestrator connected to test database.
    """
    from data_pipeline import DataOrchestrator
    orch = DataOrchestrator(database_url=docker_db_url)
    yield orch
    orch.close()


# =============================================================================
# Utility Fixtures
# =============================================================================

@pytest.fixture
def capture_logs(caplog):
    """Capture and return log messages."""
    import logging
    caplog.set_level(logging.DEBUG)
    return caplog


# =============================================================================
# Skip Conditions
# =============================================================================

def is_docker_running() -> bool:
    """Check if Docker database is accessible."""
    import psycopg2
    try:
        conn = psycopg2.connect(
            'postgresql://postgres:postgres@localhost:5432/football_dev',
            connect_timeout=3
        )
        conn.close()
        return True
    except Exception:
        return False


def has_internet() -> bool:
    """Check if internet is available."""
    import socket
    try:
        socket.create_connection(("api.sleeper.app", 443), timeout=3)
        return True
    except OSError:
        return False


# Pytest markers for conditional skipping
requires_docker = pytest.mark.skipif(
    not is_docker_running(),
    reason="Docker database not running (run: docker-compose up -d)"
)

requires_internet = pytest.mark.skipif(
    not has_internet(),
    reason="No internet connection"
)
