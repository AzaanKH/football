"""
Unit tests for weekly predictor improvements.
"""

import pickle
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from weekly_predictor import WeeklyPredictor, has_history, trend_label
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


class _ConstantModel:
    """Stand-in model returning a fixed value per row (records inputs)."""

    def __init__(self, value):
        self.value = value
        self.inputs = []

    def predict(self, X):
        self.inputs.append(X)
        return np.full(len(X), self.value, dtype=float)


def _predictor_with_models(point=15.0, low=8.0, high=22.0):
    predictor = WeeklyPredictor(db_connection=MagicMock())
    for pos in ('qb', 'rb', 'wr'):
        predictor.models[pos] = _ConstantModel(point)
        predictor.quantile_models[pos] = {
            'lower': _ConstantModel(low),
            'upper': _ConstantModel(high),
        }
    predictor._is_trained = True
    return predictor


METADATA = {
    'rb1': {'player_name': 'Back One', 'position': 'RB', 'team': 'PHI'},
    'rb_rookie': {'player_name': 'Rookie Back', 'position': 'RB', 'team': 'NYG'},
    'rb_nofeat': {'player_name': 'No Features', 'position': 'RB', 'team': 'DAL'},
    'wr1': {'player_name': 'Wide One', 'position': 'WR', 'team': 'MIN'},
    'te1': {'player_name': 'Tight End', 'position': 'TE', 'team': 'KC'},
}


class TestPredictWeekContract:
    @pytest.mark.unit
    def test_every_requested_player_gets_prediction_or_reason(self):
        predictor = _predictor_with_models()
        features = pd.DataFrame([
            {'player_id': 'rb1', 'games_played_prior': 6, 'fantasy_pts_avg_3': Decimal('14.20'),
             'fantasy_pts_trend_3': None},
            {'player_id': 'rb_rookie', 'games_played_prior': 0},
            {'player_id': 'wr1', 'games_played_prior': 4},
            {'player_id': 'te1', 'games_played_prior': 9},
        ])

        with patch.object(predictor, '_get_player_metadata', return_value=METADATA), \
             patch.object(predictor, 'get_player_features', return_value=features):
            results = predictor.predict_week(
                ['rb1', 'ghost', 'rb_rookie', 'rb_nofeat', 'wr1', 'te1', 'rb1'],
                season=2025, week=6, position='rb'
            )

        by_id = {r.player_id: r for r in results}
        assert len(results) == 6  # duplicates collapsed, nobody dropped
        assert by_id['rb1'].status == 'ok'
        assert by_id['ghost'].reason == 'unknown_player'
        assert by_id['rb_rookie'].reason == 'no_history'
        assert by_id['rb_nofeat'].reason == 'features_unavailable'
        assert by_id['wr1'].reason == 'position_mismatch'
        assert by_id['te1'].reason == 'position_mismatch'
        assert results[0].player_id == 'rb1'  # predictions first
        assert all(r.message for r in results if r.status == 'unavailable')

    @pytest.mark.unit
    def test_unsupported_position_without_position_filter(self):
        predictor = _predictor_with_models()
        features = pd.DataFrame([{'player_id': 'te1', 'games_played_prior': 9}])

        with patch.object(predictor, '_get_player_metadata', return_value=METADATA), \
             patch.object(predictor, 'get_player_features', return_value=features):
            [result] = predictor.predict_week(['te1'], season=2025, week=6)

        assert result.reason == 'unsupported_position'

    @pytest.mark.unit
    def test_missing_trend_and_decimal_features_are_json_safe(self):
        """A missing trend used to raise `None > 0`; Decimals reached the frontend as strings."""
        predictor = _predictor_with_models()
        features = pd.DataFrame([{
            'player_id': 'rb1', 'games_played_prior': 6,
            'fantasy_pts_avg_3': Decimal('14.20'), 'fantasy_pts_trend_3': None,
            'opp_position_rank': None,
        }])

        with patch.object(predictor, '_get_player_metadata', return_value=METADATA), \
             patch.object(predictor, 'get_player_features', return_value=features):
            [result] = predictor.predict_week(['rb1'], season=2025, week=6)

        summary = result.features_used
        assert summary['trend'] is None
        assert summary['avg_3_games'] == 14.2 and isinstance(summary['avg_3_games'], float)
        assert summary['opponent_rank'] is None

    @pytest.mark.unit
    def test_bounds_always_contain_prediction(self):
        predictor = _predictor_with_models(point=15.0, low=17.0, high=12.0)  # crossed quantiles
        features = pd.DataFrame([{'player_id': 'rb1', 'games_played_prior': 6}])

        [pred] = predictor.predict_with_confidence('rb', features)

        assert pred['confidence_low'] <= pred['predicted_points'] <= pred['confidence_high']


class TestHasHistory:
    @pytest.mark.unit
    @pytest.mark.parametrize('features, expected', [
        ({'games_played_prior': 5}, True),
        ({'games_played_prior': 0, 'fantasy_pts_avg_3': 12.0}, False),
        # Rows computed before games_played_prior existed have it NULL
        ({'games_played_prior': None, 'fantasy_pts_avg_3': Decimal('26.13')}, True),
        ({'games_played_prior': None, 'fantasy_pts_avg_3': None}, False),
        ({}, False),
    ])
    def test_has_history(self, features, expected):
        assert has_history(features) is expected


class TestTrendLabel:
    @pytest.mark.unit
    @pytest.mark.parametrize('slope, expected', [
        (None, None), (float('nan'), None), (Decimal('1.5'), 'improving'),
        (-0.2, 'declining'), (0, 'flat'), ('2.0', 'improving'),
    ])
    def test_trend_label(self, slope, expected):
        assert trend_label(slope) == expected


class TestFeatureMissingValues:
    @pytest.mark.unit
    def test_missing_values_stay_nan_for_new_models(self):
        predictor = WeeklyPredictor()
        df = pd.DataFrame({
            'opp_position_rank': [None, 12],
            'is_home': [None, True],
            'fantasy_pts_avg_3': [Decimal('10.5'), None],
        })

        X = predictor._coerce_features(df, ['opp_position_rank', 'is_home', 'fantasy_pts_avg_3', 'absent'])

        assert X['opp_position_rank'].isna().tolist() == [True, False]
        assert np.isnan(X['is_home'].iloc[0]) and X['is_home'].iloc[1] == 1.0
        assert X['fantasy_pts_avg_3'].iloc[0] == 10.5
        assert X['absent'].isna().all()
        assert all(dtype == float for dtype in X.dtypes)

    @pytest.mark.unit
    def test_legacy_models_keep_zero_fill(self):
        predictor = WeeklyPredictor()
        predictor.missing_strategy = 'zero'

        X = predictor._coerce_features(pd.DataFrame({'opp_position_rank': [None]}), ['opp_position_rank'])

        assert X['opp_position_rank'].tolist() == [0.0]

    @pytest.mark.unit
    def test_save_load_round_trip_and_legacy_default(self, tmp_path):
        predictor = WeeklyPredictor()
        predictor._is_trained = True
        predictor.feature_columns = {'rb': ['fantasy_pts_avg_3', 'touches_avg_3']}
        path = tmp_path / 'model.pkl'
        predictor.save(str(path))

        loaded = WeeklyPredictor.load(str(path))
        assert loaded.feature_columns == {'rb': ['fantasy_pts_avg_3', 'touches_avg_3']}
        assert loaded.missing_strategy == 'nan'

        legacy = {'models': {}, 'quantile_models': {}, 'training_metrics': {}}
        legacy_path = tmp_path / 'legacy.pkl'
        legacy_path.write_bytes(pickle.dumps(legacy))
        assert WeeklyPredictor.load(str(legacy_path)).missing_strategy == 'zero'

    @pytest.mark.unit
    def test_prediction_uses_saved_training_columns(self):
        predictor = _predictor_with_models()
        predictor.feature_columns = {'rb': ['touches_avg_3', 'fantasy_pts_avg_3']}
        features = pd.DataFrame([{'player_id': 'rb1', 'fantasy_pts_avg_3': 9, 'touches_avg_3': 18,
                                  'extra_column': 1}])

        predictor.predict('rb', features)

        assert list(predictor.models['rb'].inputs[0].columns) == ['touches_avg_3', 'fantasy_pts_avg_3']


class TestGetPlayerFeatures:
    @pytest.mark.unit
    def test_computes_on_demand_only_for_players_without_stored_rows(self):
        cursor = MagicMock()
        cursor.description = [('player_id',), ('season',), ('week',), ('fantasy_pts_avg_3',)]
        cursor.fetchall.return_value = [('rb1', 2025, 6, Decimal('14.2'))]
        predictor = WeeklyPredictor(db_connection=MagicMock(cursor=MagicMock(return_value=cursor)))
        computed = pd.DataFrame([{'player_id': 'wr1', 'season': 2025, 'week': 6, 'fantasy_pts_avg_3': 8.0}])

        with patch.object(predictor, '_compute_features_on_demand', return_value=computed) as on_demand:
            result = predictor.get_player_features(['rb1', 'wr1', 'ghost'], 2025, 6, METADATA)

        on_demand.assert_called_once()
        assert on_demand.call_args.args[0] == ['wr1']  # not rb1 (stored) or ghost (unknown)
        assert sorted(result['player_id']) == ['rb1', 'wr1']
