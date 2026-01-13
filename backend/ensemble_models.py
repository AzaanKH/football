"""
Ensemble Model Predictor for Fantasy Football

Combines XGBoost, LightGBM, CatBoost, and RandomForest for robust predictions.
Uses median aggregation and quantile regression for confidence intervals.
"""

import pandas as pd
import numpy as np
import pickle
import os
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

# Optional imports - graceful degradation if not installed
try:
    from lightgbm import LGBMRegressor
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    LGBMRegressor = None

try:
    from catboost import CatBoostRegressor
    CATBOOST_AVAILABLE = True
except ImportError:
    CATBOOST_AVAILABLE = False
    CatBoostRegressor = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    """Container for ensemble prediction results."""
    prediction: float
    confidence_low: float
    confidence_high: float
    model_predictions: Dict[str, float]


class EnsemblePredictor:
    """
    Ensemble model combining multiple gradient boosting algorithms.

    Uses median aggregation for robust predictions and quantile regression
    for confidence intervals.
    """

    # Default feature columns (from existing models.py)
    DEFAULT_FEATURES = [
        'PassingYDS', 'PassingTD', 'PassingInt', 'RushingYDS', 'RushingTD',
        'ReceivingRec', 'ReceivingYDS', 'ReceivingTD', 'Fum', 'TouchCarries',
        'TouchReceptions', 'Targets', 'RzTouch', 'Rank'
    ]

    # Hyperparameter grids for each model type
    PARAM_GRIDS = {
        'xgboost': {
            'n_estimators': [100, 200],
            'learning_rate': [0.05, 0.1],
            'max_depth': [3, 5],
            'subsample': [0.8, 1.0],
            'colsample_bytree': [0.8, 1.0]
        },
        'lightgbm': {
            'n_estimators': [100, 200],
            'learning_rate': [0.05, 0.1],
            'max_depth': [3, 5],
            'num_leaves': [31, 50],
            'subsample': [0.8, 1.0]
        },
        'catboost': {
            'iterations': [100, 200],
            'learning_rate': [0.05, 0.1],
            'depth': [4, 6],
            'l2_leaf_reg': [1, 3]
        },
        'random_forest': {
            'n_estimators': [100, 200],
            'max_depth': [5, 10, None],
            'min_samples_split': [2, 5],
            'min_samples_leaf': [1, 2]
        }
    }

    def __init__(self, features: Optional[List[str]] = None, random_state: int = 42):
        """
        Initialize the ensemble predictor.

        Args:
            features: List of feature column names. Defaults to DEFAULT_FEATURES.
            random_state: Random seed for reproducibility.
        """
        self.features = features or self.DEFAULT_FEATURES
        self.random_state = random_state
        self.models: Dict[str, Any] = {}
        self.quantile_models: Dict[str, Any] = {}  # For confidence intervals
        self.best_params: Dict[str, Dict] = {}
        self.training_metrics: Dict[str, Dict] = {}
        self._is_trained = False

    def _create_base_models(self) -> Dict[str, Any]:
        """Create instances of all base models."""
        models = {
            'xgboost': XGBRegressor(random_state=self.random_state, n_jobs=-1),
            'random_forest': RandomForestRegressor(random_state=self.random_state, n_jobs=-1)
        }

        if LIGHTGBM_AVAILABLE:
            models['lightgbm'] = LGBMRegressor(random_state=self.random_state, n_jobs=-1, verbose=-1)
        else:
            logger.warning("LightGBM not available. Install with: pip install lightgbm")

        if CATBOOST_AVAILABLE:
            models['catboost'] = CatBoostRegressor(random_state=self.random_state, verbose=0)
        else:
            logger.warning("CatBoost not available. Install with: pip install catboost")

        return models

    def _tune_model(self, model_name: str, model: Any, X: pd.DataFrame, y: pd.Series) -> Tuple[Any, Dict]:
        """
        Tune hyperparameters for a single model using GridSearchCV.

        Args:
            model_name: Name of the model type
            model: Model instance
            X: Feature DataFrame
            y: Target Series

        Returns:
            Tuple of (best_model, best_params)
        """
        param_grid = self.PARAM_GRIDS.get(model_name, {})

        if not param_grid:
            logger.info(f"No param grid for {model_name}, using defaults")
            model.fit(X, y)
            return model, {}

        # CatBoost has compatibility issues with sklearn GridSearchCV in newer versions
        # Use CatBoost's native grid_search or manual tuning
        if model_name == 'catboost':
            return self._tune_catboost(X, y)

        logger.info(f"Tuning {model_name} with GridSearchCV...")

        grid_search = GridSearchCV(
            estimator=model,
            param_grid=param_grid,
            cv=5,
            scoring='neg_mean_absolute_error',
            n_jobs=-1,
            verbose=0
        )

        grid_search.fit(X, y)

        logger.info(f"Best params for {model_name}: {grid_search.best_params_}")
        logger.info(f"Best CV MAE for {model_name}: {-grid_search.best_score_:.4f}")

        return grid_search.best_estimator_, grid_search.best_params_

    def _tune_catboost(self, X: pd.DataFrame, y: pd.Series) -> Tuple[Any, Dict]:
        """
        Tune CatBoost using its native grid search to avoid sklearn compatibility issues.
        """
        from catboost import CatBoostRegressor

        logger.info("Tuning catboost with native grid search...")

        # Use a smaller grid for faster training
        best_model = None
        best_mae = float('inf')
        best_params = {}

        param_combinations = [
            {'iterations': 100, 'learning_rate': 0.1, 'depth': 4, 'l2_leaf_reg': 3},
            {'iterations': 200, 'learning_rate': 0.05, 'depth': 6, 'l2_leaf_reg': 1},
            {'iterations': 150, 'learning_rate': 0.1, 'depth': 6, 'l2_leaf_reg': 3},
        ]

        for params in param_combinations:
            model = CatBoostRegressor(
                **params,
                random_state=self.random_state,
                verbose=0
            )

            # Simple train/validation split for tuning
            X_train, X_val, y_train, y_val = train_test_split(
                X, y, test_size=0.2, random_state=self.random_state
            )

            model.fit(X_train, y_train, eval_set=(X_val, y_val), early_stopping_rounds=20, verbose=0)
            y_pred = model.predict(X_val)
            mae = mean_absolute_error(y_val, y_pred)

            if mae < best_mae:
                best_mae = mae
                best_model = model
                best_params = params

        # Retrain best model on full data
        final_model = CatBoostRegressor(
            **best_params,
            random_state=self.random_state,
            verbose=0
        )
        final_model.fit(X, y)

        logger.info(f"Best params for catboost: {best_params}")
        logger.info(f"Best CV MAE for catboost: {best_mae:.4f}")

        return final_model, best_params

    def _train_quantile_models(self, X: pd.DataFrame, y: pd.Series) -> None:
        """
        Train quantile regression models for confidence intervals.

        Uses GradientBoostingRegressor with quantile loss for 5th and 95th percentiles.
        """
        logger.info("Training quantile models for confidence intervals...")

        # 5th percentile (lower bound)
        self.quantile_models['lower'] = GradientBoostingRegressor(
            loss='quantile',
            alpha=0.05,
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            random_state=self.random_state
        )
        self.quantile_models['lower'].fit(X, y)

        # 95th percentile (upper bound)
        self.quantile_models['upper'] = GradientBoostingRegressor(
            loss='quantile',
            alpha=0.95,
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            random_state=self.random_state
        )
        self.quantile_models['upper'].fit(X, y)

        logger.info("Quantile models trained successfully")

    def train(self, data: pd.DataFrame, target_column: str = 'TotalPoints',
              tune_hyperparameters: bool = True) -> Dict[str, Any]:
        """
        Train all ensemble models on the provided data.

        Args:
            data: DataFrame containing features and target
            target_column: Name of the target column
            tune_hyperparameters: Whether to use GridSearchCV for tuning

        Returns:
            Dictionary with training metrics for each model
        """
        logger.info(f"Training ensemble on {len(data)} samples with {len(self.features)} features")

        # Prepare data
        available_features = [f for f in self.features if f in data.columns]
        if len(available_features) < len(self.features):
            missing = set(self.features) - set(available_features)
            logger.warning(f"Missing features: {missing}")

        X = data[available_features].copy()
        y = data[target_column].copy()

        # Fill missing values
        X = X.fillna(0)
        y = y.fillna(y.mean())

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=self.random_state
        )

        # Train each base model
        base_models = self._create_base_models()

        for model_name, model in base_models.items():
            logger.info(f"\nTraining {model_name}...")

            if tune_hyperparameters:
                best_model, best_params = self._tune_model(model_name, model, X_train, y_train)
                self.models[model_name] = best_model
                self.best_params[model_name] = best_params
            else:
                model.fit(X_train, y_train)
                self.models[model_name] = model

            # Evaluate on test set
            y_pred = self.models[model_name].predict(X_test)
            metrics = {
                'mae': mean_absolute_error(y_test, y_pred),
                'rmse': np.sqrt(mean_squared_error(y_test, y_pred)),
                'r2': r2_score(y_test, y_pred)
            }
            self.training_metrics[model_name] = metrics
            logger.info(f"{model_name} - MAE: {metrics['mae']:.4f}, RMSE: {metrics['rmse']:.4f}, R2: {metrics['r2']:.4f}")

        # Train quantile models for confidence intervals
        self._train_quantile_models(X_train, y_train)

        # Compute ensemble metrics
        ensemble_pred = self._aggregate_predictions(
            {name: model.predict(X_test) for name, model in self.models.items()}
        )
        ensemble_metrics = {
            'mae': mean_absolute_error(y_test, ensemble_pred),
            'rmse': np.sqrt(mean_squared_error(y_test, ensemble_pred)),
            'r2': r2_score(y_test, ensemble_pred)
        }
        self.training_metrics['ensemble'] = ensemble_metrics
        logger.info(f"\nEnsemble - MAE: {ensemble_metrics['mae']:.4f}, RMSE: {ensemble_metrics['rmse']:.4f}, R2: {ensemble_metrics['r2']:.4f}")

        self._is_trained = True
        return self.training_metrics

    def _aggregate_predictions(self, predictions: Dict[str, np.ndarray],
                               method: str = 'median') -> np.ndarray:
        """
        Aggregate predictions from multiple models.

        Args:
            predictions: Dictionary of model_name -> predictions array
            method: Aggregation method ('median' or 'mean')

        Returns:
            Aggregated predictions array
        """
        pred_array = np.array(list(predictions.values()))

        if method == 'median':
            return np.median(pred_array, axis=0)
        elif method == 'mean':
            return np.mean(pred_array, axis=0)
        else:
            raise ValueError(f"Unknown aggregation method: {method}")

    def predict(self, X: pd.DataFrame, method: str = 'median') -> np.ndarray:
        """
        Make predictions using the ensemble.

        Args:
            X: Feature DataFrame
            method: Aggregation method ('median' or 'mean')

        Returns:
            Array of predictions
        """
        if not self._is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        # Ensure features are in correct order and fill missing
        available_features = [f for f in self.features if f in X.columns]
        X_prepared = X[available_features].copy().fillna(0)

        # Get predictions from each model
        predictions = {}
        for model_name, model in self.models.items():
            predictions[model_name] = model.predict(X_prepared)

        return self._aggregate_predictions(predictions, method)

    def predict_with_confidence(self, X: pd.DataFrame,
                                method: str = 'median') -> List[PredictionResult]:
        """
        Make predictions with confidence intervals.

        Args:
            X: Feature DataFrame
            method: Aggregation method for point prediction

        Returns:
            List of PredictionResult objects
        """
        if not self._is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        # Prepare features
        available_features = [f for f in self.features if f in X.columns]
        X_prepared = X[available_features].copy().fillna(0)

        # Get predictions from each model
        model_preds = {}
        for model_name, model in self.models.items():
            model_preds[model_name] = model.predict(X_prepared)

        # Aggregate predictions
        ensemble_pred = self._aggregate_predictions(model_preds, method)

        # Get confidence intervals from quantile models
        lower_bound = self.quantile_models['lower'].predict(X_prepared)
        upper_bound = self.quantile_models['upper'].predict(X_prepared)

        # Build results
        results = []
        for i in range(len(X)):
            result = PredictionResult(
                prediction=float(ensemble_pred[i]),
                confidence_low=float(lower_bound[i]),
                confidence_high=float(upper_bound[i]),
                model_predictions={name: float(preds[i]) for name, preds in model_preds.items()}
            )
            results.append(result)

        return results

    def get_model_predictions(self, X: pd.DataFrame) -> Dict[str, np.ndarray]:
        """
        Get individual predictions from each model.

        Args:
            X: Feature DataFrame

        Returns:
            Dictionary of model_name -> predictions array
        """
        if not self._is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        available_features = [f for f in self.features if f in X.columns]
        X_prepared = X[available_features].copy().fillna(0)

        return {name: model.predict(X_prepared) for name, model in self.models.items()}

    def get_feature_importance(self) -> pd.DataFrame:
        """
        Get aggregated feature importance from all models.

        Returns:
            DataFrame with feature importance scores
        """
        if not self._is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        importance_data = {}

        for model_name, model in self.models.items():
            if hasattr(model, 'feature_importances_'):
                importance_data[model_name] = model.feature_importances_

        if not importance_data:
            return pd.DataFrame()

        # Get feature names - use the features we know about
        n_features = len(list(importance_data.values())[0])
        feature_names = self.features[:n_features]

        df = pd.DataFrame(importance_data, index=feature_names)
        df['mean_importance'] = df.mean(axis=1)
        df = df.sort_values('mean_importance', ascending=False)

        return df

    def save(self, filepath: str) -> None:
        """
        Save the ensemble model to disk.

        Args:
            filepath: Path to save the model
        """
        if not self._is_trained:
            raise RuntimeError("Model not trained. Call train() first.")

        model_data = {
            'models': self.models,
            'quantile_models': self.quantile_models,
            'best_params': self.best_params,
            'training_metrics': self.training_metrics,
            'features': self.features,
            'random_state': self.random_state
        }

        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)

        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)

        logger.info(f"Ensemble model saved to {filepath}")

    @classmethod
    def load(cls, filepath: str) -> 'EnsemblePredictor':
        """
        Load an ensemble model from disk.

        Args:
            filepath: Path to the saved model

        Returns:
            Loaded EnsemblePredictor instance
        """
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        predictor = cls(
            features=model_data['features'],
            random_state=model_data['random_state']
        )
        predictor.models = model_data['models']
        predictor.quantile_models = model_data['quantile_models']
        predictor.best_params = model_data['best_params']
        predictor.training_metrics = model_data['training_metrics']
        predictor._is_trained = True

        logger.info(f"Ensemble model loaded from {filepath}")
        return predictor


def train_position_ensembles(data_dir: str = '.', output_dir: str = 'models') -> Dict[str, Dict]:
    """
    Train ensemble models for all positions (QB, RB, WR).

    Args:
        data_dir: Directory containing CSV data files
        output_dir: Directory to save trained models

    Returns:
        Dictionary with training metrics for each position
    """
    # File paths relative to data_dir - handles subdirectory structure
    positions = {
        'qb': [
            'old_data/filtered_quarterbacks.csv',
            'week_1/week_1_qbs.csv',
            'week_2/week_2_qbs.csv',
            'week_3/week_3_qbs.csv',
            'quarterbacks_rankings_week_4.csv'
        ],
        'rb': [
            'old_data/filtered_running_backs.csv',
            'week_1/week_1_rbs.csv',
            'week_2/week_2_rbs.csv',
            'week_3/week_3_rbs.csv',
            'running_backs_rankings_week_4.csv'
        ],
        'wr': [
            'old_data/filtered_wide_receivers.csv',
            'week_1/week_1_wrs.csv',
            'week_2/week_2_wrs.csv',
            'week_3/week_3_wrs.csv',
            'rankings/week_4_rankings.csv',
            'wide_receivers_rankings_week_4.csv'
        ]
    }

    all_metrics = {}

    for position, files in positions.items():
        logger.info(f"\n{'='*50}")
        logger.info(f"Training {position.upper()} ensemble")
        logger.info(f"{'='*50}")

        # Load and combine data
        dfs = []
        for filename in files:
            filepath = os.path.join(data_dir, filename)
            if os.path.exists(filepath):
                df = pd.read_csv(filepath)
                dfs.append(df)
                logger.info(f"Loaded {filename}: {len(df)} rows")
            else:
                logger.warning(f"File not found: {filepath}")

        if not dfs:
            logger.error(f"No data found for {position}")
            continue

        combined_data = pd.concat(dfs, ignore_index=True)
        logger.info(f"Combined data: {len(combined_data)} total rows")

        # Train ensemble
        ensemble = EnsemblePredictor()
        metrics = ensemble.train(combined_data, tune_hyperparameters=True)

        # Save model
        os.makedirs(output_dir, exist_ok=True)
        model_path = os.path.join(output_dir, f'{position}_ensemble.pkl')
        ensemble.save(model_path)

        all_metrics[position] = metrics

        # Show feature importance
        importance = ensemble.get_feature_importance()
        if not importance.empty:
            logger.info(f"\nTop 5 features for {position.upper()}:")
            for feat, row in importance.head().iterrows():
                logger.info(f"  {feat}: {row['mean_importance']:.4f}")

    return all_metrics


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'train':
        # Train all position ensembles
        data_dir = sys.argv[2] if len(sys.argv) > 2 else '.'
        output_dir = sys.argv[3] if len(sys.argv) > 3 else 'models'

        metrics = train_position_ensembles(data_dir, output_dir)

        print("\n" + "="*50)
        print("TRAINING COMPLETE")
        print("="*50)
        for position, pos_metrics in metrics.items():
            print(f"\n{position.upper()}:")
            for model, model_metrics in pos_metrics.items():
                print(f"  {model}: MAE={model_metrics['mae']:.4f}, R2={model_metrics['r2']:.4f}")
    else:
        print("Usage: python ensemble_models.py train [data_dir] [output_dir]")
        print("\nExample:")
        print("  python ensemble_models.py train . models")
