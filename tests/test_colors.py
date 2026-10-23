"""고정 팔레트·번호 순서·사용자 국기 충돌·반란국 소진·기존 저장 이관."""
import pickle

import pytest

from korciv import colors as K, config as C
from korciv.game import player_color
from test_engine import new_game


NATIONS = "#2B5B84 #C84B31 #2D8A4E #D9822B #7A3E9D #1D7874 #B8336A #8C5A32 #3B7EA1 #6B8E23 #A63A50 #C29B38 #4A5568 #D06A4C #4E6E58 #5C4B8B".split()
REBELS = "#9E6B20 #6B46C1 #2C7A7B #97266D #B7552A #386641".split()


def test_exact_requested_palettes():
    assert C.FACTION_COLORS == NATIONS
    assert C.REBEL_COLORS == REBELS
    assert len(set(NATIONS + REBELS)) == 22


@pytest.mark.parametrize('n', range(C.MAX_ENEMIES + 1))
def test_ai_number_order_and_prefix_do_not_change_with_country_count(n):
    assert K.nation_colors(n) == NATIONS[:n + 1]
    assert K.nation_colors(n) == K.nation_colors(C.MAX_ENEMIES)[:n + 1]


@pytest.mark.parametrize('player', NATIONS)
def test_custom_flag_collision_changes_only_the_conflicting_ai_slot(player):
    actual = K.nation_colors(C.MAX_ENEMIES, player.lower())
    assert actual[0] == player and len(set(actual)) == 16
    assert set(actual) == set(NATIONS)
    for i, preferred in enumerate(NATIONS[1:], 1):
        assert actual[i] == (NATIONS[0] if preferred == player else preferred)


def test_custom_nonpalette_color_preserved_and_does_not_reorder_ai():
    assert K.nation_colors(7, '#C84B32') == ['#C84B32'] + NATIONS[1:8]
    assert K.nation_colors(15, '#0AC81E') == ['#0AC81E'] + NATIONS[1:]


def test_rebels_use_fixed_palette_without_generating_neon_on_exhaustion():
    taken = list(NATIONS)
    palette = REBELS + NATIONS
    for i in range(20):
        before = list(taken)
        chosen = K.pick(taken, palette)
        if i < 6:
            assert chosen == REBELS[i] and chosen not in taken
        else:
            assert before.count(chosen) == min(before.count(c) for c in palette)
        assert chosen in palette
        taken.append(chosen)


def test_actual_rebels_follow_palette_until_exhausted():
    g = new_game(n_enemies=15, player_start='S002')
    for i in range(12):
        parent = i % 6
        rid = next(r.id for r in g.regions.values() if r.owner == -1)
        g.transfer_region(rid, parent, reason='편입')
        rebel, merged = g._spawn_rebel(parent, rid, 30)
        assert not merged and rebel.color == REBELS[i % 6]
        assert rebel.color in NATIONS + REBELS
    assert len(g.factions) == 28


@pytest.mark.parametrize('seed', [5, 17])
def test_game_and_flag_preview_use_identical_numbered_palette(seed):
    from korciv.flags import faction_flag, hex2rgb
    flag = {'bg': 'solid', 'c1': (200, 75, 49), 'em': 'disc'}
    g = new_game(seed=seed, player_start='S002', n_enemies=15, player_flag=flag)
    assert [f.color for f in g.factions] == K.nation_colors(15, player_color(flag))
    assert all(faction_flag(f)['c1'] == hex2rgb(f.color) for f in g.factions)


@pytest.mark.parametrize('custom', [False, True])
def test_legacy_saved_colors_migrate_once_without_changing_progress_or_rng(custom):
    flag = {'bg': 'solid', 'c1': (200, 75, 49), 'em': 'disc'} if custom else None
    g = new_game(player_start='S002', n_enemies=3, player_flag=flag)
    rid = next(r.id for r in g.regions.values() if r.owner == -1)
    g.transfer_region(rid, 0, reason='편입')
    g._spawn_rebel(0, rid, 30)
    for f in g.factions:
        f.color = '#00BBF9'
    g.player.money, g.player.admin, g.player.sci_points, g.turn = 12345, 678.9, 321.2345, 57
    before_rng = g.rng.getstate()
    before_regions = pickle.dumps(g.regions)
    del g.color_schema
    copy = pickle.loads(pickle.dumps(g))
    expected = K.nation_colors(3, player_color(flag))
    assert [f.color for f in copy.factions[:4]] == expected
    assert copy.factions[4].color == REBELS[0]
    assert (copy.player.money, copy.player.admin, copy.player.sci_points, copy.turn) == (12345, 678.9, 321.2345, 57)
    assert copy.rng.getstate() == before_rng
    assert pickle.dumps(copy.regions) == before_regions
    assert copy.color_schema == K.COLOR_SCHEMA
    reloaded = pickle.loads(pickle.dumps(copy))
    assert [f.color for f in reloaded.factions] == [f.color for f in copy.factions]