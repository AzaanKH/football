"""
Unit tests for the NFL calendar (data_pipeline.season) and the season
catch-up plan (setup_season).
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from data_pipeline.season import (
    GAME_DURATION, build_context, current_context, estimate_state, season_opener,
)

UTC = timezone.utc


class TestCalendar:
    @pytest.mark.unit
    @pytest.mark.parametrize('year, opener', [
        (2024, date(2024, 9, 5)),   # Labor Day Sep 2
        (2025, date(2025, 9, 4)),   # Labor Day Sep 1
        (2026, date(2026, 9, 10)),  # Labor Day Sep 7
    ])
    def test_season_opens_thursday_after_labor_day(self, year, opener):
        assert season_opener(year) == opener

    @pytest.mark.unit
    @pytest.mark.parametrize('today, expected', [
        (date(2026, 10, 5), {'season': 2026, 'week': 4, 'season_type': 'regular'}),
        (date(2026, 9, 10), {'season': 2026, 'week': 1, 'season_type': 'regular'}),
        # December/January boundary: still the 2026 regular season
        (date(2026, 12, 31), {'season': 2026, 'week': 17, 'season_type': 'regular'}),
        (date(2027, 1, 1), {'season': 2026, 'week': 17, 'season_type': 'regular'}),
        # Final regular-season weekend (Jan 9-10, 2027)
        (date(2027, 1, 10), {'season': 2026, 'week': 18, 'season_type': 'regular'}),
        (date(2027, 1, 20), {'season': 2026, 'week': 18, 'season_type': 'post'}),
        (date(2027, 3, 1), {'season': 2027, 'week': 0, 'season_type': 'off'}),
        (date(2026, 6, 1), {'season': 2026, 'week': 0, 'season_type': 'off'}),
    ])
    def test_estimate_state_from_date(self, today, expected):
        assert estimate_state(today) == expected


class TestBuildContext:
    STATE = {'season': 2026, 'week': 4, 'season_type': 'regular'}
    MNF_KICKOFF = datetime(2026, 10, 6, 0, 15, tzinfo=UTC)  # Monday 8:15 PM ET

    @pytest.mark.unit
    def test_current_week_in_progress_until_last_game_ends(self):
        monday_evening = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)
        context = build_context(self.STATE, monday_evening, 'sleeper', self.MNF_KICKOFF)

        assert context.completed_weeks == [1, 2, 3]
        assert context.prediction_week == 4

    @pytest.mark.unit
    def test_current_week_complete_after_last_game(self):
        tuesday = self.MNF_KICKOFF + GAME_DURATION
        context = build_context(self.STATE, tuesday, 'sleeper', self.MNF_KICKOFF)

        assert context.completed_weeks == [1, 2, 3, 4]
        assert context.prediction_week == 5
        assert context.last_completed_week == 4

    @pytest.mark.unit
    def test_without_schedule_only_earlier_weeks_count(self):
        context = build_context(self.STATE, datetime(2026, 10, 9, tzinfo=UTC), 'sleeper')

        assert context.completed_weeks == [1, 2, 3]
        assert context.prediction_week == 4

    @pytest.mark.unit
    def test_last_regular_week_complete_means_nothing_to_predict(self):
        state = {'season': 2026, 'week': 18, 'season_type': 'regular'}
        end = datetime(2027, 1, 10, 1, 0, tzinfo=UTC)
        context = build_context(state, end + GAME_DURATION, 'sleeper', end)

        assert context.completed_weeks == list(range(1, 19))
        assert context.prediction_week is None and context.is_offseason

    @pytest.mark.unit
    def test_postseason_and_offseason(self):
        post = build_context({'season': 2025, 'week': 18, 'season_type': 'post'},
                             datetime(2026, 1, 20, tzinfo=UTC), 'sleeper')
        off = build_context({'season': 2026, 'week': 0, 'season_type': 'off'},
                            datetime(2026, 6, 1, tzinfo=UTC), 'sleeper')
        pre = build_context({'season': 2026, 'week': 0, 'season_type': 'pre'},
                            datetime(2026, 8, 20, tzinfo=UTC), 'sleeper')

        assert post.completed_weeks == list(range(1, 19)) and post.is_offseason
        assert off.completed_weeks == [] and off.is_offseason
        assert pre.prediction_week == 1

    @pytest.mark.unit
    def test_history_seasons(self):
        context = build_context(self.STATE, datetime(2026, 10, 5, tzinfo=UTC), 'sleeper')
        assert context.history_seasons(3) == [2023, 2024, 2025, 2026]


class TestCurrentContext:
    @pytest.mark.unit
    def test_falls_back_to_calendar_when_sleeper_is_down(self, monkeypatch):
        monkeypatch.setattr('data_pipeline.season.fetch_sleeper_state', lambda: None)

        context = current_context(now=datetime(2026, 10, 5, 12, tzinfo=UTC))

        assert (context.season, context.week, context.source) == (2026, 4, 'calendar')

    @pytest.mark.unit
    def test_calendar_fallback_on_new_years_day_still_has_weeks_to_play(self, monkeypatch):
        monkeypatch.setattr('data_pipeline.season.fetch_sleeper_state', lambda: None)

        context = current_context(now=datetime(2027, 1, 1, tzinfo=UTC))

        assert context.season == 2026
        assert context.completed_weeks == list(range(1, 17))
        assert context.prediction_week == 17

    @staticmethod
    def _schedule(ends):
        """week_end_lookup over {week: last kickoff} for the 2026 season."""
        return lambda season, week: ends.get(week) if season == 2026 else None

    # Last kickoff of each 2026 week: Monday 00:15 UTC, starting Sep 15
    REGULAR_ENDS = {
        week: datetime(2026, 9, 15, 0, 15, tzinfo=UTC) + (week - 1) * timedelta(days=7)
        for week in range(1, 19)
    }

    @pytest.mark.unit
    def test_final_regular_season_weekend_from_schedule(self, monkeypatch):
        monkeypatch.setattr('data_pipeline.season.fetch_sleeper_state', lambda: None)
        ends = dict(self.REGULAR_ENDS)
        ends[18] = datetime(2027, 1, 11, 1, 20, tzinfo=UTC)  # Sunday night game
        lookup = self._schedule(ends)

        during = current_context(week_end_lookup=lookup, now=datetime(2027, 1, 10, 18, tzinfo=UTC))
        after = current_context(week_end_lookup=lookup, now=ends[18] + GAME_DURATION)

        assert during.completed_weeks == list(range(1, 18)) and during.prediction_week == 18
        assert after.completed_weeks == list(range(1, 19)) and after.is_offseason

    @pytest.mark.unit
    def test_schedule_overrides_date_estimate_for_moved_games(self, monkeypatch):
        """A week-17 game moved to Thursday Jan 7: week 17 isn't over, whatever the date says."""
        monkeypatch.setattr('data_pipeline.season.fetch_sleeper_state', lambda: None)
        ends = dict(self.REGULAR_ENDS)
        ends[17] = datetime(2027, 1, 8, 1, 15, tzinfo=UTC)
        now = datetime(2027, 1, 7, 20, tzinfo=UTC)
        assert estimate_state(now.date())['week'] == 18

        context = current_context(week_end_lookup=self._schedule(ends), now=now)

        assert context.completed_weeks == list(range(1, 17))
        assert context.prediction_week == 17

    @pytest.mark.unit
    def test_wednesday_opener_from_schedule(self, monkeypatch):
        """2026 kicks off Wednesday Sep 9, a day before the Thursday-after-Labor-Day estimate."""
        monkeypatch.setattr('data_pipeline.season.fetch_sleeper_state', lambda: None)
        now = datetime(2026, 9, 9, 23, tzinfo=UTC)
        assert estimate_state(now.date())['season_type'] == 'off'

        context = current_context(week_end_lookup=self._schedule(self.REGULAR_ENDS), now=now)

        assert (context.season, context.week, context.season_type) == (2026, 1, 'regular')
        assert context.prediction_week == 1

    @pytest.mark.unit
    def test_schedule_ignored_months_before_the_opener(self, monkeypatch):
        monkeypatch.setattr('data_pipeline.season.fetch_sleeper_state', lambda: None)

        context = current_context(week_end_lookup=self._schedule(self.REGULAR_ENDS),
                                  now=datetime(2026, 6, 1, tzinfo=UTC))

        assert context.season_type == 'off' and context.is_offseason

    @pytest.mark.unit
    def test_incomplete_schedule_falls_back_to_date(self, monkeypatch):
        monkeypatch.setattr('data_pipeline.season.fetch_sleeper_state', lambda: None)
        ends = {w: e for w, e in self.REGULAR_ENDS.items() if w <= 5}

        context = current_context(week_end_lookup=self._schedule(ends),
                                  now=datetime(2027, 1, 1, tzinfo=UTC))

        assert context.prediction_week == 17

    @pytest.mark.unit
    def test_uses_schedule_to_finish_the_current_week(self):
        lookup = MagicMock(return_value=datetime(2026, 10, 6, 0, 15, tzinfo=UTC))

        context = current_context(
            week_end_lookup=lookup,
            now=datetime(2026, 10, 7, tzinfo=UTC),
            state={'season': '2026', 'week': 4, 'season_type': 'regular'},
        )

        lookup.assert_called_once_with(2026, 4)
        assert context.prediction_week == 5


class TestSetupPlan:
    """setup_season only syncs what is missing."""

    @staticmethod
    def _conn(present):
        """present: {(table, season): {weeks}}"""
        def execute(sql, params):
            table = sql.split('FROM')[1].split()[0]
            cursor.fetchall.return_value = [(w,) for w in present.get((table, params[0]), set())]
        cursor = MagicMock()
        cursor.execute.side_effect = execute
        conn = MagicMock()
        conn.cursor.return_value = cursor
        return conn

    @pytest.mark.unit
    def test_plan_fills_only_missing_weeks_and_refreshes_recent(self):
        import setup_season
        context = build_context({'season': 2026, 'week': 5, 'season_type': 'regular'},
                                datetime(2026, 10, 9, tzinfo=UTC), 'sleeper')
        full = set(range(1, 19))
        conn = self._conn({
            ('team_weekly_matchups', 2025): full, ('player_weekly_stats', 2025): full,
            ('player_projections', 2025): full,
            ('team_weekly_matchups', 2026): full, ('player_weekly_stats', 2026): {1, 2, 3, 4},
            ('player_projections', 2026): {1, 2},
        })

        plan = setup_season.build_plan(context, conn, [2025, 2026], None, force=False)

        assert plan[2025] == {'schedule': [], 'stats': [], 'projections': [], 'prediction_week': []}
        assert plan[2026]['stats'] == [3, 4]          # last two finished weeks re-synced
        assert plan[2026]['projections'] == [3, 4, 5]  # missing + prediction week
        assert setup_season.feature_weeks(context, plan, [2025, 2026]) == [
            (2026, 3), (2026, 4), (2026, 5),
        ]

    @pytest.mark.unit
    def test_new_past_season_cascades_features_into_later_seasons(self):
        import setup_season
        context = build_context({'season': 2026, 'week': 2, 'season_type': 'regular'},
                                datetime(2026, 9, 20, tzinfo=UTC), 'sleeper')
        conn = self._conn({('player_weekly_stats', 2026): {1}})

        plan = setup_season.build_plan(context, conn, [2025, 2026], None, force=False)
        pairs = setup_season.feature_weeks(context, plan, [2025, 2026])

        assert plan[2025]['stats'] == list(range(1, 19))
        assert pairs[0] == (2025, 1) and (2026, 1) in pairs and (2026, 2) in pairs


@pytest.mark.unit
def test_week_finished_at_uses_the_last_kickoff_else_the_wednesday_after():
    from data_pipeline.season import week_finished_at

    kickoff = datetime(2026, 10, 12, 0, 15, tzinfo=timezone.utc)
    assert week_finished_at(2026, 5, lambda s, w: kickoff) == datetime(2026, 10, 12, 4, 15, tzinfo=timezone.utc)
    # 2026 opens Thursday Sep 10: week 5 is Oct 8-12, done by Wednesday Oct 14
    assert week_finished_at(2026, 5, lambda s, w: None) == datetime(2026, 10, 14, tzinfo=timezone.utc)
    assert week_finished_at(2026, 5) == datetime(2026, 10, 14, tzinfo=timezone.utc)
