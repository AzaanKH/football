"""
Static Prediction Export

Writes every prediction the app can show as JSON files the frontend loads
directly, so the site can be hosted statically while Python and PostgreSQL
stay on this machine:

    <out>/index.json                          seasons, weeks, freshness
    <out>/<season>/week-<NN>/<position>.json  search list + every player's result

Each week file holds the players /players would offer for that week (ranked
by recent scoring) and, for each of them, exactly what /predict_week returns:
a prediction or an unavailable reason, with game context and freshness.

Usage:
    python export_static.py                    # every season with features
    python export_static.py --seasons 2025 2026
    python export_static.py --verify           # compare the export with /predict_week
"""

import argparse
import json
import logging
import os
import random
import shutil
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

from weekly_predictor import WeeklyPredictor, get_db_connection

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# The frontend's position tabs (TE has no model)
EXPORT_POSITIONS = ('qb', 'rb', 'wr')
FORMAT_VERSION = 1

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', 'frontend', 'fantasy-football', 'public', 'data',
)


def week_path(season: int, week: int, position: str) -> str:
    """File path relative to the data folder (the frontend builds the same one)."""
    return f'{season}/week-{week:02d}/{position}.json'


def seasons_with_features(conn) -> Dict[int, List[int]]:
    """Season -> weeks with computed features, as /seasons and /available_weeks see them."""
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT season, week FROM player_features ORDER BY season, week")
    weeks: Dict[int, List[int]] = {}
    for season, week in cursor.fetchall():
        weeks.setdefault(season, []).append(week)
    return weeks


def candidate_players(conn, season: int, week: int, position: str) -> List[Dict]:
    """
    Players the search offers for the week: same rows and order as
    GET /players?season=&week=&position= (without its result limit).
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.player_id, p.full_name, p.team
        FROM players p
        JOIN player_features pf
            ON pf.player_id = p.player_id AND pf.season = %s AND pf.week = %s
        WHERE p.position = %s
        ORDER BY pf.fantasy_pts_avg_3 DESC NULLS LAST, p.full_name
    """, (season, week, position.upper()))
    return [{'player_id': row[0], 'name': row[1], 'team': row[2]} for row in cursor.fetchall()]


def prediction_json(pred) -> Dict:
    """One WeeklyPrediction in the /predict_week response shape."""
    if pred.status == 'ok':
        return {
            'player_id': pred.player_id,
            'player_name': pred.player_name,
            'predicted_points': pred.predicted_points,
            'confidence_low': pred.confidence_low,
            'confidence_high': pred.confidence_high,
            'features': pred.features_used,
            'context': pred.context,
        }
    return {
        'player_id': pred.player_id,
        'player_name': pred.player_name,
        'reason': pred.reason,
        'message': pred.message,
        'context': pred.context,
    }


def build_week_file(season: int, week: int, position: str, players: List[Dict],
                    results: List, freshness: Dict, current_week: Optional[Dict]) -> Dict:
    """Week file: the search list plus every player's result, split like the API."""
    return {
        'version': FORMAT_VERSION,
        'season': season,
        'week': week,
        'position': position,
        'scoring': 'ppr',
        'players': players,
        'predictions': [prediction_json(p) for p in results if p.status == 'ok'],
        'unavailable': [prediction_json(p) for p in results if p.status != 'ok'],
        'freshness': freshness,
        'current_week': current_week,
    }


def season_calendar(conn, season: int) -> Dict:
    """
    When each regular-season week of `season` counts as finished (UTC), so
    the frontend can tell which week is current long after the export,
    with the same rule as data_pipeline.season.
    """
    from data_pipeline.season import REGULAR_SEASON_WEEKS, schedule_week_end, week_finished_at

    lookup = schedule_week_end(conn)
    return {
        'season': season,
        'weeks': [
            {'week': week, 'finished_at': _iso(week_finished_at(season, week, lookup))}
            for week in range(1, REGULAR_SEASON_WEEKS + 1)
        ],
    }


def with_expiry(current_week: Optional[Dict], calendar: Dict) -> Optional[Dict]:
    """
    The current NFL week at export time, with when it stops being current
    (its last game finished). Only regular-season weeks roll over.
    """
    if not current_week:
        return None
    finished = {w['week']: w['finished_at'] for w in calendar['weeks']}
    expires_at = None
    if current_week.get('season_type') == 'regular' and current_week['season'] == calendar['season']:
        expires_at = finished.get(current_week['week'])
    return {**current_week, 'expires_at': expires_at}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def swap_in(new_dir: str, out_dir: str) -> None:
    """
    Replace out_dir with new_dir. Two renames can't be atomic together, so
    the previous export is kept as out_dir.old until the new one is in
    place, restored if the swap fails, and recovered on the next run if the
    process died in between.
    """
    old_dir = f'{out_dir}.old'
    if os.path.exists(old_dir):
        if os.path.exists(out_dir):
            shutil.rmtree(old_dir)            # leftover from a finished swap
        else:
            os.replace(old_dir, out_dir)      # a swap died after moving the old export aside

    had_previous = os.path.exists(out_dir)
    if had_previous:
        os.replace(out_dir, old_dir)
    try:
        os.replace(new_dir, out_dir)
    except BaseException:
        if had_previous:
            os.replace(old_dir, out_dir)
        raise
    shutil.rmtree(old_dir, ignore_errors=True)


def write_json(path: str, data: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        # NaN/Infinity aren't JSON: fail loudly instead of writing a file browsers reject
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def export(out_dir: str, seasons: Optional[List[int]] = None) -> Dict:
    """
    Export every (season, week, position) and return the index.

    Writes into a temporary folder and swaps it in at the end, so a failed
    export leaves the previous one intact, and weeks no longer exported
    don't linger.
    """
    # Same helpers as the API, so freshness and the current week match it
    from app import MODEL_PATH, current_nfl_week, data_freshness, default_season, _utc_iso

    predictor = WeeklyPredictor.load(MODEL_PATH)
    current_week = current_nfl_week()
    exported_at = _utc_iso(datetime.now(timezone.utc))

    out_dir = os.path.abspath(out_dir)
    tmp_dir = f'{out_dir}.tmp'
    shutil.rmtree(tmp_dir, ignore_errors=True)

    conn = get_db_connection()
    try:
        available = seasons_with_features(conn)
        selected = sorted(seasons or available, reverse=True)
        missing = [s for s in selected if s not in available]
        if missing:
            raise SystemExit(f'No features for season(s) {missing}; available: {sorted(available)}')

        calendar = season_calendar(conn, (current_week or {}).get('season') or default_season())
        current_week = with_expiry(current_week, calendar)

        view = predictor.with_connection(conn)
        index_seasons = []
        latest_freshness = None
        for season in selected:
            weeks = []
            for week in available[season]:
                freshness = data_freshness(conn, season, week)
                latest_freshness = latest_freshness or freshness
                predicted = 0
                for position in EXPORT_POSITIONS:
                    players = candidate_players(conn, season, week, position)
                    if not players:
                        continue
                    results = view.predict_week(
                        [p['player_id'] for p in players], season, week, position)
                    data = build_week_file(season, week, position, players, results,
                                           freshness, current_week)
                    predicted += len(data['predictions'])
                    write_json(os.path.join(tmp_dir, week_path(season, week, position)), data)
                weeks.append({'week': week, 'players': predicted})
                logger.info(f'{season} week {week}: {predicted} predictions')
            index_seasons.append({'season': season, 'weeks': weeks})
    finally:
        conn.close()

    newest = selected[0] if selected else None
    index = {
        'version': FORMAT_VERSION,
        'exported_at': exported_at,
        'scoring': 'ppr',
        'positions': list(EXPORT_POSITIONS),
        'seasons': index_seasons,
        'default_season': newest if newest is not None else default_season(),
        # The NFL week current at export time, and when it stops being current;
        # the calendar lets the frontend place the current week at any later date
        'current_week': current_week,
        'calendar': calendar,
        'model_trained_at': (latest_freshness or {}).get('model_trained_at'),
        'stats_through': (latest_freshness or {}).get('stats_through'),
    }
    write_json(os.path.join(tmp_dir, 'index.json'), index)

    swap_in(tmp_dir, out_dir)
    return index


# ============================================================================
# Verification: the export must match what the live API returns
# ============================================================================

# Freshness/current week are fetched at different moments; compared separately
COMPARED_KEYS = ('player_id', 'player_name', 'predicted_points', 'confidence_low',
                 'confidence_high', 'features', 'context', 'reason', 'message')


def _by_id(entries: List[Dict]) -> Dict[str, Dict]:
    return {e['player_id']: {k: e.get(k) for k in COMPARED_KEYS} for e in entries}


def compare_with_api(exported: Dict, api: Dict, player_ids: List[str]) -> List[str]:
    """Differences between the export's answer for player_ids and the API's."""
    wanted = set(player_ids)
    problems = []
    for kind in ('predictions', 'unavailable'):
        ours = _by_id([e for e in exported[kind] if e['player_id'] in wanted])
        theirs = _by_id(api[kind])
        for pid in sorted(set(ours) | set(theirs)):
            if ours.get(pid) != theirs.get(pid):
                problems.append(f'{kind} {pid}: export={ours.get(pid)} api={theirs.get(pid)}')
    # The API ranks predictions by points; ties may come back in either order
    points = [p['predicted_points'] for p in api['predictions']]
    if points != sorted(points, reverse=True):
        problems.append(f'API predictions not ranked: {points}')
    return problems


def verify(out_dir: str, samples: int, seed: int = 0) -> int:
    """
    Ask the real /predict_week (Flask test client: no server needed) for
    random groups of 2-4 exported players and compare. Returns the number of
    mismatching requests.
    """
    import app as api_module

    with open(os.path.join(out_dir, 'index.json'), encoding='utf-8') as f:
        index = json.load(f)
    files = [
        (s['season'], w['week'], position)
        for s in index['seasons'] for w in s['weeks'] for position in index['positions']
        if os.path.exists(os.path.join(out_dir, week_path(s['season'], w['week'], position)))
    ]
    rng = random.Random(seed)
    client = api_module.app.test_client()
    failures = checked_players = 0
    for _ in range(samples):
        season, week, position = rng.choice(files)
        with open(os.path.join(out_dir, week_path(season, week, position)), encoding='utf-8') as f:
            exported = json.load(f)
        ids = [p['player_id'] for p in rng.sample(exported['players'],
                                                  min(len(exported['players']), rng.randint(2, 4)))]
        response = client.post('/predict_week', json={
            'position': position, 'player_ids': ids, 'week': week, 'season': season})
        if response.status_code != 200:
            failures += 1
            logger.error(f'{season} week {week} {position}: API returned {response.status_code}')
            continue
        api = response.get_json()
        problems = compare_with_api(exported, api, ids)
        if api['freshness'].get('projections_synced_at') != exported['freshness'].get('projections_synced_at'):
            problems.append('projections_synced_at differs (data synced since the export?)')
        checked_players += len(ids)
        if problems:
            failures += 1
            logger.error(f'{season} week {week} {position} {ids}:\n  ' + '\n  '.join(problems))

    logger.info(f'Verified {samples} requests ({checked_players} players) across '
                f'{len(files)} files: {samples - failures} match, {failures} differ')
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description='Export predictions as static JSON for the frontend')
    parser.add_argument('--seasons', type=int, nargs='+', help='Seasons to export (default: all with features)')
    parser.add_argument('--out', default=DEFAULT_OUT, help='Output folder (default: frontend public/data)')
    parser.add_argument('--verify', action='store_true',
                        help='Compare the existing export with /predict_week instead of exporting')
    parser.add_argument('--samples', type=int, default=200, help='Requests to compare with --verify')
    args = parser.parse_args()

    if args.verify:
        return 1 if verify(args.out, args.samples) else 0

    index = export(args.out, args.seasons)
    weeks = sum(len(s['weeks']) for s in index['seasons'])
    logger.info(f"Exported {weeks} weeks across {len(index['seasons'])} seasons to {os.path.abspath(args.out)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
