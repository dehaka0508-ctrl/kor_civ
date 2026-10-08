"""AI 페이즈: 나라마다 주변 상황으로 확장기(1) → 경쟁기(2)를 판단한다.

1페이즈(확장기)는 맞닿은 빈 땅(중립)이 넉넉한 동안이다. 전쟁보다 빈 땅을 먼저 먹고, 돈이 모자라면
생산 건물로 재정을 늘리며, 편입으로 얻은 보병을 모아 빈 땅을 무력 점령한다(ai.py 에서 이 값을 읽는다).
2페이즈부터는 지금까지의 판단(하나의 공식)을 그대로 쓴다.
"""
from __future__ import annotations

from . import config as C
from .state import NEUTRAL


def frontier(g, fid):
    """(맞닿은 중립 지역 집합, 국경을 맞댄 나라 집합)."""
    w = g.world
    nadj, nb = set(), set()
    for r in g.regions_of(fid):
        for n in w.land_adj[r.id]:
            o = g.regions[n].owner
            if o == NEUTRAL:
                nadj.add(n)
            elif o != fid:
                nb.add(o)
    return nadj, nb


def free_ratio(n_adj: int, regions: int) -> float:
    """빈 땅 여유(0~1): 맞닿은 중립 / max(3, 지역 수 × 20%)."""
    return min(1.0, n_adj / max(C.AI_P1_FREE_MIN, C.AI_P1_FREE_SHARE * max(1, regions)))


def update(g, f) -> int:
    """매 턴 처음에 부른다. f.ai 에 phase·phase_turn·nadj·free·borders 를 기록하고 페이즈를 돌려준다.
    1페이즈는 맞닿은 빈 땅이 내 지역의 10% 이하(최소 2곳)로 줄거나 96턴이 되면 끝난다.
    전쟁을 당해도 1페이즈는 유지한다(빨리 강화하고 빈 땅으로 돌아간다)."""
    nadj, nb = frontier(g, f.id)
    n_reg = g.region_count(f.id)
    f.ai["nadj"] = len(nadj)
    f.ai["borders"] = len(nb)
    f.ai["free"] = free_ratio(len(nadj), n_reg)
    ph = f.ai.get("phase", 1)
    if ph == 1 and g.turn - f.ai.get("phase_turn", 0) >= C.AI_P1_MIN_TURNS:
        done = len(nadj) <= max(2, C.AI_P1_END_SHARE * n_reg) or g.turn >= C.AI_P1_MAX_TURN
        if done:
            ph = 2
            f.ai["phase_turn"] = g.turn
    f.ai["phase"] = ph
    return ph


def phase(f) -> int:
    """AI 의 현재 페이즈(플레이어·기록 없음은 2: 기존 판단)."""
    return f.ai.get("phase", 2) if f.is_ai else 2
