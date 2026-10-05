"""
Unit tests for evaluation metrics.
"""

import numpy as np
import pandas as pd
import pytest

from metrics import DECISION_MARGIN, START_POOL_MIN_PROJ, score, start_sit_accuracy


def _week(actuals, preds, sleeper=10.0, season=2025, week=5):
    return pd.DataFrame({
        'season': season, 'week': week,
        'actual': actuals, 'pred': preds, 'sleeper_proj': sleeper,
    })


class TestStartSitAccuracy:
    @pytest.mark.unit
    def test_perfect_ranking(self):
        df = _week([20.0, 10.0, 2.0], [15.0, 9.0, 3.0])
        assert start_sit_accuracy(df, 'pred') == 1.0

    @pytest.mark.unit
    def test_inverted_ranking(self):
        df = _week([20.0, 10.0, 2.0], [1.0, 2.0, 3.0])
        assert start_sit_accuracy(df, 'pred') == 0.0

    @pytest.mark.unit
    def test_close_scores_are_not_decisions(self):
        """Pairs whose actual scores differ by less than the margin don't count."""
        df = _week([10.0, 10.0 + DECISION_MARGIN / 2, 30.0], [9.0, 5.0, 25.0])
        # Only pairs involving the 30-pointer count, and both are ranked correctly
        assert start_sit_accuracy(df, 'pred') == 1.0

    @pytest.mark.unit
    def test_ties_count_half(self):
        df = _week([20.0, 10.0], [12.0, 12.0])
        assert start_sit_accuracy(df, 'pred') == 0.5

    @pytest.mark.unit
    def test_only_compares_within_a_week_and_startable_pool(self):
        week5 = _week([20.0, 10.0], [15.0, 9.0], week=5)
        week6 = _week([20.0, 10.0], [9.0, 15.0], week=6)
        bench = _week([0.0], [100.0], sleeper=START_POOL_MIN_PROJ - 1, week=5)
        df = pd.concat([week5, week6, bench], ignore_index=True)

        assert start_sit_accuracy(df, 'pred') == 0.5

    @pytest.mark.unit
    def test_no_decisions_is_nan(self):
        assert np.isnan(start_sit_accuracy(_week([10.0], [10.0]), 'pred'))


class TestScore:
    @pytest.mark.unit
    def test_mae_and_rmse(self):
        df = _week([10.0, 20.0], [12.0, 16.0])
        result = score(df, 'pred')

        assert result['mae'] == pytest.approx(3.0)
        assert result['rmse'] == pytest.approx(np.sqrt((4 + 16) / 2))


class TestConformalAdjustment:
    @pytest.mark.unit
    def test_widens_too_narrow_and_narrows_too_wide_ranges(self):
        from metrics import conformal_adjustment, interval_coverage
        rng = np.random.default_rng(0)
        actual = rng.normal(10, 5, 2000)

        narrow = conformal_adjustment(actual, np.full(2000, 9.0), np.full(2000, 11.0), 0.8)
        wide = conformal_adjustment(actual, np.full(2000, -20.0), np.full(2000, 40.0), 0.8)

        assert narrow > 0 > wide
        assert interval_coverage(actual, 9.0 - narrow, 11.0 + narrow) == pytest.approx(0.80, abs=0.02)
        assert interval_coverage(actual, -20.0 - wide, 40.0 + wide) == pytest.approx(0.80, abs=0.02)
