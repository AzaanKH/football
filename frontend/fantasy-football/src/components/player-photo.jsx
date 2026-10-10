import React, { useState } from 'react';
import { cn } from '../lib/utils';

/**
 * Sleeper's headshot for a player ID: a 350x254 head-and-shoulders cutout
 * with a transparent background. Unknown IDs answer 403, so failures fall
 * back to initials (discs) or nothing (cutouts).
 */
export const headshotUrl = (playerId) =>
  `https://sleepercdn.com/content/nfl/players/thumb/${encodeURIComponent(playerId)}.jpg`;

// Generational suffixes aren't a last name: "Kenneth Walker III" -> "KW"
const SUFFIXES = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v']);

/** "Bijan Robinson" -> "BR"; "Amon-Ra St. Brown" -> "AB". */
export function initials(name) {
  const words = (name || '')
    .split(/\s+/)
    .filter((w) => /^[A-Za-z]/.test(w) && !SUFFIXES.has(w.toLowerCase().replace(/\.$/, '')));
  if (!words.length) return '?';
  const first = words[0][0];
  const last = words.length > 1 ? words[words.length - 1][0] : '';
  return (first + last).toUpperCase();
}

/**
 * Whether the current player's image has fired an event (load or error).
 * Keyed by player ID, so switching players starts fresh.
 */
function useImageEvent(playerId) {
  const [eventId, setEventId] = useState(null);
  return [eventId === playerId, () => setEventId(playerId)];
}

const DISC_SIZES = {
  sm: 'size-7 text-[0.65rem]',
  md: 'size-10 text-sm',
};

/**
 * Small round headshot next to a player's name. Decorative (the name is
 * always beside it), so it has no alt text.
 */
export function PlayerPhoto({ playerId, name, size = 'md', muted = false, className }) {
  const [failed, onError] = useImageEvent(playerId);
  const [loaded, onLoad] = useImageEvent(playerId);
  return (
    <span
      aria-hidden="true"
      data-testid="player-photo"
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-sideline',
        DISC_SIZES[size],
        muted && 'grayscale opacity-70',
        className
      )}
    >
      {failed || !playerId ? (
        <span className="font-condensed font-semibold leading-none text-chalk-secondary">{initials(name)}</span>
      ) : (
        <img
          key={playerId}
          src={headshotUrl(playerId)}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={onLoad}
          onError={onError}
          // The cutout is head and shoulders; zoom toward the face so it reads at disc size
          className={cn(
            'h-full w-full origin-[50%_15%] scale-[1.4] object-cover transition-opacity duration-300',
            loaded ? 'opacity-100' : 'opacity-0'
          )}
        />
      )}
    </span>
  );
}

/**
 * Full cutout for the verdict: the player stands on the yard line below it.
 * Renders nothing when there is no photo (initials at this size would read
 * as a placeholder, not a player).
 */
export function PlayerCutout({ playerId, className }) {
  const [failed, onError] = useImageEvent(playerId);
  if (!playerId || failed) return null;
  return (
    <img
      key={playerId}
      src={headshotUrl(playerId)}
      alt=""
      aria-hidden="true"
      data-testid="player-cutout"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={onError}
      className={cn('block aspect-[350/254] w-auto select-none object-contain object-bottom', className)}
    />
  );
}
