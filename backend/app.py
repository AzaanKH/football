from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import pandas as pd
import pickle

app = Flask(__name__)
CORS(app)

with open('rb_model.pkl', 'rb') as f:
    rb_model = pickle.load(f)

with open('qb_model.pkl', 'rb') as f:
    qb_model = pickle.load(f)

with open('wr_model.pkl', 'rb') as f:
    wr_model = pickle.load(f)


feature_columns = ['PassingYDS', 'PassingTD', 'PassingInt', 'RushingYDS', 'RushingTD',
                   'ReceivingRec', 'ReceivingYDS', 'ReceivingTD', 'Fum', 'TouchCarries',
                   'TouchReceptions', 'Targets', 'RzTouch', 'Rank']


def connect_db():
    conn = sqlite3.connect('football_season.db')
    return conn


def fetch_players_from_db(position):
    conn = connect_db()
    cursor = conn.cursor()

    if position == "wr":
        cursor.execute("SELECT * FROM wide_receivers")
    elif position == "rb":
        cursor.execute("SELECT * FROM running_backs")
    elif position == "qb":
        cursor.execute("SELECT * FROM quarterbacks")
    else:
        return []

    players = cursor.fetchall()
    columns = [column[0] for column in cursor.description]
    conn.close()


    return [dict(zip(columns, player)) for player in players]


@app.route('/get_players/<position>', methods=['GET'])
def get_players(position):
    players = fetch_players_from_db(position)
    return jsonify(players)


@app.route('/predict', methods=['POST'])
def predict():
    data = request.json  
    position = data.get('position')
    players = data.get('players')  


    df = pd.DataFrame(players)
    

    for col in feature_columns:
        if col not in df.columns:
            df[col] = 0  


    for col in feature_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)


    if position == 'rb':
        predictions = rb_model.predict(df[feature_columns])
    elif position == 'qb':
        predictions = qb_model.predict(df[feature_columns])
    elif position == 'wr':
        predictions = wr_model.predict(df[feature_columns])
    else:
        return jsonify({'error': 'Invalid position'}), 400


    df['PredictedPoints'] = predictions
    df['PlayerName'] = [player['PlayerName'] for player in players]


    top_players = df.sort_values(by='PredictedPoints', ascending=False).head(3)

    return jsonify(top_players.to_dict(orient='records'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)