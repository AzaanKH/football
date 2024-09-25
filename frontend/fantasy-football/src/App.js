import React, { useState } from 'react';
import axios from 'axios';

const App = () => {
  const [position, setPosition] = useState('wr'); // Default position
  const [players, setPlayers] = useState([
    {
      PlayerName: '',
      PassingYDS: 0,
      PassingTD: 0,
      PassingInt: 0,
      RushingYDS: 0,
      RushingTD: 0,
      ReceivingRec: 0,
      ReceivingYDS: 0,
      ReceivingTD: 0,
      Fum: 0,
      TouchCarries: 0,
      TouchReceptions: 0,
      Targets: 0,
      RzTouch: 0,
      Rank: 0,
    },
  ]);
  const [predictions, setPredictions] = useState([]);

  const handlePositionChange = (e) => setPosition(e.target.value);

  const handlePlayerChange = (index, e) => {
    const updatedPlayers = [...players];
    updatedPlayers[index][e.target.name] = e.target.value;
    setPlayers(updatedPlayers);
  };

  const addPlayer = () => {
    setPlayers([
      ...players,
      {
        PlayerName: '',
        PassingYDS: 0,
        PassingTD: 0,
        PassingInt: 0,
        RushingYDS: 0,
        RushingTD: 0,
        ReceivingRec: 0,
        ReceivingYDS: 0,
        ReceivingTD: 0,
        Fum: 0,
        TouchCarries: 0,
        TouchReceptions: 0,
        Targets: 0,
        RzTouch: 0,
        Rank: 0,
      },
    ]);
  };

  const getPredictions = async () => {
    try {
      const response = await axios.post('http://localhost:5001/predict', {
        position,
        players,
      });
      setPredictions(response.data);
    } catch (error) {
      console.error('Error fetching predictions:', error);
      alert('There was an error fetching predictions. Please check your backend or input data.');
    }
  };

  return (
    <div className="App" style={{ padding: '20px' }}>
      <h1>Fantasy Football Start Prediction</h1>

      <div style={{ marginBottom: '20px' }}>
        <label>Select Position: </label>
        <select value={position} onChange={handlePositionChange}>
          <option value="wr">Wide Receiver</option>
          <option value="rb">Running Back</option>
          <option value="qb">Quarterback</option>
        </select>
      </div>

      <h2>Player Stats</h2>
      {players.map((player, index) => (
        <div key={index} style={{ marginBottom: '10px', padding: '10px', border: '1px solid #ddd' }}>
          <input
            type="text"
            placeholder="Player Name"
            name="PlayerName"
            value={player.PlayerName}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '150px' }}
          />
          <input
            type="number"
            placeholder="PassingYDS"
            name="PassingYDS"
            value={player.PassingYDS}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '90px' }}
          />
          <input
            type="number"
            placeholder="PassingTD"
            name="PassingTD"
            value={player.PassingTD}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '90px' }}
          />
          <input
            type="number"
            placeholder="PassingInt"
            name="PassingInt"
            value={player.PassingInt}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '90px' }}
          />
          <input
            type="number"
            placeholder="RushingYDS"
            name="RushingYDS"
            value={player.RushingYDS}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '90px' }}
          />
          <input
            type="number"
            placeholder="RushingTD"
            name="RushingTD"
            value={player.RushingTD}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '90px' }}
          />
          <input
            type="number"
            placeholder="ReceivingRec"
            name="ReceivingRec"
            value={player.ReceivingRec}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '100px' }}
          />
          <input
            type="number"
            placeholder="ReceivingYDS"
            name="ReceivingYDS"
            value={player.ReceivingYDS}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '100px' }}
          />
          <input
            type="number"
            placeholder="ReceivingTD"
            name="ReceivingTD"
            value={player.ReceivingTD}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '90px' }}
          />
          <input
            type="number"
            placeholder="Fumbles"
            name="Fum"
            value={player.Fum}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '70px' }}
          />
          <input
            type="number"
            placeholder="TouchCarries"
            name="TouchCarries"
            value={player.TouchCarries}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '100px' }}
          />
          <input
            type="number"
            placeholder="TouchReceptions"
            name="TouchReceptions"
            value={player.TouchReceptions}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '100px' }}
          />
          <input
            type="number"
            placeholder="Targets"
            name="Targets"
            value={player.Targets}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '70px' }}
          />
          <input
            type="number"
            placeholder="Red Zone Touches (RzTouch)"
            name="RzTouch"
            value={player.RzTouch}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '70px' }}
          />
          <input
            type="number"
            placeholder="Rank"
            name="Rank"
            value={player.Rank}
            onChange={(e) => handlePlayerChange(index, e)}
            style={{ marginRight: '10px', width: '70px' }}
          />
        </div>
      ))}

      <button onClick={addPlayer} style={{ marginTop: '10px' }}>
        Add Another Player
      </button>
      <button onClick={getPredictions} style={{ marginLeft: '10px' }}>
        Get Predictions
      </button>

      <div style={{ marginTop: '20px' }}>
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
          <p>No predictions yet</p>
        )}
      </div>
    </div>
  );
};

export default App;