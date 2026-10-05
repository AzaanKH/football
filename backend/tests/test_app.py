"""
Unit tests for the Flask API: validation, DB availability, connection
lifecycle, and model reloading. No database or model file required.
"""

import os
import time
from unittest.mock import MagicMock

import psycopg2
import pytest

import app as api
from model_store import ModelStore
from weekly_predictor import WeeklyPrediction, WeeklyPredictor


class FakePool:
    """Records connection checkouts/returns like ThreadedConnectionPool."""

    def __init__(self):
        self.conn = MagicMock(closed=0)
        self.returned = []

    def getconn(self):
        return self.conn

    def putconn(self, conn, close=False):
        self.returned.append((conn, close))


CURRENT_WEEK = {'season': 2026, 'week': 5, 'season_type': 'regular'}
# Real implementations, captured before the autouse fixture stubs them
REAL_DATA_FRESHNESS = api.data_freshness
REAL_CURRENT_NFL_WEEK = api.current_nfl_week


@pytest.fixture(autouse=True)
def offline_context(monkeypatch):
    """No network in unit tests: stub Sleeper's NFL state and freshness lookup."""
    monkeypatch.setattr(api, 'current_nfl_week', lambda: CURRENT_WEEK)
    monkeypatch.setattr(api, 'data_freshness', lambda conn, season, week: {'stub': True})


@pytest.fixture
def pool(monkeypatch):
    fake = FakePool()
    monkeypatch.setattr(api, '_get_pool', lambda: fake)
    return fake


@pytest.fixture
def predictor(monkeypatch):
    """Shared predictor whose request-scoped views return one prediction."""
    shared = MagicMock(spec=WeeklyPredictor)
    shared.db_connection = None
    shared._is_trained = True
    shared.models = {'rb': object()}
    shared.training_metrics = {}
    view = MagicMock()
    view.predict_week.return_value = [
        WeeklyPrediction(player_id='4034', player_name='A Player', predicted_points=15.0,
                         confidence_low=8.0, confidence_high=22.0, features_used={}),
        WeeklyPrediction(player_id='x', player_name=None, status='unavailable',
                         reason='unknown_player', message='Player not found in the database.'),
    ]
    shared.with_connection.return_value = view
    store = MagicMock()
    store.get.return_value = shared
    store.status.return_value = {'path': 'models/weekly_predictor.pkl'}
    monkeypatch.setattr(api, 'model_store', store)
    return shared, view


@pytest.fixture
def client():
    api.app.config['TESTING'] = False  # exercise the real error handlers
    return api.app.test_client()


VALID_BODY = {'position': 'rb', 'player_ids': ['4034'], 'week': 6, 'season': 2025}


class TestValidation:
    @pytest.mark.unit
    @pytest.mark.parametrize('body, message', [
        (None, 'JSON object'),
        ({**VALID_BODY, 'position': 'k'}, 'position must be one of'),
        ({**VALID_BODY, 'position': None}, 'position is required'),
        ({**VALID_BODY, 'player_ids': '4034'}, 'non-empty list'),
        ({**VALID_BODY, 'player_ids': []}, 'non-empty list'),
        ({**VALID_BODY, 'player_ids': [str(i) for i in range(51)]}, 'at most 50'),
        ({**VALID_BODY, 'player_ids': [{'id': 1}]}, 'player ID strings'),
        ({**VALID_BODY, 'week': 'abc'}, 'week must be an integer'),
        ({**VALID_BODY, 'week': 30}, 'week must be between'),
        ({**VALID_BODY, 'week': 6.5}, 'week must be an integer'),
        ({**VALID_BODY, 'week': None}, 'week is required'),
        ({**VALID_BODY, 'season': 'next'}, 'season must be an integer'),
    ])
    def test_predict_week_rejects_invalid_input_with_400(self, client, pool, predictor, body, message):
        if body is None:
            response = client.post('/predict_week', data='not json', content_type='text/plain')
        else:
            response = client.post('/predict_week', json=body)

        assert response.status_code == 400
        assert message in response.get_json()['error']
        assert pool.returned == []  # rejected before touching the database

    @pytest.mark.unit
    @pytest.mark.parametrize('url', [
        '/players?limit=abc', '/players?limit=0', '/players?limit=501', '/players?position=k',
        '/available_weeks?season=abc', '/player_features/4034?week=99',
    ])
    def test_get_endpoints_reject_invalid_params_with_400(self, client, pool, url):
        response = client.get(url)

        assert response.status_code == 400
        assert 'error' in response.get_json()


class TestPlayerSearchAndSeasons:
    @pytest.mark.unit
    def test_players_for_a_week_are_predictable_and_ranked(self, client, pool):
        cursor = pool.conn.cursor.return_value
        cursor.fetchall.return_value = [('4034', 'A Player', 'PHI', 'RB')]

        response = client.get('/players?position=rb&season=2025&week=6&search=phi&limit=25')

        assert response.status_code == 200
        sql, params = cursor.execute.call_args.args
        assert 'JOIN player_features' in sql
        assert 'ORDER BY pf.fantasy_pts_avg_3 DESC' in sql
        assert params == [2025, 6, 'RB', '%phi%', 'phi', 25]
        assert response.get_json()[0]['player_id'] == '4034'

    @pytest.mark.unit
    def test_players_without_week_lists_everyone(self, client, pool):
        cursor = pool.conn.cursor.return_value
        cursor.fetchall.return_value = []

        client.get('/players?position=qb')

        sql, params = cursor.execute.call_args.args
        assert 'player_features' not in sql
        assert params == ['QB', 100]

    @pytest.mark.unit
    def test_seasons_default_is_newest_season_with_data(self, client, pool):
        pool.conn.cursor.return_value.fetchall.return_value = [(2025,), (2024,)]

        assert client.get('/seasons').get_json() == {
            'seasons': [2025, 2024], 'default': 2025, 'current_week': CURRENT_WEEK,
        }

    @pytest.mark.unit
    def test_seasons_falls_back_when_no_data(self, client, pool):
        pool.conn.cursor.return_value.fetchall.return_value = []

        assert client.get('/seasons').get_json()['default'] == api.DEFAULT_SEASON


class TestDatabaseAvailability:
    @pytest.mark.unit
    def test_database_down_returns_503_not_500(self, client, monkeypatch):
        def down():
            raise psycopg2.OperationalError('connection refused')
        monkeypatch.setattr(api, '_get_pool', down)

        response = client.get('/players?position=rb')

        assert response.status_code == 503
        assert response.get_json()['error'] == 'Database unavailable'

    @pytest.mark.unit
    def test_model_status_checks_database_on_each_call(self, client, monkeypatch, predictor):
        def down():
            raise psycopg2.OperationalError('connection refused')
        monkeypatch.setattr(api, '_get_pool', down)
        assert client.get('/model_status').get_json()['postgres_available'] is False

        monkeypatch.setattr(api, '_get_pool', lambda: FakePool())
        status = client.get('/model_status').get_json()
        assert status['postgres_available'] is True
        assert status['weekly_predictor_available'] is True


class TestConnectionLifecycle:
    @pytest.mark.unit
    def test_predict_uses_request_scoped_connection(self, client, pool, predictor):
        shared, view = predictor

        response = client.post('/predict_week', json=VALID_BODY)

        assert response.status_code == 200
        shared.with_connection.assert_called_once_with(pool.conn)
        assert shared.db_connection is None  # shared model never holds a connection
        assert pool.returned == [(pool.conn, False)]
        pool.conn.rollback.assert_called_once()
        data = response.get_json()
        assert [p['player_id'] for p in data['predictions']] == ['4034']
        assert data['unavailable'][0]['reason'] == 'unknown_player'
        assert data['scoring'] == 'ppr'
        assert data['freshness'] == {'stub': True}
        assert data['current_week'] == CURRENT_WEEK

    @pytest.mark.unit
    def test_connection_returned_and_error_not_leaked_on_failure(self, client, pool, predictor):
        _, view = predictor
        view.predict_week.side_effect = RuntimeError('secret internal detail')

        response = client.post('/predict_week', json=VALID_BODY)

        assert response.status_code == 500
        assert response.get_json() == {'error': 'Internal server error'}
        assert pool.returned == [(pool.conn, False)]

    @pytest.mark.unit
    def test_broken_connection_is_discarded(self, client, pool, predictor):
        pool.conn.rollback.side_effect = psycopg2.InterfaceError('connection already closed')

        client.post('/predict_week', json=VALID_BODY)

        assert pool.returned == [(pool.conn, True)]

    @pytest.mark.unit
    def test_requests_wait_for_a_free_connection_then_503_busy(self, client, pool, predictor,
                                                               monkeypatch):
        import threading
        slots = threading.BoundedSemaphore(1)
        monkeypatch.setattr(api, '_pool_slots', slots)
        monkeypatch.setattr(api, 'DB_POOL_WAIT_SECONDS', 0.05)

        slots.acquire()  # every connection in use
        busy = client.post('/predict_week', json=VALID_BODY)
        slots.release()
        ok = client.post('/predict_week', json=VALID_BODY)

        assert busy.status_code == 503
        assert busy.get_json()['error'] == 'Server busy, please retry'
        assert ok.status_code == 200
        assert slots.acquire(blocking=False)  # slot released after the request

    @pytest.mark.unit
    def test_missing_model_returns_503(self, client, pool, monkeypatch):
        store = MagicMock()
        store.get.return_value = None
        store.last_error = None
        monkeypatch.setattr(api, 'model_store', store)

        response = client.post('/predict_week', json=VALID_BODY)

        assert response.status_code == 503
        assert pool.returned == []


class TestModelStore:
    @staticmethod
    def _touch(path, content: bytes):
        path.write_bytes(content)
        # Guarantee a distinct mtime even on coarse filesystem clocks
        stamp = time.time_ns() + int(1e9) * (len(content))
        os.utime(path, ns=(stamp, stamp))

    @pytest.mark.unit
    def test_reloads_when_file_changes(self, tmp_path):
        path = tmp_path / 'model.pkl'
        self._touch(path, b'v1')
        store = ModelStore(str(path), loader=lambda p: open(p, 'rb').read())

        assert store.get() == b'v1'
        assert store.get() == b'v1'  # unchanged file: no reload

        self._touch(path, b'v2-retrained')
        assert store.get() == b'v2-retrained'
        assert store.status()['loaded_at'] is not None

    @pytest.mark.unit
    def test_failed_reload_keeps_previous_model_without_retrying(self, tmp_path):
        path = tmp_path / 'model.pkl'
        self._touch(path, b'good')
        calls = []

        def loader(p):
            calls.append(p)
            data = open(p, 'rb').read()
            if data == b'corrupt':
                raise ValueError('bad pickle')
            return data

        store = ModelStore(str(path), loader=loader)
        assert store.get() == b'good'

        self._touch(path, b'corrupt')
        assert store.get() == b'good'
        assert store.get() == b'good'
        assert len(calls) == 2  # the corrupt file is attempted once, not every request
        assert 'bad pickle' in store.status()['last_load_error']

    @pytest.mark.unit
    def test_missing_file_returns_none(self, tmp_path):
        store = ModelStore(str(tmp_path / 'absent.pkl'), loader=lambda p: 'never')

        assert store.get() is None
        assert store.status()['file_exists'] is False


class TestPredictorPersistence:
    @pytest.mark.unit
    def test_save_is_atomic_and_leaves_no_temp_file(self, tmp_path):
        predictor = WeeklyPredictor()
        predictor._is_trained = True
        path = tmp_path / 'model.pkl'

        predictor.save(str(path))

        assert path.exists()
        assert not (tmp_path / 'model.pkl.tmp').exists()

    @pytest.mark.unit
    def test_with_connection_shares_models_not_connection(self):
        predictor = WeeklyPredictor()
        predictor.models = {'rb': object()}

        view = predictor.with_connection('conn-a')

        assert view.db_connection == 'conn-a'
        assert predictor.db_connection is None
        assert view.models is predictor.models



class TestUIContext:
    @pytest.mark.unit
    def test_data_freshness_reports_utc_times_and_latest_stats_week(self, monkeypatch, tmp_path):
        from datetime import datetime
        model = tmp_path / 'model.pkl'
        model.write_bytes(b'x')
        monkeypatch.setattr(api, 'MODEL_PATH', str(model))
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            (datetime(2026, 10, 5, 8, 30), datetime(2026, 1, 13, 3, 56), None),
            (2025, 18),
        ]
        conn = MagicMock()
        conn.cursor.return_value = cursor

        result = REAL_DATA_FRESHNESS(conn, 2025, 18)

        assert result['projections_synced_at'] == '2026-10-05T08:30:00Z'
        assert result['stats_synced_at'] == '2026-01-13T03:56:00Z'
        assert result['players_synced_at'] is None
        assert result['stats_through'] == {'season': 2025, 'week': 18}
        assert result['model_trained_at'].endswith('Z')

    @pytest.mark.unit
    def test_current_nfl_week_is_cached_and_survives_sleeper_outage(self, monkeypatch):
        import sys
        calls = []

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_nfl_state(self):
                calls.append(1)
                if len(calls) > 1:
                    raise RuntimeError('sleeper down')
                return {'season': '2026', 'week': 5, 'season_type': 'regular'}

        monkeypatch.setitem(sys.modules, 'data_pipeline.sleeper_client',
                            MagicMock(SleeperClient=FakeClient))
        monkeypatch.setattr(api, '_nfl_state', {'value': None, 'expires': 0.0})

        expected = {'season': 2026, 'week': 5, 'season_type': 'regular'}
        assert REAL_CURRENT_NFL_WEEK() == expected
        assert REAL_CURRENT_NFL_WEEK() == expected
        assert len(calls) == 1  # served from cache

        api._nfl_state['expires'] = 0.0  # cache expired, Sleeper now down
        assert REAL_CURRENT_NFL_WEEK() is None
