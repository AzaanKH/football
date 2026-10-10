"""Static export: file layout, JSON shape, and the comparison with the API."""

import json
import math

import pytest

from export_static import build_week_file, compare_with_api, week_path, write_json
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
