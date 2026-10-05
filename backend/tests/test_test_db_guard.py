"""
Unit tests for the E2E test-database safety guard.

E2E fixtures truncate every table, so they must never point at the
development database.
"""

import pytest

from tests.conftest import (
    DEFAULT_TEST_DATABASE_URL,
    assert_safe_test_database,
    get_test_database_url,
)


class TestTestDatabaseGuard:
    @pytest.mark.unit
    def test_default_url_targets_test_database(self, monkeypatch):
        monkeypatch.delenv('TEST_DATABASE_URL', raising=False)

        assert get_test_database_url() == DEFAULT_TEST_DATABASE_URL
        assert assert_safe_test_database(get_test_database_url()) == 'football_test'

    @pytest.mark.unit
    def test_rejects_development_database(self, monkeypatch):
        monkeypatch.delenv('DB_NAME', raising=False)

        with pytest.raises(RuntimeError, match='football_dev'):
            assert_safe_test_database('postgresql://postgres:postgres@localhost:5432/football_dev')

    @pytest.mark.unit
    def test_rejects_database_matching_db_name_even_if_named_test(self, monkeypatch):
        monkeypatch.setenv('DB_NAME', 'football_test')

        with pytest.raises(RuntimeError):
            assert_safe_test_database('postgresql://postgres:postgres@localhost:5432/football_test')

    @pytest.mark.unit
    def test_rejects_url_without_database_name(self):
        with pytest.raises(RuntimeError):
            assert_safe_test_database('postgresql://postgres:postgres@localhost:5432')

    @pytest.mark.unit
    def test_accepts_custom_test_database(self, monkeypatch):
        monkeypatch.delenv('DB_NAME', raising=False)

        assert assert_safe_test_database(
            'postgresql://u:p@db.example:5433/ci_football_test'
        ) == 'ci_football_test'
