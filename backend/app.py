from flask import Flask, request, jsonify
import pandas as pd
import pickle
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Load your trained models
with open('rb_model.pkl', 'rb') as f:
    rb_model = pickle.load(f)

with open('qb_model.pkl', 'rb') as f:
    qb_model = pickle.load(f)

with open('wr_model.pkl', 'rb') as f:
    wr_model = pickle.load(f)

# Define the columns used in the model for prediction
feature_columns = ['PassingYDS', 'PassingTD', 'PassingInt', 'RushingYDS', 'RushingTD', 
                   'ReceivingRec', 'ReceivingYDS', 'ReceivingTD', 'Fum', 'TouchCarries', 
                   'TouchReceptions', 'Targets', 'RzTouch', 'Rank']

@app.route('/predict', methods=['POST'])
def predict():
    data = request.json  # Get the JSON data from the request
    position = data.get('position')
    players = data.get('players')  # List of players with their stats
    
    # Convert the list of player data into a DataFrame
    df = pd.DataFrame(players)
    
    # Ensure the DataFrame has the required feature columns
    df = df[feature_columns].fillna(0)  # Handle missing values
    
    for col in feature_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # Select the appropriate model
    if position == 'rb':
        predictions = rb_model.predict(df)
    elif position == 'qb':
        predictions = qb_model.predict(df)
    elif position == 'wr':
        predictions = wr_model.predict(df)
    else:
        return jsonify({'error': 'Invalid position'}), 400
    
    # Combine predictions with player names
    df['PredictedPoints'] = predictions
    df['PlayerName'] = [player['PlayerName'] for player in players]
    
    # Sort by predicted points and get the top players (e.g., top 3)
    top_players = df.sort_values(by='PredictedPoints', ascending=False).head(3)
    
    return jsonify(top_players.to_dict(orient='records'))



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
