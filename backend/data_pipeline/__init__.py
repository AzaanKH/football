"""
Data Pipeline Module

This module handles automated data collection for fantasy football predictions.
It uses multiple data sources with fallback support:

1. Sleeper API (Primary) - Free, no auth required
2. ESPN Fantasy API (Secondary) - Cross-validation
3. Pro Football Reference (Fallback) - Web scraping

Usage:
    from data_pipeline import DataOrchestrator

    orchestrator = DataOrchestrator()
    orchestrator.sync_players()
    orchestrator.sync_weekly_stats(season=2024, week=1)
"""

from .sleeper_client import SleeperClient
from .espn_client import ESPNClient
from .scraper import ProFootballReferenceScraper
from .orchestrator import DataOrchestrator

__all__ = [
    'SleeperClient',
    'ESPNClient',
    'ProFootballReferenceScraper',
    'DataOrchestrator'
]
