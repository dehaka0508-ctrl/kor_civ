"""AI 3페이즈(결승기): 승리까지 남은 턴(ETA)을 서로 비교해 질주할지 정한다.

ETA 는 누구나 볼 수 있는 정보(지역 수·반기 랭킹·과학/경제 단계·GDP)로 어림한다.
- 과학: 남은 단계 비용 ÷ 추정 순수입(GDP × 5%)과 남은 단계 × 15턴 중 긴 쪽
- 경제: 남은 단계 비용 ÷ 추정 순수입과 남은 단계 최소 턴 중 긴 쪽
- 정복: 3분의 2까지 남은 지역 ÷ 최근(반기 랭킹 기준) 지역 증가 속도
내 ETA 가 다른 모든 나라의 가장 빠른 ETA 의 (1 + 20%) 안이면 '가장 유리'로 보고 질주한다(sprint).
"""
from __future__ import annotations

import math

from . import config as C

ETA_NONE = 999.0


def income_est(g, fid) -> float:
    return max(1.0, g.gdp(fid) * C.AI_P3_NET_RATE)


def eta_science(g, fid) -> float:
    if "science" not in g.settings.victories:
        return ETA_NONE
    f = g.factions[fid]
    rem = [st for st in C.SCIENCE_STEPS if st not in f.science]
    if not rem:
        return 4.0                                        # 유닛을 발사대로 모으기만 하면 된다
    cost = sum(g.science_step_cost(fid, st) for st in rem)
    return min(ETA_NONE, max(g.science_turns(fid) * len(rem) + 4, cost / income_est(g, fid)))


def eta_econ(g, fid) -> float:
    if not g.econ_enabled():
        return ETA_NONE
    s = g.econ_stage(fid)
    if s >= C.ECON_STAGES:
        return 1.0
    steps = C.ECON_STEPS[max(0, s - 1):]
    cost = sum(C.ECON[k]["per_turn"] * C.ECON[k]["turns"] * (C.ECON_EXCHANGES if k == "exchange" else 1)
               for k in steps) * C.MONEY_SCALE
    turns = sum(C.ECON[k]["turns"] for k in steps) + (C.AI_P3_CLUSTER_TURNS if s == 0 else 0)
    return min(ETA_NONE, max(turns, cost / income_est(g, fid)))


def region_rate(g, fid) -> float:
    """최근 지역 증가 속도(턴당): 지금 지역 수와 24~48턴 전 반기 랭킹의 지역 수 차이."""
    ranks = getattr(g, "rankings", None) or {}
    past = [t for t in ranks if 24 <= g.turn - t <= 72]
    if not past:
        return 0.0
    t0 = min(past, key=lambda t: abs(g.turn - t - 48))
    row = next((r for r in ranks[t0] if r["fid"] == fid), None)
    if row is None:
        return 0.0
    return (g.region_count(fid) - row["regions"]) / max(1, g.turn - t0)


def eta_conquest(g, fid) -> float:
    need = math.ceil(C.CONQUEST_SHARE * len(g.regions)) - g.region_count(fid)
    if need <= 0:
        return 1.0
    rate = region_rate(g, fid)
    if rate <= C.AI_P3_MIN_RATE:
        return ETA_NONE
    return min(ETA_NONE, need / rate)


ETA = {"science": eta_science, "economic": eta_econ, "conquest": eta_conquest}


def best_eta(g, fid):
    """(가장 빠른 승리 조건, 그 ETA)."""
    best = ("", ETA_NONE)
    for k, fn in ETA.items():
        e = fn(g, fid)
        if e < best[1]:
            best = (k, e)
    return best


def assess(g, f):
    """6턴마다(3페이즈): 내 ETA 와 다른 나라 ETA 를 비교해 질주 여부를 정한다. f.ai['p3'] 에 기록."""
    p3 = f.ai.get("p3")
    if not p3:
        return None
    if g.turn - p3.get("eval", -99) < C.AI_P3_EVAL_TURNS:
        return p3
    p3["eval"] = g.turn
    kind = p3["kind"]
    mine = ETA[kind](g, f.id) if kind in ETA else ETA_NONE
    rivals = {x: best_eta(g, x) for x in g.alive_ids() if x != f.id}
    leader = min(rivals, key=lambda x: (rivals[x][1], x), default=None)
    lead_eta = rivals[leader][1] if leader is not None else ETA_NONE
    p3.update(eta=round(mine, 1), rival=leader, rival_kind=rivals[leader][0] if leader is not None else "",
              rival_eta=round(lead_eta, 1),
              sprint=mine < ETA_NONE and mine <= (1 + C.AI_P3_TOL) * lead_eta)
    n = f.ai.setdefault("p3s", {"eval": 0, "sprint": 0})
    n["eval"] += 1
    n["sprint"] += int(p3["sprint"])
    return p3


def sprint(f) -> str:
    """질주 중이면 노리는 승리 조건(아니면 '')."""
    p3 = f.ai.get("p3")
    if not p3 or f.ai.get("phase", 1) < 3 or not p3.get("sprint"):
        return ""
    return p3["kind"]


def missing_science_site(g, fid):
    """과학 질주: 다음 단계를 지을 땅이 내 영토에 없으면(산맥·해안·석유) 그런 땅을 가진 이웃 지역들."""
    step = g.science_next(fid)
    if step not in ("observatory", "pad", "propellant") or g.science_sites(fid, step):
        return []
    mine = set(r.id for r in g.regions_of(fid))
    near = {n for rid in mine for n in g.world.land_adj[rid]} - mine
    return [n for n in sorted(near) if g.regions[n].owner not in (fid,) and g.regions[n].owner >= 0
            and g.science_site_ok(g.regions[n].owner, n, step)]
