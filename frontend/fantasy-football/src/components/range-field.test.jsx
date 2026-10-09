import { scaleDomain } from './range-field';

const range = (confidenceLow, confidenceHigh) => ({ confidenceLow, confidenceHigh });

test('the axis starts at 0 and spans at least 20 points', () => {
  expect(scaleDomain([range(4, 12)])).toEqual({ min: 0, max: 20 });
  expect(scaleDomain([range(8, 23.5)])).toEqual({ min: 0, max: 25 });
});

test('the axis extends below 0 when a range does', () => {
  // A backup QB projected at -1 with a calibrated range of -3 to -0.5
  expect(scaleDomain([range(-3, -0.5), range(6, 18)])).toEqual({ min: -5, max: 20 });
});
