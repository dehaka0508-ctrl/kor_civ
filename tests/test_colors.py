"""국가 색 배정(v1.3.1): 지도에 보이는 색끼리 색차가 크게, 플레이어 국기 색도 피해서."""
from korciv import colors as K
from korciv import config as C
from korciv.game import player_color

from test_engine import new_game


def test_palettes_are_big_and_distinct():
    assert len(C.FACTION_COLORS) >= 20 and len(set(c.upper() for c in C.FACTION_COLORS)) == len(C.FACTION_COLORS)
    pal = C.FACTION_COLORS + C.REBEL_COLORS
    assert len(set(c.upper() for c in pal)) == len(pal)
    assert K.min_gap(C.FACTION_COLORS) >= K.MIN_DE
    # 지각적 색차: 빨강·초록은 멀고, 아주 비슷한 두 색은 가깝다
    assert K.delta_e("#FF0000", "#00FF00") > 80 and K.delta_e((50, 50, 50), (52, 50, 50)) < 2


def test_nation_colors_greedy_and_far_from_player():
    for n in (1, 7, C.MAX_ENEMIES):
        cs = K.nation_colors(n)
        assert len(cs) == n + 1 and cs[0] == C.FACTION_COLORS[0] and len(set(cs)) == n + 1
        assert K.min_gap(cs) >= K.MIN_DE
    # 플레이어가 팔레트의 빨강과 거의 같은 색을 고르면 AI 는 그 빨강을 쓰지 않는다
    red = "#BE0035"
    cs = K.nation_colors(C.MAX_ENEMIES, red)
    assert cs[0] == red and "#BE0032" not in cs
    assert all(K.min_gap([red, c]) >= K.MIN_DE for c in cs[1:])
    # 가장 먼 색부터: 두 번째 나라 색은 첫 나라 색(과 바탕색)에서 가장 먼 팔레트 색
    best = max(C.FACTION_COLORS[1:], key=lambda c: K._gap(c, [C.FACTION_COLORS[0]]))
    assert K.nation_colors(1)[1] == best


def test_game_uses_assigned_colors_and_rebels_get_distinct_ones():
    flag = {"bg": "solid", "c1": (190, 0, 53), "em": "disc"}
    g = new_game(player_start="S002", n_enemies=C.MAX_ENEMIES, player_flag=flag)
    cols = [f.color for f in g.factions]
    assert cols == K.nation_colors(C.MAX_ENEMIES, player_color(flag))
    assert K.min_gap(cols) >= K.MIN_DE
    # 반란국: 살아 있는 나라 색과 겹치지 않고 가장 먼 색
    for _ in range(8):
        f0 = g.factions[0]
        rid = next(r.id for r in g.regions_of(f0.id) if r.id != f0.capital) if len(g.regions_of(0)) > 1 else None
        if rid is None:
            mine = [r for r in g.world.order if g.regions[r].owner == -1]
            g.transfer_region(mine[0], 0)
            rid = mine[0]
        nf, _ = g._spawn_rebel(0, rid, 30)
        alive = [f.color.upper() for f in g.factions if f.alive]
        assert len(alive) == len(set(alive))
        assert K.min_gap(alive) >= 5.0
