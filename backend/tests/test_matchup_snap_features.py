"""
Unit tests for per-game context features: snap share, opponent defense vs
position, real days of rest, and the Sleeper game-context sync.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from data_pipeline.features.matchups import MatchupFeatures
from data_pipeline.features.trends import TrendFeatures


def _trend_rows(*games):
    """games: (fantasy_pts, off_snaps, team_off_snaps), oldest first; returned newest first."""
    rows = [(2025, w, pts, 10, 5, 3, snaps, team)
            for w, (pts, snaps, team) in enumerate(games, start=1)]
    return list(reversed(rows))


class TestSnapShare:
    @pytest.mark.unit
    def test_average_and_trend_of_snap_share(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = _trend_rows((10, 30, 60), (12, 42, 60), (15, 54, 60))

        features = TrendFeatures(cursor).compute('p1', 2025, 4)

        assert float(features['snap_share_avg_3']) == pytest.approx(0.7, abs=1e-4)  # (.5+.7+.9)/3
        assert float(features['snap_share_trend_3']) > 0

    @pytest.mark.unit
    def test_games_without_snap_counts_are_skipped_not_zero(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = _trend_rows((10, None, None), (12, 48, 60), (15, 54, 60))

        features = TrendFeatures(cursor).compute('p1', 2025, 4)

        assert float(features['snap_share_avg_3']) == pytest.approx(0.85, abs=1e-4)

    @pytest.mark.unit
    def test_no_snap_data_leaves_features_empty(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = _trend_rows((10, None, None), (12, None, 0))

        features = TrendFeatures(cursor).compute('p1', 2025, 3)

        assert features['snap_share_avg_3'] is None
        assert features['snap_share_trend_3'] is None


class TestOpponentDefense:
    @pytest.mark.unit
    def test_ranks_defenses_by_points_allowed_and_caches_per_week(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ('BUF', 'RB', Decimal('18.0'), 8),
            ('KC', 'RB', Decimal('25.5'), 8),
            ('SF', 'RB', Decimal('12.0'), 6),
            ('KC', 'WR', Decimal('40.0'), 8),
        ]
        matchups = MatchupFeatures(cursor)

        sf = matchups._get_opponent_defense('SF', 'RB', 2025, 10)
        kc = matchups._get_opponent_defense('KC', 'rb', 2025, 10)
        unknown = matchups._get_opponent_defense('NYJ', 'RB', 2025, 10)

        assert sf == {'rank': 1, 'pts_allowed': Decimal('12.0')}   # toughest
        assert kc['rank'] == 3 and kc['pts_allowed'] == Decimal('25.5')
        assert unknown is None
        assert cursor.execute.call_count == 1  # one query per (season, week)

        sql, params = cursor.execute.call_args.args
        assert 's.opponent' in sql and 's.played' in sql
        assert params == (2025, 2025, 10, MatchupFeatures.DEFENSE_WINDOW_GAMES,
                          MatchupFeatures.DEFENSE_MIN_GAMES)


class TestDaysRest:
    @pytest.mark.unit
    def test_real_dates_when_known(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (4, date(2025, 9, 28))  # previous Sunday

        rest = MatchupFeatures(cursor)._get_days_rest('p1', 2025, 5, date(2025, 10, 2))  # Thursday

        assert rest == 4

    @pytest.mark.unit
    def test_falls_back_to_weeks_without_dates(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (3, None)

        assert MatchupFeatures(cursor)._get_days_rest('p1', 2025, 5, None) == 14

    @pytest.mark.unit
    def test_first_game_of_season_has_no_rest_value(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None

        assert MatchupFeatures(cursor)._get_days_rest('p1', 2025, 1, date(2025, 9, 7)) is None


class TestGameContextSync:
    @pytest.mark.unit
    def test_sleeper_game_context_parsing(self):
        from data_pipeline.sleeper_client import SleeperClient
        client = SleeperClient()
        response = MagicMock()
        response.json.return_value = [
            {'player_id': '4034', 'team': 'SF', 'opponent': 'TB', 'date': '2024-11-10',
             'stats': {'off_snp': 56.0, 'tm_off_snp': 70.0, 'pts_ppr': 20.1}},
            {'player_id': '99', 'team': 'DEN', 'opponent': 'LV', 'date': '2024-11-10',
             'stats': {'gms_active': 1.0}},
        ]
        with patch.object(client.client, 'get', return_value=response) as get:
            context = client.get_weekly_game_context(2024, 10)

        assert context['4034'] == {'team': 'SF', 'opponent': 'TB', 'game_date': '2024-11-10',
                                   'off_snaps': 56, 'team_off_snaps': 70}
        assert context['99']['off_snaps'] is None
        params = get.call_args.kwargs['params']
        assert ('position[]', 'QB') in params and ('season_type', 'regular') in params
        client.close()

    @pytest.mark.unit
    def test_game_context_failure_returns_empty(self):
        import httpx
        from data_pipeline.sleeper_client import SleeperClient
        client = SleeperClient()
        with patch.object(client.client, 'get', side_effect=httpx.ConnectError('down')):
            assert client.get_weekly_game_context(2024, 10) == {}
        client.close()
