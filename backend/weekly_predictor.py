"""
Weekly Fantasy Football Predictor

Predicts next-week fantasy points using Phase 2 features.
Unlike the legacy model, this uses:
- Rolling averages (past performance)
- Efficiency metrics (quality of touches)
- Consistency metrics (volatility)
- Trend features (improving/declining)
- Matchup features (opponent strength)

Training paradigm: Features from Week N → Actual points in Week N
(Features are computed using data BEFORE Week N, so no leakage)
"""

import pandas as pd
import numpy as np
import copy
import pickle
import os
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

from metrics import conformal_adjustment, interval_coverage, score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WeeklyPrediction:
    """
    Result for one requested player.

    status is 'ok' (prediction fields set) or 'unavailable' (reason/message
    explain why; prediction fields are None). Every requested player gets one.
    """
    player_id: str
    player_name: Optional[str]
    predicted_points: Optional[float] = None
    confidence_low: Optional[float] = None
    confidence_high: Optional[float] = None
    features_used: Dict[str, object] = field(default_factory=dict)
    status: str = 'ok'
    reason: Optional[str] = None
    message: Optional[str] = None
    # Game context for display: team, opponent, is_home, kickoff, injury_status
    context: Dict[str, object] = field(default_factory=dict)


# Reasons a requested player can't be predicted
UNAVAILABLE_MESSAGES = {
    'unknown_player': 'Player not found in the database.',
    'position_mismatch': 'Player does not play the requested position.',
    'unsupported_position': 'No model is trained for this position.',
    'no_history': 'No games played before this week, so there is no history to predict from.',
    'features_unavailable': 'Features could not be computed for this player.',
    'bye': "On bye this week (no game on the team's schedule).",
}

BOOL_FEATURES = ('is_home', 'has_prev_season_data', 'has_full_window_3', 'has_full_window_5')

# Sleeper's pre-game PPR projection for the week being predicted
SLEEPER_FEATURE = 'sleeper_proj'

# Target coverage of the confidence range (10th-90th percentile)
INTERVAL_COVERAGE = 0.80
# Share of training weeks (latest) held back to choose the point strategy and
# calibrate the range
CALIBRATION_RATIO = 0.2

# How the point prediction is produced, chosen per position at training time
POINT_SLEEPER = 'sleeper'                   # Sleeper projection as-is
POINT_SLEEPER_CORRECTED = 'sleeper+model'   # Sleeper + learned correction
POINT_MODEL = 'model'                       # standalone model (no projection)

# XGBoost threads (-1 = all cores). Tests set 1: thread start-up dominates
# on tiny data and made fits ~8x slower on a busy machine.
N_JOBS = int(os.environ.get('PREDICTOR_N_JOBS', -1))


def _to_float(value) -> Optional[float]:
    """Convert DB values (Decimal, str, None, NaN) to a JSON-safe float or None."""
    number = pd.to_numeric(value, errors='coerce')
    return None if pd.isna(number) else float(number)


def has_history(features: Dict) -> bool:
    """
    Whether a feature row is based on at least one prior game.

    games_played_prior is authoritative when present; rows computed before it
    existed (NULL) fall back to whether any rolling average was computed.
    """
    games = _to_float(features.get('games_played_prior'))
    if games is not None:
        return games > 0
    return _to_float(features.get('fantasy_pts_avg_3')) is not None


def trend_label(slope) -> Optional[str]:
    """Describe a fantasy-points trend slope; None when there is no trend data."""
    slope = _to_float(slope)
    if slope is None:
        return None
    if slope > 0:
        return 'improving'
    if slope < 0:
        return 'declining'
    return 'flat'


class WeeklyPredictor:
    """
    Predicts fantasy points for upcoming NFL week.

    Uses Phase 2 features that are computed from PRIOR weeks only,
    ensuring no data leakage in training or inference.
    """

    # Features from Phase 2 feature engineering
    PREDICTION_FEATURES = [
        # Rolling averages - recent performance
        'fantasy_pts_avg_3',
        'fantasy_pts_avg_5',
        'rushing_yds_avg_3',
        'receiving_yds_avg_3',
        'targets_avg_3',
        'touches_avg_3',
        'receptions_avg_3',
        'games_played_prior',
        'current_season_games_played',
        'has_prev_season_data',
        'has_full_window_3',
        'has_full_window_5',
        'fantasy_pts_baseline',

        # Efficiency - quality metrics
        'yards_per_carry',
        'yards_per_target',
        'yards_per_reception',
        'td_per_touch',
        'catch_rate',

        # Consistency - volatility
        'fantasy_pts_std_5',
        'boom_rate_5',
        'bust_rate_5',
        'floor_score',

        # Trends - direction
        'fantasy_pts_trend_3',
        'usage_trend_3',

        # Matchup - opponent
        'opp_position_rank',
        'opp_fantasy_pts_allowed',
        'is_home',
        'days_rest',

        # Sleeper's own pre-game PPR projection (point estimate anchor)
        SLEEPER_FEATURE,
    ]

    # Separate feature sets by position
    QB_FEATURES = [
        'fantasy_pts_avg_3', 'fantasy_pts_avg_5',
        'passing_yds_avg_3', 'rushing_yds_avg_3',
        'games_played_prior', 'current_season_games_played',
        'has_prev_season_data', 'has_full_window_3', 'has_full_window_5',
        'fantasy_pts_baseline',
        'yards_per_pass_attempt', 'td_per_pass_attempt',
        'fantasy_pts_std_5', 'boom_rate_5', 'bust_rate_5', 'floor_score',
        'fantasy_pts_trend_3', 'usage_trend_3',
        'opp_position_rank', 'opp_fantasy_pts_allowed', 'is_home', 'days_rest',
        SLEEPER_FEATURE,
    ]

    RB_FEATURES = [
        'fantasy_pts_avg_3', 'fantasy_pts_avg_5',
        'rushing_yds_avg_3', 'receiving_yds_avg_3',
        'touches_avg_3', 'targets_avg_3',
        'games_played_prior', 'current_season_games_played',
        'has_prev_season_data', 'has_full_window_3', 'has_full_window_5',
        'fantasy_pts_baseline',
        'yards_per_carry', 'yards_per_target', 'td_per_touch', 'catch_rate',
        'fantasy_pts_std_5', 'boom_rate_5', 'bust_rate_5', 'floor_score',
        'fantasy_pts_trend_3', 'usage_trend_3',
        'opp_position_rank', 'opp_fantasy_pts_allowed', 'is_home', 'days_rest',
        SLEEPER_FEATURE,
    ]

    WR_FEATURES = [
        'fantasy_pts_avg_3', 'fantasy_pts_avg_5',
        'receiving_yds_avg_3', 'targets_avg_3', 'receptions_avg_3',
        'games_played_prior', 'current_season_games_played',
        'has_prev_season_data', 'has_full_window_3', 'has_full_window_5',
        'fantasy_pts_baseline',
        'yards_per_target', 'yards_per_reception', 'td_per_touch', 'catch_rate',
        'fantasy_pts_std_5', 'boom_rate_5', 'bust_rate_5', 'floor_score',
        'fantasy_pts_trend_3', 'usage_trend_3',
        'opp_position_rank', 'opp_fantasy_pts_allowed', 'is_home', 'days_rest',
        SLEEPER_FEATURE,
    ]

    def __init__(self, db_connection=None):
        """
        Initialize predictor.

        Args:
            db_connection: PostgreSQL connection (optional, for DB queries)
        """
        self.db_connection = db_connection
        self.models: Dict[str, XGBRegressor] = {}
        self.quantile_models: Dict[str, Dict[str, object]] = {}
        self.training_metrics: Dict[str, Dict] = {}
        # Exact training columns per position, saved with the model so inference
        # can't drift from training if the class feature lists change
        self.feature_columns: Dict[str, List[str]] = {}
        # 'nan': missing values stay NaN (models handle them natively).
        # 'zero': legacy pickles trained with fillna(0); kept for compatibility.
        self.missing_strategy = 'nan'
        # Per position: how the point estimate is produced (POINT_* constants),
        # the optional correction to Sleeper's projection, and the conformal
        # widening (+) / narrowing (-) applied to the 10th-90th percentile range
        self.point_strategy: Dict[str, str] = {}
        self.correction_models: Dict[str, Optional[XGBRegressor]] = {}
        self.interval_adjustment: Dict[str, float] = {}
        self.calibration: Dict[str, Dict] = {}
        self._is_trained = False

    def get_features_for_position(self, position: str) -> List[str]:
        """Get the feature list for a position."""
        position = position.lower()
        if position == 'qb':
            return self.QB_FEATURES
        elif position == 'rb':
            return self.RB_FEATURES
        elif position == 'wr':
            return self.WR_FEATURES
        else:
            return self.PREDICTION_FEATURES

    def _load_training_frame(self, position: str) -> pd.DataFrame:
        """
        Load training dataset from database.

        For each row:
        - Features: Computed features for Week N (using data from weeks < N)
        - Target: Actual fantasy points scored in Week N
        """
        if not self.db_connection:
            raise RuntimeError("Database connection required for training")

        cursor = self.db_connection.cursor()

        # Get features joined with actual points
        # player_features.week = the week these features are FOR
        # player_weekly_stats.week = the week when points were actually scored
        query = """
            SELECT
                pf.*,
                pp.projected_points_ppr as sleeper_proj,
                pws.fantasy_points_ppr as actual_points
            FROM player_features pf
            JOIN player_weekly_stats pws
                ON pf.player_id = pws.player_id
                AND pf.season = pws.season
                AND pf.week = pws.week
            JOIN players p
                ON pf.player_id = p.player_id
            LEFT JOIN player_projections pp
                ON pp.player_id = pf.player_id
                AND pp.season = pf.season
                AND pp.week = pf.week
                AND pp.source = 'sleeper'
            WHERE p.position = %s
                AND pws.fantasy_points_ppr IS NOT NULL
                -- Target is points *if the player plays*; inactive weeks aren't outcomes
                AND pws.played
            ORDER BY pf.season, pf.week
        """

        cursor.execute(query, (position.upper(),))
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        if not rows:
            raise ValueError(f"No training data found for position {position}")

        df = pd.DataFrame(rows, columns=columns)
        logger.info(f"Loaded {len(df)} training samples for {position.upper()}")

        return df

    def _build_training_data(self, position: str) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        """Build model-ready training features, target, and week metadata."""
        df = self._load_training_frame(position)

        feature_cols = self.get_features_for_position(position)
        available_features = [f for f in feature_cols if f in df.columns]

        X = self._coerce_features(df, available_features)
        y = df['actual_points'].copy()
        meta = df[['season', 'week']].copy()

        # Ensure target is numeric
        y = pd.to_numeric(y, errors='coerce').fillna(0)

        return X, y, meta

    def _coerce_features(self, df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """
        Select columns as floats. Missing columns/values become NaN, unless this
        is a legacy model trained with zero-filling.
        """
        X = pd.DataFrame(index=df.index)
        for col in columns:
            # Booleans and Decimals from PostgreSQL arrive as object dtype
            values = df[col] if col in df.columns else pd.Series(np.nan, index=df.index)
            if col in BOOL_FEATURES:
                values = values.map(lambda v: np.nan if v is None or pd.isna(v) else float(bool(v)))
            X[col] = pd.to_numeric(values, errors='coerce').astype(float)

        if self.missing_strategy == 'zero':
            X = X.fillna(0)
        return X

    def _prepare_features(self, position: str, features: pd.DataFrame) -> pd.DataFrame:
        """Build the model input matrix with exactly the columns used in training."""
        columns = self.feature_columns.get(position) or self.get_features_for_position(position)
        return self._coerce_features(features, columns)

    def _temporal_train_test_split(
        self, X: pd.DataFrame, y: pd.Series, meta: pd.DataFrame, test_ratio: float = 0.2
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """Split by chronological season/week buckets instead of random rows."""
        week_keys = (
            meta[['season', 'week']]
            .drop_duplicates()
            .sort_values(['season', 'week'])
            .reset_index(drop=True)
        )
        if len(week_keys) < 2:
            raise ValueError("Need at least two distinct weeks for temporal split")

        n_test_weeks = max(1, int(np.ceil(len(week_keys) * test_ratio)))
        n_test_weeks = min(n_test_weeks, len(week_keys) - 1)
        test_keys = week_keys.tail(n_test_weeks)

        test_index = meta.merge(
            test_keys.assign(_is_test=True),
            on=['season', 'week'],
            how='left'
        )['_is_test'].notna()
        train_mask = ~test_index.astype(bool)
        test_mask = test_index.astype(bool)

        return X[train_mask], X[test_mask], y[train_mask], y[test_mask]

    @staticmethod
    def _new_point_model() -> XGBRegressor:
        return XGBRegressor(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=N_JOBS
        )

    @staticmethod
    def _new_correction_model() -> XGBRegressor:
        # Shallow and heavily regularized: adjusts Sleeper's projection only
        # where features carry a consistent signal; deeper models fit noise
        return XGBRegressor(
            n_estimators=100,
            learning_rate=0.03,
            max_depth=2,
            min_child_weight=20,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=N_JOBS
        )

    @staticmethod
    def _new_quantile_model(quantile: float) -> HistGradientBoostingRegressor:
        # HistGradientBoosting handles NaN natively
        return HistGradientBoostingRegressor(
            loss='quantile',
            quantile=quantile,
            max_iter=100,
            max_depth=3,
            learning_rate=0.1,
            early_stopping=False,  # 'auto' silently stops after ~10 iterations on WR-sized data
            random_state=42
        )

    def fit(self, position: str, X: pd.DataFrame, y: pd.Series,
            meta: Optional[pd.DataFrame] = None) -> None:
        """
        Fit every model for a position on exactly the rows given.

        1. Standalone model (no Sleeper projection), on all rows: fallback for
           players without a projection.
        2. On the older weeks: a correction model (actual - Sleeper projection)
           and the 10th/90th percentile range models.
        3. On the newest CALIBRATION_RATIO of weeks (meta gives season/week):
           - keep the correction only if it beats Sleeper alone (lower MAE and
             no worse start/sit accuracy), otherwise use Sleeper as-is;
           - conformal adjustment so the range covers INTERVAL_COVERAGE.
        4. Refit the correction model on all rows if it was kept.
        """
        position = position.lower()
        y = pd.Series(np.asarray(y, dtype=float), index=X.index)

        standalone_cols = [c for c in X.columns if c != SLEEPER_FEATURE]
        standalone = self._new_point_model()
        standalone.fit(X[standalone_cols], y)

        enough_weeks = meta is not None and len(meta[['season', 'week']].drop_duplicates()) >= 2
        if enough_weeks:
            fit_X, cal_X, fit_y, cal_y = self._temporal_train_test_split(X, y, meta, CALIBRATION_RATIO)
        else:
            fit_X, cal_X, fit_y, cal_y = X, X.iloc[0:0], y, y.iloc[0:0]

        lower = self._new_quantile_model(0.10).fit(fit_X, fit_y)
        upper = self._new_quantile_model(0.90).fit(fit_X, fit_y)

        strategy = POINT_MODEL
        correction = None
        calibration: Dict[str, object] = {'calibration_rows': int(len(cal_X))}

        if SLEEPER_FEATURE in X.columns and X[SLEEPER_FEATURE].notna().any():
            strategy = POINT_SLEEPER
            fit_rows = fit_X[SLEEPER_FEATURE].notna()
            cal_rows = cal_X[SLEEPER_FEATURE].notna()
            if fit_rows.any() and cal_rows.any():
                candidate = self._new_correction_model().fit(
                    fit_X[fit_rows], fit_y[fit_rows] - fit_X.loc[fit_rows, SLEEPER_FEATURE]
                )
                frame = pd.DataFrame({
                    'season': meta.loc[cal_X.index[cal_rows], 'season'].to_numpy(),
                    'week': meta.loc[cal_X.index[cal_rows], 'week'].to_numpy(),
                    'actual': cal_y[cal_rows].to_numpy(),
                    SLEEPER_FEATURE: cal_X.loc[cal_rows, SLEEPER_FEATURE].to_numpy(),
                })
                frame['corrected'] = frame[SLEEPER_FEATURE] + candidate.predict(cal_X[cal_rows])
                alone, corrected = score(frame, SLEEPER_FEATURE), score(frame, 'corrected')
                calibration['sleeper'] = alone
                calibration['sleeper+model'] = corrected
                # NaN start/sit (no decisions) never blocks the correction
                not_worse = not corrected['start_sit'] < alone['start_sit']
                if corrected['mae'] < alone['mae'] and not_worse:
                    strategy = POINT_SLEEPER_CORRECTED

            if strategy == POINT_SLEEPER_CORRECTED:
                rows = X[SLEEPER_FEATURE].notna()
                correction = self._new_correction_model().fit(
                    X[rows], y[rows] - X.loc[rows, SLEEPER_FEATURE]
                )

        adjustment = 0.0
        if len(cal_X):
            raw_low, raw_high = lower.predict(cal_X), upper.predict(cal_X)
            adjustment = conformal_adjustment(cal_y, raw_low, raw_high, INTERVAL_COVERAGE)
            calibration['raw_coverage'] = interval_coverage(cal_y, raw_low, raw_high)

        calibration.update({'strategy': strategy, 'interval_adjustment': adjustment})
        logger.info(
            f"{position.upper()} point strategy: {strategy}; range adjusted by "
            f"{adjustment:+.2f} pts (raw coverage {calibration.get('raw_coverage', float('nan')):.1%})"
        )

        self.models[position] = standalone
        self.quantile_models[position] = {'lower': lower, 'upper': upper}
        self.correction_models[position] = correction
        self.point_strategy[position] = strategy
        self.interval_adjustment[position] = adjustment
        self.calibration[position] = calibration
        self.feature_columns[position] = list(X.columns)
        self._is_trained = True

    def train(self, position: str, X: pd.DataFrame = None, y: pd.Series = None,
              refit_full: bool = True) -> Dict:
        """
        Train prediction models for a position.

        Fits on older weeks and measures on the held-out latest weeks; then,
        unless refit_full is False, refits on every week so the saved model
        also learns from the most recent games.

        Args:
            position: 'qb', 'rb', or 'wr'
            X: Optional feature DataFrame (if not provided, queries DB)
            y: Optional target Series
            refit_full: Refit on all rows after evaluation

        Returns:
            Training metrics dictionary (measured on the held-out weeks)
        """
        position = position.lower()

        if X is None or y is None:
            X, y, meta = self._build_training_data(position)
        else:
            meta = pd.DataFrame({'season': [0] * len(X), 'week': list(range(len(X)))}, index=X.index)

        logger.info(f"Training {position.upper()} model with {len(X)} samples, {len(X.columns)} features")

        X_train, X_test, y_train, y_test = self._temporal_train_test_split(X, y, meta)
        self.fit(position, X_train, y_train, meta.loc[X_train.index])

        # Evaluate the full pipeline on held-out weeks
        held_out = self.predict_with_confidence(position, X_test)
        y_pred = np.array([p['predicted_points'] for p in held_out])
        metrics = {
            'mae': mean_absolute_error(y_test, y_pred),
            'rmse': np.sqrt(mean_squared_error(y_test, y_pred)),
            'r2': r2_score(y_test, y_pred),
            'coverage_80': interval_coverage(
                y_test, [p['confidence_low'] for p in held_out], [p['confidence_high'] for p in held_out]
            ),
            'samples': len(X),
            'test_samples': len(X_test),
            'point_strategy': self.point_strategy[position],
            'features': list(X.columns),
            'refit_on_all_weeks': refit_full,
        }

        logger.info(
            f"{position.upper()} - MAE: {metrics['mae']:.2f}, RMSE: {metrics['rmse']:.2f}, "
            f"R²: {metrics['r2']:.3f}, 80% range coverage: {metrics['coverage_80']:.1%}"
        )

        if refit_full:
            self.fit(position, X, y, meta)
            metrics['point_strategy'] = self.point_strategy[position]

        self.training_metrics[position] = metrics
        return metrics

    def train_all_positions(self) -> Dict[str, Dict]:
        """Train models for all positions."""
        all_metrics = {}
        for position in ['qb', 'rb', 'wr']:
            try:
                metrics = self.train(position)
                all_metrics[position] = metrics
            except Exception as e:
                logger.error(f"Failed to train {position}: {e}")
        return all_metrics

    def _point_predictions(self, position: str, X: pd.DataFrame) -> Tuple[np.ndarray, List[str]]:
        """
        Point predictions and how each was produced (see POINT_* constants).

        Rows without a Sleeper projection always use the standalone model.
        """
        strategy = self.point_strategy.get(position, POINT_MODEL)
        standalone_cols = [c for c in X.columns if c != SLEEPER_FEATURE]
        points = self.models[position].predict(X[standalone_cols]).astype(float)
        sources = np.full(len(X), POINT_MODEL, dtype=object)

        if strategy != POINT_MODEL and SLEEPER_FEATURE in X.columns:
            projection = X[SLEEPER_FEATURE].to_numpy(dtype=float)
            has_projection = ~np.isnan(projection)
            if has_projection.any():
                points[has_projection] = projection[has_projection]
                correction = self.correction_models.get(position)
                if strategy == POINT_SLEEPER_CORRECTED and correction is not None:
                    points[has_projection] += correction.predict(X[has_projection])
                sources[has_projection] = strategy

        return points, list(sources)

    def predict(self, position: str, features: pd.DataFrame) -> np.ndarray:
        """
        Make point predictions.

        Args:
            position: Player position
            features: DataFrame with feature columns

        Returns:
            Array of predicted fantasy points
        """
        position = position.lower()
        if position not in self.models:
            raise RuntimeError(f"No model trained for position: {position}")

        X = self._prepare_features(position, features)
        return self._point_predictions(position, X)[0]

    def predict_with_confidence(self, position: str, features: pd.DataFrame) -> List[Dict]:
        """
        Make predictions with calibrated 80% ranges.

        Args:
            position: Player position
            features: DataFrame with feature columns

        Returns:
            List of dicts with predicted_points, confidence_low, confidence_high,
            and source (how the point prediction was produced)
        """
        position = position.lower()
        if position not in self.models:
            raise RuntimeError(f"No model trained for position: {position}")

        X = self._prepare_features(position, features)
        points, sources = self._point_predictions(position, X)

        adjustment = self.interval_adjustment.get(position, 0.0)
        lower_bounds = self.quantile_models[position]['lower'].predict(X) - adjustment
        upper_bounds = self.quantile_models[position]['upper'].predict(X) + adjustment

        results = []
        for i in range(len(points)):
            point = float(points[i])
            # Bounds come from separate models and can cross the point estimate;
            # widen them so the range always contains the prediction.
            low = min(float(lower_bounds[i]), point)
            high = max(float(upper_bounds[i]), point)
            results.append({
                'predicted_points': point,
                # No floor at 0: PPR points go negative (kneel-downs, turnovers),
                # and clipping broke the calibrated coverage for backup QBs
                'confidence_low': low,
                'confidence_high': high,
                'source': sources[i],
            })

        return results

    def _get_player_metadata(self, player_ids: List[str]) -> Dict[str, Dict[str, Optional[str]]]:
        """Map player_id -> {player_name, position, team, injury_status} for requested players."""
        placeholders = ','.join(['%s'] * len(player_ids))
        cursor = self.db_connection.cursor()
        cursor.execute(f"""
            SELECT player_id, full_name, position, team, injury_status
            FROM players
            WHERE player_id IN ({placeholders})
        """, player_ids)
        return {
            row[0]: {'player_name': row[1], 'position': row[2], 'team': row[3],
                     'injury_status': row[4] or None}
            for row in cursor.fetchall()
        }

    def _get_schedule(self, season: int, week: int) -> Dict[str, Dict[str, object]]:
        """
        Team -> {opponent, is_home, kickoff} for the week. Empty when the
        week's schedule hasn't been synced (so byes can't be inferred).
        """
        cursor = self.db_connection.cursor()
        cursor.execute("""
            SELECT team, opponent, is_home, game_date
            FROM team_weekly_matchups
            WHERE season = %s AND week = %s
        """, (season, week))
        return {
            row[0]: {'opponent': row[1], 'is_home': row[2],
                     'kickoff': row[3].isoformat() if row[3] else None}
            for row in cursor.fetchall()
        }

    def _get_played_ids(self, player_ids: List[str], season: int, week: int) -> set:
        """
        Players with a game played in (season, week): never on bye that week,
        even when their team for it is unknown (stats synced before per-game
        team was stored) and the current team had no game.
        """
        placeholders = ','.join(['%s'] * len(player_ids))
        cursor = self.db_connection.cursor()
        cursor.execute(f"""
            SELECT player_id FROM player_weekly_stats
            WHERE player_id IN ({placeholders})
                AND season = %s AND week = %s AND played
        """, (*player_ids, season, week))
        return {row[0] for row in cursor.fetchall()}

    def _get_week_teams(self, player_ids: List[str], season: int, week: int) -> Dict[str, str]:
        """
        The team each player was on in (season, week), from per-game stats:
        the team they played for that week; for a past week without a game
        (bye, inactive), their nearest game before it, else the nearest after.
        Players with no game that week or later are left out, so the current
        team (players.team) applies, as it should for upcoming weeks.
        """
        placeholders = ','.join(['%s'] * len(player_ids))
        cursor = self.db_connection.cursor()
        cursor.execute(f"""
            SELECT player_id, week, team FROM player_weekly_stats
            WHERE player_id IN ({placeholders})
                AND season = %s AND team IS NOT NULL
        """, (*player_ids, season))
        games: Dict[str, Dict[int, str]] = {}
        for player_id, game_week, team in cursor.fetchall():
            games.setdefault(player_id, {})[game_week] = team

        teams = {}
        for player_id, by_week in games.items():
            if week in by_week:
                teams[player_id] = by_week[week]
            elif any(w > week for w in by_week):
                before = [w for w in by_week if w < week]
                teams[player_id] = by_week[max(before) if before else min(by_week)]
        return teams

    @staticmethod
    def _game_context(meta: Dict, schedule: Dict) -> Dict[str, object]:
        """Display context for a player: team, this week's game, injury status."""
        team = meta.get('team')
        game = schedule.get(team) or {}
        return {
            'team': team,
            'opponent': game.get('opponent'),
            'is_home': game.get('is_home'),
            'kickoff': game.get('kickoff'),
            # Current status from the last players sync, not as of `week`
            'injury_status': meta.get('injury_status'),
        }

    def get_player_features(self, player_ids: List[str], season: int, week: int,
                            metadata: Optional[Dict] = None) -> pd.DataFrame:
        """
        Get features for players: stored rows first, computed on demand for
        any requested player without a stored row.

        Args:
            player_ids: List of player IDs
            season: NFL season year
            week: Week number to predict FOR (features use data from weeks < week)
            metadata: Optional output of _get_player_metadata (fetched if omitted)

        Returns:
            DataFrame with one row per player that has features
        """
        if not self.db_connection:
            raise RuntimeError("Database connection required")
        if not player_ids:
            return pd.DataFrame()

        cursor = self.db_connection.cursor()
        placeholders = ','.join(['%s'] * len(player_ids))
        cursor.execute(f"""
            SELECT pf.*
            FROM player_features pf
            WHERE pf.player_id IN ({placeholders})
                AND pf.season = %s
                AND pf.week = %s
        """, (*player_ids, season, week))
        columns = [desc[0] for desc in cursor.description]
        stored = pd.DataFrame(cursor.fetchall(), columns=columns)

        if metadata is None:
            metadata = self._get_player_metadata(player_ids)
        stored_ids = set(stored['player_id']) if not stored.empty else set()
        missing = [pid for pid in player_ids if pid in metadata and pid not in stored_ids]

        frames = [stored] if not stored.empty else []
        if missing:
            logger.info(f"Computing features on demand for {len(missing)} players (week {week})")
            computed = self._compute_features_on_demand(missing, season, week, metadata)
            if not computed.empty:
                frames.append(computed)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _compute_features_on_demand(self, player_ids: List[str], season: int, week: int,
                                    metadata: Dict) -> pd.DataFrame:
        """Compute features for players without stored rows. Failures are skipped."""
        try:
            from data_pipeline.features.feature_engineer import FeatureEngineer
        except ImportError:
            logger.error("Feature engineer not available for on-demand computation")
            return pd.DataFrame()

        engineer = FeatureEngineer(self.db_connection)
        rows = []
        for player_id in player_ids:
            try:
                matchup = self._get_matchup(metadata[player_id].get('team'), season, week)
                rows.append(engineer.compute_player_features(player_id, season, week, matchup))
            except Exception as e:
                # Reads only, but a failed statement aborts the transaction
                self.db_connection.rollback()
                logger.warning(f"On-demand features failed for {player_id}: {e}")
        return pd.DataFrame(rows)

    def _get_matchup(self, team: Optional[str], season: int, week: int) -> Dict:
        """Look up the team's opponent/home status for the week, if synced."""
        if not team:
            return {}
        cursor = self.db_connection.cursor()
        cursor.execute("""
            SELECT opponent, is_home, (game_date AT TIME ZONE 'America/New_York')::date
            FROM team_weekly_matchups
            WHERE team = %s AND season = %s AND week = %s
        """, (team, season, week))
        row = cursor.fetchone()
        return {'opponent': row[0], 'is_home': row[1], 'game_date': row[2]} if row else {}

    @staticmethod
    def _unavailable(player_id: str, player_name: Optional[str], reason: str,
                     context: Optional[Dict] = None) -> WeeklyPrediction:
        return WeeklyPrediction(
            player_id=player_id,
            player_name=player_name,
            status='unavailable',
            reason=reason,
            message=UNAVAILABLE_MESSAGES[reason],
            context=context or {},
        )

    @staticmethod
    def _feature_summary(row: Dict, source: str = POINT_MODEL) -> Dict[str, object]:
        """JSON-safe explanation fields; None means 'no data', never a fake 0."""
        return {
            'avg_3_games': _to_float(row.get('fantasy_pts_avg_3')),
            'avg_5_games': _to_float(row.get('fantasy_pts_avg_5')),
            'trend': trend_label(row.get('fantasy_pts_trend_3')),
            'opponent_rank': _to_float(row.get('opp_position_rank')),
            'boom_rate': _to_float(row.get('boom_rate_5')),
            'games_played_prior': _to_float(row.get('games_played_prior')),
            'sleeper_projection': _to_float(row.get(SLEEPER_FEATURE)),
            # How the point prediction was produced: sleeper | sleeper+model | model
            'projection_source': source,
        }

    def _get_projections(self, player_ids: List[str], season: int, week: int) -> Dict[str, float]:
        """Sleeper's PPR projection for the week, by player_id (synced players only)."""
        placeholders = ','.join(['%s'] * len(player_ids))
        cursor = self.db_connection.cursor()
        cursor.execute(f"""
            SELECT player_id, projected_points_ppr
            FROM player_projections
            WHERE player_id IN ({placeholders})
                AND season = %s AND week = %s AND source = 'sleeper'
        """, (*player_ids, season, week))
        return {row[0]: _to_float(row[1]) for row in cursor.fetchall()}

    def predict_week(self, player_ids: List[str], season: int, week: int,
                     position: str = None) -> List[WeeklyPrediction]:
        """
        Predict fantasy points for players in an upcoming week.

        Returns exactly one WeeklyPrediction per distinct requested player:
        predictions first (highest points first), then unavailable players
        in request order, each with a reason.

        Args:
            player_ids: List of player IDs to predict
            season: NFL season
            week: Week to predict FOR
            position: Required position (optional); other positions are unavailable
        """
        player_ids = list(dict.fromkeys(str(pid) for pid in player_ids))
        if not player_ids:
            return []

        metadata = self._get_player_metadata(player_ids)
        # Team as of the requested week, not today's (trades), for display,
        # bye detection and on-demand features alike
        week_teams = self._get_week_teams(list(metadata), season, week) if metadata else {}
        metadata = {
            pid: {**meta, 'team': week_teams.get(pid, meta.get('team'))}
            for pid, meta in metadata.items()
        }
        schedule = self._get_schedule(season, week)
        played = self._get_played_ids(player_ids, season, week) if schedule else set()
        features_df = self.get_player_features(player_ids, season, week, metadata)
        if not features_df.empty:
            projections = self._get_projections(player_ids, season, week)
            features_df[SLEEPER_FEATURE] = features_df['player_id'].astype(str).map(projections)
        features_by_id = {
            str(row['player_id']): row
            for row in features_df.to_dict('records')
        } if not features_df.empty else {}

        unavailable: List[WeeklyPrediction] = []
        to_predict: Dict[str, List[str]] = {}

        for pid in player_ids:
            meta = metadata.get(pid)
            if meta is None:
                unavailable.append(self._unavailable(pid, None, 'unknown_player'))
                continue

            name = meta['player_name']
            pos = (meta['position'] or '').lower()
            features = features_by_id.get(pid)
            context = self._game_context(meta, schedule)
            # Only infer a bye when the week's schedule is known, and never
            # for a player who played that week (they may have changed teams)
            on_bye = (bool(schedule) and meta.get('team') and meta['team'] not in schedule
                      and pid not in played)

            reason = None
            if position and pos != position.lower():
                reason = 'position_mismatch'
            elif on_bye:
                reason = 'bye'
            elif pos not in self.models:
                reason = 'unsupported_position'
            elif features is None:
                reason = 'features_unavailable'
            elif not has_history(features):
                reason = 'no_history'

            if reason:
                unavailable.append(self._unavailable(pid, name, reason, context))
            else:
                to_predict.setdefault(pos, []).append(pid)

        predicted: List[WeeklyPrediction] = []
        for pos, ids in to_predict.items():
            rows = [features_by_id[pid] for pid in ids]
            preds = self.predict_with_confidence(pos, pd.DataFrame(rows))

            for pid, row, pred in zip(ids, rows, preds):
                predicted.append(WeeklyPrediction(
                    player_id=pid,
                    player_name=metadata[pid]['player_name'],
                    predicted_points=round(pred['predicted_points'], 1),
                    confidence_low=round(pred['confidence_low'], 1),
                    confidence_high=round(pred['confidence_high'], 1),
                    features_used=self._feature_summary(row, pred['source']),
                    context=self._game_context(metadata[pid], schedule),
                ))

        predicted.sort(key=lambda p: p.predicted_points, reverse=True)
        return predicted + unavailable

    def save(self, filepath: str) -> None:
        """Save trained models to disk."""
        if not self._is_trained:
            raise RuntimeError("No trained models to save")

        model_data = {
            'models': self.models,
            'quantile_models': self.quantile_models,
            'training_metrics': self.training_metrics,
            'feature_columns': self.feature_columns,
            'missing_strategy': self.missing_strategy,
            'point_strategy': self.point_strategy,
            'correction_models': self.correction_models,
            'interval_adjustment': self.interval_adjustment,
            'calibration': self.calibration,
        }

        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)

        # Write then atomically swap, so a running API that reloads on file
        # change never reads a half-written pickle
        tmp_path = f"{filepath}.tmp"
        with open(tmp_path, 'wb') as f:
            pickle.dump(model_data, f)
        os.replace(tmp_path, filepath)

        logger.info(f"Weekly predictor saved to {filepath}")

    def with_connection(self, db_connection) -> 'WeeklyPredictor':
        """
        Shallow copy sharing the (read-only) trained models but using its own
        database connection, so concurrent requests never share a connection.
        """
        view = copy.copy(self)
        view.db_connection = db_connection
        return view

    @classmethod
    def load(cls, filepath: str, db_connection=None) -> 'WeeklyPredictor':
        """Load trained models from disk."""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        predictor = cls(db_connection=db_connection)
        predictor.models = model_data['models']
        predictor.quantile_models = model_data['quantile_models']
        predictor.training_metrics = model_data['training_metrics']
        predictor.feature_columns = model_data.get('feature_columns', {})
        # Pickles saved before missing_strategy existed were trained on fillna(0)
        predictor.missing_strategy = model_data.get('missing_strategy', 'zero')
        # Pickles from before Sleeper anchoring: standalone model, uncalibrated range
        predictor.point_strategy = model_data.get('point_strategy', {})
        predictor.correction_models = model_data.get('correction_models', {})
        predictor.interval_adjustment = model_data.get('interval_adjustment', {})
        predictor.calibration = model_data.get('calibration', {})
        predictor._is_trained = True

        logger.info(f"Weekly predictor loaded from {filepath}")
        return predictor

    def backtest(self, position: str, min_train_weeks: int = 4) -> Dict[str, object]:
        """
        Walk-forward backtest using chronological week folds.
        """
        position = position.lower()
        X, y, meta = self._build_training_data(position)
        week_keys = (
            meta[['season', 'week']]
            .drop_duplicates()
            .sort_values(['season', 'week'])
            .reset_index(drop=True)
        )

        folds = []
        predictions = []

        for idx in range(min_train_weeks, len(week_keys)):
            test_key = week_keys.iloc[idx]
            train_keys = week_keys.iloc[:idx]

            train_mask = meta.merge(
                train_keys.assign(_keep=True),
                on=['season', 'week'],
                how='left'
            )['_keep'].notna()
            test_mask = (
                (meta['season'] == test_key['season']) &
                (meta['week'] == test_key['week'])
            )

            if not train_mask.any() or not test_mask.any():
                continue

            model = self._new_point_model()
            model.fit(X[train_mask], y[train_mask])
            y_pred = model.predict(X[test_mask])
            y_true = y[test_mask]

            fold_metrics = {
                'season': int(test_key['season']),
                'week': int(test_key['week']),
                'samples': int(test_mask.sum()),
                'mae': float(mean_absolute_error(y_true, y_pred)),
                'rmse': float(np.sqrt(mean_squared_error(y_true, y_pred))),
            }
            folds.append(fold_metrics)
            predictions.extend(zip(y_true.tolist(), y_pred.tolist()))

        if not folds:
            raise ValueError("Not enough chronological data to backtest")

        actuals = np.array([row[0] for row in predictions])
        preds = np.array([row[1] for row in predictions])
        return {
            'position': position,
            'folds': folds,
            'overall': {
                'mae': float(mean_absolute_error(actuals, preds)),
                'rmse': float(np.sqrt(mean_squared_error(actuals, preds))),
                'r2': float(r2_score(actuals, preds)) if len(actuals) > 1 else 0.0,
                'samples': int(len(actuals)),
            }
        }


def get_db_connection():
    """Get PostgreSQL connection."""
    import psycopg2

    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        port=os.environ.get('DB_PORT', 5432),
        database=os.environ.get('DB_NAME', 'football_dev'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASSWORD', 'postgres')
    )


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python weekly_predictor.py train              # Train all positions")
        print("  python weekly_predictor.py train qb           # Train specific position")
        print("  python weekly_predictor.py predict 15 rb      # Predict week 15 RBs")
        print("  python weekly_predictor.py backtest 10-14     # Backtest weeks 10-14")
        sys.exit(1)

    command = sys.argv[1]

    if command == 'train':
        print("Training weekly prediction models...")

        try:
            conn = get_db_connection()
            predictor = WeeklyPredictor(db_connection=conn)

            if len(sys.argv) > 2:
                # Train specific position
                position = sys.argv[2]
                metrics = predictor.train(position)
                print(f"\n{position.upper()} trained: MAE={metrics['mae']:.2f}")
            else:
                # Train all positions
                all_metrics = predictor.train_all_positions()

                print("\n" + "="*50)
                print("TRAINING COMPLETE")
                print("="*50)
                for pos, metrics in all_metrics.items():
                    print(f"{pos.upper()}: MAE={metrics['mae']:.2f}, R²={metrics['r2']:.3f}")

            # Save models
            predictor.save('models/weekly_predictor.pkl')
            print("\nModels saved to models/weekly_predictor.pkl")

            conn.close()

        except Exception as e:
            print(f"Error: {e}")
            print("\nMake sure:")
            print("1. PostgreSQL is running (docker-compose up -d)")
            print("2. Data has been synced (python run_pipeline.py full-sync)")
            print("3. Features have been computed (python run_pipeline.py compute-all-features)")
            sys.exit(1)

    elif command == 'predict':
        if len(sys.argv) < 4:
            print("Usage: python weekly_predictor.py predict <week> <position>")
            sys.exit(1)

        week = int(sys.argv[2])
        position = sys.argv[3]
        if len(sys.argv) > 4:
            season = int(sys.argv[4])
        else:
            from data_pipeline.season import current_context
            season = current_context().season

        try:
            conn = get_db_connection()
            predictor = WeeklyPredictor.load('models/weekly_predictor.pkl', db_connection=conn)

            # Get top players for position
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT player_id
                FROM player_features
                WHERE season = %s AND week = %s
                LIMIT 50
            """, (season, week))
            player_ids = [row[0] for row in cursor.fetchall()]

            predictions = predictor.predict_week(player_ids, season, week, position)

            print(f"\nWeek {week} {position.upper()} Predictions:")
            print("-" * 60)
            for pred in [p for p in predictions if p.status == 'ok'][:20]:
                print(f"{pred.player_name:25} {pred.predicted_points:5.1f} pts "
                      f"({pred.confidence_low:.1f}-{pred.confidence_high:.1f})")
            skipped = [p for p in predictions if p.status != 'ok']
            if skipped:
                print(f"\n{len(skipped)} players unavailable (e.g. {skipped[0].reason})")

            conn.close()

        except FileNotFoundError:
            print("Model not found. Run 'python weekly_predictor.py train' first.")
            sys.exit(1)

    elif command == 'backtest':
        if len(sys.argv) < 3:
            print("Usage: python weekly_predictor.py backtest <position>")
            sys.exit(1)

        position = sys.argv[2]
        try:
            conn = get_db_connection()
            predictor = WeeklyPredictor(db_connection=conn)
            results = predictor.backtest(position)
            print(f"\nBacktest for {position.upper()}:")
            print(results['overall'])
            conn.close()
        except Exception as e:
            print(f"Backtest failed: {e}")
            sys.exit(1)

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
