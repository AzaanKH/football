import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css'; 

const App = () => {
  const [position, setPosition] = useState('wr'); 
  const [players, setPlayers] = useState([]); 
  const [selectedPlayers, setSelectedPlayers] = useState([]); 
  const [predictions, setPredictions] = useState([]);

  useEffect(() => {
    const fetchPlayers = async () => {
      try {
        const response = await axios.get(`http://localhost:5001/get_players/${position}`);
        setPlayers(response.data); 
      } catch (error) {
        console.error('Error fetching players:', error);
      }
    };
    fetchPlayers();
  }, [position]);

  const handlePositionChange = (e) => {
    setPosition(e.target.value);
    setSelectedPlayers([]); 
  };

  const handlePlayerChange = (index, e) => {
    const playerName = e.target.value;
    const playerData = players.find(player => player.PlayerName === playerName);

    const updatedSelectedPlayers = [...selectedPlayers];
    updatedSelectedPlayers[index] = playerData || {}; 
    setSelectedPlayers(updatedSelectedPlayers);
  };

  const addPlayer = () => {
    setSelectedPlayers([...selectedPlayers, {}]); 
  };

  const getPredictions = async () => {
    try {
      const response = await axios.post('http://localhost:5001/predict', {
        position,
        players: selectedPlayers, 
      });
      setPredictions(response.data);
    } catch (error) {
      console.error('Error fetching predictions:', error);
      alert('There was an error fetching predictions. Please check your backend or input data.');
    }
  };

  return (
    <div className="App">
      <h1>Fantasy Football Start Prediction</h1>

      <div className="select-position">
        <label>Select Position:</label>
        <select value={position} onChange={handlePositionChange}>
          <option value="wr">Wide Receiver</option>
          <option value="rb">Running Back</option>
          <option value="qb">Quarterback</option>
        </select>
      </div>

      <h2>Player Selection</h2>
      <div className="player-selection">
        {selectedPlayers.map((player, index) => (
          <div key={index} className="player-container">
            <select onChange={(e) => handlePlayerChange(index, e)} value={player?.PlayerName || ''}>
              <option value="" disabled>Select a player</option>
              {players.map((p, i) => (
                <option key={i} value={p.PlayerName}>
                  {p.PlayerName}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div style={{ textAlign: 'center' }}>
        <button className="add-player-btn" onClick={addPlayer}>
          Add Another Player
        </button>
        <button className="get-predictions-btn" onClick={getPredictions}>
          Get Predictions
        </button>
      </div>

      <div className="predictions">
        <h2>Predicted Starters</h2>
        {predictions.length > 0 ? (
          <ul>
            {predictions.map((player, index) => (
              <li key={index}>
                {player.PlayerName}: {player.PredictedPoints.toFixed(2)} Points
              </li>
            ))}
          </ul>
        ) : (
          <p className="no-predictions">No predictions yet</p>
        )}
      </div>
    </div>
  );
};

export default App;