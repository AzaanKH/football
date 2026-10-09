"""
Unit tests for mapping non-Sleeper player names to Sleeper IDs.
"""

import pytest

from data_pipeline.player_ids import PlayerIdResolver, normalize_name


class TestNormalizeName:
    @pytest.mark.unit
    @pytest.mark.parametrize('raw, expected', [
        ('Kenneth Walker III', 'kenneth walker'),
        ("Ja'Marr Chase*+", 'jamarr chase'),
        ('D.J. Moore', 'dj moore'),
        ('Amon-Ra St. Brown', 'amon ra st brown'),
        ('Marvin Harrison Jr.', 'marvin harrison'),
        ('', ''),
    ])
    def test_normalize(self, raw, expected):
        assert normalize_name(raw) == expected


class TestPlayerIdResolver:
    PLAYERS = [
        ('4866', 'Saquon Barkley', 'RB', 'PHI'),
        ('9493', 'Puka Nacua', 'WR', 'LAR'),
        ('1001', 'Josh Allen', 'QB', 'BUF'),
        ('1002', 'Josh Allen', 'LB', 'JAX'),
        ('2001', 'Mike Williams', 'WR', 'PIT'),
        ('2002', 'Mike Williams', 'WR', 'NYJ'),
    ]

    @pytest.fixture
    def resolver(self):
        return PlayerIdResolver(self.PLAYERS)

    @pytest.mark.unit
    def test_unique_name_resolves(self, resolver):
        assert resolver.resolve('Saquon Barkley*') == '4866'

    @pytest.mark.unit
    def test_unknown_name_is_unresolved(self, resolver):
        assert resolver.resolve('Not A Player', 'WR', 'NYJ') is None

    @pytest.mark.unit
    def test_position_disambiguates(self, resolver):
        assert resolver.resolve('Josh Allen', 'QB') == '1001'

    @pytest.mark.unit
    def test_team_disambiguates(self, resolver):
        assert resolver.resolve('Mike Williams', 'WR', 'PIT') == '2001'

    @pytest.mark.unit
    def test_ambiguous_name_is_not_guessed(self, resolver):
        assert resolver.resolve('Mike Williams', 'WR') is None
        assert resolver.resolve('Josh Allen') is None
