"""
Feature Engineering Module for Fantasy Football

This module provides computed features from raw player statistics:
- Rolling averages (3, 5, 10 game windows)
- Efficiency metrics (yards per carry, catch rate, etc.)
- Consistency metrics (standard deviation, boom/bust rates)
- Trend features (performance trajectory)
- Matchup features (opponent strength)

Usage:
    from data_pipeline.features import FeatureEngineer

    engineer = FeatureEngineer(db_connection)
    engineer.compute_all_features(season=2024, week=10)
"""

from .feature_engineer import FeatureEngineer
from .rolling_averages import RollingAverages
from .efficiency import EfficiencyMetrics
from .consistency import ConsistencyMetrics
from .trends import TrendFeatures
from .matchups import MatchupFeatures

__all__ = [
    'FeatureEngineer',
    'RollingAverages',
    'EfficiencyMetrics',
    'ConsistencyMetrics',
    'TrendFeatures',
    'MatchupFeatures',
]
