"""AI 3페이즈(결승기): 승리까지 남은 턴(ETA)을 서로 비교해 질주할지 정한다.

자국 경로는 지형·선행 건설·지도자별 소요 턴·진행 중 공사·재정과 과학력으로 어림한다.
상대 순수입은 공개 GDP로 추정하고, 자국 경로 비교에는 실제 유지비·식량비·다른 공사비를 뺀다.
- 과학: 실제 남은 단계 시간·선행 시설 준비·돈/과학력을 모으는 시간 중 긴 쪽
- 경제: (남은 단계 비용 − 모아 둔 돈) ÷ 추정 순수입과 남은 단계 최소 턴 중 긴 쪽
- 정복: 3분의 2까지 남은 지역 ÷ 최근(반기 랭킹 기준) 지역 증가 속도
내 ETA 가 다른 모든 나라의 가장 빠른 ETA 의 (1 + 20%) 안이면 '가장 유리'로 보고 질주한다(sprint).
"""
from __future__ import annotations

import math

from . import config as C
from . import diplomacy as D, metro as M

ETA_NONE = 999.0


def income_est(g, fid) -> float:
    return max(1.0, g.gdp(fid) * C.AI_P3_NET_RATE)


def income_available(g, fid) -> float:
    regs = g.regions_of(fid)
    f = g.factions[fid]
    food_short = max(0, sum(r.pop for r in regs) * C.FOOD_PER_POP -
                     sum(g.food_prod(fid, r) for r in regs if not r.occ and not g.resisting(r)))
    food_bill = max(0, food_short - f.res.get('food', 0) / 12) * C.MARKET_BUY['food']
    committed = sum(p.per_turn for p in g.unique_projects(regs) if p.kind not in ('science', 'econ'))
    return max(1.0, g.leader_tax_revenue(fid) - g.upkeep(fid) - food_bill - committed)


def eta_science(g, fid, income=None) -> float:
    if "science" not in g.settings.victories:
        return ETA_NONE
    f = g.factions[fid]
    rem = [st for st in C.SCIENCE_STEPS if st not in f.science or
           st in C.SCIENCE_UNITS and not g.science_units_alive(fid).get(st)]
    if not rem:
        return 4.0                                        # 유닛을 발사대로 모으기만 하면 된다
    regs = [r for r in g.regions_of(fid) if not M.is_extra(g, r.id)]
    cost, science_cost, elapsed = 0.0, 0.0, 0.0
    prep_money = 0.0
    techs = set()
    for st in rem:
        active = next((r.project for r in regs if r.project and r.project.kind == 'science' and r.project.key == st), None)
        duration = active.remaining if active else g.science_turns(fid, st)
        cost += active.per_turn * duration if active else g.science_step_cost(fid, st)
        science_cost += g.science_per_turn_cost(C.SCIENCE[st]['tier']) * duration
        # 연구소 뒤에 지형/선행 시설을 얻느라 막히는 시간도 센다. 선행 건설은 앞 단계와 병행할 수 있다.
        if st == 'observatory' and not any(r.id in g.world.mountain_regions for r in regs):
            return ETA_NONE
        if st == 'pad' and not any(g.info(r.id).coastal for r in regs):
            return ETA_NONE
        if st in ('budget', 'booster', 'module', 'propellant'):
            key = 'bank' if st == 'budget' else 'extract' if st == 'propellant' else 'factory'
            candidates = [r for r in regs if st != 'propellant' or g.info(r.id).is_oil]
            if not candidates:
                return ETA_NONE
            # 실제 소유 건물 단계와 대기열을 기준으로 최소 준비 시간을 계산한다.
            plans = []
            for r in candidates:
                level = g.blevel(r.id, key)
                build_time = build_cost = 0.0
                for lv in range(level + 1, 6):
                    money, turns = g.card_cost(fid, r.id, key, lv)
                    build_time += turns
                    build_cost += money * r.b.mult_of('base')
                if level == 0 and not r.b.empty('base'):
                    build_time += 1
                queued_time = 0
                for p in g.local_projects(r.id):
                    queued_time += p.remaining
                    if p.kind == 'build' and p.key == key and p.level >= 5:
                        build_time = min(build_time, queued_time)
                        build_cost = min(build_cost, sum(q.per_turn * q.remaining for q in g.local_projects(r.id)
                                                        if q.kind == 'build' and q.key == key))
                        break
                plans.append((build_time, build_cost))
            prep, money = min(plans)
            # 부스터와 모듈은 같은 공장을 재사용한다.
            if st != 'module' or 'booster' not in rem:
                prep_money += money
            elapsed = max(elapsed, prep)
            if prep > 0 and key in ('bank', 'factory') and key not in f.techs:
                techs.add(key)
            if prep > 0 and key == 'extract':
                techs.update(t for t in ('oil', 'coal') if any(t in M.extract_res(g, r.id) for r in candidates) and t not in f.techs)
        elapsed += duration
    if "aerospace" not in f.techs:
        techs.add('aerospace')
    science_cost += sum(g.tech_cost(fid, key) for key in techs)
    science_wait = max(0.0, science_cost - f.sci_points) / max(1.0, g.science_production(fid))
    return min(ETA_NONE, max(elapsed + 4, max(0.0, cost + prep_money - f.money) /
                            (income_est(g, fid) if income is None else income), science_wait))


def _paid(g, fid, kind) -> float:
    return sum(r.project.paid for r in g.regions_of(fid) if r.project and r.project.kind == kind)


def eta_econ(g, fid, income=None) -> float:
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
    return min(ETA_NONE, max(turns, max(0.0, cost) / (income_est(g, fid) if income is None else income)))


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
    if 'conquest' not in g.settings.victories:
        return ETA_NONE
    need = math.ceil(C.CONQUEST_SHARE * len(g.regions)) - g.region_count(fid)
    if need <= 0:
        return 1.0
    rate = region_rate(g, fid)
    if rate <= C.AI_P3_MIN_RATE:
        return ETA_NONE
    return min(ETA_NONE, need / rate)


ETA = {"science": eta_science, "economic": eta_econ, "conquest": eta_conquest}


def victory_estimates(g, fid):
    """자국 목표 비교: 공개 지형·자국 단계/재정과 현재 외교 관계를 사용한다."""
    income = income_available(g, fid)
    estimates = {k: (fn(g, fid, income=income) if k in ('science', 'economic') else fn(g, fid))
                 for k, fn in ETA.items() if k in g.settings.victories}
    if 'diplomatic' in g.settings.victories:
        cid = D.coalition_of(g, fid)
        outsiders = set(g.nation_ids()) - (g.dip.coalitions[cid]['members'] if cid is not None else {fid})
        # 현행 전원 연합 승리: 적대국이 남았을 때 낙관적인 단기 완승으로 계산하지 않는다.
        can = not (g.mods(fid).value('no_alliance') or g.mods(fid).value('no_coalition'))
        close = can and cid is not None and all(D.allied(g, fid, x) and
                    D.opinion(g, x, fid) >= D.threshold(g, x, fid, C.COALITION_MIN)
                    and not g.mods(x).value('no_coalition') for x in outsiders)
        waits = [max(0, min(g.mods(y).value('coalition_alliance_turns', C.COALITION_ALLIANCE_TURNS)
                           for y in (fid, x)) - (g.turn - g.dip.alliance.get(D.pair(fid, x), g.turn)))
                 for x in outsiders] if close else []
        estimates['diplomatic'] = (1 + max(waits, default=0) + 2 * len(outsiders)) if close else ETA_NONE
    if 'time' in g.settings.victories:
        scores = g.time_scores()
        estimates['time'] = max(1, g.settings.max_turns - g.turn) if scores and max(scores, key=scores.get) == fid else ETA_NONE
    return estimates


def prefer_fastest(scores, estimates):
    """실행 가능한 가장 빠른 길을 우선한다. 10%/2턴 이내 오차권에서만 성향·조건 점수로 고른다."""
    viable = {k: e for k, e in estimates.items() if k in scores and scores[k] > 0 and e < ETA_NONE}
    if not viable:
        return max(scores, key=scores.get)
    fastest = min(viable.values())
    close = [k for k, eta in viable.items() if eta <= fastest + max(2, fastest * .1)]
    return max(close, key=lambda k: (scores[k], -viable[k]))


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
    rivals = {x: best_eta(g, x) for x in g.nation_ids() if x != f.id}
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
        # 우호도에 따라: 좋아하는 나라는 덜, 싫어하는 나라는 더 견제한다(우호도 ±100 → ×(1 ∓ 0.4))
        op = D.opinion(g, f.id, leader)
        urg = max(0.0, min(1.0, urg * (1 - C.AI_P3_HARASS_OP_K * op / 100)))
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
    rivals = {x: best_eta(g, x) for x in g.nation_ids() if x != f.id}
    leader = min(rivals, key=lambda x: (rivals[x][1], x), default=None)
    lead_eta = rivals[leader][1] if leader is not None else ETA_NONE
    # 경제: 기축통화 하나만 남았으면 경쟁자와 견주지 않고 질주(그것부터 짓고 남는 돈으로 수비·생산 건물)
    last_step = kind == "economic" and g.econ_stage(f.id) >= C.ECON_STAGES - 1
    p3.update(eta=round(mine, 1), rival=leader, rival_kind=rivals[leader][0] if leader is not None else "",
              rival_eta=round(lead_eta, 1),
              sprint=last_step or (mine < ETA_NONE and mine <= (1 + C.AI_P3_TOL) * lead_eta))
    # 우세한 나라의 수비 강도: 내 승리가 가까울수록 0 → 1(질주 중일 때만)
    p3["defense"] = round(max(0.0, min(1.0, (C.AI_P3_URGENT_ETA - mine) / C.AI_P3_URGENT_ETA)), 2) \
        if p3["sprint"] else 0.0
    if last_step:
        p3["defense"] = max(p3["defense"], C.AI_P3_LAST_STEP_DEF)   # 기축통화만 남음: 견제가 몰리니 수비도 최소 이만큼
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


def key_value(g, rid) -> float:
    """승리 거점 가치(0이면 아님). 빼앗으면 승리가 막히거나 늦어지는 곳일수록 크다.
    - 발사대(과학 유닛을 모아 발사하는 곳)·과학 유닛이 있는 곳 10
    - 경제 시설: 기축통화·국제금융센터·경제특구 10, 증권거래소 6(빼앗으면 사라진다)
    - 과학·경제 공사 중 8(빼앗으면 멈춘다)
    - 수도 4, 연구소·관측소 2"""
    rr = g.regions[rid]
    if rr.owner < 0:
        return 0.0
    cache = g.__dict__.get("_keyv")
    if cache is None or cache[0] != g.turn:
        units = {}
        for a in g.armies.values():
            if any(a.units.get(k) for k in C.SCIENCE_UNITS):
                units.setdefault(a.loc, set()).add(a.owner)
        cache = g.__dict__["_keyv"] = (g.turn, {}, units)
    hit = cache[1].get(rid)
    if hit is not None and hit[0] == rr.owner:
        return hit[1]
    v = _key_value(g, rr, rid, cache[2])
    cache[1][rid] = (rr.owner, v)
    return v


def _key_value(g, rr, rid, sci_units) -> float:
    v = 0.0
    if "pad" in rr.sci:
        v = 10.0
    elif "observatory" in rr.sci:
        v = 8.0                                   # 부서지면 과학승리를 다시 지을 때까지 막는다: 지키고 노릴 거점
    elif rr.sci:
        v = 2.0
    if rr.econ & {"currency", "ifc", "sez"}:
        v = max(v, 10.0)
    elif rr.econ:
        v = max(v, 6.0)
    if rr.project is not None and rr.project.kind in ("science", "econ"):
        v = max(v, 8.0)
    if g.factions[rr.owner].capital == rid:
        v = max(v, 4.0)
    if v < 10 and rr.owner in sci_units.get(rid, ()):
        v = 10.0
    return v


def retake_targets(g, fid) -> dict:
    """빼앗겼지만 저항·회복 기간이라 되찾으면 되살아나는 내 과학·경제 시설·공사 지역: {지역: 가치}."""
    out = {}
    for r in g.regions.values():
        lb, lp = r.lost_bld, r.lost_project
        mine = (lb and lb["fid"] == fid) or (lp and lp["fid"] == fid)
        if not mine or r.owner == fid or not r.resist or r.resist.get("from") != fid:
            continue
        if g.resist_phase(r)[0] not in ("resist", "recover"):
            continue
        v = 6.0
        if lb and ("pad" in lb["sci"] or lb["econ"] & {"currency", "ifc", "sez"}):
            v = 10.0
        elif lp:
            v = 8.0
        out[r.id] = v
    return out


def key_region(g, rid) -> bool:
    """승리에 중요한 지역: 수도, 발사대·과학 유닛, 경제 시설, 과학·경제 공사 중."""
    return key_value(g, rid) >= 4


def key_targets(g, t, depth=6) -> dict:
    """t 의 승리 거점(가치 6 이상)에서 육로로 몇 칸인지: {지역: (거리, 가치)} — 공격 부대를 거점 쪽으로 이끈다."""
    from collections import deque
    srcs = [(r.id, key_value(g, r.id)) for r in g.regions_of(t)]
    srcs = [(rid, v) for rid, v in srcs if v >= 6]
    out = {}
    q = deque()
    for rid, v in srcs:
        out[rid] = (0, v)
        q.append(rid)
    while q:
        u = q.popleft()
        d, v = out[u]
        if d >= depth:
            continue
        for n in g.world.land_adj[u]:
            if n not in out or out[n][0] > d + 1:
                out[n] = (d + 1, v)
                q.append(n)
    return out


def lead_defense(f) -> float:
    """질주 중인(가장 유리한) 나라의 수비 강도 0~1: 승리가 가까울수록 크다."""
    p3 = f.ai.get("p3")
    if not p3 or f.ai.get("phase", 1) < 3 or not p3.get("sprint"):
        return 0.0
    return p3.get("defense", 0.0)


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
    if step == "propellant" and any(g.info(r.id).is_oil for r in g.regions_of(fid)):
        return []                    # 석유 지역이 있으면 정유공장을 5단계까지 올리면 된다
    site_ok = (lambda o, n: g.info(n).is_oil) if step == "propellant" else (lambda o, n: g.science_site_ok(o, n, step))
    mine = set(r.id for r in g.regions_of(fid))
    near = {n for rid in mine for n in g.world.land_adj[rid]} - mine
    return [n for n in sorted(near) if g.regions[n].owner not in (fid,) and g.regions[n].owner >= 0
            and site_ok(g.regions[n].owner, n)]


# ------------------------------------------------------------------ 외교 3페이즈: 정복 강대국에 편승
def conquest_minded(g, x) -> bool:
    """정복을 노리는 나라: AI 는 2페이즈 방향·3페이즈가 정복, 플레이어는 정복 3페이즈 문턱(2/N)을 넘었으면."""
    from . import ai_phase as PH
    xf = g.factions[x]
    if not xf.alive:
        return False
    if xf.is_ai:
        p2 = xf.ai.get("p2") or {}
        return p2.get("path") == "conquest" or PH.p3_kind(xf) == "conquest"
    return "conquest" in PH.p3_reached(g, x)


def follower_patron(g, f):
    """외교로 강국에 기대는 나라(외교 3페이즈, 또는 2페이즈 '어느 쪽도 유리하지 않음')의 강국. 아니면 None."""
    from . import ai_phase as PH
    p2 = f.ai.get("p2") or {}
    if not (PH.p3_kind(f) == "diplomatic" or (f.ai.get("phase", 1) >= 2 and p2.get("hopeless"))):
        return None
    p = p2.get("patron")
    if p is None or not g.factions[p].alive or D.at_war(g, f.id, p):
        return None
    return p


def coalition_share(g, fid) -> float:
    """내 연합(없으면 나 혼자)이 생존국 가운데 차지하는 비율: 외교승리 진척."""
    alive = g.nation_ids()
    cid = D.coalition_of(g, fid)
    n = len(g.dip.coalitions[cid]["members"] & set(alive)) if cid is not None else 1
    return n / max(1, len(alive))


def recruit(g, f, patron):
    """연합에 끌어들일 나라: 연합 밖이고 강국과 전쟁 중이 아니며 강국·나와 사이가 나쁘지 않은 나라 중
    서로 우호도가 가장 높은 나라(약할수록 조금 더: 보호가 필요하다)."""
    fid = f.id
    cid = D.coalition_of(g, fid)
    members = g.dip.coalitions[cid]["members"] if cid is not None else {fid, patron}
    best, best_s = None, None
    for x in g.nation_ids():
        if x in members or x in (fid, patron) or g.mods(x).value("no_alliance"):
            continue
        if D.at_war(g, patron, x) or D.at_war(g, fid, x) or D.opinion(g, patron, x) < C.AI_P3_RECRUIT_MIN_OP:
            continue
        s = (D.opinion(g, x, fid) + D.opinion(g, fid, x)) / 50 - 0.3 * min(2.0, g.mil_power(x) / max(10.0, g.mil_power(patron)))
        if best_s is None or s > best_s:
            best, best_s = x, s
    return best
