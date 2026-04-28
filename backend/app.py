from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PostgreSQL connection for new prediction system
POSTGRES_AVAILABLE = False
pg_connection = None

try:
    import psycopg2

    def get_pg_connection():
        return psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            port=os.environ.get('DB_PORT', 5432),
            database=os.environ.get('DB_NAME', 'football_dev'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'postgres')
        )

    # Test connection
    test_conn = get_pg_connection()
    test_conn.close()
    POSTGRES_AVAILABLE = True
    logger.info("PostgreSQL connection available")
except Exception as e:
    logger.warning(f"PostgreSQL not available: {e}")
    logger.warning("Weekly predictions require PostgreSQL. Start with: docker-compose up -d")

# Weekly predictor (Phase 4)
WEEKLY_PREDICTOR_AVAILABLE = False
weekly_predictor = None

try:
    from weekly_predictor import WeeklyPredictor

    model_path = 'models/weekly_predictor.pkl'
    if os.path.exists(model_path) and POSTGRES_AVAILABLE:
        weekly_predictor = WeeklyPredictor.load(model_path, db_connection=get_pg_connection())
        WEEKLY_PREDICTOR_AVAILABLE = True
        logger.info("Weekly predictor loaded successfully")
    else:
        logger.info("Weekly predictor model not found. Train with: python weekly_predictor.py train")
except ImportError as e:
    logger.warning(f"Weekly predictor not available: {e}")
except Exception as e:
    logger.warning(f"Failed to load weekly predictor: {e}")

app = Flask(__name__)
CORS(app)


@app.route('/model_status', methods=['GET'])
def model_status():
    """
    Get status of available models.

    Returns:
        Dictionary with model availability and metrics
    """
    status = {
        'weekly_predictor_available': WEEKLY_PREDICTOR_AVAILABLE,
        'postgres_available': POSTGRES_AVAILABLE
    }

    if WEEKLY_PREDICTOR_AVAILABLE and weekly_predictor:
        status['weekly_predictor'] = {
            'trained': weekly_predictor._is_trained,
            'positions': list(weekly_predictor.models.keys()),
            'metrics': weekly_predictor.training_metrics
        }

    return jsonify(status)


# ============================================================================
# NEW WEEKLY PREDICTION ENDPOINTS (Phase 4)
# These use Phase 2 features for proper next-week predictions
# ============================================================================

@app.route('/players', methods=['GET'])
def get_players_postgres():
    """
    Get players from PostgreSQL database.

    Query params:
        position: Filter by position (qb, rb, wr)
        limit: Max results (default 100)
        search: Search by name

    Returns:
        List of players with id, name, team, position
    """
    if not POSTGRES_AVAILABLE:
        return jsonify({'error': 'PostgreSQL not available. Start with: docker-compose up -d'}), 503

    position = request.args.get('position', '').upper()
    limit = int(request.args.get('limit', 100))
    search = request.args.get('search', '')

    try:
        conn = get_pg_connection()
        cursor = conn.cursor()

        query = """
            SELECT player_id, full_name, team, position
            FROM players
            WHERE position IN ('QB', 'RB', 'WR', 'TE')
        """
        params = []

        if position:
            query += " AND position = %s"
            params.append(position)

        if search:
            query += " AND full_name ILIKE %s"
            params.append(f'%{search}%')

        query += " ORDER BY full_name LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        columns = ['player_id', 'full_name', 'team', 'position']
        players = [dict(zip(columns, row)) for row in cursor.fetchall()]

        conn.close()
        return jsonify(players)

    except Exception as e:
        logger.error(f"Error fetching players: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/predict_week', methods=['POST'])
def predict_week():
    """
    Predict fantasy points for upcoming week using Phase 2 features.

    This is the NEW prediction system that properly predicts future performance
    using rolling averages, efficiency metrics, trends, and matchup data.

    Request body:
        position: 'qb', 'rb', or 'wr'
        player_ids: List of player IDs to predict
        week: Week number to predict FOR
        season: NFL season (default: 2024)

    Returns:
        {
            week: 15,
            season: 2024,
            predictions: [
                {
                    player_id: "4034",
                    player_name: "Saquon Barkley",
                    predicted_points: 18.5,
                    confidence_low: 12.3,
                    confidence_high: 24.7,
                    features: {
                        avg_3_games: 16.2,
                        trend: "improving",
                        ...
                    }
                }
            ]
        }
    """
    if not WEEKLY_PREDICTOR_AVAILABLE:
        return jsonify({
            'error': 'Weekly predictor not available',
            'help': 'Train with: python weekly_predictor.py train',
            'requires': ['PostgreSQL running', 'Data synced', 'Features computed']
        }), 503

    data = request.json
    position = data.get('position')
    player_ids = data.get('player_ids', [])
    week = data.get('week')
    season = data.get('season', 2024)

    if not position:
        return jsonify({'error': 'position is required'}), 400
    if not player_ids:
        return jsonify({'error': 'player_ids is required'}), 400
    if not week:
        return jsonify({'error': 'week is required'}), 400

    try:
        # Get fresh DB connection for this request
        conn = get_pg_connection()
        weekly_predictor.db_connection = conn

        predictions = weekly_predictor.predict_week(
            player_ids=player_ids,
            season=season,
            week=week,
            position=position
        )

        conn.close()

        # Convert dataclass to dict
        results = []
        for pred in predictions:
            results.append({
                'player_id': pred.player_id,
                'player_name': pred.player_name,
                'predicted_points': pred.predicted_points,
                'confidence_low': pred.confidence_low,
                'confidence_high': pred.confidence_high,
                'features': pred.features_used
            })

        return jsonify({
            'week': week,
            'season': season,
            'position': position,
            'predictions': results
        })

    except Exception as e:
        logger.error(f"Prediction error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/available_weeks', methods=['GET'])
def available_weeks():
    """
    Get weeks that have computed features available for predictions.

    Query params:
        season: NFL season (default: 2024)

    Returns:
        List of weeks with feature data
    """
    if not POSTGRES_AVAILABLE:
        return jsonify({'error': 'PostgreSQL not available'}), 503

    season = int(request.args.get('season', 2024))

    try:
        conn = get_pg_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT week, COUNT(*) as player_count
            FROM player_features
            WHERE season = %s
            GROUP BY week
            ORDER BY week
        """, (season,))

        weeks = [{'week': row[0], 'players': row[1]} for row in cursor.fetchall()]

        conn.close()
        return jsonify({'season': season, 'weeks': weeks})

    except Exception as e:
        logger.error(f"Error fetching weeks: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/player_features/<player_id>', methods=['GET'])
def get_player_features(player_id):
    """
    Get computed features for a specific player.

    Query params:
        season: NFL season (default: 2024)
        week: Specific week (optional, returns latest if not specified)

    Returns:
        Player features used for prediction
    """
    if not POSTGRES_AVAILABLE:
        return jsonify({'error': 'PostgreSQL not available'}), 503

    season = int(request.args.get('season', 2024))
    week = request.args.get('week')

    try:
        conn = get_pg_connection()
        cursor = conn.cursor()

        if week:
            cursor.execute("""
                SELECT pf.*, p.full_name, p.team, p.position
                FROM player_features pf
                JOIN players p ON pf.player_id = p.player_id
                WHERE pf.player_id = %s AND pf.season = %s AND pf.week = %s
            """, (player_id, season, int(week)))
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

        conn.close()

        if not row:
            return jsonify({'error': 'No features found for player'}), 404

        return jsonify(dict(zip(columns, row)))

    except Exception as e:
        logger.error(f"Error fetching features: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
