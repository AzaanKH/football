import { fireEvent, render, screen } from '@testing-library/react';
import { PlayerCutout, PlayerPhoto, headshotUrl, initials } from './player-photo';

test('headshots come from Sleeper by player ID', () => {
  expect(headshotUrl('9221')).toBe('https://sleepercdn.com/content/nfl/players/thumb/9221.jpg');
  expect(headshotUrl('a/b')).toBe('https://sleepercdn.com/content/nfl/players/thumb/a%2Fb.jpg');
});

test('initials use the first and last name, skipping suffixes and punctuation', () => {
  expect(initials('Bijan Robinson')).toBe('BR');
  expect(initials('Amon-Ra St. Brown')).toBe('AB');
  expect(initials('Kenneth Walker III')).toBe('KW');
  expect(initials('Brian Thomas Jr.')).toBe('BT');
  expect(initials('J.J. McCarthy')).toBe('JM');
  expect(initials('Cher')).toBe('C');
  expect(initials(null)).toBe('?');
});

test('a disc shows the headshot, then initials if it fails, and retries for a new player', () => {
  const { container, rerender } = render(<PlayerPhoto playerId="9221" name="Jahmyr Gibbs" />);
  const img = container.querySelector('img');
  expect(img).toHaveAttribute('src', headshotUrl('9221'));
  expect(img).toHaveAttribute('alt', ''); // the name is always beside it
  expect(screen.getByTestId('player-photo')).toHaveAttribute('aria-hidden', 'true');

  fireEvent.error(img);
  expect(container.querySelector('img')).not.toBeInTheDocument();
  expect(screen.getByText('JG')).toBeInTheDocument();

  rerender(<PlayerPhoto playerId="4866" name="Saquon Barkley" />);
  expect(container.querySelector('img')).toHaveAttribute('src', headshotUrl('4866'));
});

test('the headshot fades in once loaded', () => {
  const { container } = render(<PlayerPhoto playerId="9221" name="Jahmyr Gibbs" />);
  const img = container.querySelector('img');
  expect(img).toHaveClass('opacity-0');
  fireEvent.load(img);
  expect(img).toHaveClass('opacity-100');
});

test('a cutout disappears when there is no photo', () => {
  render(<PlayerCutout playerId="9221" />);
  const cutout = screen.getByTestId('player-cutout');
  fireEvent.error(cutout);
  expect(screen.queryByTestId('player-cutout')).not.toBeInTheDocument();
});
