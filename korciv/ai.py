"""AI (기획서 11절): 대전략·작전·전술·외교 4층 유틸리티 판단.

AI 는 플레이어와 같은 안개 규칙을 따른다(적 부대는 자기 시야 안의 것만 본다).
"""
from __future__ import annotations

import math

from . import config as C
from . import diplomacy as D
from . import rules as R
from .state import NEUTRAL


# ------------------------------------------------------------------ 대전략
def set_strategy(g, f):
    a = f.aggression
    w = {"military": 0.4 + a / 10, "economy": 1.4 - a / 25, "expansion": 1.2, "defense": 0.6}
    alive = g.alive_ids()
    gdps = sorted(alive, key=lambda x: -g.gdp(x))
    mils = sorted(alive, key=lambda x: -g.mil_power(x))
    vt = g.settings.victories
    goal = "economic" if "economic" in vt else "conquest"
    if gdps and gdps[0] == f.id and "economic" in vt:
        w["economy"] += 0.4
        goal = "economic"
    if mils and mils[0] == f.id and a >= 6 and "conquest" in vt:
        w["military"] += 0.4
        goal = "conquest"
    if "landmark" in vt and g.gdp(f.id) > 300_000:
        goal = "landmark"
    if D.enemies(g, f.id):
        w["military"] += 0.5
        w["defense"] += 0.5
    if g.turn < 48:
        w["expansion"] += 0.5
    f.ai["weights"] = w
    f.ai["goal"] = goal
    f.ai["strategy_turn"] = g.turn


def plan_turn(g, fid):
    f = g.factions[fid]
    if not f.alive:
        return
    if "weights" not in f.ai or g.turn - f.ai.get("strategy_turn", -99) >= C.AI_STRATEGY_PERIOD:
        set_strategy(g, f)
    f.auto_food = True
    _market(g, f)
    _tax(g, f)
    _diplomacy(g, f)
    threat = threat_map(g, fid)
    _merge_idle(g, fid)
    _austerity(g, f, threat)
    _army_orders(g, f, threat)
    _slots(g, f, threat)
    for r in g.regions_of(fid):   # 슬롯이 비는 지역은 생산 집중(건설·생산 중엔 효과 없음)
        r.focus = True


# ------------------------------------------------------------------ 위협도
def visible_hostile_power(g, fid, loc):
    if not g.is_visible(fid, loc):
        return 0.0
    return sum(C.UNITS[k]["atk"] * n for a in g.hostile_units_at(fid, loc)
               for k, n in a.units.items() if a.owner != NEUTRAL)


def region_defense(g, fid, rid):
    rr = g.regions[rid]
    d = sum(C.UNITS[k]["df"] * n for a in g.armies_at(rid, fid) for k, n in a.units.items())
    best_line = max(rr.lines.values(), default=0)
    return d * (1 + C.LINE_BONUS * best_line)


def threat_map(g, fid):
    """지역별 위협도 = 인접 적 전력 / 내 지역 방어력."""
    out = {}
    w = g.world
    for r in g.regions_of(fid):
        enemy = 0.0
        for n in w.land_adj[r.id]:
            o = g.regions[n].owner
            if o in (NEUTRAL, fid):
                enemy += visible_hostile_power(g, fid, n) if o != NEUTRAL else 0
                continue
            if D.at_war(g, fid, o):
                enemy += visible_hostile_power(g, fid, n) + 10
            elif not D.has_nonaggr(g, fid, o) and D.opinion(g, fid, o) < -20:
                enemy += 0.3 * sum(C.UNITS[k]["atk"] * c for a in g.armies_at(n, o)
                                   for k, c in a.units.items()) if g.is_visible(fid, n) else 0
        if enemy > 0:
            out[r.id] = enemy / (region_defense(g, fid, r.id) + 10)
    return out


# ------------------------------------------------------------------ 시장·세율
def _market(g, f):
    need_oil = 4 if f.ai.get("weights", {}).get("military", 0) > 1.0 else 2
    if f.res.get("oil", 0) < need_oil and f.money > 4000:
        g.market_buy(f.id, "oil", need_oil - int(f.res["oil"]))
    for res, keep in (("coal", 40), ("elec", 30)):
        if f.res.get(res, 0) > keep * 2:
            g.market_sell(f.id, res, f.res[res] - keep)
    cons = f.last.get("food_cons", 0)
    if cons and f.res.get("food", 0) > cons * 30:
        g.market_sell(f.id, "food", f.res["food"] - cons * 20)
    if f.res.get("oil", 0) > 80:
        g.market_sell(f.id, "oil", f.res["oil"] - 60)


def _tax(g, f):
    regs = g.regions_of(f.id)
    if not regs:
        return
    avg = g.avg_happiness(f.id)
    worst = min(r.happy for r in regs)
    t = f.tax
    if worst < -45 or avg < -15:
        t -= 0.02
    elif avg < -5:
        t -= 0.01
    elif f.money < 0 or (avg > 5 and t < C.TAX_DEFAULT):
        t += 0.01
    elif avg > 30 and f.money < 5000:
        t += 0.01
    target_hi = 0.15 if f.aggression >= 7 else 0.12
    t = max(0.02, min(target_hi, t))
    if abs(t - f.tax) > 1e-6:
        g.set_tax(f.id, t)


# ------------------------------------------------------------------ 외교
def national_power(g, fid):
    return g.power.get(fid, 0.0)


def _diplomacy(g, f):
    fid = f.id
    alive = g.alive_ids()
    # 강화
    for e in D.enemies(g, fid):
        w = g.dip.wars.get(D.pair(fid, e))
        if not w:
            continue
        losing = D.war_score(g, fid, e) < -5
        long_war = g.turn - w["start"] > C.PEACE_WAR_TURNS
        if losing or long_war:
            ef = g.factions[e]
            if ef.is_ai:
                ok, _ = D.treaty_check(g, e, fid, "peace")
                if ok:
                    D.make_peace(g, fid, e)
            else:
                _queue_player(g, fid, "peace")
    # AI 간 조약
    for b in alive:
        if b == fid or not g.factions[b].is_ai or D.at_war(g, fid, b):
            continue
        for kind in ("nonaggr", "alliance", "coalition"):
            ok1, _ = D.treaty_check(g, fid, b, kind)
            ok2, _ = D.treaty_check(g, b, fid, kind)
            if ok1 and ok2:
                D.sign_treaty(g, fid, b, kind)
                break
    # 선전포고
    if g.turn <= C.AI_WAR_GRACE_TURNS or len(D.enemies(g, fid)) >= C.AI_MAX_WARS:
        return
    my_mil = g.mil_power(fid) + 1
    my_regs = g.regions_of(fid)
    if not my_regs:
        return
    my_avg_y = sum(r.output for r in my_regs) / len(my_regs) + 1
    neighbors = {}
    for r in my_regs:
        for n in g.world.land_adj[r.id]:
            o = g.regions[n].owner
            if o not in (NEUTRAL, fid):
                neighbors[o] = neighbors.get(o, 0.0) + g.regions[n].output
    best, best_w = None, 1.0
    for o, border_y in neighbors.items():
        if D.has_nonaggr(g, fid, o) or D.at_war(g, fid, o):
            continue
        their = g.mil_power(o) + sum(g.mil_power(x) for x in alive if x != o and D.allied(g, x, o)) + 1
        value = 0.5 + min(1.0, border_y / (my_avg_y * 4))
        mine = my_mil
        if g.hegemon == o:
            # 공동 전선: 이미 패권 세력과 싸우는 세력의 전력 일부를 더한다
            mine += C.HEGEMON_JOINT_FRONT * sum(g.mil_power(x) for x in alive
                                                if x not in (fid, o) and D.at_war(g, x, o)
                                                and not D.at_war(g, x, fid))
        W = (f.aggression / 10) * (mine / their) * value - D.opinion(g, fid, o) / 100
        W -= len(D.enemies(g, fid)) * 0.5
        if g.hegemon == o:
            W += min(C.HEGEMON_WAR_MAX, C.HEGEMON_WAR_K * (g.hegemon_share - C.HEGEMON_SHARE))
        if W > best_w:
            best, best_w = o, W
    if best is not None:
        D.declare_war(g, fid, best)


def _queue_player(g, fid, kind):
    f = g.factions[fid]
    key = f"proposed_{kind}"
    if g.turn - f.ai.get(key, -99) < 8:
        return
    f.ai[key] = g.turn
    g.pending_proposals.append({"from": fid, "kind": kind})


def propose_to_player(g):
    """다음 턴 시작 시 AI 가 플레이어에게 조약을 제안."""
    pid = g.player_id
    for f in g.factions:
        if not f.alive or not f.is_ai:
            continue
        if D.at_war(g, f.id, pid):
            w = g.dip.wars.get(D.pair(f.id, pid))
            if w and (D.war_score(g, f.id, pid) < -5 or g.turn - w["start"] > C.PEACE_WAR_TURNS):
                _queue_player(g, f.id, "peace")
            continue
        for kind in ("coalition", "alliance", "nonaggr"):
            ok, _ = D.treaty_check(g, f.id, pid, kind)
            if ok:
                _queue_player(g, f.id, kind)
                break


def handle_rebellion(g, fid, rid):
    """수용 비용 < 산출 8턴분이면 수용, 아니면 진압 성공률 70% 이상이면 진압."""
    f = g.factions[fid]
    cost = g.rebellion_accept_cost(fid, rid)
    if cost < g.region_output_estimate(rid) * 8 and f.money >= cost:
        return g.resolve_rebellion(fid, rid, "pay")
    if g.suppress_chance(fid, rid) >= 0.7:
        return g.resolve_rebellion(fid, rid, "suppress")
    if f.tax >= C.REBEL_ACCEPT_TAX_CUT:
        return g.resolve_rebellion(fid, rid, "tax")
    if f.money >= cost:
        return g.resolve_rebellion(fid, rid, "pay")
    return g.resolve_rebellion(fid, rid, "suppress")


def _austerity(g, f, threat):
    """자금이 음수이고 적자면 후방 병력부터 해산해 유지비를 줄인다."""
    if f.money >= 0 or f.last.get("net", 0) >= 0:
        return
    deficit = -f.last.get("net", 0)
    for a in sorted([a for a in g.armies.values() if a.owner == f.id and a.domain() == "land"
                     and a.loc not in threat], key=lambda a: -a.count()):
        for k in ("tank", "art", "inf"):
            while a.units.get(k, 0) > (1 if k == "inf" else 0) and deficit > 0:
                g.disband(a.id, {k: 1})
                deficit -= C.UNITS[k]["upkeep"]
            if a.id not in g.armies:
                break
        if deficit <= 0:
            return


# ------------------------------------------------------------------ 전술: 부대
def _merge_idle(g, fid):
    by_loc = {}
    for a in list(g.armies.values()):
        if a.owner == fid and not a.order and a.domain() == "land" and not g.world.is_sea(a.loc):
            by_loc.setdefault(a.loc, []).append(a)
    for loc, arms in by_loc.items():
        base = arms[0]
        for other in arms[1:]:
            g.merge_armies(base.id, other.id)


def _army_orders(g, f, threat):
    fid = f.id
    w = g.world
    tax = max(0.05, f.tax)
    at_war = bool(D.enemies(g, fid))
    wts = f.ai.get("weights", {})
    annexing = {r.project.key for r in g.regions_of(fid) if r.project and r.project.kind == "annex"}
    armies = [a for a in g.armies.values() if a.owner == fid and a.domain() == "land"
              and not w.is_sea(a.loc)]
    front = set(threat)
    for a in armies:
        if a.id not in g.armies:
            continue
        rr = g.regions[a.loc]
        # 점령 중이면 자리를 지킨다
        if rr.occ and rr.occ["by"] == fid:
            continue
        reach = g.reachable(a)
        best, best_u, best_mode = None, 0.0, "assault"
        for node, opt in reach.items():
            if opt["action"] != "attack" or w.is_sea(node):
                continue
            tgt = g.regions[node]
            if tgt.owner == NEUTRAL:
                if node in annexing:
                    continue
                if wts.get("military", 1) < 0.9 and a.count() < 3:
                    continue
            for mode in ("assault", "surprise"):
                pv = g.preview_attack(a, node, mode)
                if not pv or pv["A"] <= 0:
                    continue
                if mode == "surprise":
                    p = pv["surprise_p"]
                    dd = p * pv["def_dmg_win"] + (1 - p) * pv["def_dmg_fail"]
                    ad = p * pv["att_dmg_win"] + (1 - p) * pv["att_dmg_fail"]
                else:
                    dd, ad = pv["def_dmg"], pv["att_dmg"]
                kill = dd >= pv["def_hp"] * 0.95
                enemy_val = dd * 35
                own_val = ad * 35
                cap_val = g.region_output_estimate(node) * tax * 24 if kill else 0
                u = enemy_val - own_val + cap_val
                if tgt.owner == NEUTRAL and not kill:
                    u = -1
                if u > best_u:
                    best, best_u, best_mode = node, u, mode
        if best:
            g.order_army(a.id, best, best_mode)
            continue
        # 빈 적지·중립지 점령
        for node, opt in reach.items():
            if opt["action"] == "move" and not w.is_sea(node) and g.hostile(fid, g.regions[node].owner) \
                    and node not in annexing:
                g.order_army(a.id, node)
                break
        if a.order:
            continue
        # 포병 폭격
        if a.units.get("art") and at_war:
            tgts = [n for n, o in reach.items() if o["action"] in ("bombard", "attack")
                    and g.regions[n].owner != NEUTRAL and g.hostile_units_at(fid, n)]
            if tgts:
                g.order_army(a.id, tgts[0], force_bombard=True)
                continue
        # 전선으로 이동: 1개짜리 수비대는 전쟁 중 후방일 때만 움직인다
        if a.count() <= 1 and (not at_war or a.loc in front):
            continue
        if a.loc in front and threat.get(a.loc, 0) > 0.5:
            continue
        dest = _nearest_front(g, fid, a.loc, front, threat)
        if dest and dest in reach and reach[dest]["action"] == "move":
            g.order_army(a.id, dest)
        elif dest:
            step = _step_toward(g, fid, a.loc, dest, reach)
            if step:
                g.order_army(a.id, step)
    # 폭격기
    for a in g.armies.values():
        if a.owner != fid or a.domain() != "air" or not at_war:
            continue
        reach = g.reachable(a)
        tg = [(visible_hostile_power(g, fid, n), n) for n, o in reach.items() if o["action"] == "bombard"
              and g.regions[n].owner != NEUTRAL]
        tg.sort(reverse=True)
        if tg and tg[0][0] > 0:
            g.order_army(a.id, tg[0][1], force_bombard=True)


def _nearest_front(g, fid, start, front, threat):
    if not front:
        return None
    from collections import deque
    q = deque([start])
    seen = {start: None}
    while q:
        u = q.popleft()
        if u in front and u != start:
            return u
        for v in g.world.land_adj[u]:
            if v not in seen and g.regions[v].owner == fid:
                seen[v] = u
                q.append(v)
    return None


def _step_toward(g, fid, start, dest, reach):
    from collections import deque
    prev = {dest: None}
    q = deque([dest])
    while q:
        u = q.popleft()
        if u in reach and reach[u]["action"] == "move" and g.regions[u].owner == fid:
            return u
        for v in g.world.land_adj[u]:
            if v not in prev and g.regions[v].owner == fid:
                prev[v] = u
                q.append(v)
    return None


def auto_slots(g, fid, military=True):
    """플레이어 편의: 빈 슬롯을 AI 판단으로 채운다. 채운 슬롯 수를 반환."""
    f = g.factions[fid]
    if "weights" not in f.ai:
        set_strategy(g, f)
    before = g.idle_slots(fid)
    _slots(g, f, threat_map(g, fid), military=military)
    return before - g.idle_slots(fid)


# ------------------------------------------------------------------ 작전: 슬롯
def _delta_output(g, rid, key):
    rr = g.regions[rid]
    b = dict(rr.b)
    old = R.region_output(rr.pop, b["farm"], b["fishery"], b["factory"], b["bank"], rr.landmark, 1.0)
    b[key] += 1
    new = R.region_output(rr.pop, b["farm"], b["fishery"], b["factory"], b["bank"], rr.landmark, 1.0)
    return new - old


def _slots(g, f, threat, military=True):
    fid = f.id
    wts = f.ai.get("weights", {"military": 1, "economy": 1, "expansion": 1, "defense": 1})
    tax = max(0.05, f.tax)
    regs = g.regions_of(fid)
    if not regs:
        return
    income = f.last.get("tax", sum(g.region_output_estimate(r.id) for r in regs) * tax)
    upkeep = g.upkeep(fid)
    committed = sum(r.project.per_turn for r in regs if r.project and r.project.kind != "landmark")
    reserve = 200 + upkeep * 3
    avail = (income - upkeep) * 0.95 + max(0.0, f.money - reserve) / 5 - committed
    food_bal = f.last.get("food_prod", 0) - f.last.get("food_cons", 0)
    food_short = food_bal < 0 or f.res.get("food", 0) < f.last.get("food_cons", 1) * 2
    at_war = bool(D.enemies(g, fid))
    idle = [r for r in regs if not r.project and not r.occ and (f.is_ai or not r.focus)]
    cands = []
    # 군 생산 수요
    mil_units = sum(a.count() for a in g.armies.values() if a.owner == fid)
    desired = max(2, int(len(regs) * (0.8 if at_war else 0.35) * wts.get("military", 1)))
    if f.aggression >= 6 and g.turn > 6:
        desired += 3
    mil_need = max(0, desired - mil_units)
    producing = sum(1 for r in regs if r.project and r.project.kind == "unit")
    mil_need = max(0, mil_need - producing)
    for r in idle:
        info = g.info(r.id)
        # 편입
        for t in g.annex_targets(fid, r.id):
            if t["busy"]:
                continue
            y = g.region_output_estimate(t["target"])
            gain = y * tax * C.AI_UTILITY_HORIZON * wts.get("expansion", 1) + y * 2
            cands.append((gain / t["cost"], r.id, "annex", t["target"], None, t["cost"] / t["turns"]))
        # 생산 건물
        for key in ("farm", "fishery", "factory", "bank"):
            lv = r.b[key] + 1
            if lv > 5 or (key == "fishery" and not g.can_fish(r.id)):
                continue
            cost = R.prod_building_cost(key, lv)
            turns = g.build_time(fid, key, R.prod_building_turns(lv))
            dy = _delta_output(g, r.id, key)
            gain = dy * tax * C.AI_UTILITY_HORIZON * wts.get("economy", 1)
            if key in ("farm", "fishery"):
                dfood = C.FOOD_PER_G * (R.g(lv) - R.g(lv - 1))
                gain += dfood * C.MARKET_BUY["food"] * C.AI_UTILITY_HORIZON * (1.0 if food_short else 0.15)
            if key == "factory":
                gain *= 0.8  # 연료 필요
            cands.append((gain / cost, r.id, "build", key, None, cost / turns))
        if (info.is_oil or info.is_coal) and r.b["extract"] < 5:
            lv = r.b["extract"] + 1
            cost = R.prod_building_cost("extract", lv)
            gain = lv * 20 * C.AI_UTILITY_HORIZON
            cands.append((gain / cost, r.id, "build", "extract", None, cost / (2 * lv)))
        if r.b["factory"] >= 2 and r.b["power"] < 2:
            lv = r.b["power"] + 1
            cost = R.prod_building_cost("power", lv, info.power_site)
            gain = 250 * R.g(r.b["factory"]) * tax * C.AI_UTILITY_HORIZON * 1.5
            cands.append((gain / cost, r.id, "build", "power", None, cost / (2 * lv)))
        if info.specialty and r.b["specialty"] < 3 and g.turn > 24:
            lv = r.b["specialty"] + 1
            cost = R.prod_building_cost("specialty", lv)
            cands.append((0.15, r.id, "build", "specialty", None, cost / (2 * lv)))
        # 방어선
        th = threat.get(r.id, 0)
        if at_war and th > 0.8:
            for n in g.world.land_adj[r.id]:
                o = g.regions[n].owner
                if o not in (NEUTRAL, fid) and D.at_war(g, fid, o) and r.lines.get(n, 0) < 3:
                    lv = r.lines.get(n, 0) + 1
                    cost = R.def_building_cost("line", lv)
                    cands.append((th * wts.get("defense", 1) * 0.8, r.id, "build", "line", n,
                                  cost / C.DEF_TURNS[lv - 1]))
                    break
    # 군 생산 후보: 위협 높은 곳 우선
    if mil_need > 0 and military:
        order = sorted(idle, key=lambda r: -threat.get(r.id, 0) - (0.2 if r.id == f.capital else 0))
        for r in order[:mil_need]:
            key = "inf"
            if f.res.get("oil", 0) >= 2 and f.money > 8000 and g.rng.random() < 0.35:
                key = "tank"
            elif g.rng.random() < 0.15 and f.money > 3000:
                key = "art"
            per = g.unit_cost(fid, r.id, key)
            u = (1.5 + threat.get(r.id, 0)) * wts.get("military", 1)
            cands.append((u, r.id, "unit", key, None, per))
    # 랜드마크
    if f.is_ai and f.money > C.LANDMARK_COST_PER_TURN * 4 and income - upkeep > C.LANDMARK_COST_PER_TURN * 0.6:
        building = any(r.project and r.project.kind == "landmark" for r in regs)
        if not building:
            owned_do = {g.info(r.id).do8 for r in regs if r.landmark}
            cap = g.regions[f.capital]
            target = cap if not cap.landmark else next(
                (r for r in sorted(regs, key=lambda r: -r.pop) if not r.landmark and not r.project
                 and g.info(r.id).do8 not in owned_do), None)
            if target and not target.project and not target.occ:
                g.start_project(fid, target.id, "landmark", "landmark")
    cands.sort(key=lambda c: -c[0])
    used = set()
    for u, rid, kind, key, border, per in cands:
        if rid in used or u <= 0.05:
            continue
        if per > avail and not (kind == "unit" and f.money > per * 2):
            continue
        ok, _ = g.start_project(fid, rid, kind, key, border=border)
        if ok:
            used.add(rid)
            avail -= per
        if avail <= 0:
            break
