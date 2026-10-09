from flask import Flask, request, jsonify
from flask_cors import CORS
from contextlib import contextmanager
import os
import logging
import threading
import time
from datetime import datetime, timezone

import psycopg2
from psycopg2 import pool as pg_pool

from model_store import ModelStore
from weekly_predictor import WeeklyPredictor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_PATH = os.environ.get('MODEL_PATH', 'models/weekly_predictor.pkl')
# Optional override; otherwise the current NFL season (see default_season)
DEFAULT_SEASON_OVERRIDE = os.environ.get('DEFAULT_SEASON')

# Positions the API accepts (TE is listed; predictions explain it has no model)
POSITIONS = {'qb', 'rb', 'wr', 'te'}
MAX_PLAYERS_PER_REQUEST = 50

DB_HELP = 'Start the database with: docker-compose up -d'

app = Flask(__name__)
CORS(app)

# The model reloads itself whenever the pickle changes (e.g. scheduled retrain)
model_store = ModelStore(MODEL_PATH, loader=WeeklyPredictor.load)


# ============================================================================
# Database connections: one pooled connection per request, always returned
# ============================================================================

DB_POOL_MAX = int(os.environ.get('DB_POOL_MAX', 10))
DB_POOL_WAIT_SECONDS = float(os.environ.get('DB_POOL_WAIT_SECONDS', 10))

_pool = None
_pool_lock = threading.Lock()
# ThreadedConnectionPool raises immediately when every connection is in use;
# this makes requests queue for a free connection instead of failing a burst.
_pool_slots = threading.BoundedSemaphore(DB_POOL_MAX)


class PoolBusy(Exception):
    """No connection freed up within DB_POOL_WAIT_SECONDS."""


def _get_pool():
    """Create the connection pool on first use; retried until the DB is up."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pg_pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=DB_POOL_MAX,
                    host=os.environ.get('DB_HOST', 'localhost'),
                    port=os.environ.get('DB_PORT', 5432),
                    database=os.environ.get('DB_NAME', 'football_dev'),
                    user=os.environ.get('DB_USER', 'postgres'),
                    password=os.environ.get('DB_PASSWORD', 'postgres'),
                    connect_timeout=5,
                )
    return _pool


@contextmanager
def db_connection():
    """
    Borrow a connection for the duration of a request.

    The transaction is rolled back (all API queries are reads) before the
    connection goes back to the pool; broken connections are discarded.
    """
    pool = _get_pool()
    if not _pool_slots.acquire(timeout=DB_POOL_WAIT_SECONDS):
        raise PoolBusy()
    try:
        conn = pool.getconn()
    except BaseException:
        _pool_slots.release()
        raise

    discard = False
    try:
        yield conn
    finally:
        try:
            if conn.closed:
                discard = True
            else:
                conn.rollback()
        except psycopg2.Error:
            discard = True
        pool.putconn(conn, close=discard)
        _pool_slots.release()


# ============================================================================
# Input validation: invalid input is a 400, never a 500
# ============================================================================

class BadRequest(ValueError):
    """Client input error, returned as HTTP 400."""


def _int_param(value, name: str, minimum: int, maximum: int, default=None) -> int:
    if value is None or value == '':
        if default is None:
            raise BadRequest(f'{name} is required')
        return default
    if isinstance(value, bool):
        raise BadRequest(f'{name} must be an integer')
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise BadRequest(f'{name} must be an integer')
    if isinstance(value, float) and value != number:
        raise BadRequest(f'{name} must be an integer')
    if not minimum <= number <= maximum:
        raise BadRequest(f'{name} must be between {minimum} and {maximum}')
    return number


def _season_param(value) -> int:
    if value is None or value == '':
        return default_season()
    return _int_param(value, 'season', 1999, 2100)


def _position_param(value, required: bool) -> str:
    if value is None or value == '':
        if required:
            raise BadRequest('position is required')
        return ''
    if not isinstance(value, str) or value.lower() not in POSITIONS:
        raise BadRequest(f"position must be one of: {', '.join(sorted(POSITIONS))}")
    return value.lower()


def _player_ids_param(value) -> list:
    if not isinstance(value, list) or not value:
        raise BadRequest('player_ids must be a non-empty list')
    if len(value) > MAX_PLAYERS_PER_REQUEST:
        raise BadRequest(f'player_ids accepts at most {MAX_PLAYERS_PER_REQUEST} players')
    ids = []
    for pid in value:
        if isinstance(pid, bool) or not isinstance(pid, (str, int)) or not str(pid).strip():
            raise BadRequest('player_ids must contain player ID strings')
        if len(str(pid)) > 50:
            raise BadRequest('player_ids contains an invalid ID')
        ids.append(str(pid).strip())
    return ids


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequest('Request body must be a JSON object')
    return body


@app.errorhandler(BadRequest)
def handle_bad_request(e):
    return jsonify({'error': str(e)}), 400


@app.errorhandler(psycopg2.OperationalError)
@app.errorhandler(pg_pool.PoolError)
def handle_db_unavailable(e):
    logger.warning(f"Database unavailable: {e}")
    return jsonify({'error': 'Database unavailable', 'help': DB_HELP}), 503


@app.errorhandler(PoolBusy)
def handle_pool_busy(e):
    logger.warning("No database connection free within the wait timeout")
    return jsonify({'error': 'Server busy, please retry'}), 503


@app.errorhandler(Exception)
def handle_unexpected(e):
    # Let Flask render real HTTP errors (404, 405, ...) normally
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    logger.exception("Unhandled error")
    return jsonify({'error': 'Internal server error'}), 500


# ============================================================================
# Context for the UI: current NFL week and data freshness
# ============================================================================

NFL_STATE_TTL_SECONDS = 3600
NFL_STATE_RETRY_SECONDS = 300
_nfl_state = {'value': None, 'expires': 0.0}
_nfl_state_lock = threading.Lock()


def current_nfl_week():
    """
    {season, week, season_type} from Sleeper, cached for an hour.

    Returns None if Sleeper is unreachable (retried after a few minutes),
    so the API keeps working offline.
    """
    with _nfl_state_lock:
        if time.time() < _nfl_state['expires']:
            return _nfl_state['value']
        try:
            from data_pipeline.sleeper_client import SleeperClient
            with SleeperClient() as client:
                state = client.get_nfl_state() or {}
            value = {
                'season': int(state['season']),
                'week': int(state['week']),
                'season_type': state.get('season_type'),
            }
            ttl = NFL_STATE_TTL_SECONDS
        except Exception as e:
            logger.warning(f"Could not fetch current NFL week: {e}")
            value, ttl = None, NFL_STATE_RETRY_SECONDS
        _nfl_state.update(value=value, expires=time.time() + ttl)
        return value


def default_season() -> int:
    """DEFAULT_SEASON if set, else the current NFL season (Sleeper, then the calendar)."""
    if DEFAULT_SEASON_OVERRIDE:
        return int(DEFAULT_SEASON_OVERRIDE)
    current = current_nfl_week()
    if current:
        return current['season']
    from data_pipeline.season import estimate_state
    return estimate_state(datetime.now(timezone.utc).date())['season']


def _utc_iso(value):
    """Naive UTC timestamps (DB) or POSIX times -> ISO 8601 with Z, or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=timezone.utc)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def data_freshness(conn, season: int, week: int) -> dict:
    """When each input was last refreshed, for the UI's freshness line."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            MAX(completed_at) FILTER (WHERE data_type = 'projections'
                                      AND season = %s AND week = %s),
            MAX(completed_at) FILTER (WHERE data_type = 'stats'),
            MAX(completed_at) FILTER (WHERE data_type = 'players')
        FROM ingestion_log
        WHERE status = 'completed'
    """, (season, week))
    projections_at, stats_at, players_at = cursor.fetchone()

    cursor.execute("""
        SELECT season, week FROM player_weekly_stats
        ORDER BY season DESC, week DESC LIMIT 1
    """)
    latest = cursor.fetchone()

    try:
        model_at = os.path.getmtime(MODEL_PATH)
    except OSError:
        model_at = None

    return {
        'projections_synced_at': _utc_iso(projections_at),
        'stats_synced_at': _utc_iso(stats_at),
        'players_synced_at': _utc_iso(players_at),
        'stats_through': {'season': latest[0], 'week': latest[1]} if latest else None,
        'model_trained_at': _utc_iso(model_at),
    }


def _require_model():
    predictor = model_store.get()
    if predictor is None:
        return None, (jsonify({
            'error': 'Weekly predictor not available',
            'help': 'Train with: python weekly_predictor.py train',
            'last_load_error': model_store.last_error,
        }), 503)
    return predictor, None


# ============================================================================
# Endpoints
# ============================================================================

@app.route('/model_status', methods=['GET'])
def model_status():
    """
    Get status of the database and the weekly prediction model.

    Checked on every call, so it reflects the current state (not startup).
    """
    try:
        with db_connection() as conn:
            conn.cursor().execute('SELECT 1')
        postgres_available = True
    except (psycopg2.Error, pg_pool.PoolError):
        postgres_available = False

    predictor = model_store.get()
    status = {
        'weekly_predictor_available': predictor is not None and postgres_available,
        'postgres_available': postgres_available,
        'model': model_store.status(),
        'default_season': default_season(),
    }

    if predictor is not None:
        status['weekly_predictor'] = {
            'trained': predictor._is_trained,
            'positions': list(predictor.models.keys()),
            'metrics': predictor.training_metrics
        }

    return jsonify(status)


@app.route('/players', methods=['GET'])
def get_players_postgres():
    """
    Get players from PostgreSQL database.

    Query params:
        position: Filter by position (qb, rb, wr, te)
        limit: Max results (1-500, default 100)
        search: Search by name

    Returns:
        List of players with id, name, team, position
    """
    position = _position_param(request.args.get('position'), required=False).upper()
    limit = _int_param(request.args.get('limit'), 'limit', 1, 500, default=100)
    search = request.args.get('search', '').strip()
    if len(search) > 100:
        raise BadRequest('search must be at most 100 characters')

    # With season+week: only players who have features for that week (i.e. can
    # be predicted), most productive first. Otherwise: everyone, alphabetical.
    week_arg = request.args.get('week')
    week = _int_param(week_arg, 'week', 1, 22) if week_arg else None
    season = _season_param(request.args.get('season')) if week else None

    if week:
        query = """
            SELECT p.player_id, p.full_name, p.team, p.position
            FROM players p
            JOIN player_features pf
                ON pf.player_id = p.player_id AND pf.season = %s AND pf.week = %s
            WHERE p.position IN ('QB', 'RB', 'WR', 'TE')
        """
        params = [season, week]
        order = " ORDER BY pf.fantasy_pts_avg_3 DESC NULLS LAST, p.full_name"
    else:
        query = """
            SELECT p.player_id, p.full_name, p.team, p.position
            FROM players p
            WHERE p.position IN ('QB', 'RB', 'WR', 'TE')
        """
        params = []
        order = " ORDER BY p.full_name"

    if position:
        query += " AND p.position = %s"
        params.append(position)

    if search:
        query += " AND (p.full_name ILIKE %s OR p.team ILIKE %s)"
        params.extend([f'%{search}%', search])

    query += order + " LIMIT %s"
    params.append(limit)

    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        columns = ['player_id', 'full_name', 'team', 'position']
        players = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return jsonify(players)


@app.route('/predict_week', methods=['POST'])
def predict_week():
    """
    Predict fantasy points for an upcoming week using engineered features.

    Request body:
        position: 'qb', 'rb', 'wr' or 'te'
        player_ids: List of player IDs to predict (max 50)
        week: Week number to predict FOR (1-22)
        season: NFL season (default: current NFL season)

    Returns:
        {week, season, position,
         predictions: [{player_id, player_name, predicted_points,
                        confidence_low, confidence_high, features}],
         unavailable: [{player_id, player_name, reason, message}]}
    """
    body = _json_body()
    position = _position_param(body.get('position'), required=True)
    player_ids = _player_ids_param(body.get('player_ids'))
    week = _int_param(body.get('week'), 'week', 1, 22)
    season = _season_param(body.get('season'))

    predictor, error = _require_model()
    if error:
        return error

    with db_connection() as conn:
        # Request-scoped view: shares the models, never the connection
        predictions = predictor.with_connection(conn).predict_week(
            player_ids=player_ids,
            season=season,
            week=week,
            position=position
        )
        freshness = data_freshness(conn, season, week)

    # Every requested player appears in exactly one list
    results = []
    unavailable = []
    for pred in predictions:
        if pred.status == 'ok':
            results.append({
                'player_id': pred.player_id,
                'player_name': pred.player_name,
                'predicted_points': pred.predicted_points,
                'confidence_low': pred.confidence_low,
                'confidence_high': pred.confidence_high,
                'features': pred.features_used,
                'context': pred.context,
            })
        else:
            unavailable.append({
                'player_id': pred.player_id,
                'player_name': pred.player_name,
                'reason': pred.reason,
                'message': pred.message,
                'context': pred.context,
            })

    return jsonify({
        'week': week,
        'season': season,
        'position': position,
        'scoring': 'ppr',
        'predictions': results,
        'unavailable': unavailable,
        'freshness': freshness,
        # Injury statuses are current; only meaningful when this is the current week
        'current_week': current_nfl_week(),
    })


@app.route('/seasons', methods=['GET'])
def seasons():
    """
    Seasons that have computed features, newest first.

    Returns:
        {seasons: [2025, 2024, ...], default: <newest season with data>}
        default falls back to the current NFL season when no features exist yet.
    """
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT season FROM player_features ORDER BY season DESC")
        available = [row[0] for row in cursor.fetchall()]

    return jsonify({
        'seasons': available,
        'default': available[0] if available else default_season(),
        'current_week': current_nfl_week(),
    })


@app.route('/available_weeks', methods=['GET'])
def available_weeks():
    """
    Get weeks that have computed features available for predictions.

    Query params:
        season: NFL season (default: current NFL season)

    Returns:
        List of weeks with feature data
    """
    season = _season_param(request.args.get('season'))

    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT week, COUNT(*) as player_count
            FROM player_features
            WHERE season = %s
            GROUP BY week
            ORDER BY week
        """, (season,))
        weeks = [{'week': row[0], 'players': row[1]} for row in cursor.fetchall()]

    return jsonify({'season': season, 'weeks': weeks})


@app.route('/player_features/<player_id>', methods=['GET'])
def get_player_features(player_id):
    """
    Get computed features for a specific player.

    Query params:
        season: NFL season (default: current NFL season)
        week: Specific week (optional, returns latest if not specified)

    Returns:
        Player features used for prediction
    """
    season = _season_param(request.args.get('season'))
    week_arg = request.args.get('week')
    week = _int_param(week_arg, 'week', 1, 22) if week_arg else None

    with db_connection() as conn:
        cursor = conn.cursor()
        if week:
            cursor.execute("""
                SELECT pf.*, p.full_name, p.team, p.position
                FROM player_features pf
                JOIN players p ON pf.player_id = p.player_id
                WHERE pf.player_id = %s AND pf.season = %s AND pf.week = %s
            """, (player_id, season, week))
        else:
            cursor.execute("""
                SELECT pf.*, p.full_name, p.team, p.position
                FROM player_features pf
                JOIN players p ON pf.player_id = p.player_id
                WHERE pf.player_id = %s AND pf.season = %s
                ORDER BY pf.week DESC
                LIMIT 1
            """, (player_id, season))

        columns = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()

    if not row:
        return jsonify({'error': 'No features found for player'}), 404

    return jsonify(dict(zip(columns, row)))


if __name__ == '__main__':
    # Localhost-only with debugger off by default: the Werkzeug debugger allows
    # arbitrary code execution, so never expose it on the network.
    # Opt in with FLASK_DEBUG=1 and/or FLASK_HOST=0.0.0.0.
    app.run(
        host=os.environ.get('FLASK_HOST', '127.0.0.1'),
        port=int(os.environ.get('FLASK_PORT', 5001)),
        debug=os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes'),
    )
