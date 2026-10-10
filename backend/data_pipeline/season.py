"""
NFL Calendar

Single source of truth for "where are we in the NFL season", so data
collection, scheduling and the API follow the real calendar instead of a
hard-coded season.

Sleeper's /state/nfl is authoritative. If it can't be reached, the current
week is the first one whose games haven't all finished on the synced
schedule; without a synced schedule, it is estimated from the date (the
regular season opens the Thursday after Labor Day; weeks run Thursday
through Monday, and the last ones fall in January).

A regular-season week counts as completed only after its last game has
finished: with the week's schedule synced, that is the last kickoff plus
GAME_DURATION; without it, weeks before Sleeper's current week.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

REGULAR_SEASON_WEEKS = 18
# Kickoff to final whistle, with margin for overtime and stat corrections
GAME_DURATION = timedelta(hours=4)


@dataclass(frozen=True)
class SeasonContext:
    """
    Attributes:
        season: Season whose games are current or most recent (e.g. 2026)
        week: Sleeper's current week (0 before the season starts)
        season_type: 'pre', 'regular', 'post' or 'off'
        completed_weeks: Regular-season weeks of `season` with final stats
        prediction_week: Week to predict, or None when no games are upcoming
        source: 'sleeper' or 'calendar'
    """
    season: int
    week: int
    season_type: str
    completed_weeks: List[int] = field(default_factory=list)
    prediction_week: Optional[int] = None
    source: str = 'sleeper'

    @property
    def is_offseason(self) -> bool:
        return self.prediction_week is None

    @property
    def last_completed_week(self) -> int:
        return self.completed_weeks[-1] if self.completed_weeks else 0

    def history_seasons(self, years: int) -> List[int]:
        """The current season plus `years` previous seasons, oldest first."""
        return list(range(self.season - years, self.season + 1))


def season_opener(year: int) -> date:
    """Thursday after Labor Day (first Monday of September)."""
    first = date(year, 9, 1)
    labor_day = first + timedelta(days=(0 - first.weekday()) % 7)
    return labor_day + timedelta(days=3)


def estimate_state(today: date) -> Dict:
    """Sleeper-shaped NFL state estimated from the calendar alone."""
    # January/February belong to the season that opened the previous September
    # (its last regular-season weeks, then the playoffs)
    season = today.year if today.month >= 3 else today.year - 1
    opener = season_opener(season)
    if today < opener:
        # March to the opener: the upcoming season hasn't started
        return {'season': season, 'week': 0, 'season_type': 'off'}
    week = (today - opener).days // 7 + 1
    if week <= REGULAR_SEASON_WEEKS:
        return {'season': season, 'week': week, 'season_type': 'regular'}
    return {'season': season, 'week': REGULAR_SEASON_WEEKS, 'season_type': 'post'}


def week_finished_at(season: int, week: int,
                     week_end_lookup: Optional[Callable[[int, int], Optional[datetime]]] = None
                     ) -> datetime:
    """
    When every game of (season, week) is over: its last kickoff (synced
    schedule) plus GAME_DURATION; without a synced schedule, the date
    estimate (the start of the Wednesday after the week's Thursday, UTC).
    """
    end = week_end_lookup(season, week) if week_end_lookup else None
    if end is not None:
        return end + GAME_DURATION
    week_wednesday = season_opener(season) + timedelta(days=7 * (week - 1) + 6)
    return datetime(week_wednesday.year, week_wednesday.month, week_wednesday.day, tzinfo=timezone.utc)


def schedule_state(season: int, now: datetime,
                   week_end_lookup: Callable[[int, int], Optional[datetime]]) -> Optional[Dict]:
    """
    NFL state from the synced schedule: the current week is the first one whose
    last game hasn't finished. Follows the real dates (a Wednesday opener,
    games moved for weather or international slots) where the date estimate
    can't. None when any week of the season is missing from the schedule.
    """
    for week in range(1, REGULAR_SEASON_WEEKS + 1):
        end = week_end_lookup(season, week)
        if end is None:
            return None
        if now < end + GAME_DURATION:
            return {'season': season, 'week': week, 'season_type': 'regular'}
    return {'season': season, 'week': REGULAR_SEASON_WEEKS, 'season_type': 'post'}


def fetch_sleeper_state() -> Optional[Dict]:
    """Sleeper's NFL state, or None if unreachable."""
    try:
        from .sleeper_client import SleeperClient
        with SleeperClient() as client:
            return client.get_nfl_state()
    except Exception as e:
        logger.warning(f"Could not fetch NFL state from Sleeper: {e}")
        return None


def build_context(state: Dict, now: datetime, source: str,
                  week_end: Optional[datetime] = None) -> SeasonContext:
    """
    Turn an NFL state into completed weeks and the week to predict.

    Args:
        state: {'season', 'week', 'season_type'} (Sleeper or estimated)
        now: Current time (timezone-aware)
        source: Where the state came from
        week_end: Last kickoff of the current week, if its schedule is synced
    """
    season = int(state['season'])
    week = int(state.get('week') or 0)
    season_type = state.get('season_type') or 'regular'

    if season_type == 'regular' and week >= 1:
        completed = list(range(1, min(week, REGULAR_SEASON_WEEKS + 1)))
        current_done = week_end is not None and now >= week_end + GAME_DURATION
        if current_done and week <= REGULAR_SEASON_WEEKS:
            completed.append(week)
        next_week = week + 1 if current_done else week
        prediction_week = next_week if next_week <= REGULAR_SEASON_WEEKS else None
    elif season_type == 'post':
        completed, prediction_week = list(range(1, REGULAR_SEASON_WEEKS + 1)), None
    else:
        # Offseason / preseason: nothing played yet; week 1 projections may exist
        completed = []
        prediction_week = 1 if season_type == 'pre' else None

    return SeasonContext(
        season=season, week=week, season_type=season_type,
        completed_weeks=completed, prediction_week=prediction_week, source=source,
    )


def current_context(
    week_end_lookup: Optional[Callable[[int, int], Optional[datetime]]] = None,
    now: Optional[datetime] = None,
    state: Optional[Dict] = None,
) -> SeasonContext:
    """
    Where we are in the NFL season right now.

    Args:
        week_end_lookup: (season, week) -> last kickoff (UTC), from the synced
            schedule; makes the current week count as complete once played,
            and places the current week when Sleeper is unreachable
        now: Override the clock (tests)
        state: Override the NFL state (tests); otherwise Sleeper, then calendar
    """
    now = now or datetime.now(timezone.utc)
    source = 'sleeper'
    if state is None:
        state = fetch_sleeper_state()
    if not state or 'season' not in state:
        state, source = estimate_state(now.date()), 'calendar'
        # Months before the opener, the synced schedule would already say
        # "week 1"; trust it only from the week before the estimated opener
        near_season = now.date() >= season_opener(int(state['season'])) - timedelta(days=7)
        if week_end_lookup and near_season:
            try:
                state = schedule_state(int(state['season']), now, week_end_lookup) or state
            except Exception as e:
                logger.warning(f"Could not read the schedule to place the current week: {e}")

    week_end = None
    if week_end_lookup and state.get('season_type') == 'regular' and int(state.get('week') or 0) >= 1:
        try:
            week_end = week_end_lookup(int(state['season']), int(state['week']))
        except Exception as e:
            logger.warning(f"Could not read the schedule for the current week: {e}")

    return build_context(state, now, source, week_end)


def schedule_week_end(conn) -> Callable[[int, int], Optional[datetime]]:
    """week_end_lookup backed by team_weekly_matchups."""
    def lookup(season: int, week: int) -> Optional[datetime]:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MAX(game_date) FROM team_weekly_matchups
            WHERE season = %s AND week = %s
        """, (season, week))
        row = cursor.fetchone()
        if not row or row[0] is None:
            return None
        value = row[0]
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return lookup
