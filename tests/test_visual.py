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
