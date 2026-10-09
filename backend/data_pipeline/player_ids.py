"""
Player ID Resolution

Maps player names from non-Sleeper sources (e.g. Pro Football Reference) to
Sleeper player IDs, which are the primary keys used throughout the database.

Matching is deliberately conservative: a name that matches zero players, or
several players that position/team can't disambiguate, is left unresolved
rather than guessed.
"""

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

# Generational suffixes that sources include inconsistently
_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}


def normalize_name(name: str) -> str:
    """
    Normalize a player name for matching.

    'Kenneth Walker III' -> 'kenneth walker'
    'Ja'Marr Chase*+'    -> 'jamarr chase'      (PFR Pro Bowl/All-Pro markers)
    'D.J. Moore'         -> 'dj moore'
    """
    if not name:
        return ''
    text = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode()
    text = re.sub(r"[^a-z0-9 ]", '', text.lower().replace('-', ' '))
    parts = [p for p in text.split() if p not in _SUFFIXES]
    return ' '.join(parts)


class PlayerIdResolver:
    """Resolve (name, position, team) to a single Sleeper player ID."""

    def __init__(self, players: Iterable[Tuple[str, str, Optional[str], Optional[str]]]):
        """
        Args:
            players: Rows of (player_id, full_name, position, team)
        """
        self._by_name: Dict[str, List[Tuple[str, Optional[str], Optional[str]]]] = {}
        for player_id, full_name, position, team in players:
            key = normalize_name(full_name)
            if key:
                self._by_name.setdefault(key, []).append((player_id, position, team))

    def resolve(self, name: str, position: Optional[str] = None,
                team: Optional[str] = None) -> Optional[str]:
        """
        Return the matching player ID, or None if unmatched or ambiguous.
        """
        candidates = self._by_name.get(normalize_name(name), [])

        if len(candidates) > 1 and position:
            candidates = [c for c in candidates if (c[1] or '').upper() == position.upper()]
        if len(candidates) > 1 and team:
            candidates = [c for c in candidates if (c[2] or '').upper() == team.upper()]

        return candidates[0][0] if len(candidates) == 1 else None
