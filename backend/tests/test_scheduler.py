"""
Unit tests for weekly scheduler context resolution and orchestration.
"""

import pytest
from unittest.mock import MagicMock, patch

import scheduler


class TestSchedulerUnit:
    @pytest.mark.unit
    def test_resolve_pipeline_context_uses_explicit_prediction_week(self):
        """Tuesday automation should treat the current NFL week as the upcoming prediction week."""
        context = scheduler.resolve_pipeline_context(season=2024, nfl_week=10)

        assert context['season'] == 2024
        assert context['prediction_week'] == 10
        assert context['completed_week'] == 9
        assert context['weeks_to_refresh'] == [8, 9]

    @pytest.mark.unit
    def test_resolve_pipeline_context_handles_week_one(self):
        """Week one should not attempt to sync a nonexistent completed week zero."""
        context = scheduler.resolve_pipeline_context(season=2024, nfl_week=1)

        assert context['prediction_week'] == 1
        assert context['completed_week'] == 0
        assert context['weeks_to_refresh'] == []

    @pytest.mark.unit
    def test_job_sync_prediction_context_runs_matchups_and_projections(self):
        """Prediction-context sync should update both matchups and projections for the upcoming week."""
        with patch('scheduler.resolve_pipeline_context', return_value={
            'season': 2024,
            'prediction_week': 10,
            'completed_week': 9,
            'weeks_to_refresh': [8, 9],
            'nfl_week': 10,
        }), patch('data_pipeline.DataOrchestrator') as orchestrator_cls:
            orchestrator = MagicMock()
            orchestrator.sync_matchups.return_value = {'processed': 32}
            orchestrator.sync_projections.return_value = {'processed': 400}
            orchestrator_cls.return_value.__enter__.return_value = orchestrator

            result = scheduler.job_sync_prediction_context()

            assert result['matchups']['processed'] == 32
            assert result['projections']['processed'] == 400
            orchestrator.sync_matchups.assert_called_once_with(2024, 10)
            orchestrator.sync_projections.assert_called_once_with(2024, 10)

    @pytest.mark.unit
    def test_matchup_failure_does_not_block_projections(self):
        """Projections are the point estimate; a broken matchup feed must not skip them."""
        with patch('scheduler.resolve_pipeline_context', return_value={
            'season': 2024, 'prediction_week': 10, 'completed_week': 9,
            'weeks_to_refresh': [8, 9], 'nfl_week': 10,
        }), patch('data_pipeline.DataOrchestrator') as orchestrator_cls:
            orchestrator = MagicMock()
            orchestrator.sync_matchups.side_effect = Exception('No matchup data available')
            orchestrator.sync_projections.return_value = {'processed': 400}
            orchestrator_cls.return_value.__enter__.return_value = orchestrator

            result = scheduler.job_sync_prediction_context()

            assert result['matchups']['status'] == 'failed'
            assert result['projections']['processed'] == 400

    @pytest.mark.unit
    def test_job_refresh_projections_syncs_prediction_week(self):
        with patch('scheduler.resolve_pipeline_context', return_value={
            'season': 2025, 'prediction_week': 7, 'completed_week': 6,
            'weeks_to_refresh': [5, 6], 'nfl_week': 7,
        }), patch('data_pipeline.DataOrchestrator') as orchestrator_cls:
            orchestrator = MagicMock()
            orchestrator.sync_projections.return_value = {'processed': 3000}
            orchestrator_cls.return_value.__enter__.return_value = orchestrator

            assert scheduler.job_refresh_projections() == {'processed': 3000}
            orchestrator.sync_projections.assert_called_once_with(2025, 7)

    @pytest.mark.unit
    def test_job_sync_weekly_stats_uses_completed_weeks_only(self):
        """Stats sync should refresh completed weeks, not the upcoming prediction week."""
        with patch('scheduler.resolve_pipeline_context', return_value={
            'season': 2024,
            'prediction_week': 10,
            'completed_week': 9,
            'weeks_to_refresh': [8, 9],
            'nfl_week': 10,
        }), patch('data_pipeline.DataOrchestrator') as orchestrator_cls:
            orchestrator = MagicMock()
            orchestrator.sync_weekly_stats.side_effect = [
                {'processed': 100},
                {'processed': 120},
            ]
            orchestrator_cls.return_value.__enter__.return_value = orchestrator

            result = scheduler.job_sync_weekly_stats()

            assert sorted(result.keys()) == [8, 9]
            assert orchestrator.sync_weekly_stats.call_args_list[0].args == (2024, 8)
            assert orchestrator.sync_weekly_stats.call_args_list[1].args == (2024, 9)

    @pytest.mark.unit
    def test_job_sync_weekly_stats_skips_offseason(self):
        """Offseason should return a skipped result instead of a failure."""
        with patch('scheduler.resolve_pipeline_context', return_value={
            'season': 2026,
            'prediction_week': 1,
            'completed_week': 0,
            'weeks_to_refresh': [],
            'nfl_week': 0,
            'is_offseason': True,
        }):
            result = scheduler.job_sync_weekly_stats()

        assert result['skipped'] is True

    @pytest.mark.unit
    def test_job_sync_prediction_context_skips_offseason(self):
        """Offseason should skip matchup/projection sync cleanly."""
        with patch('scheduler.resolve_pipeline_context', return_value={
            'season': 2026,
            'prediction_week': 1,
            'completed_week': 0,
            'weeks_to_refresh': [],
            'nfl_week': 0,
            'is_offseason': True,
        }):
            result = scheduler.job_sync_prediction_context()

        assert result['skipped'] is True

    @pytest.mark.unit
    def test_job_compute_features_skips_offseason(self):
        """Offseason should skip feature computation cleanly."""
        with patch('scheduler.resolve_pipeline_context', return_value={
            'season': 2026,
            'prediction_week': 1,
            'completed_week': 0,
            'weeks_to_refresh': [],
            'nfl_week': 0,
            'is_offseason': True,
        }):
            result = scheduler.job_compute_features()

        assert result['skipped'] is True


class TestSchedulerTimezone:
    @pytest.mark.unit
    def test_jobs_run_in_eastern_time_on_a_pacific_host(self):
        """Explicit CronTriggers default to the host zone; every job must be Eastern."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        eastern = ZoneInfo('America/New_York')
        with patch('apscheduler.triggers.cron.get_localzone',
                   return_value=ZoneInfo('America/Los_Angeles')):
            jobs = scheduler.FantasyScheduler().scheduler.get_jobs()

        assert len(jobs) == 7
        for job in jobs:
            assert str(job.trigger.timezone) == 'America/New_York', job.id

        gameday = next(j for j in jobs if j.id == 'refresh_projections_gameday')
        # Sunday morning, Oct 11 2026: the refresh must land before 1 PM ET kickoffs
        now = datetime(2026, 10, 11, 9, 0, tzinfo=eastern)
        fire = gameday.trigger.get_next_fire_time(None, now)
        assert fire == datetime(2026, 10, 11, 11, 45, tzinfo=eastern)
