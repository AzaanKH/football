"""
Model Evaluation

Scores the weekly predictor against simple baselines on identical held-out
games, so model changes are judged by evidence rather than training metrics.

Methods (all scored on the same rows):
    model       WeeklyPredictor fit only on weeks before the held-out weeks
    avg_3       3-game average PPR (from the stored features)
    avg_5       5-game average PPR
    sleeper_proj  Sleeper's own weekly PPR projection

Metrics:
    MAE / RMSE  point accuracy on played games
    start/sit   among startable players (Sleeper projection >= metrics.START_POOL_MIN_PROJ)
                in the same week and position, every pair whose actual scores
                differ by >= metrics.DECISION_MARGIN: how often the method ranks the
                higher scorer first (ties count half)
    coverage    share of actual scores inside the model's 80% range, and its
                mean width

Usage:
    python evaluation.py                 # all positions
    python evaluation.py rb wr           # selected positions
"""

import logging
import sys
from typing import Dict, List, Optional

import pandas as pd

from metrics import interval_coverage, score
from weekly_predictor import SLEEPER_FEATURE, WeeklyPredictor, get_db_connection

logger = logging.getLogger(__name__)

POSITIONS = ('qb', 'rb', 'wr')
BASELINES = ('avg_3', 'avg_5', SLEEPER_FEATURE)


def load_evaluation_frame(predictor: WeeklyPredictor, position: str) -> pd.DataFrame:
    """Played games with features, actual points and Sleeper's projection."""
    df = predictor._load_training_frame(position)
    df['actual'] = pd.to_numeric(df['actual_points'], errors='coerce')
    df['avg_3'] = pd.to_numeric(df['fantasy_pts_avg_3'], errors='coerce')
    df['avg_5'] = pd.to_numeric(df['fantasy_pts_avg_5'], errors='coerce')
    df[SLEEPER_FEATURE] = pd.to_numeric(df[SLEEPER_FEATURE], errors='coerce')
    return df


def evaluate_position(predictor: WeeklyPredictor, position: str,
                      feature_columns: Optional[List[str]] = None,
                      test_ratio: float = 0.2) -> Dict:
    """
    Fit on older weeks, score all methods on the held-out latest weeks.

    feature_columns overrides the position's default feature list, so
    candidate feature sets can be compared on identical games.
    """
    df = load_evaluation_frame(predictor, position)
    columns = feature_columns or predictor.get_features_for_position(position)
    columns = [c for c in columns if c in df.columns]

    X = predictor._coerce_features(df, columns)
    y = df['actual']
    meta = df[['season', 'week']]
    X_train, X_test, y_train, _ = predictor._temporal_train_test_split(X, y, meta, test_ratio)

    predictor.fit(position, X_train, y_train, meta.loc[X_train.index])
    test = df.loc[X_test.index].copy()
    bounds = predictor.predict_with_confidence(position, test)
    test['model'] = [b['predicted_points'] for b in bounds]
    test['low'] = [b['confidence_low'] for b in bounds]
    test['high'] = [b['confidence_high'] for b in bounds]

    # Every method on the same rows: games where all baselines exist
    common = test.dropna(subset=list(BASELINES))
    results = {method: score(common, method) for method in ('model',) + BASELINES}

    return {
        'position': position,
        'test_games': len(test),
        'compared_games': len(common),
        'weeks': f"{test['season'].min()} W{test[test['season'] == test['season'].min()]['week'].min()}"
                 f" - {test['season'].max()} W{test[test['season'] == test['season'].max()]['week'].max()}",
        'methods': results,
        'point_strategy': predictor.point_strategy.get(position),
        'interval': {
            'coverage_80': interval_coverage(test['actual'], test['low'], test['high']),
            'mean_width': float((test['high'] - test['low']).mean()),
        },
        'features': columns,
    }


def print_report(reports: List[Dict]) -> None:
    for report in reports:
        print(f"\n{report['position'].upper()}  held-out {report['weeks']}  "
              f"({report['compared_games']} of {report['test_games']} games have every baseline)")
        print(f"  model point strategy: {report['point_strategy']}")
        print(f"  {'method':13} {'MAE':>6} {'RMSE':>6} {'start/sit':>10}")
        for method, metrics in report['methods'].items():
            print(f"  {method:13} {metrics['mae']:6.2f} {metrics['rmse']:6.2f} "
                  f"{metrics['start_sit']:10.1%}")
        interval = report['interval']
        print(f"  80% range: coverage {interval['coverage_80']:.1%}, "
              f"mean width {interval['mean_width']:.1f} pts")


def main(positions: List[str]) -> List[Dict]:
    conn = get_db_connection()
    try:
        predictor = WeeklyPredictor(db_connection=conn)
        reports = [evaluate_position(predictor, position) for position in positions]
    finally:
        conn.close()
    print_report(reports)
    return reports


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    requested = [p.lower() for p in sys.argv[1:]] or list(POSITIONS)
    main(requested)
