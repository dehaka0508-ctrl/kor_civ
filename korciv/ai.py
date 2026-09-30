"""AI (기획서 11절): 대전략·작전·전술·외교 4층 유틸리티 판단.

AI 는 플레이어와 같은 안개 규칙을 따른다(적 부대는 자기 시야 안의 것만 본다).
"""
from __future__ import annotations

import math

from . import config as C
from . import diplomacy as D
from . import rules as R
from .leaders import GOV_AGGR_ADJ
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


# ------------------------------------------------------------------ 정보·전력 판단 (전장의 안개 기준)
def eff_aggression(g, f) -> float:
    """지도자 호전성 + 정치체제 보정(0~10)."""
    return max(0.0, min(10.0, f.aggression + GOV_AGGR_ADJ.get(f.gov, 0.0)))


def war_op_threshold(g, f, target, ratio=1.0, can_expand=True) -> float:
    """이 우호도 이하여야 선전포고를 검토한다. 호전적일수록 높다(호전성 9면 우호도가 조금 좋아도 가능).
    보이는 전력이 압도적이면(유혹), 평화적으로 넓힐 땅이 없으면(필요) 조금 더 쉽게 넘는다."""
    aggr = eff_aggression(g, f)
    thr = C.AI_WAR_OP_BASE + C.AI_WAR_OP_PER_AGGR * aggr
    if g.hegemon == target:
        thr += C.AI_WAR_OP_HEGEMON
    if ratio > 1:
        thr += min(C.AI_WAR_OP_TEMPT_MAX, aggr * math.log2(ratio))
    if not can_expand and aggr >= 4:
        thr += C.AI_WAR_OP_NEED
    return thr


def _armies_by_loc(g):
    out = {}
    for a in g.armies.values():
        out.setdefault(a.loc, []).append(a)
    return out


def update_intel(g, f):
    """이번 턴 시야에 보이는 다른 세력 병력을 세고, 예전에 본 병력은 기억(서서히 잊음)."""
    vis = g.visible(f.id)
    seen = {}
    for a in g.armies.values():
        if a.owner not in (NEUTRAL, f.id) and a.loc in vis:
            seen[a.owner] = seen.get(a.owner, 0.0) + g.army_power(a)
    mem = f.ai.setdefault("intel", {})
    for o in g.alive_ids():
        if o != f.id:
            mem[o] = max(seen.get(o, 0.0), mem.get(o, 0.0) * C.AI_INTEL_DECAY)
    f.ai["seen"] = seen
    f.ai["intel_turn"] = g.turn


def perceived_power(g, fid, o) -> float:
    """fid 가 추정하는 o 의 전력: 보이는 병력(또는 기억) + 시야 밖 지역의 추정 수비대."""
    if g.settings.fog == 0:
        return g.mil_power(o)
    f = g.factions[fid]
    if f.ai.get("intel_turn") != g.turn:
        update_intel(g, f)
    known = max(f.ai.get("seen", {}).get(o, 0.0), f.ai.get("intel", {}).get(o, 0.0))
    vis = g.visible(fid)
    hidden = sum(1 for r in g.regions_of(o) if r.id not in vis)
    return known + hidden * C.AI_HIDDEN_GARRISON


def front_analysis(g, fid, o, by_loc=None):
    """fid 와 o 의 전선 분석. 구역별 국지 전력비와 돌파 가능 지점(보이는 방어가 약한 인접 적 지역)."""
    w = g.world
    vis = g.visible(fid)
    by_loc = by_loc or _armies_by_loc(g)

    def power(loc, owner):
        return sum(g.army_power(a) for a in by_loc.get(loc, ()) if a.owner == owner)

    sectors = []
    enemy_border = set()
    for r in g.regions_of(fid):
        adj = [n for n in w.land_adj[r.id] if g.regions[n].owner == o]
        inside = power(r.id, o)                 # 우리 땅에 들어온 적
        if not adj and not inside:
            continue
        enemy_border.update(adj)
        mine = power(r.id, fid)
        theirs = inside + sum(power(n, o) for n in adj if n in vis)
        sectors.append((r.id, mine, theirs))
    targets = []
    for n in enemy_border:
        atk = sum(C.UNITS[k]["atk"] * c for m in w.land_adj[n] if g.regions[m].owner == fid
                  for a in by_loc.get(m, ()) if a.owner == fid for k, c in a.units.items())
        if n in vis:
            dfn = sum(C.UNITS[k]["df"] * c for a in by_loc.get(n, ()) if a.owner == o for k, c in a.units.items())
        else:
            dfn = C.AI_HIDDEN_GARRISON * 1.2
        dfn *= 1 + C.LINE_BONUS * max(g.regions[n].lines.values(), default=0)
        if atk > 1.2 * dfn + 5:
            targets.append(n)
    superior = sum(1 for _, m, t in sectors if m >= 1.3 * t + 10 and m >= 20)
    inferior = sum(1 for _, m, t in sectors if t >= 1.3 * m + 10)
    return {"sectors": len(sectors), "superior": superior, "inferior": inferior,
            "targets": sorted(targets), "border": sorted(enemy_border)}


def war_assessment(g, fid, e):
    """전쟁을 계속할지 판단. desire 가 클수록 강화를 원한다. reasons 는 사람이 읽는 판단 근거."""
    f = g.factions[fid]
    info = D.war_info(g, fid, e) or {"turns": 0, "declarer": None, "lost": 0, "gained": 0, "lost_frac": 0.0,
                                     "score": 0.0}
    alive = g.alive_ids()
    my = g.mil_power(fid) + 0.5 * sum(g.mil_power(x) for x in alive
                                      if x not in (fid, e) and D.at_war(g, x, e) and D.allied(g, x, fid))
    their = perceived_power(g, fid, e) + 0.5 * sum(perceived_power(g, fid, x) for x in alive
                                                   if x not in (fid, e) and D.at_war(g, x, fid) and D.allied(g, x, e))
    ratio = my / max(10.0, their)
    fr = front_analysis(g, fid, e)
    aggr = eff_aggression(g, f)
    other_wars = max(0, len(D.enemies(g, fid)) - 1)
    avg_h = g.avg_happiness(fid)
    d, pro, con = 0.0, [], []
    if ratio < 1:
        d += 0.9 * (1 - ratio)
        pro.append(f"보이는 병력 열세({ratio:.1f}배)")
    if info["lost_frac"] > 0:
        d += 1.5 * info["lost_frac"]
        pro.append(f"영토 {info['lost']}곳 상실")
    if info["turns"] > 12:
        d += 0.025 * (info["turns"] - 12)
        pro.append(f"전쟁 {info['turns']}턴째")
    if avg_h < 0:
        d += 0.015 * -avg_h
        if avg_h < -15:
            pro.append("민심 악화")
    if f.money < 0:
        d += 0.4
        pro.append("재정 적자")
    if other_wars:
        d += 0.3 * other_wars
        pro.append("다른 전선")
    cap = g.regions.get(f.capital)
    if info["lost_frac"] > 0.5 or (cap and cap.occ and cap.occ["by"] == e):
        d += 0.8
        pro.append("수도 위협")
    # 역전 가능성: 전선 일부라도 우세하거나 뚫을 곳이 보이면 계속 싸운다
    turn_around = min(0.8, 0.3 * fr["superior"] + 0.15 * len(fr["targets"]))
    if turn_around > 0:
        d -= turn_around
        con.append(f"전선 {fr['superior']}곳 우세·돌파 가능 {len(fr['targets'])}곳")
    if ratio > 1:
        d -= min(0.6, 0.4 * (ratio - 1))
        con.append(f"병력 우세({ratio:.1f}배)")
    net = info["gained"] - info["lost"]
    goals = f.ai.get("war_goals", {}).get(e) or []
    if info["declarer"] == fid and goals:
        done = sum(1 for r in goals if g.regions[r].owner == fid) / len(goals)
        d += 0.6 * done
        if done >= 0.5:
            pro.append("전쟁 목표 달성")
    elif net > 0:
        d += min(0.4, 0.1 * net)       # 얻을 만큼 얻었다
    if info["declarer"] == fid and info["turns"] < 6:
        d -= 0.3                          # 막 시작한 전쟁은 쉽게 접지 않는다
    d -= (aggr - 5) * 0.06
    return {"desire": d, "ratio": ratio, "front": fr, "info": info, "pro": pro, "con": con}


def peace_reason(a, accept: bool) -> str:
    if accept:
        return "강화 수락: " + (", ".join(a["pro"][:3]) or "전쟁을 이어갈 이유가 줄었습니다")
    return "거절: " + (", ".join(a["con"][:2]) or "아직 전쟁을 계속할 여력이 있습니다") + " — 역전할 수 있다고 봅니다"


# ------------------------------------------------------------------ 외교
def national_power(g, fid):
    return g.power.get(fid, 0.0)


def _diplomacy(g, f):
    fid = f.id
    alive = g.alive_ids()
    update_intel(g, f)
    # 강화: 병력 판단·전선·피로·목표를 종합
    for e in D.enemies(g, fid):
        a = war_assessment(g, fid, e)
        if a["desire"] < C.AI_PEACE_SEEK:
            continue
        ef = g.factions[e]
        if ef.is_ai:
            b = war_assessment(g, e, fid)
            if b["desire"] >= C.AI_PEACE_ACCEPT:
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
    _consider_war(g, f)


def _consider_war(g, f):
    """선전포고: 우호도가 호전성별 문턱 아래인 이웃 중, 보이는 전력·돌파 지점·얻을 가치를 따져 결정."""
    fid = f.id
    my_enemies = D.enemies(g, fid)
    if g.turn <= C.AI_WAR_GRACE_TURNS or len(my_enemies) >= C.AI_MAX_WARS:
        return
    regs = g.regions_of(fid)
    if not regs or f.money < 0 or g.avg_happiness(fid) < -20:
        return
    alive = g.alive_ids()
    aggr = eff_aggression(g, f)
    w = g.world
    neighbors = set()
    can_expand = False
    for r in regs:
        for n in w.land_adj[r.id]:
            o = g.regions[n].owner
            if o == NEUTRAL:
                can_expand = True
            elif o != fid:
                neighbors.add(o)
    by_loc = _armies_by_loc(g)
    my_total = g.mil_power(fid) * (1 - 0.35 * len(my_enemies))    # 다른 전선에 묶인 병력 제외
    best, best_s, best_goals = None, 1.0, []
    for o in sorted(neighbors):
        if D.has_nonaggr(g, fid, o) or D.at_war(g, fid, o) or D.peace_left(g, fid, o) > 0:
            continue
        their = perceived_power(g, fid, o) + sum(perceived_power(g, fid, x) for x in alive
                                                 if x not in (fid, o) and D.allied(g, x, o))
        their /= 1 + 0.5 * len(D.enemies(g, o))       # 상대도 다른 전쟁에 병력이 묶여 있다
        mine = my_total
        cid = D.coalition_of(g, fid)
        if cid is not None:
            mine += 0.5 * sum(g.mil_power(x) for x in g.dip.coalitions[cid]["members"] if x != fid)
        if g.hegemon == o:
            mine += C.HEGEMON_JOINT_FRONT * sum(g.mil_power(x) for x in alive
                                                if x not in (fid, o) and D.at_war(g, x, o)
                                                and not D.at_war(g, x, fid))
        ratio = mine / max(10.0, their)
        op = D.opinion(g, fid, o)
        thr = war_op_threshold(g, f, o, ratio, can_expand)
        if op > thr:
            continue                      # 아직 참을 만하다
        need = 1.5 - 0.07 * aggr
        if ratio < need:
            continue
        fr = front_analysis(g, fid, o, by_loc)
        if not fr["targets"] and ratio < need + 0.5:
            continue                      # 뚫을 곳이 보이지 않는다
        prize = sum(g.region_value(n)[0] for n in fr["targets"]) + 0.3 * sum(
            g.region_value(n)[0] for n in fr["border"] if n not in fr["targets"])
        s = (aggr / 10) * min(2.5, ratio) * (0.5 + min(1.5, prize / 15))
        s += (thr - op) / 40                               # 문턱보다 얼마나 더 미운가
        if not can_expand:
            s += 0.3                                        # 평화적으로 넓힐 땅이 없다
        s -= 0.5 * len(my_enemies)
        if g.avg_happiness(fid) < 0:
            s -= 0.3
        if g.hegemon == o:
            s += min(C.HEGEMON_WAR_MAX, C.HEGEMON_WAR_K * (g.hegemon_share - C.HEGEMON_SHARE))
        if s > best_s:
            best, best_s, best_goals = o, s, fr["targets"][:4] or fr["border"][:2]
    if best is not None:
        ok, _ = D.declare_war(g, fid, best)
        if ok:
            f.ai.setdefault("war_goals", {})[best] = best_goals


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
            if war_assessment(g, f.id, pid)["desire"] >= C.AI_PEACE_SEEK:
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
            # 이미 편입 중인 대상은 오래 걸리는(가치 4 이상) 곳만 공동 편입으로 거든다
            if t["joint"] and (t["joint"] >= 3 or t["value"] < 4):
                continue
            tr = g.regions[t["target"]]
            y = g.region_output_estimate(t["target"])
            food = R.food_output(tr.b["farm"], tr.b["fishery"])
            per_turn = y * tax + food * C.MARKET_BUY["food"] * (1.0 if food_short else 0.15)
            # 완공까지 슬롯이 묶이고 이득은 그 뒤부터: 가치가 높은(오래 걸리는) 지역일수록 할인
            gain = per_turn * max(0, C.AI_ANNEX_HORIZON - t["eff_turns"]) * wts.get("expansion", 1)
            if t["joint"]:   # 거드는 몫은 앞당겨지는 턴만큼만
                gain *= (t["turns"] - t["eff_turns"]) / max(1, t["turns"])
            cands.append((gain / t["cost"], r.id, "annex", t["target"], None, t["cost"] / t["turns"]))
        # 생산 건물
        for key in ("farm", "fishery", "factory", "bank"):
            lv = r.b[key] + 1
            if lv > 5 or (key == "fishery" and not g.can_fish(r.id)):
                continue
            cost = R.prod_building_cost(key, lv)
            turns = g.build_time(fid, key, R.prod_building_turns(lv))
            dy = _delta_output(g, r.id, key)
            horizon = max(0, C.AI_UTILITY_HORIZON - turns)
            gain = dy * tax * horizon * wts.get("economy", 1)
            if key in ("farm", "fishery"):
                dfood = C.FOOD_PER_G * (R.g(lv) - R.g(lv - 1))
                gain += dfood * C.MARKET_BUY["food"] * horizon * (1.0 if food_short else 0.15)
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
