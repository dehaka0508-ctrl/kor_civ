"""v1.2.22 시인성: 북중·북러 국경(주변국 땅이 우리 지역 경계에 맞붙음), 산 모양 3종, 지도자 시대순."""
import math
import os

import numpy as np
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from korciv import leaders as LD  # noqa: E402
from korciv.data import load_world  # noqa: E402
from korciv.ui import mapview as MV  # noqa: E402


@pytest.fixture(scope="module")
def world():
    return load_world()


@pytest.fixture(scope="module")
def mv(world):
    return MV.MapView(world)


def _inside(polys, x, y):
    return any(x0 <= x <= x1 and y0 <= y <= y1 and MV.pip(x, y, arr) for _, arr, (x0, y0, x1, y1) in polys)


def test_national_border_line_runs_from_yalu_to_tumen(world):
    lines = world.foreign.get("borders", [])
    main = max(lines, key=len)
    length = sum(math.dist(a, b) for a, b in zip(main, main[1:]))
    assert length > 12                                    # 압록강 하구 ~ 두만강 하구(도 단위 길이)
    ends = sorted([tuple(main[0]), tuple(main[-1])])
    assert ends[0][0] < 124.6 and ends[1][0] > 130.5      # 서쪽 끝은 신의주, 동쪽 끝은 두만강 하구


def test_foreign_land_abuts_korean_regions_without_gaps(world, mv):
    """국경선 양옆을 찍으면 한쪽은 우리 지역, 다른 쪽은 중국·러시아 땅이다(사이에 바다색 틈이 없다)."""
    main = np.array(max(world.foreign["borders"], key=len), dtype=float)
    pts = MV.proj_arr(main)
    near = [p for p in mv.foreign_polys if p[0] in ("중국", "러시아")]
    bad = 0
    n = 0
    for i in range(3, len(pts) - 3, 7):
        (x0, y0), (x1, y1) = pts[i - 1], pts[i + 1]
        d = math.hypot(x1 - x0, y1 - y0)
        if d < 1e-6:
            continue
        nx, ny = -(y1 - y0) / d, (x1 - x0) / d
        x, y = pts[i]
        e = 0.12                                         # 기준 좌표 0.12 ≈ 1.2km
        a, b = (x + nx * e, y + ny * e), (x - nx * e, y - ny * e)
        ka, kb = mv.pick_land(*a), mv.pick_land(*b)
        fa, fb = _inside(near, *a), _inside(near, *b)
        n += 1
        if not ((ka and fb) or (kb and fa)):
            bad += 1
    assert n > 50 and bad <= n * 0.05, (bad, n)


def test_foreign_land_does_not_cover_korean_labels(world, mv):
    for rid in world.order:
        x, y = mv.label[rid]
        assert not _inside(mv.foreign_polys, x, y) or mv.pick_land(x, y) == rid


def test_outer_rivers_are_marked(mv):
    assert sum(mv.terrain_outer) >= 10 and len(mv.border_lines) >= 1
    assert len(mv.terrain_span) == len(mv.terrain_outer)


def test_ridge_marks_mix_three_shapes():
    picks = [MV._ridge_pick(7, i) for i in range(60)]
    assert {s for s, _, _ in picks} == {0, 1, 2}
    assert picks == [MV._ridge_pick(7, i) for i in range(60)]          # 다시 그려도 같은 모양
    assert max(len(g) for g in _runs([s for s, _, _ in picks])) <= 2
    assert all(0.8 <= sc <= 1.2 for _, sc, _ in picks)
    surf = pygame.Surface((400, 60))
    surf.fill((230, 220, 196))
    MV.draw_ridge_marks(surf, [(10, 30), (390, 30)], 2.0, seed=3)
    assert pygame.transform.average_color(surf) != (230, 220, 196, 255)


def _runs(seq):
    out, cur = [], []
    for s in seq:
        if cur and cur[-1] != s:
            out.append(cur)
            cur = []
        cur.append(s)
    out.append(cur)
    return out


def test_leader_picker_is_chronological_but_engine_order_is_fixed():
    for _, _, keys in LD.LEADER_CATEGORIES:
        eras = [LD.LEADER_ERA[k] for k in keys]
        assert eras == sorted(eras)
    assert set(LD.LEADER_ERA) == {l["key"] for l in LD.LEADERS} - {"cus"}
    # AI 지도자 무작위 배정에 쓰는 게임 안 순서는 예전 그대로(같은 시드면 같은 지도자)
    assert [l["key"] for l in LD.LEADERS][:6] == ["dan", "jum", "onz", "egg", "sur", "dae"]
    assert [l["key"] for l in LD.LEADERS][-1] == "cus"


def test_clip_poly_keeps_inside_part():
    sq = np.array([[-10.0, -10.0], [30.0, -10.0], [30.0, 30.0], [-10.0, 30.0]])
    c = MV.clip_poly(sq, 0, 0, 20, 20)
    assert c[:, 0].min() >= 0 and c[:, 0].max() <= 20 and c[:, 1].min() >= 0 and c[:, 1].max() <= 20
    area = 0.5 * abs(np.dot(c[:, 0], np.roll(c[:, 1], -1)) - np.dot(c[:, 1], np.roll(c[:, 0], -1)))
    assert area == pytest.approx(400)
    assert not len(MV.clip_poly(sq + 100, 0, 0, 20, 20))
    inner = np.array([[1.0, 1.0], [5.0, 1.0], [3.0, 4.0]])
    assert MV.clip_poly(inner, 0, 0, 20, 20) is inner


def test_region_polygons_have_no_gaps_or_slivers():
    """v1.2.25: 지역 다각형은 겹침·틈 없는 묶음 — 이웃이 함께 쓰는 경계는 같은 꼭짓점(따로 단순화해 어긋나지 않게)."""
    shp = pytest.importorskip("shapely")
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    w = load_world()
    regs = {rid: unary_union([Polygon(r).buffer(0) for r in geo["polys"]]) for rid, geo in w.geometry.items()}
    U = unary_union(list(regs.values()))
    holes = [Polygon(h).area for p in getattr(U, "geoms", [U]) for h in p.interiors]
    assert not holes                                          # 지역 사이 틈 없음
    tree = shp.STRtree(list(regs.values()))
    ids = list(regs)
    for i, rid in enumerate(ids):
        for j in tree.query(regs[rid]):
            if j <= i:
                continue
            inter = regs[rid].intersection(regs[ids[j]]).area
            if inter > 1e-9:                                  # 겹치면 한 지역이 다른 지역을 둘러싼 경우뿐
                small = min(regs[rid].area, regs[ids[j]].area)
                assert inter == pytest.approx(small, rel=1e-3), (rid, ids[j], inter)


def test_glow_is_colored_by_screen_owner_map():
    """국경 안쪽 번짐: 세기만 저해상도에서 늘리고, 색·칠할 곳은 화면 해상도 주인 번호로(이웃으로 번지지 않게)."""
    surf = pygame.Surface((4, 2))
    surf.fill((100, 100, 100))
    ds = pygame.Surface((4, 2))
    ds.fill((200, 0, 0))                                      # 번짐 세기 200(전선 그림자 없음)
    ids = pygame.Surface((4, 2))
    ids.fill((0, 0, 0))
    for x, code in enumerate((0, 1, 2, 3)):                   # 바다·중립·세력 2·세력 3
        ids.fill((code, 0, 0), (x, 0, 1, 2))
    lut = np.zeros((256, 3), np.uint8)
    lut[2], lut[3] = (255, 0, 0), (0, 0, 255)
    MV.MapView._fx_compose(surf, ds, ids, lut, False)
    assert surf.get_at((0, 0))[:3] == (100, 100, 100) and surf.get_at((1, 0))[:3] == (100, 100, 100)
    r2, b3 = surf.get_at((2, 0)), surf.get_at((3, 0))
    assert r2[0] > 180 and r2[2] < 60 and b3[2] > 180 and b3[0] < 60
