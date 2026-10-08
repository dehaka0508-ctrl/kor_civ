"""AI (기획서 11절): 대전략·작전·전술·외교 4층 유틸리티 판단.

AI 는 플레이어와 같은 안개 규칙을 따른다(적 부대는 자기 시야 안의 것만 본다).
"""
from __future__ import annotations

import math

from . import config as C
from . import diplomacy as D
from . import rules as R
from .leaders import GOV_AGGR_ADJ, LEADER_BY_KEY
from .state import NEUTRAL


# ------------------------------------------------------------------ 지도자 성향
# 행동마다 관련된 지도자 효과 (키, 방향). 방향 +1 은 값이 클수록 유리, −1 은 작을수록 유리.
# 특수 키는 _bias_term 에서 기준값과의 차이로 바꾼다.
LEADER_BIAS_KEYS = {
    "inf": [("atk_inf", 1), ("cost_mil", -1), ("inf_cost_early", -1), ("inf_wave", 1)],
    "tank": [("cost_tank", -1), ("cost_mil", -1)],
    "art": [("bomb_art", 1), ("cost_mil", -1)],
    "naval": [("cost_naval", -1), ("naval_power", 1), ("naval_bomb", 1), ("amphib_extra", 1), ("cut_supply", -1),
              ("amphib_atk", 1)],
    "air": [("cost_air", -1)],
    "farm": [("output_prod", 1), ("build_time_prod", -1), ("build_time_all", -1), ("output_farm", 1)],
    "fishery": [("output_prod", 1), ("build_time_prod", -1), ("build_time_all", -1)],
    "factory": [("output_factory", 1), ("output_prod", 1), ("cost_factory", -1), ("build_time_factory", -1),
                ("build_time_prod", -1), ("build_time_all", -1), ("build_time_industry", -1)],
    "bank": [("output_bank", 1), ("output_prod", 1), ("build_time_prod", -1), ("build_time_all", -1)],
    "line": [("line_k", 1), ("cost_line", -1), ("ambushed_def", 1)],
    "power": [("build_time_industry", -1)],
    "extract": [("build_time_industry", -1)],
    "annex": [("occ_time", -1)],
    "science": [("science_turns", 1), ("cost_science", -1)],
    "assault": [("atk_assault", 1), ("no_ally_assault", 1), ("atk_vs_line", 1)],
    "surprise": [("surprise", 1)],
    "war": [("war_weary_rate", -1), ("war_start_weary", -1), ("resist_time", -1), ("guerrilla", -1),
            ("capital_fall_rebel", -1), ("outnumbered_dmg", -1), ("bounty", -1)],
    "ally": [("ally_war_atk", 1), ("treaty_threshold", -1), ("no_ally_assault", -1)],
}
LEADER_BIAS_K = 0.6        # 효과 크기 → 확률·효용 배수
LEADER_BIAS_MAX = 0.15     # 소폭: 최대 ±15%


def _bias_term(key, v) -> float:
    """효과 값을 '기준 대비 비율'로."""
    if key == "amphib_extra":
        return v - 1.0
    if key == "line_k":
        return (v - C.LINE_BONUS) / C.LINE_BONUS
    if key == "science_turns":
        return (C.SCIENCE_TURNS - v) / C.SCIENCE_TURNS
    if key == "surprise":
        return v * 2
    if key == "treaty_threshold":
        return v / 50
    if key in ("guerrilla",):
        return 0.1 * v
    if key == "capital_fall_rebel":
        return 0.1 * (v - 1)
    if isinstance(v, bool):
        return 0.0
    return float(v)


def leader_bias(g, fid, action) -> float:
    """AI 지도자의 버프·디버프에 따라 유리한 행동은 조금 더, 불리한 행동은 조금 덜(×0.85~1.15)."""
    fx = LEADER_BY_KEY.get(g.factions[fid].leader, {}).get("fx", {})
    s = 0.0
    for key, sign in LEADER_BIAS_KEYS.get(action, ()):
        if key in fx:
            s += sign * _bias_term(key, fx[key])
    return 1 + max(-LEADER_BIAS_MAX, min(LEADER_BIAS_MAX, LEADER_BIAS_K * s))


# ------------------------------------------------------------------ 대전략
def choose_victory_goal(g, f):
    """1년에 한 번: 국내 상황·주변 정세·지도자 성향으로 추구할 승리 조건을 고른다(플레이어에게 보이지 않음).
    정복(군사력·영토 비율), 과학(재정·진행 단계·필요한 땅), 경제(GDP 몫), 외교(동맹·연합), 시간(1위 유지)."""
    vt = [v for v in ("conquest", "science", "economic", "diplomatic", "time") if v in g.settings.victories]
    if not vt:
        return None
    alive = g.alive_ids()
    n = max(1, len(alive))
    fid = f.id
    aggr = eff_aggression(g, f)
    my_mil = g.mil_power(fid)
    top_mil = max((g.mil_power(x) for x in alive), default=1) or 1
    regs = g.regions_of(fid)
    neighbors = {g.regions[m].owner for r in regs for m in g.world.land_adj[r.id]} - {NEUTRAL, fid}
    weak_nb = sum(1 for o in neighbors if my_mil > 1.5 * perceived_power(g, fid, o))
    allies = sum(1 for o in alive if o != fid and D.allied(g, fid, o))
    wars = len(D.enemies(g, fid))
    # 정복: 2/3 목표 대비 진척
    c_prog = len(regs) / max(1, len(g.regions)) / C.CONQUEST_SHARE
    # 경제(기축통화): 진척 단계, 수도 주변 은행, 우호 선언 이상 관계, 모아 둔 돈
    e_stage = g.econ_stage(fid)
    near = g.near_capital(fid, 2)
    hi_banks = sum(1 for r in regs if r.id in near and r.b["bank"] >= 4)
    partners, _ = D.econ_partners(g, fid)
    rich = min(1.0, f.money / 3_000_000)
    # 과학: 완료 단계, 다음 단계 비용을 감당할 재정, 필요한 땅(석유·공장 5단계·해안·산맥)
    k_done = len(f.science)
    step = g.science_next(fid)
    afford = step is not None and f.money > 0.5 * g.science_step_cost(fid, step)
    has_oil = any(g.info(r.id).is_oil for r in regs)
    has_f5 = any(r.b["factory"] >= 5 for r in regs) + any(r.b["bank"] >= 5 for r in regs)   # 예산 편성은 은행 5단계
    has_coast = any(g.info(r.id).coastal for r in regs)
    has_mtn = any(r.id in g.world.mountain_regions for r in regs)
    # 외교: 내 연합이 살아 있는 세력 중 차지하는 비율
    cid = D.coalition_of(g, fid)
    c_frac = len(g.dip.coalitions[cid]["members"] & set(alive)) / n if cid is not None else 0.0
    can_ally = not g.mods(fid).value("no_alliance")
    # 시간: 남은 턴이 적을수록, 점수 1위일수록
    max_t = getattr(g.settings, "max_turns", C.TIME_VICTORY_TURNS)
    t_prog = g.turn / max(1, max_t)
    sc = g.time_scores()
    top = max(sc, key=sc.get) == fid if sc else False
    score = {
        # 전쟁 피로가 쌓였으면 정복을 덜 노린다
        "conquest": (0.05 + 0.05 * aggr + 0.3 * my_mil / top_mil + 0.08 * min(2, weak_nb) + 0.5 * min(1.0, c_prog)
                     - 0.004 * f.war_weary - 0.05 * wars * (allies == 0)) * leader_bias(g, fid, "war"),
        "economic": (0.05 + 0.03 * (10 - aggr) + 0.12 * e_stage + 0.03 * min(5, hi_banks)
                     + 0.04 * min(3, partners) + 0.15 * rich) * leader_bias(g, fid, "bank"),
        "science": (0.05 + 0.03 * (10 - aggr) + 0.12 * k_done + (0.15 if afford else 0)
                    + 0.1 * has_oil + 0.05 * has_f5 + 0.03 * (has_coast + has_mtn)) * leader_bias(g, fid, "science"),
        "diplomatic": ((0.05 + 0.03 * (10 - aggr) + 0.6 * c_frac + 0.04 * min(4, allies))
                       * leader_bias(g, fid, "ally") if can_ally else -1.0),
        "time": 0.3 + (0.4 * t_prog if top else 0.1 * t_prog),
    }
    return max(vt, key=lambda v: score[v] + g.rng.uniform(0, 0.25))


def set_strategy(g, f):
    a = f.aggression
    w = {"military": 0.4 + a / 10, "economy": 1.4 - a / 25, "expansion": 1.2, "defense": 0.6}
    if "victory_goal" not in f.ai or g.turn - f.ai.get("goal_turn", -999) >= C.TURNS_PER_YEAR:
        f.ai["victory_goal"] = choose_victory_goal(g, f)
        f.ai["goal_turn"] = g.turn
    goal = f.ai["victory_goal"]
    # 목표는 약한 가중치만: 맹목적으로 그 조건만 좇지 않는다
    k = C.AI_GOAL_WEIGHT
    if goal == "conquest":
        w["military"] += k
        w["expansion"] += k / 2
    elif goal == "economic":
        w["economy"] += 2 * k
        w["expansion"] += k / 4
        w["military"] = max(0.2, w["military"] - k / 2)
    elif goal == "science":
        w["economy"] += k
    elif goal == "diplomatic":
        w["defense"] += k / 2
        w["military"] -= k / 2
    elif goal == "time":
        w["economy"] += k / 2
        w["expansion"] += k / 2
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
    _science_orders(g, f)
    _naval_orders(g, f, threat)
    _air_orders(g, f, threat)
    _slots(g, f, threat)
    # 슬롯이 비는 지역: 인구가 상한에 한참 못 미치고 민심·식량에 여유가 있으면 인구 성장 집중,
    # 아니면 생산 집중(둘 다 건설·생산 중엔 효과 없음)
    food_ok = f.last.get("food_prod", 0) >= f.last.get("food_cons", 0) * 1.05 or f.res.get("food", 0) > \
        f.last.get("food_cons", 1) * 8
    for r in g.regions_of(fid):
        # 과밀(−2) 문턱 아래에서만 키운다
        grow = food_ok and g.growth_happy(r) >= C.POP_FOCUS_MIN_H + 3 and r.pop < g.crowd_thresholds(r.id)[0]
        r.pop_focus, r.focus = grow, not grow


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
    if D.enemies(g, f.id) and f.money > 10000:
        need_oil = 8                      # 전쟁 중: 함선·항공기 생산용 석유
    # 에너지 자원은 돈으로 살 수 없다: 넉넉할 때만 판다(공장·발전소 몫은 남긴다)
    for res, keep in (("coal", 40), ("elec", 30)):
        if f.res.get(res, 0) > keep * 2:
            g.market_sell(f.id, res, f.res[res] - keep)
    cons = f.last.get("food_cons", 0)
    if cons and f.res.get("food", 0) > cons * 30:
        g.market_sell(f.id, "food", f.res["food"] - cons * 20)
    if f.res.get("oil", 0) > 80 + need_oil:
        g.market_sell(f.id, "oil", f.res["oil"] - 60)


def _tax(g, f):
    """행복도와 재정으로 세율을 유연하게 조절한다.
    - 재정이 빠듯하면(적자·비축 부족) 행복도가 버티는 한 올린다.
    - 행복도가 낮거나(산출 감소·반란) 비축이 넉넉하면 내린다(행복도 10 이상이어야 인구가 는다).
    - 상한은 호전성·전쟁 여부·지도자 세율 상한에 따라 12~20%, 하한 5%."""
    regs = g.regions_of(f.id)
    if not regs:
        return
    # 실질 행복도(전쟁 피로·징집 피로 반영). 점령 직후 지역(저항·회복, 36턴 반란 없음)은 세율로 달라지지 않으니 뺀다
    calm = [r for r in regs if not g.resist_phase(r)[0]] or regs
    hs = [g.eff_happy(r) for r in calm]
    avg = sum(hs) / len(hs)
    worst = min(hs)
    last = f.last
    net = last.get("net", 0.0)
    spend = sum(r.project.per_turn for r in regs if r.project and r.project.kind not in ("science", "econ"))
    reserve = 300 + g.upkeep(f.id) * 5 + spend * 3
    at_war = bool(D.enemies(g, f.id))
    hi = 0.12 + 0.005 * max(0.0, eff_aggression(g, f) - 5) + (0.03 if at_war else 0.0)
    if f.ai.get("victory_goal") == "economic":
        hi += C.AI_ECON_TAX_BONUS                    # 경제승리를 노리면 돈을 더 거둔다
    hi = min(g.tax_max(f.id), hi, 0.20)
    # 비축이 아주 넉넉한데 실질 행복도가 낮으면(전쟁 피로 등) 세율을 0%까지 내려 민심을 산다
    lo = 0.0 if f.money > reserve * 20 and avg < 0 else 0.05
    t = f.tax
    if worst < -45 or avg < -20:
        t -= 0.02                                   # 반란 위험
    elif avg < -8:
        t -= 0.01
    elif (net < 0 and f.money < reserve) or f.money < 0:
        t += 0.02 if f.money < 0 else 0.01         # 재정 위기: 올린다
    elif f.money > reserve * 4 and avg < 12:
        t -= 0.01                                   # 넉넉하면 민심(인구 성장)에 투자
    elif f.money < reserve * 1.5 and avg > 5:
        t += 0.01                                   # 비축이 얇고 민심에 여유
    elif avg > 25:
        t += 0.01
    t = max(lo, min(hi, t))
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
    thr += C.VICTORY_THREAT_WAR * g.victory_threat(target)       # 과학·경제 승리에 가까운 나라 견제
    if ratio > 1:
        thr += min(C.AI_WAR_OP_TEMPT_MAX, aggr * math.log2(ratio))
    if not can_expand and aggr >= 4:
        thr += C.AI_WAR_OP_NEED
    if f.ai.get("victory_goal") == "conquest":
        thr += 5
    elif f.ai.get("victory_goal") == "diplomatic":
        thr -= 8                           # 외교승리를 노리면 전쟁을 꺼린다
    elif f.ai.get("victory_goal") == "economic":
        thr -= 4                           # 경제승리는 우호 관계가 필요하다
    thr += 30 * (leader_bias(g, f.id, "war") - 1)        # 지도자 성향: 전쟁에 유리하면 ±4.5까지
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
    # 사기(실질 평균 행복도 −10 이하면 전투력 감소)까지 반영한 전력
    my = g.mil_power(fid) * g.morale(fid) + 0.5 * sum(
        g.mil_power(x) * g.morale(x) for x in alive if x not in (fid, e) and D.at_war(g, x, e) and D.allied(g, x, fid))
    their = perceived_power(g, fid, e) * g.morale(e) + 0.5 * sum(
        perceived_power(g, fid, x) for x in alive if x not in (fid, e) and D.at_war(g, x, fid) and D.allied(g, x, e))
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
    if f.war_weary > 20:
        d += 0.006 * (f.war_weary - 20)        # 전쟁 피로도는 평화가 와야 줄어든다
        if f.war_weary > 50:
            pro.append(f"전쟁 피로 {f.war_weary:.0f}")
    if avg_h < -40:
        d += 0.4                               # 반란이 코앞
        pro.append("반란 위기")
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
    if f.ai.get("victory_goal") == "diplomatic":
        d += 0.15                          # 외교승리를 노리면 강화에 적극적
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
    _social(g, f)
    _consider_war(g, f)


def _social(g, f):
    """우호 선언·비난. 온건할수록 우호 선언을, 호전적일수록 비난을 자주 쓴다."""
    fid = f.id
    aggr = eff_aggression(g, f)
    alive = [x for x in g.alive_ids() if x != fid]
    # 우호 선언: 나를 좋게 보는(또는 적의 적인) 세력과 가까워진다
    p_friend = C.AI_FRIEND_DECL_P * (10 - aggr) / 10 * leader_bias(g, fid, "ally")
    if f.ai.get("victory_goal") in ("diplomatic", "economic"):
        p_friend *= 1.5                    # 외교·경제승리는 우호 관계가 필요하다
    if alive and g.rng.random() < p_friend:
        my_enemies = set(D.enemies(g, fid))
        cands = []
        for x in alive:
            ok, _ = D.friendship_check(g, fid, x)
            if not ok or D.opinion(g, fid, x) < 0:
                continue
            # 선언하면 x 와 적대하는 세력이 나를 싫어하게 된다(−5): 그 손실을 따진다
            cost = sum(1 for y in alive if y != x and g.factions[y].is_ai and D.hostile_to(g, y, x)
                       and not D.at_war(g, fid, y))
            score = D.opinion(g, fid, x) / 20 + len(my_enemies & set(D.enemies(g, x))) - C.AI_FRIEND_BACKLASH_W * cost
            if D.allied(g, fid, x):
                score -= 0.5                 # 이미 동맹이면 덜 급하다
            cands.append((score, x))
        if cands:
            score, x = max(cands)
            if score > 0:
                if g.factions[x].is_ai:
                    D.declare_friendship(g, fid, x)
                else:
                    _queue_player(g, fid, "friendship")
    # 비난: 전쟁 중이거나 몹시 미운 세력. 남발(24턴 안 3번째)은 손해라 2번까지만
    if D.recent_denounces(g, fid) >= C.DENOUNCE_SPAM_N - 1:
        return
    p_den = C.AI_DENOUNCE_P * aggr / 10
    if not alive or g.rng.random() >= p_den:
        return
    cands = []
    for x in alive:
        if not D.denounce_check(g, fid, x)[0] or not D.hostile_to(g, fid, x):
            continue
        if not g.factions[x].is_ai and g.rng.random() >= C.AI_DENOUNCE_PLAYER:
            continue                         # 플레이어는 낮은 확률로만
        score = -D.opinion(g, fid, x) / 30 + (1.0 if D.at_war(g, fid, x) else 0) + (0.8 if g.hegemon == x else 0)
        # 비난에 동조할(대상과 적대하는) 세력이 많을수록 이득
        score += 0.3 * sum(1 for y in alive if y != x and g.factions[y].is_ai and D.hostile_to(g, y, x))
        cands.append((score, x))
    if cands:
        D.denounce(g, fid, max(cands)[1])


def _consider_war(g, f):
    """선전포고: 우호도가 호전성별 문턱 아래인 이웃 중, 보이는 전력·돌파 지점·얻을 가치를 따져 결정."""
    fid = f.id
    my_enemies = D.enemies(g, fid)
    if g.turn <= C.AI_WAR_GRACE_TURNS or len(my_enemies) >= C.AI_MAX_WARS:
        return
    regs = g.regions_of(fid)
    avg_h = g.avg_happiness(fid)              # 실질 행복도(전쟁 피로 반영)
    if not regs or f.money < 0 or avg_h < -20 or f.war_weary > 45:
        return
    alive = g.alive_ids()
    aggr = eff_aggression(g, f)
    # 선포하면 전쟁 피로 +15, 전쟁 중 턴당 +0.5: 약 20턴 전쟁 뒤의 실질 행복도를 내다본다
    start_w = C.WAR_WEARY_START["aggressor"] * g.mods(fid).mult("war_start_weary")
    already = any(w.get("aggressor") == fid for p, w in g.dip.wars.items() if fid in p)   # 이미 선포국 증가율
    proj_h = avg_h - start_w - (0 if already else 20 * C.WAR_WEARY_TURN["aggressor"]
                                * g.mods(fid).mult("war_weary_rate"))
    # 전쟁광 평판: 다른 세력 우호도가 깎인다(1년 안에 잇따라 선포하면 더). 조약·우호 관계가 많을수록 아깝다
    rep_pen = -D.warmonger_penalty(g, fid)
    ties = sum(1 for x in alive if x != fid and (D.is_friend(g, fid, x) or D.has_nonaggr(g, fid, x)))
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
    my_total = g.mil_power(fid) * g.morale(fid) * (1 - 0.35 * len(my_enemies))    # 다른 전선에 묶인 병력 제외
    best, best_s, best_goals = None, 1.0, []
    for o in sorted(neighbors):
        if D.has_nonaggr(g, fid, o) or D.at_war(g, fid, o) or D.peace_left(g, fid, o) > 0:
            continue
        their = perceived_power(g, fid, o) * g.morale(o) + sum(perceived_power(g, fid, x) for x in alive
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
        # 빼앗은 땅은 저항(산출 없음) 뒤 회복 기간을 거치므로 값어치를 깎아 본다
        prize = _resist_discount() * (sum(g.region_value(n)[0] for n in fr["targets"]) + 0.3 * sum(
            g.region_value(n)[0] for n in fr["border"] if n not in fr["targets"]))
        s = (aggr / 10) * min(2.5, ratio) * (0.5 + min(1.5, prize / 15))
        s += (thr - op) / 40                               # 문턱보다 얼마나 더 미운가
        if not can_expand:
            s += 0.3                                        # 평화적으로 넓힐 땅이 없다
        s -= 0.5 * len(my_enemies)
        if avg_h < 0:
            s -= 0.3
        if proj_h < -15:
            s -= min(1.2, (-15 - proj_h) / 40)              # 전쟁 피로로 민심이 무너질 전망
        s -= (rep_pen - 10) / 25 + 0.03 * ties * rep_pen / 10   # 전쟁광 평판
        if g.hegemon == o:
            s += min(C.HEGEMON_WAR_MAX, C.HEGEMON_WAR_K * (g.hegemon_share - C.HEGEMON_SHARE))
        s += C.VICTORY_THREAT_SCORE * g.victory_threat(o)
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
                     and a.loc not in threat and not g.is_science_army(a)], key=lambda a: -a.count()):
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
        if a.owner == fid and not a.order and a.domain() == "land" and not g.world.is_sea(a.loc) \
                and not g.is_science_army(a):
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
              and not w.is_sea(a.loc) and not g.is_science_army(a)]
    front = set(threat)
    crisis = _war_crisis(g, fid, threat)
    cap_min = capital_min_garrison(g, f, threat)
    for a in armies:
        if a.id not in g.armies:
            continue
        rr = g.regions[a.loc]
        # 수도 방위군: 최소 병력은 수도에 남긴다(넘는 병력만 움직인다)
        if a.loc == f.capital:
            others = sum(x.count(("land",)) for x in g.armies_at(a.loc, fid)
                         if x.id != a.id and x.domain() == "land")
            keep = max(0, cap_min - others)
            if keep >= a.count():
                continue
            if keep > 0:
                stay = {}
                for k in ("inf", "art", "tank"):
                    t = min(a.units.get(k, 0), keep - sum(stay.values()))
                    if t > 0:
                        stay[k] = t
                g.split_army(a.id, stay)
        # 중립 땅 점령은 평시이거나, 전쟁 중이라도 위기가 아니고 작은 부대(2개 이하)일 때만.
        # 나라가 위태로운데 큰 부대가 중립 땅에 묶여 있지 않도록 한다.
        neutral_ok = not crisis and (not at_war or a.count() <= 2)
        # 점령 중이면 자리를 지킨다(중립 땅인데 지금은 그럴 때가 아니면 점령을 버리고 전선으로)
        if fid in rr.occs and (rr.owner != NEUTRAL or neutral_ok):
            continue
        # 저항 중인 점령지: 옛 주인이 맞닿아 있고 아직 전쟁 중이면 작은 부대는 남아 지킨다(비우면 바로 탈환된다)
        if rr.owner == fid and g.resisting(rr) and a.count() <= 3:
            old = rr.resist.get("from")
            if old is not None and D.at_war(g, fid, old) and any(
                    g.regions[n].owner == old for n in w.land_adj[a.loc]):
                continue
        reach = g.reachable(a)
        best, best_u, best_mode = None, 0.0, "assault"
        for node, opt in reach.items():
            if opt["action"] != "attack" or w.is_sea(node):
                continue
            tgt = g.regions[node]
            if tgt.owner == NEUTRAL:
                if node in annexing or not neutral_ok:
                    continue
                if wts.get("military", 1) < 0.9 and a.count() < 3:
                    continue
            for mode in (("assault",) if g.mods(fid).value("no_surprise") else ("assault", "surprise")):
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
                # 적 지역은 빼앗아도 저항·회복을 거쳐 이득이 늦다(중립 지역은 바로)
                horizon = 24 if tgt.owner == NEUTRAL else 24 - C.RESIST_TURNS - 0.2 * C.RESIST_RECOVER_TURNS
                cap_val = g.region_output_estimate(node) * tax * horizon if kill else 0
                u = enemy_val - own_val + cap_val
                if mode == "assault" and pv["line"] > 0 and dd > ad:
                    u += C.ASSAULT_LINE_BREAK * 400 * pv["line"]   # 방어선을 무너뜨릴 수 있다
                if tgt.owner == NEUTRAL and not kill:
                    u = -1
                elif u > 0:
                    u *= leader_bias(g, fid, mode)          # 지도자 성향: 돌격/기습
                if u > best_u:
                    best, best_u, best_mode = node, u, mode
        if best:
            g.order_army(a.id, best, best_mode)
            continue
        # 육군 공격이 불리하면 들이받지 않고 포병으로 먼저 깎는다(선제 폭격)
        if a.units.get("art") and at_war:
            strong = [n for n, o in reach.items() if o["action"] == "attack" and not w.is_sea(n)
                      and g.regions[n].owner != NEUTRAL and g.hostile_units_at(fid, n)]
            if strong and g._can_bombard(a, strong[0]):
                strong.sort(key=lambda n: -visible_hostile_power(g, fid, n))
                g.order_army(a.id, strong[0], force_bombard=True)
                continue
        # 빈 적지·중립지 점령
        for node, opt in reach.items():
            if opt["action"] == "move" and not w.is_sea(node) and g.hostile(fid, g.regions[node].owner) \
                    and node not in annexing and (neutral_ok or g.regions[node].owner != NEUTRAL):
                g.order_army(a.id, node)
                break
        if a.order:
            continue
        # 포병 폭격: 적 병력을 우선, 없으면 건물이 많은 적 지역(30% 확률로 생산·방어 건물 −1단계)
        if a.units.get("art") and at_war:
            tgts = [n for n, o in reach.items() if o["action"] in ("bombard", "attack")
                    and g.regions[n].owner != NEUTRAL and g.hostile(fid, g.regions[n].owner)]
            if tgts:
                tgts.sort(key=lambda n: (-bool(g.hostile_units_at(fid, n)), -_building_levels(g, n)))
                if g.hostile_units_at(fid, tgts[0]) or _building_levels(g, tgts[0]) > 0:
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
        if not a.order and rr.owner == NEUTRAL and not neutral_ok:
            # 전선이 안 보여도 중립 땅에 머물지 말고 수도 쪽 내 영토로 돌아온다
            home = [n for n, o in reach.items() if o["action"] == "move" and g.regions.get(n)
                    and g.regions[n].owner == fid]
            if home:
                cap = f.capital
                home.sort(key=lambda n: (w.distances_from(n, 30).get(cap, 99), n))
                g.order_army(a.id, home[0])
    # 폭격기
    for a in g.armies.values():
        if a.owner != fid or a.domain() != "air" or not at_war:
            continue
        reach = g.reachable(a)
        tg = [(visible_hostile_power(g, fid, n) + 2 * _building_levels(g, n), n) for n, o in reach.items()
              if o["action"] == "bombard" and g.regions[n].owner != NEUTRAL]
        tg.sort(reverse=True)
        if tg and tg[0][0] > 0:
            g.order_army(a.id, tg[0][1], force_bombard=True)


def econ_saving_target(g, fid) -> float:
    """경제승리 목표일 때 모아 둘 돈: 다음에 지을 경제 단계(경제특구·국제금융센터·기축통화) 총비용의 1.1배."""
    st = g.econ_stage(fid)
    if st < 2 or st >= C.ECON_STAGES:
        return 0.0
    step = C.ECON_STEPS[st - 1]
    if g.econ_busy(fid, step) is not None:
        return 0.0
    spec = C.ECON[step]
    return spec["per_turn"] * C.MONEY_SCALE * spec["turns"] * 1.1


def finance_plan(g, fid) -> set:
    """금융 권역 계획: 수도에서 시작해 맞닿은 자국 지역을 은행이 높은(같으면 인구가 많은) 곳부터 붙여 5곳."""
    cap = g.factions[fid].capital
    if g.regions[cap].owner != fid:
        return set()
    plan = {cap}
    while len(plan) < C.ECON_CLUSTER:
        front = {v for u in plan for v in g.world.land_adj[u] if v not in plan and g.regions[v].owner == fid}
        if not front:
            break
        plan.add(max(front, key=lambda v: (g.regions[v].b["bank"], g.regions[v].pop, v)))
    return plan


def _econ_orders(g, f, regs, idle, cands, threat, income, upkeep, bias):
    """경제승리(기축통화) 단계 착수와 금융 권역 은행 건설. 목표면 조건을 낮추고, 그 밖엔 재정이 아주 넉넉할 때만."""
    fid = f.id
    if not f.is_ai or not g.econ_enabled():
        return
    goal = f.ai.get("victory_goal") == "economic"
    sm, si = ((2.0, 0.3) if goal else (4, 0.6))
    sm, si = sm / bias("bank"), si / bias("bank")
    cap = f.capital
    ex = g.econ_buildings(fid, "exchange")
    ex_busy = [r.id for r in regs if r.project and r.project.kind == "econ" and r.project.key == "exchange"]
    for step in reversed(g.econ_available(fid)):        # 뒤 단계부터: 증권거래소만 계속 짓지 않게
        if step != "exchange" and g.econ_busy(fid, step) is not None:
            continue
        if step == "exchange" and len(ex) + len(ex_busy) >= C.ECON_EXCHANGES and (cap in ex or cap in ex_busy):
            continue                                  # 경제특구 조건(수도 포함 3곳)만큼만
        spec = C.ECON[step]
        per = spec["per_turn"] * C.MONEY_SCALE
        if not ((f.money > per * sm and income - upkeep > per * si)
                or f.money > per * spec["turns"] * (1.1 if goal else 2.5)):
            continue
        sites = [r for r in regs if g.econ_site_ok(fid, r.id, step) and not r.project and not r.occ
                 and not g.resisting(r)]
        if step == "exchange" and cap not in ex and cap not in ex_busy:
            sites = [r for r in sites if r.id == cap] or ([] if len(ex) + len(ex_busy) >= C.ECON_EXCHANGES - 1 else sites)
        if sites:
            best = min(sites, key=lambda r: (threat.get(r.id, 0), -r.pop))
            if g.start_project(fid, best.id, "econ", step)[0]:
                break                                 # 큰 공사는 한 턴에 하나씩
    if goal and len(g.finance_cluster(fid)) < C.ECON_CLUSTER:
        plan = finance_plan(g, fid)
        pool = [r for r in idle if r.id in plan and r.b["bank"] < 5]
        for r0 in sorted(pool, key=lambda r: -r.b["bank"])[:2]:
            lv = r0.b["bank"] + 1
            cost = R.prod_building_cost("bank", lv)
            turns = g.build_time(fid, "bank", R.prod_building_turns(lv))
            cands.append((3.0, r0.id, "build", "bank", None, cost / turns))


def _resist_discount():
    """빼앗은 적 지역의 값어치 배수: 저항 턴 + 회복 턴의 절반만큼 산출을 잃는다고 보고 72턴(편입 이득 기간의 2배) 기준으로 할인."""
    return 1 - (C.RESIST_TURNS + C.RESIST_RECOVER_TURNS / 2) / (2 * C.AI_ANNEX_HORIZON)


def _building_levels(g, rid):
    """폭격으로 부술 수 있는 건물 단계 합(생산·방어 건물·방어선)."""
    rr = g.regions[rid]
    return sum(rr.b.get(k, 0) for k in list(C.PROD_BUILDINGS) + ["shelter", "aa"]) + sum(rr.lines.values())


def capital_min_garrison(g, f, threat) -> int:
    """수도에 늘 남겨 둘 최소 육군 수: 2 + 영토 20곳당 1, 적대 이웃과 맞닿았으면 +2, 위협이 크면 +2."""
    cap = f.capital
    if cap not in g.regions or g.regions[cap].owner != f.id:
        return 0
    n = 2 + g.region_count(f.id) // 20
    for m in g.world.land_adj[cap]:
        o = g.regions[m].owner
        if o not in (NEUTRAL, f.id) and (D.at_war(g, f.id, o) or D.opinion(g, f.id, o) <= C.AI_DEF_OP):
            n += 2
            break
    if threat.get(cap, 0) >= 1.0:
        n += 2
    return n


def _sea_targets(g, fid):
    """우리 해안이 닿은 해역(과 그 옆 해역)의 적(전쟁 중) 해안 지역, 그중 항구가 있는 곳, 적과 육로로 맞닿았는지."""
    w = g.world
    enemies = set(D.enemies(g, fid))
    seas = {s for r in g.regions_of(fid) if w.regions[r.id].coastal for s in w.regions[r.id].seas}
    seas |= {s2 for s in list(seas) for s2 in w.seas[s].adj}
    tgts = sorted({v for s in seas for v in w.seas[s].coast if g.regions[v].owner in enemies})
    ports = [v for v in tgts if g.regions[v].b["port"]]
    contact = any(g.regions[n].owner in enemies for r in g.regions_of(fid) for n in w.land_adj[r.id])
    return tgts, ports, contact


def _naval_orders(g, f, threat):
    """함대: 상륙함은 항구에서 병력을 태워 적 해안(항구 우선)에 상륙, 구축함은 적 항구를 먼저 포격, 빈 상륙함은 귀항."""
    fid = f.id
    w = g.world
    if not D.enemies(g, fid):
        return
    cap_min = capital_min_garrison(g, f, threat)
    for fl in [a for a in list(g.armies.values()) if a.owner == fid and a.domain() == "naval"]:
        if fl.id not in g.armies or fl.order:
            continue
        at_port = not w.is_sea(fl.loc)
        if fl.units.get("lst") and at_port:
            # 태우기: 같은 항구의 육군(수도 방위군은 남김)
            for la in [a for a in g.armies_at(fl.loc, fid) if a.domain() == "land" and not a.order]:
                room = fl.cargo_cap() - fl.cargo_used()
                if room <= 0:
                    break
                keep = cap_min if fl.loc == f.capital else 0
                take = {}
                for k in ("tank", "inf", "art"):
                    per = C.UNITS[k].get("cargo", 1)
                    n = min(la.units.get(k, 0) - (keep if k == "inf" else 0), (room - sum(
                        C.UNITS[x]["cargo"] * v for x, v in take.items())) // per)
                    if n > 0:
                        take[k] = n
                if not take:
                    continue
                if sum(take.values()) >= la.count():
                    g.merge_armies(fl.id, la.id)
                else:
                    b, _ = g.split_army(la.id, take)
                    if b:
                        g.merge_armies(fl.id, b.id)
        reach = g.reachable(fl)
        cargo = fl.count(("land",))
        if fl.units.get("lst") and at_port and cargo < 3:
            # 태울 병력 부르기: 근처(이번 턴에 올 수 있는) 대기 육군 하나를 항구로
            for la in sorted([a for a in g.armies.values() if a.owner == fid and a.domain() == "land"
                              and not w.is_sea(a.loc) and a.loc != fl.loc and a.count() >= 2
                              and a.loc != f.capital and a.loc not in threat], key=lambda a: -a.count()):
                if la.order and la.order.get("type") == "attack":
                    continue
                if g.reachable(la).get(fl.loc, {}).get("action") == "move":
                    g.order_army(la.id, fl.loc)
                    break
            continue
        if fl.units.get("lst") and cargo >= 3:
            best, best_s = None, 0.0
            for v, o in reach.items():
                if o["action"] != "attack" or w.is_sea(v):
                    continue
                rr = g.regions[v]
                s_ = g.region_value(v)[0] + (4 if rr.b["port"] else 0)        # 항구가 있는 곳을 우선
                defs = g.hostile_units_at(fid, v)
                if defs:
                    pv = g.preview_attack(fl, v, "assault")
                    if not pv or pv["def_dmg"] < pv["def_hp"] * 0.95 or pv["att_dmg"] > pv["def_dmg"]:
                        continue
                    s_ -= 2
                if s_ > best_s:
                    best, best_s = v, s_
            if best:
                g.order_army(fl.id, best, "assault")
                continue
        if fl.units.get("dd") and not at_port:
            bt = [v for v, o in reach.items() if o["action"] == "bombard"]
            if bt:
                bt.sort(key=lambda v: (-g.regions[v].b["port"], -visible_hostile_power(g, fid, v)))
                g.order_army(fl.id, bt[0], force_bombard=True)
                continue
        if fl.units.get("dd") and at_port:
            _, ports, _ = _sea_targets(g, fid)
            seas = [v for v, o in reach.items() if o["action"] == "move" and w.is_sea(v)
                    and any(p in w.seas[v].coast for p in ports)]
            if seas:
                g.order_army(fl.id, seas[0])
                continue
        if not at_port and (cargo == 0 or not fl.units.get("lst")):
            home = [v for v, o in reach.items() if o["action"] == "move" and not w.is_sea(v)]
            if home:
                g.order_army(fl.id, home[0])


def _science_orders(g, f):
    """과학승리 유닛: 발사대 지역으로 모은다(발사대가 여럿이면 유닛들에서 가장 가까운 곳)."""
    fid = f.id
    sci = [a for a in g.armies.values() if a.owner == fid and g.is_science_army(a) and not g.world.is_sea(a.loc)]
    if not sci:
        return
    pads = [r.id for r in g.regions_of(fid) if "pad" in r.sci]
    if not pads:
        return
    w = g.world

    def total_dist(p):
        d = w.distances_from(p, 30)
        return sum(d.get(a.loc, 99) for a in sci)
    pad = min(pads, key=total_dist)
    for a in sci:
        if a.loc == pad or a.goto == pad:
            continue
        g.order_army(a.id, pad)


def _air_orders(g, f, threat):
    """전투기: 위협이 가장 큰 곳에서 가까운 자국 공항으로 옮겨 지상전을 지원한다."""
    fid = f.id
    if not threat:
        return
    hot = max(threat, key=threat.get)
    for a in [a for a in g.armies.values() if a.owner == fid and a.domain() == "air" and not a.order
              and a.units.get("ftr") and not a.units.get("bmb")]:
        reach = g.reachable(a)
        bases = [v for v, o in reach.items() if o["action"] == "move"]
        if not bases:
            continue
        d_now = g.world.distances_from(hot, 6).get(a.loc, 99)
        best = min(bases, key=lambda v: g.world.distances_from(hot, 6).get(v, 99))
        if g.world.distances_from(hot, 6).get(best, 99) < d_now:
            g.order_army(a.id, best)


def _war_crisis(g, fid, threat) -> bool:
    """전쟁 중 위기: 적이 내 땅을 점령 중이거나, 이번 전쟁에서 땅을 잃었거나, 위협도 1 이상인 지역이 있다."""
    enemies = D.enemies(g, fid)
    if not enemies:
        return False
    if any(by != fid for r in g.regions_of(fid) for by in r.occs):
        return True
    if any(D.war_info(g, fid, e).get("lost", 0) > 0 for e in enemies):
        return True
    return any(v >= 1.0 for v in threat.values())


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


def fuel_balance(g, fid) -> dict:
    """턴당 공장 연료 수급 추정(채굴만, 재고 제외): supply 공장에 넣을 수 있는 연료, demand 공장 단계 합,
    spare = supply − demand, plant_room 남는 발전소 용량, raw_left 발전소에 못 넣은 석탄·석유."""
    mined = g.energy_mined(fid)
    plants, facts = g.energy_sites(fid)
    cap = sum(r.b["power"] for r in plants)
    conv_oil = min(cap, mined["oil"])
    conv_coal = min(cap - conv_oil, mined["coal"])
    supply = (mined["elec"] + C.POWER_ELEC["oil"] * conv_oil + C.POWER_ELEC["coal"] * conv_coal
              + (mined["coal"] - conv_coal) + (mined["oil"] - conv_oil))
    demand = sum(r.b["factory"] for r in facts)
    return {"supply": supply, "demand": demand, "spare": supply - demand,
            "plant_room": cap - conv_oil - conv_coal, "raw_left": mined["coal"] - conv_coal + mined["oil"] - conv_oil}


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
    old = R.region_output(rr.pop, b["farm"], b["fishery"], b["factory"], b["bank"])
    b[key] += 1
    new = R.region_output(rr.pop, b["farm"], b["fishery"], b["factory"], b["bank"])
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
    committed = sum(r.project.per_turn for r in regs if r.project and r.project.kind not in ("science", "econ"))
    reserve = 200 + upkeep * 3
    avail = (income - upkeep) * 0.95 + max(0.0, f.money - reserve) / 5 - committed
    eco = f.is_ai and f.ai.get("victory_goal") == "economic" and g.econ_enabled()
    if eco:
        save = econ_saving_target(g, fid)
        if save and f.money < save:
            # 다음 경제 단계 비용을 모으는 중: 비축은 헐지 않고 순수입의 절반만 다른 공사에 쓴다
            avail = min(avail, (income - upkeep) * C.AI_ECON_SAVE_SPEND - committed)
    food_bal = f.last.get("food_prod", 0) - f.last.get("food_cons", 0)
    food_short = food_bal < 0 or f.res.get("food", 0) < f.last.get("food_cons", 1) * 2
    at_war = bool(D.enemies(g, fid))
    idle = [r for r in regs if not r.project and not r.occ and not g.resisting(r) and (f.is_ai or not (r.focus or getattr(r, "pop_focus", False)))]
    fuel = fuel_balance(g, fid)
    unit_val = 1300 * tax                     # 공장 연료 1개가 턴당 버는 세수(대략)
    cands = []
    bias = (lambda a: leader_bias(g, fid, a)) if f.is_ai else (lambda a: 1.0)
    annex_bias = bias("annex")
    if g.mods(fid).value("minority_rule") and len(regs) >= C.MINORITY_REGIONS:
        annex_bias *= 0.85                    # 홍타이지 '소수민족': 넓힐수록 민심이 깎인다
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
            if t.get("rival_left") is not None and t["rival_left"] < t["eff_turns"]:
                continue                  # 다른 세력이 먼저 끝낼 곳은 경쟁하지 않는다
            tr = g.regions[t["target"]]
            y = g.region_output_estimate(t["target"])
            food = R.food_output(tr.b["farm"], tr.b["fishery"])
            per_turn = y * tax + food * C.MARKET_BUY["food"] * (1.0 if food_short else 0.15)
            # 완공까지 슬롯이 묶이고 이득은 그 뒤부터: 가치가 높은(오래 걸리는) 지역일수록 할인
            gain = per_turn * max(0, C.AI_ANNEX_HORIZON - t["eff_turns"]) * wts.get("expansion", 1)
            if t["joint"]:   # 거드는 몫은 앞당겨지는 턴만큼만
                gain *= (t["turns"] - t["eff_turns"]) / max(1, t["turns"])
            gain *= annex_bias
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
                dfood = C.FOOD_PER_G                       # 농장·어장은 단계마다 같은 양
                gain += dfood * C.MARKET_BUY["food"] * horizon * (1.0 if food_short else 0.15)
            if key == "factory" and fuel["spare"] < 1:
                # 남는 연료가 없으면 새 칸은 놀고, 이미 들어가는 연료의 1개당 산출 상승분만 이득
                pu = C.FACTORY_UNIT_OUTPUT
                up = (pu[lv - 1] - pu[lv - 2]) * getattr(r, "fuel_used", 0) if lv >= 2 else 0
                gain = up * tax * horizon * wts.get("economy", 1)
            gain *= bias(key)
            if eco and key in ("factory", "bank"):
                gain *= C.AI_ECON_PROD_MULT
            cands.append((gain / cost, r.id, "build", key, None, cost / turns))
        if (info.is_oil or info.is_coal) and r.b["extract"] < 5:
            lv = r.b["extract"] + 1
            cost = R.prod_building_cost("extract", lv)
            turns = g.build_time(fid, "extract", R.prod_building_turns(lv))
            horizon = max(0, C.AI_UTILITY_HORIZON - turns)
            # 연료가 모자라면 1개 더 캐는 만큼 공장이 돈다(발전소가 남으면 석탄 1 → 전기 2), 남으면 판매가 정도
            per = (unit_val * (2 if fuel["plant_room"] > 0 else 1) if fuel["spare"] < 0
                   else C.MARKET_SELL["oil" if info.is_oil else "coal"])
            cands.append((per * horizon / cost * bias("extract") * (C.AI_ECON_FUEL_MULT if eco else 1.0),
                          r.id, "build", "extract", None, cost / turns))
        if r.b["power"] < 5 and fuel["spare"] < 0 and fuel["raw_left"] > 0:
            # 발전소: 공장 연료가 모자라고 발전소에 못 넣은 석탄·석유가 남을 때(석탄 1 → 공장 연료 2)
            lv = r.b["power"] + 1
            cost = R.prod_building_cost("power", lv, info.power_site)
            turns = g.build_time(fid, "power", R.prod_building_turns(lv))
            gain = unit_val * max(0, C.AI_UTILITY_HORIZON - turns)
            cands.append((gain / cost * bias("power") * (C.AI_ECON_FUEL_MULT if eco else 1.0),
                          r.id, "build", "power", None, cost / turns))
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
                    cands.append((th * wts.get("defense", 1) * 0.8 * bias("line"), r.id, "build", "line", n,
                                  cost / C.DEF_TURNS[lv - 1]))
                    break
    # 평시 방어 건설: 우호도가 낮은 이웃과 맞닿은 지역은 재정이 넉넉할수록 조금씩 더 자주 방어 건물을 올린다
    wealth = max(0.0, min(1.5, (f.money - reserve) / (max(0.0, income) * 20 + reserve * 4 + 1)))
    for r in idle:
        worst_op, worst_n = None, None
        for n in g.world.land_adj[r.id]:
            o = g.regions[n].owner
            if o in (NEUTRAL, fid) or D.at_war(g, fid, o):
                continue
            op = D.opinion(g, fid, o)
            if op <= C.AI_DEF_OP and (worst_op is None or op < worst_op):
                worst_op, worst_n = op, n
        if worst_n is None:
            continue
        hostility = min(2.0, 1 + (C.AI_DEF_OP - worst_op) / 60)
        p = (C.AI_DEF_BASE_P + C.AI_DEF_WEALTH_P * wealth) * hostility * bias("line")
        if g.rng.random() >= p:
            continue
        # 같은 단계라면 방어선 우선: (단계, 우선순위)가 가장 낮은 것
        opts = [(r.lines.get(worst_n, 0), 0, "line", worst_n), (r.b["shelter"], 1, "shelter", None),
                (r.b["aa"], 2, "aa", None)]
        lv, _, key, border = min(opts)
        if lv >= C.AI_DEF_MAX_LEVEL:
            continue
        cost = (R.def_building_cost(key, lv + 1) * (g.mods(fid).mult("cost_line") if key == "line" else 1))
        # 확률을 통과하면 그 지역 슬롯은 방어 건설이 차지한다(예산 안에서)
        cands.append((50 + hostility, r.id, "build", key, border, cost / C.DEF_TURNS[lv]))
    # 수도 방위: 최소 방위군과 방어 건물
    idle_ids = {r.id for r in idle}
    cap = g.regions.get(f.capital)
    if cap is not None and cap.owner == fid and f.capital in idle_ids:
        cap_min = capital_min_garrison(g, f, threat)
        garrison = sum(a.count(("land",)) for a in g.armies_at(f.capital, fid) if a.domain() == "land")
        if military and garrison < cap_min:
            cands.append((3.0 + threat.get(f.capital, 0), f.capital, "unit", "inf", None,
                          g.unit_cost(fid, f.capital, "inf")))
        else:
            for n in sorted(g.world.land_adj[f.capital]):
                o = g.regions[n].owner
                if o in (NEUTRAL, fid):
                    continue
                war = D.at_war(g, fid, o)
                lv = cap.lines.get(n, 0)
                top = 4 if war else (3 if D.opinion(g, fid, o) <= C.AI_DEF_OP else 1)
                if lv < top and (war or f.money > reserve * 2):
                    cost = R.def_building_cost("line", lv + 1) * g.mods(fid).mult("cost_line")
                    cands.append((55 if war else 51, f.capital, "build", "line", n, cost / C.DEF_TURNS[lv]))
                    break
    # 공군: 전쟁 중이거나 호전적이고 넉넉하면 공항 → 전투기(지상전 지원)·폭격기
    airports = [r for r in regs if r.b["airport"]]
    n_ftr = sum(a.units.get("ftr", 0) for a in g.armies.values() if a.owner == fid)
    n_bmb = sum(a.units.get("bmb", 0) for a in g.armies.values() if a.owner == fid)
    if military and (at_war or f.aggression >= 6) and f.money > 15000 and not airports and g.turn > 24:
        site = cap if (cap is not None and cap.owner == fid and f.capital in idle_ids) else None
        if site is None:
            pool_ap = sorted(idle, key=lambda r: -threat.get(r.id, 0) - r.pop / 100)
            site = pool_ap[0] if pool_ap else None
        if site is not None:
            cost = C.SINGLE_BUILDINGS["airport"]["cost"] * C.BUILD_COST_MULT
            cands.append((2.0 * bias("air"), site.id, "build", "airport", None,
                          cost / C.SINGLE_BUILDINGS["airport"]["turns"]))
    if military and at_war and airports:
        ap_idle = [r for r in airports if r.id in idle_ids]
        if ap_idle and g.can_pay_oil(fid, C.UNITS["ftr"]["oil"]) and f.money > 3000 and n_ftr < 2 + len(regs) // 25:
            r0 = ap_idle[0]
            cands.append((2.2 * bias("air"), r0.id, "unit", "ftr", None, g.unit_cost(fid, r0.id, "ftr")))
        elif ap_idle and g.can_pay_oil(fid, C.UNITS["bmb"]["oil"]) and f.money > 4000 and n_bmb < 1 + len(regs) // 40:
            r0 = ap_idle[0]
            cands.append((1.8 * bias("air"), r0.id, "unit", "bmb", None, g.unit_cost(fid, r0.id, "bmb")))
    # 해군: 육로로 불리하거나 닿지 않는 적 해안을 노린다(상륙함), 적 항구가 있으면 구축함
    if military and at_war:
        sea_t, enemy_ports, land_contact = _sea_targets(g, fid)
        ports_idle = [r for r in regs if r.b["port"] and r.id in idle_ids]
        n_lst = sum(a.units.get("lst", 0) for a in g.armies.values() if a.owner == fid)
        n_dd = sum(a.units.get("dd", 0) for a in g.armies.values() if a.owner == fid)
        unfavorable = threat and max(threat.values()) >= 1.0
        want_navy = sea_t and (not land_contact or unfavorable or f.aggression >= 6
                               or g.rng.random() < 0.5 * max(0.0, bias("naval") - 1))
        has_port = any(r.b["port"] for r in regs)
        if want_navy and not has_port and f.money > 6000:
            coast = sorted([r for r in idle if g.world.regions[r.id].coastal],
                           key=lambda r: -threat.get(r.id, 0) - r.pop / 100)
            if coast:
                cost = C.SINGLE_BUILDINGS["port"]["cost"] * C.BUILD_COST_MULT
                cands.append((2.3 * bias("naval"), coast[0].id, "build", "port", None,
                              cost / C.SINGLE_BUILDINGS["port"]["turns"]))
        if sea_t and ports_idle and g.can_pay_oil(fid, C.UNITS["lst"]["oil"]) and f.money > 2000:
            if n_lst < 1 + len(regs) // 40 and (not land_contact or unfavorable or g.rng.random() < 0.15):
                r0 = ports_idle[0]
                cands.append((2.4 * bias("naval"), r0.id, "unit", "lst", None, g.unit_cost(fid, r0.id, "lst")))
            elif enemy_ports and n_dd < n_lst + 1 and g.can_pay_oil(fid, C.UNITS["dd"]["oil"]) and f.money > 4000:
                r0 = ports_idle[-1]
                cands.append((2.0 * bias("naval"), r0.id, "unit", "dd", None, g.unit_cost(fid, r0.id, "dd")))
    # 상륙함이 빈 채로 기다리는 항구: 그 자리에서 태울 병력을 뽑는다
    if military and at_war:
        for fl in g.armies.values():
            if fl.owner == fid and fl.units.get("lst") and fl.loc in idle_ids and fl.count(("land",)) < 3:
                cands.append((2.5, fl.loc, "unit", "inf", None, g.unit_cost(fid, fl.loc, "inf")))
                break
    # 군 생산 후보: 위협 높은 곳 우선
    if mil_need > 0 and military:
        # 징집 피로: 더 뽑으면 징집 피로가 생길 수 있는 지역(최근 10턴 중 6턴 이상)은 위급할 때(위협 1 이상)만
        safe = min(C.CONSCRIPT_PENALTY) - 1
        pool = [r for r in idle if g.drafted_turns(r.id) < safe or threat.get(r.id, 0) >= 1.0]
        order = sorted(pool, key=lambda r: -threat.get(r.id, 0) - (0.2 if r.id == f.capital else 0)
                       + 0.05 * g.drafted_turns(r.id))
        for r in order[:mil_need]:
            key = "inf"
            # 지도자 성향: 유리한 병종은 조금 더 자주(보병 대비 상대 배수)
            if g.can_pay_oil(fid, C.UNITS["tank"]["oil"]) and f.money > 3000 and g.rng.random() < 0.35 * bias("tank") / bias("inf"):
                key = "tank"
            elif g.rng.random() < (0.28 if at_war else 0.15) * bias("art") / bias("inf") and f.money > 3000:
                key = "art"                    # 전쟁 중엔 선제 폭격용 포병을 더
            per = g.unit_cost(fid, r.id, key)
            u = (1.5 + threat.get(r.id, 0)) * wts.get("military", 1) * bias(key)
            cands.append((u, r.id, "unit", key, None, per))
    # 과학승리 단계: 목표면 조건을 낮춘다. 그 밖엔 재정이 아주 넉넉할 때만
    step = g.science_next(fid) if (f.is_ai and "science" in g.settings.victories) else None
    if step is not None and g.science_busy(fid, step) is None:
        sci_goal = f.ai.get("victory_goal") == "science"
        sc_turns = g.science_turns(fid)
        sc_total = g.science_step_cost(fid, step)
        sc_per = sc_total / sc_turns
        sm, si = ((2.0, 0.3) if sci_goal else (4, 0.6))
        sm, si = sm / bias("science"), si / bias("science")
        if (f.money > sc_per * sm and income - upkeep > sc_per * si) or f.money > sc_total * (1.1 if sci_goal else 2.5):
            sites = [r for r in regs if g.science_site_ok(fid, r.id, step) and not r.project and not r.occ
                     and not g.resisting(r)]
            if sites:
                # 위협이 적고 수도에 가까운 곳(유닛은 발사대까지 옮겨야 한다)
                dist = g.world.distances_from(f.capital, 30)
                best = min(sites, key=lambda r: (threat.get(r.id, 0), dist.get(r.id, 99)))
                g.start_project(fid, best.id, "science", step)
            elif sci_goal and step in ("booster", "module", "budget"):
                # 공장(예산 편성은 은행) 5단계 지역이 없으면 가장 높은 곳부터 올린다
                bk = "bank" if step == "budget" else "factory"
                pool_f = [r for r in idle if r.b[bk] < 5]
                if pool_f:
                    r0 = max(pool_f, key=lambda r: (r.b[bk], r.pop))
                    lv = r0.b[bk] + 1
                    cost = R.prod_building_cost(bk, lv) * (g.mods(fid).mult("cost_factory") if bk == "factory" else 1)
                    turns = g.build_time(fid, bk, R.prod_building_turns(lv))
                    cands.append((3.0, r0.id, "build", bk, None, cost / turns))
    _econ_orders(g, f, regs, idle, cands, threat, income, upkeep, bias)
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
