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
import pickle
import os
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WeeklyPrediction:
    """Container for weekly prediction results."""
    player_id: str
    player_name: str
    predicted_points: float
    confidence_low: float
    confidence_high: float
    features_used: Dict[str, float]


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
    ]

    # Separate feature sets by position
    QB_FEATURES = [
        'fantasy_pts_avg_3', 'fantasy_pts_avg_5',
        'passing_yds_avg_3', 'rushing_yds_avg_3',
        'yards_per_pass_attempt', 'td_per_pass_attempt',
        'fantasy_pts_std_5', 'boom_rate_5', 'bust_rate_5', 'floor_score',
        'fantasy_pts_trend_3', 'usage_trend_3',
        'opp_position_rank', 'opp_fantasy_pts_allowed', 'is_home', 'days_rest',
    ]

    RB_FEATURES = [
        'fantasy_pts_avg_3', 'fantasy_pts_avg_5',
        'rushing_yds_avg_3', 'receiving_yds_avg_3',
        'touches_avg_3', 'targets_avg_3',
        'yards_per_carry', 'yards_per_target', 'td_per_touch', 'catch_rate',
        'fantasy_pts_std_5', 'boom_rate_5', 'bust_rate_5', 'floor_score',
        'fantasy_pts_trend_3', 'usage_trend_3',
        'opp_position_rank', 'opp_fantasy_pts_allowed', 'is_home', 'days_rest',
    ]

    WR_FEATURES = [
        'fantasy_pts_avg_3', 'fantasy_pts_avg_5',
        'receiving_yds_avg_3', 'targets_avg_3', 'receptions_avg_3',
        'yards_per_target', 'yards_per_reception', 'td_per_touch', 'catch_rate',
        'fantasy_pts_std_5', 'boom_rate_5', 'bust_rate_5', 'floor_score',
        'fantasy_pts_trend_3', 'usage_trend_3',
        'opp_position_rank', 'opp_fantasy_pts_allowed', 'is_home', 'days_rest',
    ]

    def __init__(self, db_connection=None):
        """
        Initialize predictor.

        Args:
            db_connection: PostgreSQL connection (optional, for DB queries)
        """
        self.db_connection = db_connection
        self.models: Dict[str, XGBRegressor] = {}
        self.quantile_models: Dict[str, Dict[str, GradientBoostingRegressor]] = {}
        self.training_metrics: Dict[str, Dict] = {}
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

    def _build_training_data(self, position: str) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Build training dataset from database.

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
                pws.fantasy_points_ppr as actual_points
            FROM player_features pf
            JOIN player_weekly_stats pws
                ON pf.player_id = pws.player_id
                AND pf.season = pws.season
                AND pf.week = pws.week
            JOIN players p
                ON pf.player_id = p.player_id
            WHERE p.position = %s
                AND pws.fantasy_points_ppr IS NOT NULL
                AND pf.fantasy_pts_avg_3 IS NOT NULL
            ORDER BY pf.season, pf.week
        """

        cursor.execute(query, (position.upper(),))
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        if not rows:
            raise ValueError(f"No training data found for position {position}")

        df = pd.DataFrame(rows, columns=columns)
        logger.info(f"Loaded {len(df)} training samples for {position.upper()}")

        # Get features and target
        feature_cols = self.get_features_for_position(position)
        available_features = [f for f in feature_cols if f in df.columns]

        X = df[available_features].copy()
        y = df['actual_points'].copy()

        # Convert all columns to numeric (handles object types from PostgreSQL)
        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors='coerce')

        # Fill missing values
        X = X.fillna(0)

        # Convert boolean to int
        if 'is_home' in X.columns:
            X['is_home'] = X['is_home'].astype(int)

        # Ensure target is numeric
        y = pd.to_numeric(y, errors='coerce').fillna(0)

        return X, y

    def train(self, position: str, X: pd.DataFrame = None, y: pd.Series = None) -> Dict:
        """
        Train prediction model for a position.

        Args:
            position: 'qb', 'rb', or 'wr'
            X: Optional feature DataFrame (if not provided, queries DB)
            y: Optional target Series

        Returns:
            Training metrics dictionary
        """
        position = position.lower()

        if X is None or y is None:
            X, y = self._build_training_data(position)

        logger.info(f"Training {position.upper()} model with {len(X)} samples, {len(X.columns)} features")

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # Train main model
        model = XGBRegressor(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1
        )
        model.fit(X_train, y_train)
        self.models[position] = model

        # Train quantile models for confidence intervals
        self.quantile_models[position] = {}

        # Lower bound (10th percentile)
        lower_model = GradientBoostingRegressor(
            loss='quantile',
            alpha=0.10,
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            random_state=42
        )
        lower_model.fit(X_train, y_train)
        self.quantile_models[position]['lower'] = lower_model

        # Upper bound (90th percentile)
        upper_model = GradientBoostingRegressor(
            loss='quantile',
            alpha=0.90,
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            random_state=42
        )
        upper_model.fit(X_train, y_train)
        self.quantile_models[position]['upper'] = upper_model

        # Evaluate
        y_pred = model.predict(X_test)
        metrics = {
            'mae': mean_absolute_error(y_test, y_pred),
            'rmse': np.sqrt(mean_squared_error(y_test, y_pred)),
            'r2': r2_score(y_test, y_pred),
            'samples': len(X),
            'features': list(X.columns)
        }
        self.training_metrics[position] = metrics

        logger.info(f"{position.upper()} - MAE: {metrics['mae']:.2f}, RMSE: {metrics['rmse']:.2f}, R²: {metrics['r2']:.3f}")

        # Feature importance
        importance = pd.DataFrame({
            'feature': X.columns,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)

        logger.info(f"Top 5 features for {position.upper()}:")
        for _, row in importance.head().iterrows():
            logger.info(f"  {row['feature']}: {row['importance']:.4f}")

        self._is_trained = True
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

        # Ensure correct features
        model_features = self.get_features_for_position(position)
        X = features.copy()

        # Add missing features as 0
        for col in model_features:
            if col not in X.columns:
                X[col] = 0

        # Select only needed features in correct order
        available = [f for f in model_features if f in X.columns]
        X = X[available]

        # Convert all columns to numeric (handles object types from PostgreSQL)
        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors='coerce')

        X = X.fillna(0)

        # Convert boolean
        if 'is_home' in X.columns:
            X['is_home'] = X['is_home'].astype(int)

        return self.models[position].predict(X)

    def predict_with_confidence(self, position: str, features: pd.DataFrame) -> List[Dict]:
        """
        Make predictions with confidence intervals.

        Args:
            position: Player position
            features: DataFrame with feature columns

        Returns:
            List of dicts with prediction, confidence_low, confidence_high
        """
        position = position.lower()
        if position not in self.models:
            raise RuntimeError(f"No model trained for position: {position}")

        # Prepare features
        model_features = self.get_features_for_position(position)
        X = features.copy()

        for col in model_features:
            if col not in X.columns:
                X[col] = 0

        available = [f for f in model_features if f in X.columns]
        X = X[available]

        # Convert all columns to numeric (handles object types from PostgreSQL)
        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors='coerce')

        X = X.fillna(0)

        if 'is_home' in X.columns:
            X['is_home'] = X['is_home'].astype(int)

        # Get predictions
        predictions = self.models[position].predict(X)
        lower_bounds = self.quantile_models[position]['lower'].predict(X)
        upper_bounds = self.quantile_models[position]['upper'].predict(X)

        results = []
        for i in range(len(predictions)):
            results.append({
                'predicted_points': float(predictions[i]),
                'confidence_low': float(max(0, lower_bounds[i])),  # Can't be negative
                'confidence_high': float(upper_bounds[i]),
            })

        return results

    def get_player_features(self, player_ids: List[str], season: int, week: int) -> pd.DataFrame:
        """
        Get computed features for players from database.

        Args:
            player_ids: List of player IDs
            season: NFL season year
            week: Week number to predict FOR

        Returns:
            DataFrame with features for each player
        """
        if not self.db_connection:
            raise RuntimeError("Database connection required")

        cursor = self.db_connection.cursor()

        # Get features for the specified week
        # These features were computed using data from weeks < week
        placeholders = ','.join(['%s'] * len(player_ids))
        query = f"""
            SELECT
                pf.*,
                p.full_name as player_name,
                p.position
            FROM player_features pf
            JOIN players p ON pf.player_id = p.player_id
            WHERE pf.player_id IN ({placeholders})
                AND pf.season = %s
                AND pf.week = %s
        """

        cursor.execute(query, (*player_ids, season, week))
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        if not rows:
            # Features not yet computed - compute on the fly
            logger.warning(f"No pre-computed features for week {week}, computing on demand")
            return self._compute_features_on_demand(player_ids, season, week)

        return pd.DataFrame(rows, columns=columns)

    def _compute_features_on_demand(self, player_ids: List[str], season: int, week: int) -> pd.DataFrame:
        """Compute features on demand if not pre-computed."""
        try:
            from data_pipeline.features.feature_engineer import FeatureEngineer

            engineer = FeatureEngineer(self.db_connection)

            all_features = []
            for player_id in player_ids:
                features = engineer.compute_player_features(player_id, season, week)
                all_features.append(features)

            return pd.DataFrame(all_features)
        except ImportError:
            logger.error("Feature engineer not available for on-demand computation")
            return pd.DataFrame()

    def predict_week(self, player_ids: List[str], season: int, week: int,
                     position: str = None) -> List[WeeklyPrediction]:
        """
        Predict fantasy points for players in upcoming week.

        Args:
            player_ids: List of player IDs to predict
            season: NFL season
            week: Week to predict FOR
            position: Position filter (optional)

        Returns:
            List of WeeklyPrediction objects
        """
        # Get features from database
        features_df = self.get_player_features(player_ids, season, week)

        if features_df.empty:
            logger.warning("No features available for prediction")
            return []

        results = []

        # Group by position and predict
        for pos in features_df['position'].unique():
            pos_lower = pos.lower()
            if position and pos_lower != position.lower():
                continue

            if pos_lower not in self.models:
                logger.warning(f"No model for position {pos}, skipping")
                continue

            pos_df = features_df[features_df['position'] == pos]

            # Get predictions with confidence
            preds = self.predict_with_confidence(pos_lower, pos_df)

            for i, (_, row) in enumerate(pos_df.iterrows()):
                pred = preds[i]

                # Extract key features for explanation
                feature_summary = {
                    'avg_3_games': row.get('fantasy_pts_avg_3', 0),
                    'avg_5_games': row.get('fantasy_pts_avg_5', 0),
                    'trend': 'improving' if row.get('fantasy_pts_trend_3', 0) > 0 else 'declining',
                    'opponent_rank': row.get('opp_position_rank'),
                    'boom_rate': row.get('boom_rate_5', 0),
                }

                results.append(WeeklyPrediction(
                    player_id=row['player_id'],
                    player_name=row.get('player_name', f"Player {row['player_id']}"),
                    predicted_points=round(pred['predicted_points'], 1),
                    confidence_low=round(pred['confidence_low'], 1),
                    confidence_high=round(pred['confidence_high'], 1),
                    features_used=feature_summary
                ))

        # Sort by predicted points
        results.sort(key=lambda x: x.predicted_points, reverse=True)

        return results

    def save(self, filepath: str) -> None:
        """Save trained models to disk."""
        if not self._is_trained:
            raise RuntimeError("No trained models to save")

        model_data = {
            'models': self.models,
            'quantile_models': self.quantile_models,
            'training_metrics': self.training_metrics,
        }

        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)

        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)

        logger.info(f"Weekly predictor saved to {filepath}")

    @classmethod
    def load(cls, filepath: str, db_connection=None) -> 'WeeklyPredictor':
        """Load trained models from disk."""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        predictor = cls(db_connection=db_connection)
        predictor.models = model_data['models']
        predictor.quantile_models = model_data['quantile_models']
        predictor.training_metrics = model_data['training_metrics']
        predictor._is_trained = True

        logger.info(f"Weekly predictor loaded from {filepath}")
        return predictor


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
        season = int(sys.argv[4]) if len(sys.argv) > 4 else 2024

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
            for pred in predictions[:20]:
                print(f"{pred.player_name:25} {pred.predicted_points:5.1f} pts "
                      f"({pred.confidence_low:.1f}-{pred.confidence_high:.1f})")

            conn.close()

        except FileNotFoundError:
            print("Model not found. Run 'python weekly_predictor.py train' first.")
            sys.exit(1)

    elif command == 'backtest':
        print("Backtesting not yet implemented")
        # TODO: Implement walk-forward backtesting

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
