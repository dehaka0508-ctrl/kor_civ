"""행정·과학 투자와 위인 운용. 군사 작전과 같은 자원·건설 API를 사용한다."""
from __future__ import annotations

import math

from . import config as C
from . import diplomacy as D
from .progression import TECHS


def education_centers(g, fid):
    """인구 상위 30%와 수도에 연구 시설을 집중한다."""
    regs = sorted(g.regions_of(fid), key=lambda r: (-r.pop, r.id))
    return {r.id for r in regs[:max(1, math.ceil(len(regs) * .3))]} | {g.factions[fid].capital}


def science_reserve(g, fid):
    """진행 중인 모든 과학 공사에 필요한 과학력 5턴분."""
    return 5 * sum(round(200 * 1.15 ** C.SCIENCE[p.key]["tier"])
                   for p in g.unique_projects(g.regions_of(fid)) if p.kind == "science")


def admin_weight(g, f, rid, level, threat):
    prod, cons = g.admin_balance(f.id)
    interior = not any(g.regions[n].owner in D.enemies(g, f.id)
                       for n in g.world.land_adj[rid]) and threat.get(rid, 0) < 1
    return 3.5 if level <= 3 and interior and prod - cons < g.total_pop(f.id) * .1 else 1.0


def infrastructure_candidates(g, f, r, opts, threat, edu_centers):
    """신규 내정 건물 효용. 실제 옵션의 정책 할인·광역 비용·입지 제한을 따른다."""
    cands = []
    for o in opts:
        if o["kind"] != "build" or not o["ok"] or o["key"] not in ("admin", "edu"):
            continue
        key, level = o["key"], o["level"]
        cost = max(1, o["cost"])
        horizon = max(1, C.AI_UTILITY_HORIZON - o["turns"])
        if key == "admin":
            neighbors = [n for n in g.world.land_adj[r.id] if g.regions[n].owner == f.id]
            if level == 4 and r.metro is None and r.id != f.capital and len(neighbors) < 2:
                continue
            levels = (0, 5, 15, 30, 50, 100)
            delta = levels[min(5, level)] - levels[max(0, level - 1)]
            value = delta * 12 * horizon / cost * admin_weight(g, f, r.id, level, threat)
            if level == 4:
                value *= 1 + min(4, len(neighbors)) * .2
        elif key == "edu":
            if r.id not in edu_centers:
                continue
            coeff = (0, 1, 2, 4, 6, 10)
            delta = r.pop * (coeff[min(level, 5)] - coeff[max(0, level - 1)])
            value = delta * 6 * horizon / cost
            if f.ai.get("victory_goal") == "science":
                value *= 1.5
        if o.get("slot") and level <= 1:
            # 행정·연구 1단계는 기본 슬롯 한 칸을 쓴다: 마지막 빈 칸이면 덜 반긴다(v1.3.8)
            proj = g.projected_slots(r.id)["base"]
            if sum(1 for c in proj if c is None) <= 1:
                value *= C.AI_LAST_SLOT_MULT
        cands.append((value, r.id, "build", key, None, o["per_turn"]))
    return cands


def tech_order(g, f):
    goal = f.ai.get("victory_goal", f.ai.get("goal", "economic"))
    if D.enemies(g, f.id) or goal == "conquest":
        first = ["inf", "art", "tank", "ftr", "bank", "factory", "power"]
    elif goal == "science":
        first = ["factory", "oil", "bank", "aerospace", "power"]
    else:
        first = ["bank", "factory", "power"]
    # 식량·자원이나 함대가 있는 나라는 그 분야도 계속 발전시킨다.
    regs = g.regions_of(f.id)
    extras = ["farm"]
    if any(g.can_fish(r.id) for r in regs):
        extras += ["fishery"]
    if any(g.info(r.id).is_coal for r in regs):
        extras += ["coal"]
    if any(g.info(r.id).is_oil for r in regs):
        extras += ["oil"]
    extras += ["inf", "art", "tank", "ftr"]
    if any(g.info(r.id).coastal for r in regs):
        extras += ["lst", "dd", "cv"]
    extras += ["bmb", "aerospace"]
    return list(dict.fromkeys(first + extras))


def _recruit(g, f, kind, rid, reserve=0):
    if kind == "scientist" and f.leader == "sej":
        sites = [r for r in g.regions_of(f.id) if r.b.get("edu", 0) >= 4]
        if not sites:
            return False
        rid = max(sites, key=lambda r: (r.pop, r.id)).id
    if kind == "scientist" and f.sci_points < g.great_person_cost(f.id, kind) + reserve:
        return False
    if kind != "scientist" and f.admin < g.great_person_cost(f.id, kind) + reserve:
        return False
    return g.recruit_great_person(f.id, kind, rid)[0]


def progression_orders(g, f, threat, crisis=False):
    regs = g.regions_of(f.id)
    if not regs:
        return
    people = [p for p in g.great_people if p["owner"] == f.id]
    kinds = {p["kind"] for p in people}
    worst = min(regs, key=lambda r: (g.eff_happy(r), r.id))
    endangered = g.eff_happy(worst) <= -35
    # 반란·전선 위기에 필요한 위인을 정책보다 먼저 확보한다.
    if endangered and "artist" not in kinds:
        _recruit(g, f, "artist", worst.id)
    if crisis and "general" not in kinds:
        site = max(regs, key=lambda r: (threat.get(r.id, 0), r.id)).id
        _recruit(g, f, "general", site)
    prod, cons = g.admin_balance(f.id)
    # 적자를 4턴 버틸 최소 비축은 지킨다. 위인 비상 구매는 이 제한보다 우선한다.
    keep = max(0, cons - prod) * 4
    for _ in range(5):
        level = f.policy_level
        if level >= 5:
            break
        cost = (100, 250, 500, 900, 1500)[level]
        if f.admin < cost + keep or not g.unlock_policy(f.id)[0]:
            break
    reserve = science_reserve(g, f.id)
    for key in tech_order(g, f):
        if key in f.techs:
            continue
        if f.sci_points < g.tech_cost(f.id, key) + reserve:
            break
        if not g.unlock_tech(f.id, key)[0]:
            break
    if "chancellor" not in kinds and (prod < cons * 1.1 or f.policy_level >= 5):
        _recruit(g, f, "chancellor", f.capital, keep)
    science_sites = [r for r in regs if r.project and r.project.kind == "science"]
    if "scientist" not in kinds and (science_sites or "aerospace" in f.techs):
        target = max(science_sites or regs, key=lambda r: (r.pop, r.id))
        _recruit(g, f, "scientist", target.id, reserve)
    great_people_orders(g, f, threat)


def great_people_orders(g, f, threat):
    regs = g.regions_of(f.id)
    if not regs:
        return
    occupied_generals = set()
    for person in list(g.great_people):
        if person["owner"] != f.id:
            continue
        kind = person["kind"]
        target = None
        use = False
        if kind in ("scientist", "chancellor"):
            project_kind = "science" if kind == "scientist" else "econ"
            sites = [r for r in regs if r.project and r.project.kind == project_kind
                     and r.project.turns - r.project.progress > (3 if kind == "scientist" else 1)]
            if sites:
                target = max(sites, key=lambda r: (r.project.turns - r.project.progress, r.pop)).id
                use = True
            elif kind == "scientist":
                universities = [r for r in regs if r.b.get("edu", 0) >= 4]
                if universities:
                    target = max(universities, key=lambda r: (r.pop, r.id)).id
            else:
                target = f.capital
        elif kind == "artist":
            rr = min(regs, key=lambda r: (g.eff_happy(r), r.id))
            target = g.queue_region(rr.id).id
            use = True
        elif kind == "general":
            front = [r for r in regs if any(
                g.regions[n].owner in D.enemies(g, f.id) for n in g.world.land_adj[r.id])]
            choices = [r for r in (front or regs) if r.id not in occupied_generals]
            if choices:
                target = max(choices, key=lambda r: (
                    sum(a.count(("land",)) for a in g.armies_at(r.id, f.id)) * (1 + threat.get(r.id, 0)),
                    threat.get(r.id, 0), r.id)).id
                occupied_generals.add(target)
        if target is None:
            continue
        if person["loc"] != target:
            g.move_great_person(person["id"], target)
        if use and person["loc"] == target:
            g.activate_great_person(person["id"])
