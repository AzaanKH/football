"""Static export: file layout, JSON shape, and the comparison with the API."""

import json
import math
import os
import shutil
from datetime import datetime
from unittest.mock import MagicMock

import pytest

import export_static
from export_static import (build_week_file, compare_with_api, season_calendar, swap_in,
                           week_path, with_expiry, write_json)
from weekly_predictor import WeeklyPrediction, WeeklyPredictor

pytestmark = pytest.mark.unit

CONTEXT = {'team': 'DET', 'opponent': 'ARI', 'is_home': False,
           'kickoff': '2026-10-11T20:25:00+00:00', 'injury_status': None}


def ok(pid, points):
    return WeeklyPrediction(player_id=pid, player_name=f'P{pid}', predicted_points=points,
                            confidence_low=points - 8, confidence_high=points + 8,
                            features_used={'projection_source': 'sleeper'}, context=CONTEXT)


def test_week_path_matches_the_frontend_layout():
    assert week_path(2026, 5, 'rb') == '2026/week-05/rb.json'
    assert week_path(2025, 18, 'qb') == '2025/week-18/qb.json'


def test_week_file_splits_results_like_predict_week():
    results = [ok('1', 20.5), WeeklyPredictor._unavailable('2', 'Bye Back', 'bye', CONTEXT)]
    players = [{'player_id': '1', 'name': 'P1', 'team': 'DET'}]

    data = build_week_file(2026, 5, 'rb', players, results, {'stub': True}, {'season': 2026, 'week': 5})

    assert data['players'] == players
    assert data['predictions'] == [{
        'player_id': '1', 'player_name': 'P1', 'predicted_points': 20.5,
        'confidence_low': 12.5, 'confidence_high': 28.5,
        'features': {'projection_source': 'sleeper'}, 'context': CONTEXT,
    }]
    assert data['unavailable'] == [{
        'player_id': '2', 'player_name': 'Bye Back', 'reason': 'bye',
        'message': "On bye this week (no game on the team's schedule).", 'context': CONTEXT,
    }]
    assert (data['season'], data['week'], data['position'], data['scoring']) == (2026, 5, 'rb', 'ppr')


def test_write_json_refuses_nan(tmp_path):
    with pytest.raises(ValueError):
        write_json(str(tmp_path / 'bad.json'), {'x': math.nan})
    write_json(str(tmp_path / 'a' / 'good.json'), {'x': 1})
    assert json.loads((tmp_path / 'a' / 'good.json').read_text()) == {'x': 1}


def test_compare_with_api_checks_only_requested_players():
    exported = build_week_file(2026, 5, 'rb', [], [ok('1', 20.5), ok('2', 15.0), ok('3', 9.0)], {}, None)
    first, second = exported['predictions'][:2]

    assert compare_with_api(exported, {'predictions': [first, second], 'unavailable': []}, ['1', '2']) == []
    assert compare_with_api(exported, {'predictions': [second, first], 'unavailable': []}, ['1', '2']) == [
        'API predictions not ranked: [15.0, 20.5]']

    changed = {**exported['predictions'][0], 'predicted_points': 21.0}
    problems = compare_with_api(exported, {'predictions': [changed], 'unavailable': []}, ['1'])
    assert len(problems) == 1 and problems[0].startswith('predictions 1:')

    # A player the API reported differently (missing here) is a mismatch too
    assert compare_with_api(exported, {'predictions': [], 'unavailable': []}, ['3'])


# ============================================================================
# Swapping the new export in
# ============================================================================

def _export_dir(path, marker):
    path.mkdir()
    (path / 'index.json').write_text(json.dumps({'marker': marker}))
    return str(path)


def _marker(path):
    return json.loads((path / 'index.json').read_text())['marker']


def test_swap_in_replaces_the_export_and_cleans_up(tmp_path):
    out = tmp_path / 'data'
    _export_dir(out, 'old')
    swap_in(_export_dir(tmp_path / 'data.tmp', 'new'), str(out))

    assert _marker(out) == 'new'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['data']


def test_failed_swap_restores_the_previous_export(tmp_path, monkeypatch):
    out = tmp_path / 'data'
    _export_dir(out, 'old')
    new = _export_dir(tmp_path / 'data.tmp', 'new')

    real_replace = os.replace

    def fail_moving_new_in(src, dst):
        if src == new:
            raise PermissionError('folder in use')
        real_replace(src, dst)

    monkeypatch.setattr(export_static.os, 'replace', fail_moving_new_in)
    with pytest.raises(PermissionError):
        swap_in(new, str(out))

    # The site's data path still works, with the previous export
    assert _marker(out) == 'old'
    assert not (tmp_path / 'data.old').exists()


def test_swap_recovers_an_export_stranded_by_a_killed_run(tmp_path):
    # A run died after moving data aside: only data.old is left
    _export_dir(tmp_path / 'data.old', 'stranded')
    out = tmp_path / 'data'
    swap_in(_export_dir(tmp_path / 'data.tmp', 'new'), str(out))
    assert _marker(out) == 'new'

    # ...and when the new swap fails, the recovered export is what remains
    _export_dir(tmp_path / 'data.old', 'stranded-again')
    shutil.rmtree(out)
    with pytest.raises(FileNotFoundError):
        swap_in(str(tmp_path / 'missing.tmp'), str(out))
    assert _marker(out) == 'stranded-again'


def test_swap_into_an_empty_location(tmp_path):
    out = tmp_path / 'data'
    swap_in(_export_dir(tmp_path / 'data.tmp', 'first'), str(out))
    assert _marker(out) == 'first'


# ============================================================================
# Current week expiry
# ============================================================================

def test_calendar_uses_the_schedule_else_the_date_estimate():
    conn = MagicMock()
    kickoff = datetime(2026, 10, 12, 0, 15)  # week 5's last game (naive UTC, as stored)
    # One lookup per week, in order: only week 5 is on the synced schedule
    rows = iter([(None,)] * 4 + [(kickoff,)] + [(None,)] * 13)
    conn.cursor.return_value.fetchone.side_effect = lambda: next(rows)

    calendar = season_calendar(conn, 2026)

    assert calendar['season'] == 2026
    assert [w['week'] for w in calendar['weeks']] == list(range(1, 19))
    # Synced: last kickoff + 4 hours
    assert calendar['weeks'][4]['finished_at'] == '2026-10-12T04:15:00Z'
    # Not synced: the Wednesday after the week (2026 opens Thu Sep 10)
    assert calendar['weeks'][0]['finished_at'] == '2026-09-16T00:00:00Z'


def test_current_week_expires_when_its_last_game_finishes():
    calendar = {'season': 2026, 'weeks': [
        {'week': 5, 'finished_at': '2026-10-13T04:15:00Z'},
        {'week': 6, 'finished_at': '2026-10-20T04:15:00Z'},
    ]}
    current = {'season': 2026, 'week': 5, 'season_type': 'regular'}

    assert with_expiry(current, calendar) == {**current, 'expires_at': '2026-10-13T04:15:00Z'}
    # Outside the regular season there is no weekly rollover
    assert with_expiry({**current, 'season_type': 'off'}, calendar)['expires_at'] is None
    assert with_expiry(None, calendar) is None
