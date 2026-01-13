"""
Unit Tests for ESPN Fantasy API Client

These tests use mocked HTTP responses to test the ESPNClient
without making actual API calls.
"""

import pytest
from unittest.mock import MagicMock, patch
import httpx

from data_pipeline.espn_client import ESPNClient, transform_espn_player


class TestESPNClientUnit:
    """Unit tests for ESPNClient with mocked HTTP."""

    @pytest.fixture
    def mock_client(self):
        """Create an ESPNClient with mocked httpx.Client."""
        with patch('data_pipeline.espn_client.httpx.Client') as mock:
            client_instance = MagicMock()
            mock.return_value = client_instance
            espn = ESPNClient()
            espn.client = client_instance
            yield espn, client_instance
            espn.close()

    @pytest.mark.unit
    def test_init_without_auth(self):
        """Test initialization without authentication cookies."""
        with patch('data_pipeline.espn_client.httpx.Client') as mock:
            ESPNClient()

            call_kwargs = mock.call_args[1]
            assert call_kwargs['cookies'] == {}
            assert 'User-Agent' in call_kwargs['headers']
            assert 'X-Fantasy-Source' in call_kwargs['headers']

    @pytest.mark.unit
    def test_init_with_auth(self):
        """Test initialization with authentication cookies."""
        with patch('data_pipeline.espn_client.httpx.Client') as mock:
            ESPNClient(espn_s2='test_s2', swid='test_swid')

            call_kwargs = mock.call_args[1]
            assert call_kwargs['cookies']['espn_s2'] == 'test_s2'
            assert call_kwargs['cookies']['SWID'] == 'test_swid'

    @pytest.mark.unit
    def test_get_players_success(self, mock_client):
        """Test fetching players from ESPN."""
        client, http_mock = mock_client

        players_data = {
            'players': [
                {'player': {'id': 1, 'fullName': 'Patrick Mahomes'}},
                {'player': {'id': 2, 'fullName': 'Josh Allen'}}
            ]
        }

        response_mock = MagicMock()
        response_mock.json.return_value = players_data
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_players(season=2024, limit=100)

        assert len(result) == 2
        http_mock.get.assert_called_once()

    @pytest.mark.unit
    def test_get_players_error(self, mock_client):
        """Test handling of API errors."""
        client, http_mock = mock_client

        http_mock.get.side_effect = Exception("API Error")

        result = client.get_players(season=2024)

        assert result == []

    @pytest.mark.unit
    def test_get_player_news_success(self, mock_client):
        """Test fetching player news."""
        client, http_mock = mock_client

        news_data = {
            'feed': [
                {'headline': 'News 1'},
                {'headline': 'News 2'}
            ]
        }

        response_mock = MagicMock()
        response_mock.json.return_value = news_data
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_player_news(player_id=12345, limit=5)

        assert len(result) == 2
        assert result[0]['headline'] == 'News 1'

    @pytest.mark.unit
    def test_get_player_news_empty(self, mock_client):
        """Test handling of no news."""
        client, http_mock = mock_client

        response_mock = MagicMock()
        response_mock.json.return_value = None
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_player_news(player_id=12345)

        assert result == []

    @pytest.mark.unit
    def test_get_team_injuries_success(self, mock_client):
        """Test fetching team injuries."""
        client, http_mock = mock_client

        injuries_data = {
            'items': [
                {'athlete': {'displayName': 'Player 1'}, 'status': 'Questionable'},
                {'athlete': {'displayName': 'Player 2'}, 'status': 'Out'}
            ]
        }

        response_mock = MagicMock()
        response_mock.json.return_value = injuries_data
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_team_injuries(team_id=12)

        assert len(result) == 2

    @pytest.mark.unit
    def test_get_scoreboard_success(self, mock_client):
        """Test fetching scoreboard data."""
        client, http_mock = mock_client

        scoreboard_data = {'games': [{'id': 1}, {'id': 2}]}

        response_mock = MagicMock()
        response_mock.json.return_value = scoreboard_data
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_scoreboard(season=2024, week=10)

        assert result == scoreboard_data

    @pytest.mark.unit
    def test_get_league_data_success(self, mock_client):
        """Test fetching league data."""
        client, http_mock = mock_client

        league_data = {
            'id': 12345,
            'teams': [{'id': 1}, {'id': 2}]
        }

        response_mock = MagicMock()
        response_mock.json.return_value = league_data
        response_mock.raise_for_status = MagicMock()
        http_mock.get.return_value = response_mock

        result = client.get_league_data(league_id=12345, season=2024)

        assert result == league_data

    @pytest.mark.unit
    def test_rate_limiting(self, mock_client):
        """Test rate limiting between requests."""
        client, http_mock = mock_client

        import time
        start = time.time()

        client._rate_limit()
        client._rate_limit()

        elapsed = time.time() - start
        # Should wait at least 500ms (0.5s)
        assert elapsed >= client._min_request_interval * 0.9

    @pytest.mark.unit
    def test_context_manager(self):
        """Test context manager closes client."""
        with patch('data_pipeline.espn_client.httpx.Client') as mock:
            client_instance = MagicMock()
            mock.return_value = client_instance

            with ESPNClient() as client:
                pass

            client_instance.close.assert_called_once()


class TestTransformESPNPlayer:
    """Tests for ESPN player data transformation."""

    @pytest.mark.unit
    def test_transform_qb_player(self):
        """Test transforming a QB player."""
        espn_player = {
            'player': {
                'id': 3139477,
                'fullName': 'Patrick Mahomes',
                'firstName': 'Patrick',
                'lastName': 'Mahomes',
                'defaultPositionId': 1,  # QB
                'proTeamId': 12,
                'injuryStatus': 'ACTIVE'
            }
        }

        result = transform_espn_player(espn_player)

        assert result['espn_id'] == '3139477'
        assert result['full_name'] == 'Patrick Mahomes'
        assert result['position'] == 'QB'
        assert result['source'] == 'espn'

    @pytest.mark.unit
    def test_transform_rb_player(self):
        """Test transforming an RB player."""
        espn_player = {
            'player': {
                'id': 4047646,
                'fullName': 'Saquon Barkley',
                'defaultPositionId': 2  # RB
            }
        }

        result = transform_espn_player(espn_player)

        assert result['position'] == 'RB'

    @pytest.mark.unit
    def test_transform_wr_player(self):
        """Test transforming a WR player."""
        espn_player = {
            'player': {
                'id': 123,
                'fullName': 'Test Receiver',
                'defaultPositionId': 3  # WR
            }
        }

        result = transform_espn_player(espn_player)

        assert result['position'] == 'WR'

    @pytest.mark.unit
    def test_transform_te_player(self):
        """Test transforming a TE player."""
        espn_player = {
            'player': {
                'id': 456,
                'fullName': 'Test TE',
                'defaultPositionId': 4  # TE
            }
        }

        result = transform_espn_player(espn_player)

        assert result['position'] == 'TE'

    @pytest.mark.unit
    def test_transform_unknown_position(self):
        """Test transforming player with unknown position."""
        espn_player = {
            'player': {
                'id': 789,
                'fullName': 'Unknown Position',
                'defaultPositionId': 99
            }
        }

        result = transform_espn_player(espn_player)

        assert result['position'] == ''

    @pytest.mark.unit
    def test_transform_empty_player(self):
        """Test transforming empty player data."""
        result = transform_espn_player({})

        assert result['espn_id'] == ''
        assert result['full_name'] == ''
        assert result['source'] == 'espn'
