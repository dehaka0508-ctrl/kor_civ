"""AI 3페이즈(결승기): 승리까지 남은 턴(ETA)을 서로 비교해 질주할지 정한다.

ETA 는 누구나 볼 수 있는 정보(지역 수·반기 랭킹·과학/경제 단계·GDP)로 어림한다.
- 과학: (남은 단계 비용 − 모아 둔 돈) ÷ 추정 순수입(GDP × 5%)과 남은 단계 × 15턴 중 긴 쪽
- 경제: (남은 단계 비용 − 모아 둔 돈) ÷ 추정 순수입과 남은 단계 최소 턴 중 긴 쪽
- 정복: 3분의 2까지 남은 지역 ÷ 최근(반기 랭킹 기준) 지역 증가 속도
내 ETA 가 다른 모든 나라의 가장 빠른 ETA 의 (1 + 20%) 안이면 '가장 유리'로 보고 질주한다(sprint).
"""
from __future__ import annotations

import math

from . import config as C
from . import diplomacy as D

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
    cost = sum(g.science_step_cost(fid, st) for st in rem) - _paid(g, fid, "science") - max(0.0, f.money)
    return min(ETA_NONE, max(g.science_turns(fid) * len(rem) + 4, max(0.0, cost) / income_est(g, fid)))


def _paid(g, fid, kind) -> float:
    return sum(r.project.paid for r in g.regions_of(fid) if r.project and r.project.kind == kind)


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
    cost -= _paid(g, fid, "econ") + max(0.0, g.factions[fid].money)
    return min(ETA_NONE, max(turns, max(0.0, cost) / income_est(g, fid)))


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


def watch(g, f):
    """6턴마다(2페이즈 이상): 승리가 가장 가까운 다른 나라와 그 위급도(견제). 3페이즈는 assess 가 함께 정한다.
    2페이즈 나라도 승리가 임박한 나라는 견제한다(그때는 대부분 아직 3페이즈가 아니다)."""
    if f.ai.get("phase", 1) >= 3:
        return assess(g, f)
    w = f.ai.setdefault("watch", {})
    if g.turn - w.get("eval", -99) < C.AI_P3_EVAL_TURNS:
        return w
    w["eval"] = g.turn
    mine = best_eta(g, f.id)[1]
    rivals = {x: best_eta(g, x) for x in g.alive_ids() if x != f.id}
    leader = min(rivals, key=lambda x: (rivals[x][1], x), default=None)
    lead_eta = rivals[leader][1] if leader is not None else ETA_NONE
    _set_urgency(g, f, w, leader, lead_eta, mine, sprinting=False, kind=None)
    return w


def _set_urgency(g, f, rec, leader, lead_eta, mine, sprinting, kind):
    """견제 위급도: 나보다 앞선 나라의 ETA 가 짧을수록 0 → 1. 질주 중이거나 외교(강대국 편승)는 견제하지 않는다."""
    urg = 0.0
    if (not sprinting and kind != "diplomatic" and leader is not None and lead_eta < mine
            and not D.allied(g, f.id, leader)):
        urg = max(0.0, min(1.0, (C.AI_P3_URGENT_ETA - lead_eta) / C.AI_P3_URGENT_ETA))
    rec["rival"], rec["rival_eta"] = leader, round(lead_eta, 1)
    rec["urgency"] = round(urg, 2)
    rec["harass"] = leader if urg >= C.AI_P3_HARASS_MIN else None


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
    _set_urgency(g, f, p3, leader, lead_eta, mine, p3["sprint"], kind)
    n = f.ai.setdefault("p3s", {})
    n["eval"] = n.get("eval", 0) + 1
    n["sprint"] = n.get("sprint", 0) + int(p3["sprint"])
    n["harass"] = n.get("harass", 0) + int(p3["harass"] is not None)
    return p3


def harass(g, f):
    """견제 대상과 위급도(대상이 없으면 (None, 0)). 대상이 죽었거나 동맹이 되었으면 없음."""
    ph = f.ai.get("phase", 1)
    p3 = f.ai.get("p3") if ph >= 3 else f.ai.get("watch") if ph == 2 else None
    if not p3:
        return None, 0.0
    t = p3.get("harass")
    if t is None or not g.factions[t].alive or D.allied(g, f.id, t):
        return None, 0.0
    return t, p3.get("urgency", 0.0)


def key_region(g, rid) -> bool:
    """승리에 중요한 지역: 수도, 과학·경제 시설(완공·건설 중)."""
    rr = g.regions[rid]
    if rr.owner < 0:
        return False
    return (g.factions[rr.owner].capital == rid or bool(rr.sci) or bool(rr.econ)
            or (rr.project is not None and rr.project.kind in ("science", "econ")))


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
