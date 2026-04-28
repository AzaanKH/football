"""
Unit tests for weekly predictor improvements.
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from weekly_predictor import WeeklyPredictor
from data_pipeline.features.rolling_averages import RollingAverages


class TestRollingAveragesReliability:
    @pytest.mark.unit
    def test_rolling_averages_use_available_history_and_set_reliability_flags(self):
        """Early-season windows should use available games and expose reliability context."""
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (2023, 17, 18.0, 0, 30, 0, 0, 6, 4, 0, 0, 1),
            (2024, 1, 12.0, 0, 50, 0, 0, 8, 5, 0, 0, 0),
        ]
        rolling = RollingAverages(cursor)

        features = rolling.compute(player_id='p1', season=2024, week=2)

        assert float(features['fantasy_pts_avg_3']) == 15.0
        assert float(features['touches_avg_3']) == 4.5
        assert features['games_played_prior'] == 2
        assert features['current_season_games_played'] == 1
        assert features['has_prev_season_data'] is True
        assert features['has_full_window_3'] is False
        assert features['fantasy_pts_baseline'] is not None


class TestWeeklyPredictorUnit:
    @pytest.mark.unit
    def test_temporal_split_holds_out_latest_week(self):
        """Training split should reserve the newest week buckets for evaluation."""
        predictor = WeeklyPredictor()
        X = pd.DataFrame({'feature': [1, 2, 3, 4]})
        y = pd.Series([10, 20, 30, 40])
        meta = pd.DataFrame({
            'season': [2024, 2024, 2024, 2024],
            'week': [1, 2, 3, 4],
        })

        X_train, X_test, y_train, y_test = predictor._temporal_train_test_split(X, y, meta, test_ratio=0.25)

        assert X_train['feature'].tolist() == [1, 2, 3]
        assert X_test['feature'].tolist() == [4]
        assert y_test.tolist() == [40]

    @pytest.mark.unit
    def test_compute_features_on_demand_adds_metadata(self):
        """On-demand feature computation must return player metadata needed by predict_week."""
        db_connection = MagicMock()
        cursor = MagicMock()
        cursor.description = [('player_id',), ('player_name',), ('position',)]
        cursor.fetchall.return_value = [('4046', 'Patrick Mahomes', 'QB')]
        db_connection.cursor.return_value = cursor

        predictor = WeeklyPredictor(db_connection=db_connection)

        engineer_instance = MagicMock()
        engineer_instance.compute_player_features.return_value = {
            'player_id': '4046',
            'season': 2024,
            'week': 10,
            'fantasy_pts_avg_3': 25.0,
        }
        engineer_class = MagicMock(return_value=engineer_instance)
        engineer_class.__enter__ = MagicMock(return_value=engineer_instance)
        engineer_class.__exit__ = MagicMock(return_value=False)

        with patch('data_pipeline.features.feature_engineer.FeatureEngineer', return_value=engineer_instance):
            result = predictor._compute_features_on_demand(['4046'], 2024, 10)

        assert result.iloc[0]['player_id'] == '4046'
        assert result.iloc[0]['player_name'] == 'Patrick Mahomes'
        assert result.iloc[0]['position'] == 'QB'

    @pytest.mark.unit
    def test_backtest_aggregates_fold_metrics(self):
        """Backtest should run walk-forward folds and report overall metrics."""
        predictor = WeeklyPredictor()
        X = pd.DataFrame({'feature': [1, 2, 3, 4, 5]})
        y = pd.Series([10, 12, 14, 16, 18])
        meta = pd.DataFrame({
            'season': [2024] * 5,
            'week': [1, 2, 3, 4, 5],
        })

        with patch.object(predictor, '_build_training_data', return_value=(X, y, meta)):
            result = predictor.backtest('qb', min_train_weeks=2)

        assert result['position'] == 'qb'
        assert result['overall']['samples'] > 0
        assert len(result['folds']) == 3
