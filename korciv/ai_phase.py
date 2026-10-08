"""AI 페이즈: 나라마다 주변 상황으로 확장기(1) → 경쟁기(2) → 결승기(3)를 판단한다.

1페이즈(확장기)는 맞닿은 빈 땅(중립)이 넉넉한 동안이다. 전쟁보다 빈 땅을 먼저 먹고, 돈이 모자라면
생산 건물로 재정을 늘리며, 편입으로 얻은 보병을 모아 빈 땅을 무력 점령한다(ai.py 에서 이 값을 읽는다).
2페이즈부터는 지금까지의 판단(하나의 공식)을 그대로 쓴다.
3페이즈(결승기)는 노리는 승리 조건이 눈앞에 보일 때 들어간다(목표별 문턱, p3_reached).
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
    f.ai["nb"] = sorted(nb)
    ph = f.ai.get("phase", 1)
    if ph == 1 and g.turn - f.ai.get("phase_turn", 0) >= C.AI_P1_MIN_TURNS:
        done = len(nadj) <= max(2, C.AI_P1_END_SHARE * n_reg) or g.turn >= C.AI_P1_MAX_TURN
        if done:
            ph = 2
            f.ai["phase_turn"] = g.turn
    elif ph >= 2:
        ph = _p3_update(g, f, ph, nb)
    f.ai["phase"] = ph
    return ph


# ------------------------------------------------------------------ 3페이즈(결승기) 문턱
def conquest_need(g) -> float:
    """정복 3페이즈 문턱: 전체 지역의 2/시작 국가 수(8개국이면 25%, 평균 몫의 2배)."""
    return C.AI_P3_CONQ_K / max(2, g.settings.n_enemies + 1)


def p3_reached(g, fid) -> set:
    """이 나라가 문턱을 넘은 승리 조건: 정복(지역 2/N), 과학(3단계 완료), 경제(2단계 완료: 금융 권역 + 증권거래소 3곳)."""
    out = set()
    if g.region_count(fid) >= conquest_need(g) * len(g.regions):
        out.add("conquest")
    if "science" in g.settings.victories and len(g.factions[fid].science) >= C.AI_P3_SCI_STEPS:
        out.add("science")
    if g.econ_enabled() and g.econ_stage(fid) >= C.AI_P3_ECON_STAGE:
        out.add("economic")
    return out


def in_p3(g, fid) -> bool:
    """3페이즈인가. 플레이어는 어느 승리 조건이든 문턱을 넘었으면 3페이즈로 본다."""
    f = g.factions[fid]
    if not f.alive:
        return False
    if f.is_ai:
        return f.ai.get("phase", 1) >= 3
    return bool(p3_reached(g, fid))


def _p3_update(g, f, ph, nb) -> int:
    """2 → 3: 노리는 승리 방향(2페이즈 path)의 문턱을 넘으면. 외교는 셋 다 할 능력이 없어 외교 방향인데
    국경을 맞댄 나라가 모두 3페이즈일 때. 3 → 2: 문턱에서 크게 밀려나면(정복은 문턱의 80% 미만)."""
    p2 = f.ai.get("p2") or {}
    path = p2.get("path")
    reached = p3_reached(g, f.id)
    if ph == 2:
        kind = None
        if path in reached:
            kind = path
        elif path == "diplomatic" and nb and all(in_p3(g, o) for o in nb):
            kind = "diplomatic"
        if kind:
            f.ai["p3"] = {"kind": kind, "turn": g.turn}
            f.ai["phase_turn"] = g.turn
            _p3_log(g, f, "enter", kind)
            return 3
        return 2
    kind = (f.ai.get("p3") or {}).get("kind")
    lost = False
    if kind == "conquest":
        lost = g.region_count(f.id) < C.AI_P3_EXIT * conquest_need(g) * len(g.regions)
    elif kind in ("science", "economic"):
        lost = kind not in reached
    elif kind == "diplomatic":
        lost = not nb or sum(1 for o in nb if in_p3(g, o)) < len(nb) / 2
    if lost:
        _p3_log(g, f, "exit", kind)
        f.ai.pop("p3", None)
        f.ai["phase_turn"] = g.turn
        return 2
    return 3


def _p3_log(g, f, ev, kind):
    log = f.ai.setdefault("p3_log", [])
    log.append([g.turn, ev, kind, g.region_count(f.id)])
    del log[:-20]


def p3_kind(f):
    """3페이즈에서 노리는 승리 조건(아니면 None)."""
    return (f.ai.get("p3") or {}).get("kind") if f.ai.get("phase", 1) >= 3 else None


def phase(f) -> int:
    """AI 의 현재 페이즈(플레이어·기록 없음은 2: 기존 판단)."""
    return f.ai.get("phase", 2) if f.is_ai else 2
