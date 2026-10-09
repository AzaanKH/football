import { render, screen } from '@testing-library/react';
import axios from 'axios';
import App from './App';

jest.mock('axios');

test('renders the predictor without a backend', async () => {
  axios.get.mockRejectedValue(new Error('Network Error'));
  render(<App />);
  expect(screen.getByRole('heading', { name: 'Fantasy Football Predictor' })).toBeInTheDocument();
});
