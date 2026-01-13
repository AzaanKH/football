"""
Unit Tests for Pro Football Reference Scraper

These tests use mocked HTTP responses to test the scraper
without making actual web requests.
"""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from bs4 import BeautifulSoup

from data_pipeline.scraper import (
    ProFootballReferenceScraper,
    transform_pfr_fantasy_stats
)


class TestProFootballReferenceScraperUnit:
    """Unit tests for ProFootballReferenceScraper with mocked HTTP."""

    @pytest.fixture
    def mock_scraper(self):
        """Create a scraper with mocked requests.Session."""
        with patch('data_pipeline.scraper.requests.Session') as mock:
            session_instance = MagicMock()
            mock.return_value = session_instance
            scraper = ProFootballReferenceScraper(delay=0.01)  # Short delay for tests
            scraper.session = session_instance
            yield scraper, session_instance
            scraper.close()

    @pytest.fixture
    def sample_fantasy_html(self):
        """Sample HTML for fantasy stats table."""
        return """
        <html>
        <body>
        <table id="fantasy">
            <thead>
                <tr>
                    <th>Rk</th>
                    <th>Player</th>
                    <th>Tm</th>
                    <th>FantPos</th>
                    <th>G</th>
                    <th>Passing_Yds</th>
                    <th>Passing_TD</th>
                    <th>FantPt</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>1</td>
                    <td>Patrick Mahomes</td>
                    <td>KAN</td>
                    <td>QB</td>
                    <td>16</td>
                    <td>4183</td>
                    <td>27</td>
                    <td>321.5</td>
                </tr>
                <tr>
                    <td>2</td>
                    <td>Josh Allen</td>
                    <td>BUF</td>
                    <td>QB</td>
                    <td>16</td>
                    <td>4306</td>
                    <td>29</td>
                    <td>389.2</td>
                </tr>
            </tbody>
        </table>
        </body>
        </html>
        """

    @pytest.mark.unit
    def test_init_creates_session_with_headers(self):
        """Test that scraper initializes with correct headers."""
        with patch('data_pipeline.scraper.requests.Session') as mock:
            session_instance = MagicMock()
            mock.return_value = session_instance

            ProFootballReferenceScraper(delay=3.0)

            session_instance.headers.update.assert_called_once()
            headers = session_instance.headers.update.call_args[0][0]
            assert 'User-Agent' in headers
            assert 'Accept' in headers

    @pytest.mark.unit
    def test_get_page_success(self, mock_scraper, sample_fantasy_html):
        """Test successful page fetch."""
        scraper, session_mock = mock_scraper

        response_mock = MagicMock()
        response_mock.content = sample_fantasy_html.encode()
        response_mock.raise_for_status = MagicMock()
        session_mock.get.return_value = response_mock

        result = scraper._get_page("https://example.com")

        assert result is not None
        assert isinstance(result, BeautifulSoup)
        session_mock.get.assert_called_once()

    @pytest.mark.unit
    def test_get_page_network_error(self, mock_scraper):
        """Test handling of network errors."""
        scraper, session_mock = mock_scraper

        import requests
        session_mock.get.side_effect = requests.RequestException("Network error")

        result = scraper._get_page("https://example.com")

        assert result is None

    @pytest.mark.unit
    def test_get_fantasy_stats_success(self, mock_scraper, sample_fantasy_html):
        """Test fetching fantasy stats."""
        scraper, session_mock = mock_scraper

        response_mock = MagicMock()
        response_mock.content = sample_fantasy_html.encode()
        response_mock.raise_for_status = MagicMock()
        session_mock.get.return_value = response_mock

        result = scraper.get_fantasy_stats(2024)

        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2

    @pytest.mark.unit
    def test_get_fantasy_stats_no_table(self, mock_scraper):
        """Test handling of missing table."""
        scraper, session_mock = mock_scraper

        html_no_table = "<html><body><p>No table here</p></body></html>"
        response_mock = MagicMock()
        response_mock.content = html_no_table.encode()
        response_mock.raise_for_status = MagicMock()
        session_mock.get.return_value = response_mock

        result = scraper.get_fantasy_stats(2024)

        assert result is None

    @pytest.mark.unit
    def test_get_weekly_fantasy_stats_success(self, mock_scraper, sample_fantasy_html):
        """Test fetching weekly fantasy stats."""
        scraper, session_mock = mock_scraper

        response_mock = MagicMock()
        response_mock.content = sample_fantasy_html.encode()
        response_mock.raise_for_status = MagicMock()
        session_mock.get.return_value = response_mock

        result = scraper.get_weekly_fantasy_stats(2024, 10)

        assert result is not None
        assert 'season' in result.columns
        assert 'week' in result.columns
        assert result['season'].iloc[0] == 2024
        assert result['week'].iloc[0] == 10

    @pytest.mark.unit
    def test_rate_limiting(self, mock_scraper):
        """Test rate limiting delays requests."""
        scraper, session_mock = mock_scraper

        scraper.delay = 0.1  # 100ms

        import time
        start = time.time()

        scraper._rate_limit()
        scraper._rate_limit()

        elapsed = time.time() - start
        assert elapsed >= 0.09  # Allow 10% tolerance

    @pytest.mark.unit
    def test_context_manager(self):
        """Test context manager closes session."""
        with patch('data_pipeline.scraper.requests.Session') as mock:
            session_instance = MagicMock()
            mock.return_value = session_instance

            with ProFootballReferenceScraper() as scraper:
                pass

            session_instance.close.assert_called_once()

    @pytest.mark.unit
    def test_get_passing_stats_url(self, mock_scraper):
        """Test correct URL construction for passing stats."""
        scraper, session_mock = mock_scraper

        html_with_table = """
        <html><body>
        <table id="passing"><thead><tr><th>Rk</th></tr></thead>
        <tbody><tr><td>1</td></tr></tbody></table>
        </body></html>
        """
        response_mock = MagicMock()
        response_mock.content = html_with_table.encode()
        response_mock.raise_for_status = MagicMock()
        session_mock.get.return_value = response_mock

        scraper.get_passing_stats(2024)

        called_url = session_mock.get.call_args[0][0]
        assert '/years/2024/passing.htm' in called_url

    @pytest.mark.unit
    def test_get_rushing_stats_url(self, mock_scraper):
        """Test correct URL construction for rushing stats."""
        scraper, session_mock = mock_scraper

        html_with_table = """
        <html><body>
        <table id="rushing"><thead><tr><th>Rk</th></tr></thead>
        <tbody><tr><td>1</td></tr></tbody></table>
        </body></html>
        """
        response_mock = MagicMock()
        response_mock.content = html_with_table.encode()
        response_mock.raise_for_status = MagicMock()
        session_mock.get.return_value = response_mock

        scraper.get_rushing_stats(2024)

        called_url = session_mock.get.call_args[0][0]
        assert '/years/2024/rushing.htm' in called_url

    @pytest.mark.unit
    def test_get_receiving_stats_url(self, mock_scraper):
        """Test correct URL construction for receiving stats."""
        scraper, session_mock = mock_scraper

        html_with_table = """
        <html><body>
        <table id="receiving"><thead><tr><th>Rk</th></tr></thead>
        <tbody><tr><td>1</td></tr></tbody></table>
        </body></html>
        """
        response_mock = MagicMock()
        response_mock.content = html_with_table.encode()
        response_mock.raise_for_status = MagicMock()
        session_mock.get.return_value = response_mock

        scraper.get_receiving_stats(2024)

        called_url = session_mock.get.call_args[0][0]
        assert '/years/2024/receiving.htm' in called_url


class TestTransformPFRFantasyStats:
    """Tests for PFR stats transformation."""

    @pytest.mark.unit
    def test_transform_basic_stats(self):
        """Test transforming basic fantasy stats."""
        df = pd.DataFrame({
            'Player': ['Patrick Mahomes', 'Josh Allen'],
            'Tm': ['KAN', 'BUF'],
            'FantPos': ['QB', 'QB'],
            'Passing_Yds': [4183, 4306],
            'Passing_TD': [27, 29],
            'FantPt': [321.5, 389.2]
        })

        results = transform_pfr_fantasy_stats(df, 2024)

        assert len(results) == 2
        assert results[0]['full_name'] == 'Patrick Mahomes'
        assert results[0]['team'] == 'KAN'
        assert results[0]['position'] == 'QB'
        assert results[0]['season'] == 2024
        assert results[0]['source'] == 'scraped'

    @pytest.mark.unit
    def test_transform_with_missing_values(self):
        """Test transforming data with NaN values."""
        df = pd.DataFrame({
            'Player': ['Test Player'],
            'Tm': ['TST'],
            'Passing_Yds': [None],
            'Rushing_Yds': [100.0]
        })

        results = transform_pfr_fantasy_stats(df, 2024)

        assert len(results) == 1
        # NaN should be converted to 0
        assert results[0].get('passing_yards', 0) == 0
        assert results[0]['rushing_yards'] == 100.0

    @pytest.mark.unit
    def test_transform_empty_dataframe(self):
        """Test transforming empty DataFrame."""
        df = pd.DataFrame()

        results = transform_pfr_fantasy_stats(df, 2024)

        assert results == []

    @pytest.mark.unit
    def test_transform_filters_empty_names(self):
        """Test that rows without names are filtered."""
        df = pd.DataFrame({
            'Player': ['Valid Player', None, ''],
            'Tm': ['TST', 'TST', 'TST'],
            'FantPt': [100, 50, 25]
        })

        results = transform_pfr_fantasy_stats(df, 2024)

        # Only the first row with valid name should be included
        assert len(results) == 1
        assert results[0]['full_name'] == 'Valid Player'
