"""AI (기획서 11절): 대전략·작전·전술·외교 4층 유틸리티 판단.

AI 는 플레이어와 같은 안개 규칙을 따른다(적 부대는 자기 시야 안의 것만 본다).
"""
from __future__ import annotations

import math

from . import ai_endgame as EG
from . import ai_phase as PH
from . import ai_strategy as ST
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
    "tank": [("cost_tank", -1), ("cost_mil", -1), ("cost_noninf", -1)],
    "art": [("bomb_art", 1), ("cost_mil", -1), ("cost_noninf", -1)],
    "naval": [("cost_naval", -1), ("naval_power", 1), ("naval_bomb", 1), ("amphib_extra", 1), ("cut_supply", -1),
              ("amphib_atk", 1), ("cost_noninf", -1)],
    "air": [("cost_air", -1), ("cost_noninf", -1)],
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
                    + 0.05 * has_oil + 0.05 * has_f5 + 0.03 * (has_coast + has_mtn)) * leader_bias(g, fid, "science"),
        "diplomatic": ((0.05 + 0.03 * (10 - aggr) + 0.6 * c_frac + 0.04 * min(4, allies))
                       * leader_bias(g, fid, "ally") if can_ally else -1.0),
        "time": 0.3 + (0.4 * t_prog if top else 0.1 * t_prog),
    }
    return max(vt, key=lambda v: score[v] + g.rng.uniform(0, 0.25))


def set_strategy(g, f):
    a = f.aggression
    w = {"military": 0.4 + a / 10, "economy": 1.4 - a / 25, "expansion": 1.2, "defense": 0.6}
    if PH.phase(f) >= 2 and ST.path_of(f):
        f.ai["victory_goal"] = ST.path_of(f)          # 2페이즈: 종합 판단으로 고른 방향
    elif "victory_goal" not in f.ai or g.turn - f.ai.get("goal_turn", -999) >= C.TURNS_PER_YEAR:
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
        if not (PH.phase(f) >= 2 and ST.state(f).get("hopeless")):
            w["military"] -= k / 2             # 강국에 기대는 약소국은 군사를 줄이지 않는다(살아남는 게 먼저)
    elif goal == "time":
        w["economy"] += k / 2
        w["expansion"] += k / 2
    if D.enemies(g, f.id):
        w["military"] += 0.5
        w["defense"] += 0.5
    if g.turn < 48:
        w["expansion"] += 0.5
    f.ai["weights"] = w
    f.ai["weights_base"] = dict(w)
    f.ai["goal"] = goal
    f.ai["strategy_turn"] = g.turn


def _posture_weights(f):
    """2페이즈 태세(위기·경계)에 따라 전략 가중치를 매 턴 조정한다(기본값은 set_strategy 가 만든 것)."""
    w = dict(f.ai.get("weights_base") or f.ai.get("weights") or {})
    for k, dv in C.AI_P2_POSTURE_W.get(ST.posture_of(f), {}).items():
        w[k] = max(0.2, w.get(k, 1.0) + dv)
    urg = _harass_urg(f)
    if urg:
        # 견제: 상대 승리가 가까울수록(위급도가 클수록) 가파르게 군사를 늘린다(내정은 그대로)
        w["military"] = w.get("military", 1.0) + C.AI_P3_HARASS_MIL * urg * (1 + urg)
    f.ai["weights"] = w


def _harass_urg(f) -> float:
    ph = f.ai.get("phase", 1)
    rec = f.ai.get("p3") if ph >= 3 else f.ai.get("watch") if ph == 2 else None
    return rec.get("urgency", 0.0) if rec and rec.get("harass") is not None else 0.0


def plan_turn(g, fid):
    f = g.factions[fid]
    if not f.alive:
        return
    PH.update(g, f)
    p2 = PH.phase(f) >= 2
    if p2:
        ST.update(g, f, threat_map(g, fid))
    if p2:
        EG.watch(g, f)                        # 6턴마다 승리까지 남은 턴을 비교: 3페이즈는 질주 여부, 모두 견제 위급도
    if PH.p3_kind(f) == "diplomatic":
        follower_update(g, f)                 # 외교 3페이즈: 정복을 노리는 강국에 기댄다
    if ("weights" not in f.ai or g.turn - f.ai.get("strategy_turn", -99) >= C.AI_STRATEGY_PERIOD
            or (p2 and f.ai.get("goal") != ST.path_of(f))):
        set_strategy(g, f)
    if p2:
        _posture_weights(f)
    f.auto_food = True
    _market(g, f)
    _tax(g, f)
    _diplomacy(g, f)
    threat = threat_map(g, fid)
    _merge_idle(g, fid)
    _austerity(g, f, threat)
    _army_orders(g, f, threat)
    _science_orders(g, f)
    _patrol_orders(g, f)
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


def _unhappy_loss_penalty(g, f, h, k):
    """행복도 h 일 때 산출·전투력 손실(같은 곡선, −50에서 7.5%)에 비례한 감점.
    적자이거나(2페이즈) 군사력이 위협에 못 미치면 나라가 흔들리는 중이라 2배."""
    loss = 1 - R.unhappy_output_mult(h)
    if loss <= 0:
        return 0.0
    shaky = f.last.get("net", 0) < 0 or (f.is_ai and PH.phase(f) >= 2 and ST.state(f).get("mil_ok") is False)
    return k * loss * (C.AI_UNHAPPY_SHAKY if shaky else 1.0)


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
    loss = _unhappy_loss_penalty(g, f, avg_h, C.AI_PEACE_LOSS_K)
    if loss > 0:
        d += loss                              # 민심 때문에 산출·전투력이 떨어져 나라가 흔들린다
        if loss >= 0.2:
            pro.append("산출·사기 저하")
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
    if f.is_ai and PH.phase(f) == 1 and f.ai.get("free", 0) > 0:
        d += C.AI_P1_PEACE * f.ai["free"]  # 1페이즈: 빨리 끝내고 빈 땅으로
        pro.append("확장할 빈 땅")
    elif f.is_ai and PH.phase(f) >= 2:
        if ST.posture_of(f) == "crisis":
            d += C.AI_P2_CRISIS_PEACE
            pro.append("국가 위기")
        if ST.path_of(f) not in (None, "conquest"):
            d += C.AI_P2_NONCONQ_PEACE     # 정복을 노리지 않으면 전쟁을 오래 끌지 않는다
        h_tgt, urg = EG.harass(g, f)
        if e == h_tgt and ST.posture_of(f) != "crisis":
            d -= C.AI_P3_HARASS_PEACE * urg  # 견제 전쟁: 쉽게 접지 않는다
            con.append("승리 저지")
        if EG.sprint(f) == "conquest" and ST.posture_of(f) != "crisis":
            d -= C.AI_P3_SPRINT_PEACE      # 3페이즈 정복 질주: 이기고 있는 전쟁은 끝까지
            con.append("정복 질주")
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
    if f.ai.get("intel_turn") != g.turn:
        update_intel(g, f)                 # 한 턴에 한 번만(기억 감쇠가 두 번 걸리지 않게)
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
    # 정복을 노리는 강국은 자기에게 기대는 나라를 받아준다(같이 외교승리든 혼자 정복승리든 둘 다 승리)
    if PH.phase(f) >= 2 and EG.conquest_minded(g, fid):
        for x in alive:
            if x != fid and g.factions[x].is_ai and EG.follower_patron(g, g.factions[x]) == fid:
                D.add_opinion(g, fid, x, C.AI_P3_PATRON_WARM)
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
    if PH.phase(f) >= 2:
        _p2_anchor(g, f)
    _social(g, f)
    _consider_war(g, f)
    if PH.phase(f) >= 2:
        _p3_harass_war(g, f)
    if PH.p3_kind(f) == "diplomatic":
        _follower_wars(g, f)


def _p2_anchor(g, f):
    """2페이즈 관계 만들기. 어느 쪽도 유리하지 않은 나라는 먼저 '의지할 강국'과 연합까지(외교승리),
    그다음(또는 그 밖의 나라는) '우방'과 불가침까지(전선 이중화 방지)."""
    s = ST.state(f)
    pat = EG.follower_patron(g, f)
    if pat is not None:
        if PH.p3_kind(f) == "diplomatic":
            # 외교 3페이즈: 이 강국에 기대기로 했다 — 강국의 전쟁광 평판 따위로 내 쪽 마음이 식지 않는다
            gap = max(C.ALLIANCE_MIN, C.COALITION_MIN) + C.AI_P2_GIFT_MARGIN - D.opinion(g, f.id, pat)
            if gap > 0:
                D.add_opinion(g, f.id, pat, gap)
        _p2_court(g, f, pat, "coalition", C.AI_P2_PATRON_OP)
        # 외교 3페이즈: 강국과 동맹 이상이면 다른 나라도 연합으로 끌어들인다(큰 연합 = 빠른 외교승리, 강국 단독 정복 저지)
        if PH.p3_kind(f) == "diplomatic" and D.allied(g, f.id, pat):
            r = s.get("recruit")
            if r is None or not g.factions[r].alive or D.same_coalition(g, f.id, r) or D.at_war(g, pat, r):
                r = s["recruit"] = EG.recruit(g, f, pat)
            if r is not None:
                _p2_court(g, f, r, "coalition", C.AI_P3_RECRUIT_OP)
    a = s.get("anchor")
    if a is not None and a != s.get("patron"):
        # 3페이즈 경제: 기축통화에 동맹 1곳이 필요하다 — 우방과 동맹(연합)까지
        goal = "coalition" if PH.p3_kind(f) == "economic" else "treaty"
        _p2_court(g, f, a, goal, C.AI_P2_ANCHOR_OP)


def _p2_court(g, f, o, goal, drift):
    """o 와 관계를 goal(treaty: 우호 선언 + 불가침, coalition: 동맹을 거쳐 연합)까지 끌어올린다.
    내 우호도를 매 턴 drift 만큼 올리고(관계를 맺기로 한 결정), 우호 선언을 하고, 다음 단계 문턱까지 모자란
    상대 우호도는 선물로 채운다(선물 간격은 우방·강국 공통). 조약·동맹·연합은 AI 끼리는 양쪽 조건이 맞으면
    _diplomacy 에서 자동 체결, 상대가 플레이어면 제안으로 간다."""
    fid = f.id
    s = ST.state(f)
    if o is None or not g.factions[o].alive or D.at_war(g, fid, o):
        return
    D.add_opinion(g, fid, o, drift)
    if not D.declared_friends(g, fid, o):
        ok, _ = D.friendship_check(g, fid, o)
        if ok:
            if g.factions[o].is_ai:
                D.declare_friendship(g, fid, o)
            else:
                _queue_player(g, fid, "friendship")
            return
        target = C.DECL_FRIEND_MIN + 10            # 선언을 받아들일 만큼
    elif not (D.has_nonaggr(g, fid, o) or D.has_passage(g, fid, o) or D.allied(g, fid, o)):
        target = D.threshold(g, o, fid, C.TREATY_MIN) + C.AI_P2_GIFT_MARGIN
    elif goal == "treaty":
        return                                    # 우방은 불가침까지면 충분하다
    elif not D.allied(g, fid, o):
        target = D.threshold(g, o, fid, C.ALLIANCE_MIN) + C.AI_P2_GIFT_MARGIN
    else:
        target = D.threshold(g, o, fid, C.COALITION_MIN) + C.AI_P2_GIFT_MARGIN   # 연합(동맹 24턴 뒤)·유지
    if not g.factions[o].is_ai:
        return                                    # 플레이어에게는 조약 제안(propose_to_player)으로
    post = s.get("posture", "normal")
    if post == "crisis" or (post == "defend" and not s.get("mil_ok")):
        return                                    # 살아남는 게 먼저: 위기·군사력이 모자란 경계 중에는 선물하지 않는다
    gap = target - D.opinion(g, o, fid)
    if gap <= 0 or g.turn - s.get("gift_turn", -99) < C.AI_P2_GIFT_EVERY:
        return
    reserve = 300 + g.upkeep(fid) * 5
    net = f.last.get("tax", 0) - f.last.get("upkeep", 0)
    share, turns = ((C.AI_P2_PATRON_GIFT_SHARE, C.AI_P2_PATRON_GIFT_NET) if goal == "coalition"
                    else (C.AI_P2_GIFT_SHARE, C.AI_P2_GIFT_NET))
    budget = max(0.0, f.money - reserve) * share
    if f.ai.get("victory_goal") != "diplomatic":
        budget = min(budget, max(0.0, net) * turns)   # 외교 방향은 모아 둔 돈도 외교에 쓴다(다른 방향은 순수입 몇 턴분까지)
    amount = min(budget, D.gift_needed(g, o, gap, fid))
    if amount >= 50:
        v = D.ai_gift(g, fid, o, amount)
        s["gift_turn"] = g.turn
        s["gifts"] = s.get("gifts", 0) + 1
        s["gift_money"] = s.get("gift_money", 0) + round(amount)
        s["gift_op"] = round(s.get("gift_op", 0) + v, 2)


def _social(g, f):
    """우호 선언·비난. 온건할수록 우호 선언을, 호전적일수록 비난을 자주 쓴다."""
    fid = f.id
    aggr = eff_aggression(g, f)
    alive = [x for x in g.alive_ids() if x != fid]
    # 우호 선언: 나를 좋게 보는(또는 적의 적인) 세력과 가까워진다
    p_friend = C.AI_FRIEND_DECL_P * (10 - aggr) / 10 * leader_bias(g, fid, "ally")
    if g.mods(fid).value("tribute"):
        # 야율융서 '전연의 맹약': 우호 선언 관계마다 공물이 들어오니, 호전적이어도 온건형만큼 우호 선언을 한다
        p_friend = max(p_friend, C.AI_FRIEND_DECL_P * (10 - C.AI_TRIBUTE_FRIEND_AGGR) / 10) * C.AI_TRIBUTE_FRIEND_MULT
    if f.ai.get("victory_goal") in ("diplomatic", "economic"):
        p_friend *= 1.5                    # 외교·경제승리는 우호 관계가 필요하다
    if PH.phase(f) >= 2:
        p_friend *= 1 + C.AI_POOR_FRIEND * ST.poverty(g, fid)   # GDP 하위권은 외교에 더 적극적
    # 포위 방지: 국경을 맞댄 나라가 많을수록(강약과 상관없이) 이웃과 우호 관계를 맺으려 한다
    borders = {g.regions[n].owner for r in g.regions_of(fid) for n in g.world.land_adj[r.id]} - {NEUTRAL, fid}
    p_friend *= 1 + min(0.5, C.AI_FRIEND_ENCIRCLE_P * max(0, len(borders) - 2))
    if alive and g.rng.random() < p_friend:
        my_enemies = set(D.enemies(g, fid))
        cands = []
        patron = ST.state(f).get("patron") if PH.phase(f) >= 2 else None
        for x in alive:
            ok, _ = D.friendship_check(g, fid, x)
            if not ok or D.opinion(g, fid, x) < 0:
                continue
            if patron is not None and x != patron and D.hostile_to(g, patron, x):
                continue                     # 의지할 강국의 적과는 가까워지지 않는다
            # 선언하면 x 와 적대하는 세력이 나를 싫어하게 된다(−5): 그 손실을 따진다
            cost = sum(1 for y in alive if y != x and g.factions[y].is_ai and D.hostile_to(g, y, x)
                       and not D.at_war(g, fid, y))
            score = D.opinion(g, fid, x) / 20 + len(my_enemies & set(D.enemies(g, x))) - C.AI_FRIEND_BACKLASH_W * cost
            if g.mods(fid).value("tribute"):
                score += 0.5                 # 공물: 관계 하나하나가 수입이다
            if D.allied(g, fid, x):
                score -= 0.5                 # 이미 동맹이면 덜 급하다
            if x in borders:
                # 이웃 하나를 우방으로 돌리면 둘러싸일 걱정이 준다: 아직 우방이 아닌 다른 이웃이 많을수록 가점
                rest = sum(1 for y in borders if y != x and not (D.declared_friends(g, fid, y) or D.allied(g, fid, y)))
                score += C.AI_FRIEND_ENCIRCLE_W * min(3, rest)
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
    keep = {ST.state(f).get("anchor"), ST.state(f).get("patron")} if PH.phase(f) >= 2 else set()
    keep |= {x for x in alive if g.factions[x].is_ai and EG.follower_patron(g, g.factions[x]) == fid}   # 나에게 기댄 나라
    for x in alive:
        if x in keep or not D.denounce_check(g, fid, x)[0] or not D.hostile_to(g, fid, x):
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
    if f.last.get("tax", 0) - f.last.get("upkeep", 0) < 0:
        return                               # 턴 수입 적자(세수 < 유지비)면 새 전쟁을 벌이지 않는다
    p2 = ST.state(f) if PH.phase(f) >= 2 else None
    if p2 is not None and p2.get("posture") == "crisis":
        _p2_block(f, "위기")
        return                               # 위기 중에는 새 전쟁을 벌이지 않는다(경계 중에는 양면 전선 검사로 거른다)
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
    spr = EG.sprint(f)
    h_tgt, urg = EG.harass(g, f)
    site_regions = EG.missing_science_site(g, fid) if spr == "science" else []
    site_owners = {g.regions[n].owner for n in site_regions}
    for o in sorted(neighbors):
        if D.has_nonaggr(g, fid, o) or D.at_war(g, fid, o) or D.peace_left(g, fid, o) > 0:
            continue
        if p2 is not None and o in (p2.get("anchor"), p2.get("patron")):
            continue                          # 우방·의지할 강국은 치지 않는다
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
        if cid is not None:
            ok_c, refuse, wait = D.coalition_consent(g, fid, o)
            if refuse:
                if p2 is not None:
                    _p2_block(f, "연합 반대")
                continue                      # 연합 전원이 동의해야 선포할 수 있다
        if p2 is not None:
            why = p2_war_gate(g, fid, p2, o, ratio)
            if why:
                _p2_block(f, why)
                continue
        op = D.opinion(g, fid, o)
        thr = war_op_threshold(g, f, o, ratio, can_expand)
        if op > thr:
            continue                      # 아직 참을 만하다
        need = (1.5 - 0.07 * aggr - (C.AI_P3_SPRINT_NEED if spr == "conquest" else 0.0)
                - (C.AI_P3_HARASS_NEED * urg if o == h_tgt else 0.0))
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
        s -= _unhappy_loss_penalty(g, f, proj_h, C.AI_WAR_LOSS_K)   # 산출·사기 손실로 나라가 흔들릴 전망
        s -= (rep_pen - 10) / 25 + 0.03 * ties * rep_pen / 10   # 전쟁광 평판
        if g.hegemon == o:
            s += min(C.HEGEMON_WAR_MAX, C.HEGEMON_WAR_K * (g.hegemon_share - C.HEGEMON_SHARE))
        s += C.VICTORY_THREAT_SCORE * g.victory_threat(o)
        if PH.phase(f) == 1:
            s -= C.AI_P1_WAR_PENALTY * f.ai.get("free", 0.0)   # 1페이즈: 전쟁보다 빈 땅부터
        elif p2 is not None:
            if p2.get("path") == "conquest":
                # 정복 방향이라고 맹목적으로 치지 않는다: 전력 우위와 얻을 땅이 있을 때만 가점
                s += C.AI_P2_PATH_WAR * min(1.0, max(0.0, ratio - need)) * min(1.0, prize / 15)
            else:
                s += C.AI_P2_OTHER_WAR
        goals = fr["targets"][:4] or fr["border"][:2]
        if spr == "conquest":
            s += C.AI_P3_SPRINT_WAR                         # 3페이즈 정복 질주: 땅을 넓힐 전쟁을 더 적극적으로
        if o == h_tgt:
            s += C.AI_P3_HARASS_WAR * urg * (1 + urg)       # 견제: 승리가 임박할수록 가파르게
        if spr == "science" and o in site_owners:
            s += C.AI_P3_SITE_WAR                           # 과학 질주: 다음 단계를 지을 땅(산맥·해안·석유)을 가진 이웃
            goals = [n for n in site_regions if g.regions[n].owner == o][:2] + goals[:2]
        if s > best_s:
            best, best_s, best_goals = o, s, goals
    if best is not None:
        ok, _ = D.declare_war(g, fid, best)
        if not ok and D.coalition_consent(g, fid, best)[2]:
            # 연합에 플레이어가 있으면 동의를 구한다(수락하면 연합 전원이 함께 선포)
            if g.turn - f.ai.get("proposed_coalition_war", -99) >= 8:
                f.ai["proposed_coalition_war"] = g.turn
                g.pending_proposals.append({"from": fid, "kind": "coalition_war", "target": best})
        if ok:
            f.ai.setdefault("war_goals", {})[best] = best_goals
            if p2 is not None:
                p2["target"] = best


def _p3_harass_war(g, f):
    """3페이즈 견제 선포(6턴마다): 승리가 임박한 나라를 늦추려는 전쟁이라 이길 필요는 없다(우호도 문턱 없음).
    대신 나라가 흔들리지 않고(적자·민심·피로·위기·전쟁 2곳), 땅·바다·하늘로 닿으며, 그 나라와 이미 싸우는 나라들의
    힘을 합쳐 상대의 0.6배 이상이고(맹목적으로 덤비지 않는다), 위급도만큼의 확률로."""
    fid = f.id
    t, urg = EG.harass(g, f)
    if t is None or g.turn - f.ai.get("harass_eval", -99) < C.AI_P3_EVAL_TURNS:
        return
    f.ai["harass_eval"] = g.turn
    why = _harass_block(g, f, t, urg)
    st = f.ai.setdefault("p3s", {})
    if why:
        b = st.setdefault("harass_block", {})
        b[why] = b.get(why, 0) + 1
        return
    if D.has_nonaggr(g, fid, t):
        D.break_nonaggr(g, fid, t)           # 승리가 아주 임박하면 불가침을 깨고서라도
    ok, _ = D.declare_war(g, fid, t, reason="승리 저지 선전포고")
    if ok:
        st["harass_war"] = st.get("harass_war", 0) + 1


def follower_update(g, f):
    """외교 3페이즈(6턴마다): 기댈 강국이 없거나 정복을 노리지 않는 나라면 정복을 노리는 강국으로 바꾼다."""
    s = ST.state(f)
    if g.turn - s.get("follow_eval", -99) < C.AI_P3_EVAL_TURNS:
        return
    s["follow_eval"] = g.turn
    s["hopeless"] = True                      # 강국에 기대 연합으로 이긴다(_p2_anchor 가 강국과 연합까지)
    cur = s.get("patron")
    best = ST.choose_patron(g, f)
    if best is None:
        return
    if (cur is None or not g.factions[cur].alive or D.at_war(g, f.id, cur)
            or (not EG.conquest_minded(g, cur) and EG.conquest_minded(g, best)
                and perceived_power(g, f.id, best) >= C.AI_P3_PATRON_SWITCH * perceived_power(g, f.id, cur)
                and not D.same_coalition(g, f.id, cur))):
        s["patron"] = best


def _follower_wars(g, f):
    """외교 3페이즈, 강국과 동맹 이상일 때(6턴마다): ① 강국에게 무너지는 이웃과의 전쟁에 끼어들어 땅을 나눠 먹는다
    (강국 혼자 3분의 2를 차지해 정복승리로 혼자 이기지 않게). ② 같은 연합이면 강국과 나 둘 다 맞닿은 약한 나라에
    연합 공동 선포로 강국을 끌어들인다(연합 밖의 나라가 줄어야 외교승리)."""
    fid = f.id
    pat = EG.follower_patron(g, f)
    if pat is None or not D.allied(g, fid, pat):
        return
    if g.turn - f.ai.get("follow_war_eval", -99) < C.AI_P3_EVAL_TURNS:
        return
    f.ai["follow_war_eval"] = g.turn
    if (f.money < 0 or f.last.get("tax", 0) - f.last.get("upkeep", 0) < 0 or g.avg_happiness(fid) < -20
            or f.war_weary > 45 or ST.posture_of(f) == "crisis" or len(D.enemies(g, fid)) >= C.AI_MAX_WARS):
        return
    w = g.world
    mine = {r.id for r in g.regions_of(fid)}
    touch = lambda x: [n for rid in mine for n in w.land_adj[rid] if g.regions[n].owner == x]
    st = f.ai.setdefault("p3s", {})
    # ① 편승 참전
    joins = []
    for x in D.enemies(g, pat):
        if D.at_war(g, fid, x) or D.has_nonaggr(g, fid, x) or D.peace_left(g, fid, x) > 0 or D.allied(g, fid, x):
            continue
        t = touch(x)
        info = D.war_info(g, x, pat)
        if t and (info.get("lost", 0) > 0 or g.region_count(x) <= C.AI_P3_DYING_REGIONS):
            joins.append((len(set(t)), x, sorted(set(t))))
    if joins:
        _, x, t = max(joins)
        ok, _ = D.declare_war(g, fid, x, reason="강대국 편승 참전")
        if ok:
            f.ai.setdefault("war_goals", {})[x] = t[:4]
            st["join"] = st.get("join", 0) + 1
            return
    # ② 강국 끌어들이기(같은 연합)
    blk = st.setdefault("drag_block", {})
    if not D.same_coalition(g, fid, pat):
        blk["연합 아님"] = blk.get("연합 아님", 0) + 1
        return
    if len(D.enemies(g, pat)) >= C.AI_MAX_WARS:
        blk["강국 전쟁 많음"] = blk.get("강국 전쟁 많음", 0) + 1
        return
    if g.rng.random() >= C.AI_P3_DRAG_P:
        return
    pat_regs = {r.id for r in g.regions_of(pat)}
    cands = []
    for x in g.alive_ids():
        if x in (fid, pat) or D.same_coalition(g, fid, x) or D.at_war(g, fid, x) or D.has_nonaggr(g, fid, x):
            continue
        if D.peace_left(g, fid, x) > 0 or D.peace_left(g, pat, x) > 0:
            continue
        if not any(n in pat_regs for r in g.regions_of(x) for n in w.land_adj[r.id]):
            continue                          # 강국과 맞닿아야 강국이 싸운다
        if perceived_power(g, fid, x) > C.AI_P3_DRAG_RATIO * perceived_power(g, fid, pat):
            continue
        t = touch(x)                          # 나와도 맞닿으면 땅을 나눠 먹을 수 있어 더 좋다
        cands.append((len(set(t)), -g.region_count(x), x, sorted(set(t))))
    if not cands:
        blk["대상 없음"] = blk.get("대상 없음", 0) + 1
        return
    _, _, x, t = max(cands)
    ok, msg = D.declare_war(g, fid, x, reason="연합 공동 선전포고")
    if ok:
        f.ai.setdefault("war_goals", {})[x] = t[:4]
        st["drag"] = st.get("drag", 0) + 1
    else:
        blk["동의 실패"] = blk.get("동의 실패", 0) + 1


def loyal(g, x, y) -> bool:
    """x 가 y 와의 동맹을 깨지 않는가: y 가 x 에 기댄 나라(강국 입장: 같이 외교승리든 혼자 정복승리든 둘 다 승리)이거나
    x 가 y 에 기댄 나라."""
    return EG.follower_patron(g, g.factions[y]) == x or EG.follower_patron(g, g.factions[x]) == y


def _harass_block(g, f, t, urg):
    """견제 선포를 하지 않는 이유(없으면 None)."""
    fid = f.id
    if D.at_war(g, fid, t):
        return "이미 전쟁"
    if D.peace_left(g, fid, t) > 0 or (D.has_nonaggr(g, fid, t) and urg < C.AI_P3_HARASS_BREAK):
        return "조약·휴전"
    if (f.money < 0 or f.last.get("tax", 0) - f.last.get("upkeep", 0) < 0 or g.avg_happiness(fid) < -20
            or f.war_weary > 45 or ST.posture_of(f) == "crisis"):
        return "내정"
    if len(D.enemies(g, fid)) >= C.AI_MAX_WARS:
        return "전쟁 2곳"
    s2 = ST.state(f)
    if t in (s2.get("anchor"), s2.get("patron")):
        return "우방"
    if D.coalition_of(g, fid) is not None and D.coalition_consent(g, fid, t)[1]:
        return "연합 반대"
    w = g.world
    regs = g.regions_of(fid)
    t_regs = {r.id for r in g.regions_of(t)}
    by_land = any(n in t_regs for r in regs for n in w.land_adj[r.id])
    by_air = any(r.b["airport"] and any(v in t_regs for v in w.distances_from(r.id, C.BOMB_RANGE)) for r in regs)
    seas = {s_ for r in regs if w.regions[r.id].coastal for s_ in w.regions[r.id].seas}
    seas |= {s2_ for s_ in list(seas) for s2_ in w.seas[s_].adj}
    by_sea = any(v in t_regs for s_ in seas for v in w.seas[s_].coast)
    if not (by_land or by_air or by_sea):
        return "닿지 않음"
    alive = g.alive_ids()
    joint = g.mil_power(fid) * g.morale(fid) + 0.5 * sum(
        g.mil_power(x) for x in alive if x not in (fid, t) and D.at_war(g, x, t))
    their = perceived_power(g, fid, t) * g.morale(t) / (1 + 0.5 * len(D.enemies(g, t)))
    # 국경이 닿으면 반격을 견딜 만큼(0.6배), 바다·하늘로만 닿으면 반격이 어려워 0.3배면 된다
    need = (C.AI_P3_HARASS_RATIO if by_land else C.AI_P3_HARASS_RATIO_FAR) * (1 - C.AI_P3_HARASS_RATIO_URG * urg)
    if joint < need * max(10.0, their):
        return "전력 부족"
    if g.rng.random() >= min(1.0, C.AI_P3_HARASS_P_K * urg):
        return "확률"
    return None


def coalition_war_consent(g, c, a, b) -> bool:
    """연합 회원 c 가 a 의 b 에 대한 선전포고에 동의하는가: b 와 따로 동맹이 아니고, 나라가 흔들리지 않으며
    (적자·민심·전쟁 피로·위기·이미 전쟁 2곳), b 가 패권국·승리 근접국이거나 c 가 b 를 좋게 보지 않을 때."""
    fc = g.factions[c]
    if D.allied(g, c, b):
        return False
    if (fc.money < 0 or fc.last.get("tax", 0) - fc.last.get("upkeep", 0) < 0 or g.avg_happiness(c) < -20
            or fc.war_weary > 45 or len(D.enemies(g, c)) >= C.AI_MAX_WARS):
        return False
    if PH.phase(fc) >= 2 and ST.posture_of(fc) == "crisis":
        return False
    if g.hegemon == b or g.victory_threat(b) >= 0.5 or EG.best_eta(g, b)[1] < C.AI_P3_URGENT_ETA:
        return True                           # 패권국·승리가 임박한 나라를 막는 전쟁에는 동의
    if EG.follower_patron(g, fc) == a:
        return True                           # 기댄 강국의 전쟁에는 함께한다(땅을 나눠 먹는다)
    if (EG.conquest_minded(g, c) and perceived_power(g, c, b) * C.AI_P3_CONQ_CONSENT < g.mil_power(c)
            and any(g.regions[n].owner == c for r in g.regions_of(b) for n in g.world.land_adj[r.id])):
        return True                           # 정복을 노리는 나라는 맞닿은 약한 나라와의 전쟁에 기꺼이 동의
    return D.opinion(g, c, b) <= C.AI_COALITION_WAR_OP


def p2_war_gate(g, fid, p2, o, ratio):
    """2페이즈에서 o 에게 새로 선전포고하면 안 되는 이유(없으면 None).
    - 국경 병력: o 가 국경에 내 국경 병력의 1.3배 넘게 모았는데 전체 전력이 2배가 안 되면
    - 양면 전선: o 말고 위협도 0.8 이상이고 불가침·동맹이 없는 이웃이 있는데 o 보다 2.5배 강하지 않으면"""
    sc = p2.get("scan", {})
    v = sc.get(o)
    if v and v.get("mass", 0) > C.AI_P2_MASS and ratio < C.AI_P2_MASS_RATIO:
        return "국경 병력"
    if ratio < C.AI_P2_TWO_FRONT_RATIO and any(
            x != o and w_.get("T", 0) >= C.AI_P2_TWO_FRONT_T and not D.has_nonaggr(g, fid, x) and not D.allied(g, fid, x)
            for x, w_ in sc.items()):
        return "양면 전선"
    return None


def _p2_block(f, why):
    """2페이즈 전쟁 판단을 막은 이유를 센다(분석용)."""
    b = ST.state(f).setdefault("blocks", {})
    b[why] = b.get(why, 0) + 1


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
    # 1페이즈(평시): 편입으로 얻어 흩어져 있는 보병을 집결지로 모아 빈 땅을 무력 점령한다(돈이 들지 않는 확장)
    p1 = f.is_ai and PH.phase(f) == 1 and not at_war
    rally = _p1_rally(g, fid, annexing) if p1 else None
    spoils = EG.follower_patron(g, f) if f.is_ai else None    # 외교: 강국이 무너뜨리는 나라의 땅을 나눠 먹는다
    # 견제: 승리가 임박한 나라와 전쟁 중이면 그 나라의 승리 거점(발사대·경제 시설·공사 중)을 노린다
    h_tgt, _ = EG.harass(g, f) if f.is_ai else (None, 0.0)
    keys = EG.key_targets(g, h_tgt) if h_tgt is not None and D.at_war(g, fid, h_tgt) else {}
    # 빼앗긴 내 승리 시설·공사: 저항·회복 기간 안에 되찾으면 되살아난다(못 되찾으면 철거) — 무엇보다 먼저
    retake = EG.retake_targets(g, fid) if f.is_ai and at_war else {}
    # 승리 거점 수비(과학·경제를 짓는 쪽): 거점마다 최소 수비대를 남기고, 모자라면 채운다
    guards = key_guards(g, f, threat) if f.is_ai else {}
    short = {rid: n - sum(x.count(("land",)) for x in g.armies_at(rid, fid) if x.domain() == "land")
             for rid, n in guards.items()}
    short = {rid: k for rid, k in short.items() if k > 0}
    tactic = f.is_ai and at_war and f.ai.get("victory_goal") == "conquest"
    border_keep = set()
    if p1:
        border_keep = {r.id for r in g.regions_of(fid)
                       if any(g.regions[n].owner not in (NEUTRAL, fid) for n in w.land_adj[r.id])}
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
        elif a.loc in guards:
            others = sum(x.count(("land",)) for x in g.armies_at(a.loc, fid)
                         if x.id != a.id and x.domain() == "land")
            keep = max(0, guards[a.loc] - others)
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
        # 정복 전술: 최전선(적과 맞닿은 칸)은 전차·보병이, 포병은 그 바로 뒤 칸에서 2칸 포격으로 받친다
        if tactic and a.units.get("art"):
            if a.count() > a.units["art"] and _enemy_adj(g, fid, a.loc):
                b, _ = g.split_army(a.id, {"art": a.units["art"]})
                if b is not None:
                    _art_tactic(g, fid, b)
            elif a.count() == a.units["art"] and _art_tactic(g, fid, a):
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
                if not p1 and wts.get("military", 1) < 0.9 and a.count() < 3:
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
                if spoils is not None and tgt.owner != NEUTRAL and D.at_war(g, spoils, tgt.owner):
                    cap_val *= C.AI_P3_SPOILS
                u = enemy_val - own_val + cap_val
                if mode == "assault" and pv["line"] > 0 and dd > ad:
                    u += C.ASSAULT_LINE_BREAK * 400 * pv["line"]   # 방어선을 무너뜨릴 수 있다
                if node in keys and tgt.owner == h_tgt and (kill or dd > ad):
                    kd, kv = keys[node]
                    u += C.AI_P3_KEY_ATK * kv / (1 + kd)   # 견제: 승리 거점(과 그리로 가는 길)을 먼저
                if node in retake and (kill or dd > ad):
                    u += C.AI_P3_KEY_ATK * retake[node]    # 빼앗긴 내 승리 시설 되찾기
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
                # 돌격이 어려우면 포격으로 수비대를 깎는다: 견제 대상의 승리 거점부터
                strong.sort(key=lambda n: (-(keys.get(n, (9, 0))[1] / (1 + keys.get(n, (9, 0))[0])),
                                           -visible_hostile_power(g, fid, n)))
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
        # 1페이즈: 국경(다른 나라와 맞닿은 곳)의 마지막 1개는 남기고, 나머지는 집결지로
        if p1 and rally is not None and rr.owner == fid:
            alone = sum(x.count() for x in g.armies_at(a.loc, fid) if x.domain() == "land") <= a.count()
            if not (a.loc in border_keep and alone and a.count() <= 1) and a.loc != rally:
                if rally in reach and reach[rally]["action"] == "move":
                    g.order_army(a.id, rally)
                else:
                    step = _step_toward(g, fid, a.loc, rally, reach)
                    if step:
                        g.order_army(a.id, step)
                if a.order:
                    continue
        # 승리 거점 수비대가 모자라면 그리로
        if short and rr.owner == fid and a.loc not in guards:
            dest = min(short, key=lambda rid: (w.distances_from(a.loc, 30).get(rid, 99), rid))
            step = dest if reach.get(dest, {}).get("action") == "move" else _step_toward(g, fid, a.loc, dest, reach)
            if step:
                g.order_army(a.id, step)
                short[dest] -= a.count()
                if short[dest] <= 0:
                    del short[dest]
                continue
        # 견제 전쟁·탈환: 큰 부대는 되찾을 내 시설 또는 상대 승리 거점에 가장 가까운 내 국경으로
        if (keys or retake) and a.count() >= 3 and not (a.loc in front and threat.get(a.loc, 0) > 0.5):
            near = list(retake) or [rid for rid, (kd, kv) in keys.items() if kd == 0]
            dist = w.distances_from(a.loc, 30)
            dest = min(near, key=lambda rid: (dist.get(rid, 99), rid)) if near else None
            if dest is not None and dist.get(dest, 99) < 99:
                step = _step_toward(g, fid, a.loc, dest, reach)
                if step and step != a.loc:
                    g.order_army(a.id, step)
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
    # 폭격기(3페이즈 견제 대상의 수도·과학·경제 시설을 먼저)
    h_tgt, _urg = EG.harass(g, f) if f.is_ai else (None, 0.0)
    for a in list(g.armies.values()):
        if a.id not in g.armies or a.owner != fid or a.domain() != "air" or not at_war or a.order:
            continue
        if h_tgt is not None and a.units.get("bmb") and _board_carrier(g, a):
            continue
        reach = g.reachable(a)
        tg = [(_bomb_value(g, fid, n, h_tgt), n) for n, o in reach.items()
              if o["action"] == "bombard" and g.regions[n].owner != NEUTRAL]
        tg.sort(reverse=True)
        if tg and tg[0][0] > 0:
            g.order_army(a.id, tg[0][1], force_bombard=True)


def _enemy_adj(g, fid, rid) -> bool:
    """rid 가 전쟁 중인 적의 땅과 맞닿았는가(최전선)."""
    return any(g.regions[n].owner not in (NEUTRAL, fid) and D.at_war(g, fid, g.regions[n].owner)
               for n in g.world.land_adj[rid])


def _art_tactic(g, fid, a) -> bool:
    """포병 부대(포병만): 최전선 바로 뒤의 내 땅(적과 맞닿지 않고 적 땅이 2칸 안)에서 포격한다.
    거기 있으면 적 병력(없으면 건물)이 가장 많은 적 지역을 포격하고, 아니면 가장 가까운 그런 자리로 간다. 처리했으면 True."""
    w = g.world

    def enemy(n):
        o = g.regions[n].owner
        return o not in (NEUTRAL, fid) and D.at_war(g, fid, o)

    def targets(loc):
        return [n for n in g.land_within(loc, C.ART_RANGE) if enemy(n)]

    def second(loc):
        return g.regions[loc].owner == fid and not _enemy_adj(g, fid, loc) and bool(targets(loc))
    if second(a.loc):
        tg = max(targets(a.loc), key=lambda n: (bool(g.hostile_units_at(fid, n)), visible_hostile_power(g, fid, n),
                                                 _building_levels(g, n), n))
        if (g.hostile_units_at(fid, tg) or _building_levels(g, tg) > 0) and g._can_bombard(a, tg):
            g.order_army(a.id, tg, force_bombard=True)
        return True                               # 쏠 곳이 없어도 자리를 지킨다
    spots = [n for n, o in g.reachable(a).items() if o["action"] == "move" and not w.is_sea(n) and second(n)]
    if spots:
        dist = w.distances_from(a.loc, 30)
        g.order_army(a.id, min(spots, key=lambda n: (dist.get(n, 99), n)))
        return True
    return False


def harassed_by(g, fid) -> list:
    """fid 를 견제 대상으로 삼고 전쟁 중인 나라들."""
    return [x for x in g.alive_ids() if x != fid and g.factions[x].is_ai and D.at_war(g, x, fid)
            and EG.harass(g, g.factions[x])[0] == fid]


def key_guards(g, f, threat) -> dict:
    """승리 거점(가치 6 이상) 수비대: {지역: 최소 육군}. 과학·경제 3페이즈이거나, 전쟁 중이거나 견제를 받으면.
    기본 2, 위협 0.5 이상 +2, 견제를 받는 중이면 +1."""
    fid = f.id
    if PH.phase(f) < 2:
        return {}
    keys = [r.id for r in g.regions_of(fid) if EG.key_value(g, r.id) >= 6 and r.id != f.capital]
    if not keys:
        return {}
    at_war = bool(D.enemies(g, fid))
    hunted = bool(harassed_by(g, fid)) if at_war else False
    if not (PH.p3_kind(f) in ("science", "economic") or at_war):
        return {}
    d = EG.lead_defense(f)                    # 우세한 나라: 승리가 가까울수록 더 단단히
    out = {}
    for rid in keys:
        n = C.AI_KEY_GUARD + (2 if threat.get(rid, 0) >= 0.5 else 0) + (1 if hunted else 0)
        out[rid] = n + round(C.AI_P3_LEAD_GUARD * d)
    return out


def patrol_seas(g, f) -> set:
    """우세한 나라(수비 강도 0.3 이상)의 해안 승리 거점 앞바다: 구축함을 띄워 둘 해역."""
    if EG.lead_defense(f) < C.AI_P3_LEAD_PATROL:
        return set()
    return {s_ for r in g.regions_of(f.id) if g.info(r.id).coastal and EG.key_value(g, r.id) >= 6
            for s_ in g.world.regions[r.id].seas}


def _patrol_production(g, f, regs, idle, idle_ids, cands):
    seas = patrol_seas(g, f)
    if not seas:
        return
    fid = f.id
    d = EG.lead_defense(f)
    n_dd = sum(a.units.get("dd", 0) for a in g.armies.values() if a.owner == fid)
    if n_dd >= len(seas):
        return
    ports_idle = [r for r in regs if r.b["port"] and r.id in idle_ids]
    if ports_idle and g.can_pay_oil(fid, C.UNITS["dd"]["oil"]) and f.money > 4000:
        cands.append((1.5 + d, ports_idle[0].id, "unit", "dd", None, g.unit_cost(fid, ports_idle[0].id, "dd")))
    elif not any(r.b["port"] for r in regs) and f.money > 6000:
        coast = [r for r in idle if g.world.regions[r.id].coastal]
        if coast:
            cost = C.SINGLE_BUILDINGS["port"]["cost"] * C.BUILD_COST_MULT
            cands.append((1.4 + d, coast[0].id, "build", "port", None, cost / C.SINGLE_BUILDINGS["port"]["turns"]))


def _patrol_orders(g, f):
    """우세한 나라: 구축함을 해안 승리 거점 앞바다마다 하나씩 띄워 둔다(이미 있으면 그대로)."""
    seas = patrol_seas(g, f)
    if not seas:
        return
    fleets = [a for a in g.armies.values() if a.owner == f.id and a.domain() == "naval" and a.units.get("dd")
              and not a.units.get("lst") and not a.units.get("cv") and not a.order]
    taken = {a.loc for a in fleets if a.loc in seas}
    for fl in fleets:
        if fl.loc in seas:
            continue
        free = sorted(seas - taken)
        if not free:
            break
        dist = g.world.distances_from(fl.loc, 30)
        tgt = min(free, key=lambda s_: (dist.get(s_, 99), s_))
        if g.order_army(fl.id, tgt)[0]:
            taken.add(tgt)


def _key_defense(g, f, idle_ids, cands, threat, at_war):
    fid = f.id
    guards = key_guards(g, f, threat)
    if not guards:
        return
    hunted = bool(harassed_by(g, fid)) if at_war else False
    d = EG.lead_defense(f)
    top = C.AI_KEY_SHELTER + (1 if (hunted or at_war) else 0) + (1 if d >= 0.5 else 0)
    aa_top = max(min(2, top - 1) if (hunted or at_war) else 0, round(1 + 2 * d) if d > 0 else 0)
    line_top = max(2 if hunted else 0, round(1 + 2 * d) if d > 0 else 0)
    for rid, need in guards.items():
        if rid not in idle_ids:
            continue
        rr = g.regions[rid]
        garrison = sum(a.count(("land",)) for a in g.armies_at(rid, fid) if a.domain() == "land")
        if garrison < need:
            cands.append((3.0 + threat.get(rid, 0), rid, "unit", "inf", None, g.unit_cost(fid, rid, "inf")))
            continue
        if rr.b["shelter"] < top:
            lv = rr.b["shelter"]
            cands.append((53.0, rid, "build", "shelter", None, R.def_building_cost("shelter", lv + 1) / C.DEF_TURNS[lv]))
            continue
        if rr.b["aa"] < aa_top:
            lv = rr.b["aa"]
            cands.append((52.0, rid, "build", "aa", None, R.def_building_cost("aa", lv + 1) / C.DEF_TURNS[lv]))
            continue
        # 방어선: 다른 나라와 맞닿은 경계·해안선 중 가장 낮은 곳부터(우세한 나라는 승리가 가까울수록 높게)
        borders = [n for n in g.world.land_adj[rid] if g.regions[n].owner not in (NEUTRAL, fid)]
        if g.info(rid).coastal:
            borders.append("coast")
        if borders and line_top:
            b = min(borders, key=lambda n: (rr.lines.get(n, 0), n))
            lv = rr.lines.get(b, 0)
            if lv < line_top:
                cost = R.def_building_cost("line", lv + 1) * g.mods(fid).mult("cost_line")
                cands.append((51.5, rid, "build", "line", b, cost / C.DEF_TURNS[lv]))


def _bomb_value(g, fid, rid, h_tgt):
    v = visible_hostile_power(g, fid, rid) + 2 * _building_levels(g, rid)
    if h_tgt is not None and g.regions[rid].owner == h_tgt:
        v += 3 + 2 * EG.key_value(g, rid)                # 견제: 승리 거점의 수비대·시설을 먼저 깎는다
    return v


def _board_carrier(g, a) -> bool:
    """폭격기를 항공모함에 태운다: 같은 지역(공항·항구)이면 탑승, 빈 칸이 있는 항모가 항구(공항)에서 기다리면
    그리로 이동. 태웠거나 움직였으면 True."""
    fl = g.boarding_target(a.id)
    if fl is not None:
        return fl.air_used() + a.count() <= fl.air_cap() and g.board(a.id)[0]
    w = g.world
    for cv in g.armies.values():
        if (cv.owner == a.owner and cv.units.get("cv") and not w.is_sea(cv.loc) and not cv.units.get("bmb")
                and cv.air_used() + a.count() <= cv.air_cap()):
            if g.reachable(a).get(cv.loc, {}).get("action") == "move":
                return g.order_army(a.id, cv.loc)[0]
    return False


def _p1_rally(g, fid, annexing):
    """1페이즈 집결지: 아직 편입·점령하지 않은 빈 땅(중립)과 가장 많이 맞닿은 내 지역.
    다른 나라와도 맞닿은 빈 땅(경합지)은 1.5배로 친다. 수도에서 멀면 조금 감점."""
    w = g.world
    cap = g.factions[fid].capital
    dist = w.distances_from(cap, 30) if cap in g.regions else {}
    best, best_s = None, 0.0
    for r in g.regions_of(fid):
        s = 0.0
        for n in w.land_adj[r.id]:
            rr = g.regions[n]
            if rr.owner != NEUTRAL or n in annexing or fid in rr.occs:
                continue
            contested = any(g.regions[m].owner not in (NEUTRAL, fid) for m in w.land_adj[n])
            s += 1.5 if contested else 1.0
        if s <= 0:
            continue
        s -= 0.05 * dist.get(r.id, 30)
        if best is None or s > best_s or (s == best_s and r.id < best):
            best, best_s = r.id, s
    return best


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
    """경제승리(기축통화) 단계 착수와 금융 권역 은행 건설. 경제가 목표일 때만(다른 방향은 그 방향에 돈을 모은다)."""
    fid = f.id
    if not f.is_ai or not g.econ_enabled() or f.ai.get("victory_goal") != "economic":
        return
    sm, si = 2.0 / bias("bank"), 0.3 / bias("bank")
    spr = EG.sprint(f) == "economic"
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
                or f.money > per * spec["turns"] * 1.1
                or (spr and f.money > per * C.AI_P3_SPRINT_START)):
            continue
        sites = [r for r in regs if g.econ_site_ok(fid, r.id, step) and not r.project and not r.occ
                 and not g.resisting(r)]
        if step == "exchange" and cap not in ex and cap not in ex_busy:
            sites = [r for r in sites if r.id == cap] or ([] if len(ex) + len(ex_busy) >= C.ECON_EXCHANGES - 1 else sites)
        if sites:
            best = min(sites, key=lambda r: (threat.get(r.id, 0), -r.pop))
            if g.start_project(fid, best.id, "econ", step)[0]:
                if spr:
                    best.project.priority = -1        # 질주: 승리 조건 공사에 돈을 먼저
                break                                 # 큰 공사는 한 턴에 하나씩
    if len(g.finance_cluster(fid)) < C.ECON_CLUSTER:
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
    if EG.sprint(f):
        n += C.AI_P3_SPRINT_GARRISON         # 질주 중: 승리 조건(수도 시설)을 지킨다
    return n


def _sea_targets(g, fid):
    """우리 해안이 닿은 해역(과 그 옆 해역)의 적(전쟁 중) 해안 지역, 그중 항구가 있는 곳, 적과 육로로 맞닿았는지."""
    w = g.world
    enemies = set(D.enemies(g, fid))
    seas = {s for r in g.regions_of(fid) if w.regions[r.id].coastal for s in w.regions[r.id].seas}
    for _ in range(C.AI_SEA_REACH):              # 해역 두 칸까지(바다는 육로보다 빠르다)
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
    h_tgt, _urg = EG.harass(g, f) if f.is_ai else (None, 0.0)
    patrol = patrol_seas(g, f) if f.is_ai else set()
    for fl in [a for a in list(g.armies.values()) if a.owner == fid and a.domain() == "naval"]:
        if fl.id not in g.armies or fl.order:
            continue
        at_port = not w.is_sea(fl.loc)
        if fl.loc in patrol and fl.units.get("dd") and not fl.units.get("lst") and not fl.units.get("cv"):
            # 앞바다 경계 중인 구축함: 자리를 지키며 닿는 적만 포격
            bt = [v for v, o in g.reachable(fl).items() if o["action"] == "bombard"]
            if bt:
                g.order_army(fl.id, max(bt, key=lambda v: (visible_hostile_power(g, fid, v), v)), force_bombard=True)
            continue
        if fl.units.get("cv"):
            _carrier_orders(g, f, fl, h_tgt, at_port)
            continue
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
                if rr.owner == h_tgt:
                    s_ += 3 + EG.key_value(g, v)                              # 견제: 방어선을 우회해 승리 거점에 상륙
                defs = g.hostile_units_at(fid, v)
                if defs:
                    pv = g.preview_attack(fl, v, "assault")
                    # 보통은 수비대를 다 잡을 수 있을 때만. 견제 대상의 승리 거점이면 남는 장사(주는 피해 > 받는 피해)이고
                    # 수비대 절반 넘게 잡을 수 있으면 상륙한다(함포·폭격으로 먼저 깎아 둔다)
                    need = 0.5 if (rr.owner == h_tgt and EG.key_value(g, v) >= 6) else 0.95
                    if not pv or pv["def_dmg"] < pv["def_hp"] * need or pv["att_dmg"] > pv["def_dmg"]:
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
                bt.sort(key=lambda v: (-(g.regions[v].owner == h_tgt) * (1 + EG.key_value(g, v)),
                                       -g.regions[v].b["port"], -visible_hostile_power(g, fid, v)))
                g.order_army(fl.id, bt[0], force_bombard=True)
                continue
        if fl.units.get("dd") and at_port:
            _, ports, _ = _sea_targets(g, fid)
            seas = [v for v, o in reach.items() if o["action"] == "move" and w.is_sea(v)
                    and any(p in w.seas[v].coast for p in ports)]
            if seas:
                g.order_army(fl.id, seas[0])
                continue
        # 이번 턴에 닿는 목표가 없으면 적 해안(견제 대상의 승리 거점·항구 우선) 쪽 해역으로 나아간다(해역 두 칸까지)
        if (fl.units.get("dd") or (fl.units.get("lst") and cargo >= 3)) and _sail_toward(g, f, fl, reach, h_tgt):
            continue
        if not at_port and (cargo == 0 or not fl.units.get("lst")):
            home = [v for v, o in reach.items() if o["action"] == "move" and not w.is_sea(v)]
            if home:
                g.order_army(fl.id, home[0])


def _sail_toward(g, f, fl, reach, h_tgt) -> bool:
    """함대를 적 해안 쪽 해역으로 한 칸 움직인다(움직였으면 True). 목표 해안: 견제 대상의 승리 거점 > 항구 > 그 밖."""
    w = g.world
    tgts, _, _ = _sea_targets(g, f.id)
    if not tgts:
        return False
    def worth(v):
        rr = g.regions[v]
        return (rr.owner == h_tgt) * (2 + EG.key_value(g, v)) + 2 * rr.b["port"] + 1
    goal = {}
    for v in tgts:
        for s_ in w.regions[v].seas:
            goal[s_] = max(goal.get(s_, 0), worth(v))
    if fl.loc in goal:
        return False                              # 이미 목표 해역: 다음 턴 상륙·포격
    from collections import deque
    start = fl.loc if w.is_sea(fl.loc) else None
    starts = [start] if start else list(w.regions[fl.loc].seas)
    prev = {s_: None for s_ in starts}
    q = deque(starts)
    best = None
    while q:
        u = q.popleft()
        if u in goal and (best is None or goal[u] > goal[best]):
            best = u
        for v in w.seas[u].adj:
            if v not in prev:
                prev[v] = u
                q.append(v)
    if best is None:
        return False
    step = best
    while prev.get(step) is not None and reach.get(step, {}).get("action") != "move":
        step = prev[step]
    if reach.get(step, {}).get("action") == "move":
        return g.order_army(fl.id, step)[0]
    return False


def _carrier_orders(g, f, fl, h_tgt, at_port):
    """항공모함 함대: 폭격기를 태우면 견제 대상 앞바다로 나가 폭격하고, 폭격기가 없으면 항구에서 기다린다."""
    fid = f.id
    w = g.world
    if not fl.units.get("bmb"):
        if not at_port:
            home = [v for v, o in g.reachable(fl).items() if o["action"] == "move" and not w.is_sea(v)]
            if home:
                g.order_army(fl.id, home[0])
        return
    reach = g.reachable(fl)
    bt = [v for v, o in reach.items() if o["action"] == "bombard" and g.regions[v].owner != NEUTRAL]
    if bt and not at_port:
        best = max(bt, key=lambda v: (_bomb_value(g, fid, v, h_tgt), v))
        g.order_army(fl.id, best, force_bombard=True)
        return
    if h_tgt is None:
        return
    # 대상 해안에 폭격 거리로 닿는 해역으로
    t_regs = {r.id for r in g.regions_of(h_tgt)}
    seas = [v for v, o in reach.items() if o["action"] == "move" and w.is_sea(v)
            and any(u in t_regs for u in w.distances_from(v, C.BOMB_RANGE))]
    if seas:
        g.order_army(fl.id, max(seas, key=lambda v: (sum(1 for u in w.distances_from(v, C.BOMB_RANGE)
                                                         if u in t_regs and EG.key_region(g, u)), v)))
        return
    far = [v for v, o in reach.items() if o["action"] == "move" and w.is_sea(v)]
    if far:
        tgt = min(t_regs, key=lambda u: (not EG.key_region(g, u), u)) if t_regs else None
        if tgt is not None:
            g.order_army(fl.id, min(far, key=lambda v: (w.distances_from(v, 40).get(tgt, 99), v)))


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
    # 1페이즈: 이번 턴 예상 수지(세수 − 유지비 − 진행 중인 모든 공사비)가 적자면 생산 건물로 재정부터 늘린다
    p1 = f.is_ai and PH.phase(f) == 1
    all_committed = sum(r.project.per_turn for r in regs if r.project)
    deficit = p1 and income - upkeep - all_committed < 0
    prod_k = C.AI_P1_DEFICIT_PROD if deficit else 1.0
    annex_k = C.AI_P1_DEFICIT_ANNEX if deficit else 1.0
    # 2페이즈 태세: 위기면 돈을 군사로(생산 건물·편입 감점, 과학·경제 단계 착수 중지), 경계면 군사력이 모자랄 때 큰 공사 보류
    post = ST.posture_of(f) if (f.is_ai and PH.phase(f) >= 2) else "normal"
    if post == "crisis":
        prod_k *= C.AI_P2_CRISIS_PROD
        annex_k *= C.AI_P2_CRISIS_ANNEX
    elif post == "defend":
        prod_k *= C.AI_P2_DEFEND_PROD
    big_ok = post == "normal" or (post == "defend" and ST.state(f).get("mil_ok", False))
    spr = EG.sprint(f) if f.is_ai else ""
    if spr:
        big_ok = post != "crisis"             # 질주 중: 위기만 아니면 승리 조건 공사를 멈추지 않는다
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
    if spr:
        desired = int(desired * (C.AI_P3_SPRINT_MIL_CONQ if spr == "conquest" else C.AI_P3_SPRINT_MIL))
    # 정복 방향(2페이즈 이상): 다른 승리 조건 공사에 돈을 쓰지 않으니 여윳돈만큼 병력·전차·공군을 더 갖춘다
    conq_rich = 0.0
    if f.is_ai and PH.phase(f) >= 2 and f.ai.get("victory_goal") == "conquest":
        conq_rich = max(0.0, min(1.0, (f.money - reserve) / (max(0.0, income) * C.AI_P2_CONQ_RICH_TURNS + reserve * 4 + 1)))
        desired = int(desired * (1 + C.AI_P2_CONQ_MIL * conq_rich))
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
            gain *= annex_bias * annex_k
            cands.append((gain / t["cost"], r.id, "annex", t["target"], None, t["cost"] / t["turns"]))
        # 1페이즈: 생산 건물은 편입할 곳이 없는 안쪽 지역부터(맞닿은 중립이 있는 지역 슬롯은 편입에 남긴다)
        place_k = 1.0
        if p1:
            place_k = C.AI_P1_FRONTIER_PROD if any(
                g.regions[n].owner == NEUTRAL for n in g.world.land_adj[r.id]) else C.AI_P1_INTERIOR_PROD
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
            gain *= bias(key) * prod_k * place_k
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
            cands.append((per * horizon / cost * bias("extract") * (C.AI_ECON_FUEL_MULT if eco else 1.0) * prod_k * place_k,
                          r.id, "build", "extract", None, cost / turns))
        pb = g.mods(fid).value("port_bank", 0)
        if pb and info.coastal and not r.b["port"]:
            # 근초고왕 '해상 왕국': 항구 = 은행 3단계만큼의 산출
            cost = C.SINGLE_BUILDINGS["port"]["cost"] * C.BUILD_COST_MULT
            turns = g.build_time(fid, "port", C.SINGLE_BUILDINGS["port"]["turns"])
            dy = C.BANK_OUTPUT * R.g(pb) * g.mods(fid).mult("output_bank") * g.mods(fid).mult("output_prod")
            gain = dy * tax * max(0, C.AI_UTILITY_HORIZON - turns) * wts.get("economy", 1) * prod_k * place_k
            cands.append((gain / cost, r.id, "build", "port", None, cost / turns))
        if r.b["power"] < 5 and fuel["spare"] < 0 and fuel["raw_left"] > 0:
            # 발전소: 공장 연료가 모자라고 발전소에 못 넣은 석탄·석유가 남을 때(석탄 1 → 공장 연료 2)
            lv = r.b["power"] + 1
            cost = R.prod_building_cost("power", lv, info.power_site)
            turns = g.build_time(fid, "power", R.prod_building_turns(lv))
            gain = unit_val * max(0, C.AI_UTILITY_HORIZON - turns)
            cands.append((gain / cost * bias("power") * (C.AI_ECON_FUEL_MULT if eco else 1.0) * prod_k * place_k,
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
    # 승리 거점 수비(과학·경제를 짓는 쪽): 수비대가 모자라면 그 자리에서 보병, 그다음 방공호(폭격 피해 ↓)·대공포
    if f.is_ai and military:
        _key_defense(g, f, idle_ids, cands, threat, at_war)
        _patrol_production(g, f, regs, idle, idle_ids, cands)
    # 공군: 전쟁 중이거나 호전적이고 넉넉하면 공항 → 전투기(지상전 지원)·폭격기
    airports = [r for r in regs if r.b["airport"]]
    n_ftr = sum(a.units.get("ftr", 0) for a in g.armies.values() if a.owner == fid)
    n_bmb = sum(a.units.get("bmb", 0) for a in g.armies.values() if a.owner == fid)
    conq_air = conq_rich >= C.AI_P2_CONQ_AIR
    if (military and (at_war or f.aggression >= 6 or spr or conq_air) and f.money > 15000 and not airports
            and g.turn > 24):
        site = cap if (cap is not None and cap.owner == fid and f.capital in idle_ids) else None
        if site is None:
            pool_ap = sorted(idle, key=lambda r: -threat.get(r.id, 0) - r.pop / 100)
            site = pool_ap[0] if pool_ap else None
        if site is not None:
            cost = C.SINGLE_BUILDINGS["airport"]["cost"] * C.BUILD_COST_MULT
            cands.append((2.0 * bias("air"), site.id, "build", "airport", None,
                          cost / C.SINGLE_BUILDINGS["airport"]["turns"]))
    if military and (at_war or spr or conq_air) and airports:
        ap_idle = [r for r in airports if r.id in idle_ids]
        ftr_ok = ap_idle and g.can_pay_oil(fid, C.UNITS["ftr"]["oil"]) and f.money > 3000 and n_ftr < 2 + len(regs) // 25
        bmb_ok = (ap_idle and g.can_pay_oil(fid, C.UNITS["bmb"]["oil"]) and f.money > 4000
                  and n_bmb < C.AI_BMB_BASE + len(regs) // C.AI_BMB_PER_REG)
        # 폭격기는 육로가 막혀도 거점을 깎을 수 있다: 전투기보다 적으면 폭격기부터
        if bmb_ok and (n_bmb < n_ftr or not ftr_ok):
            r0 = ap_idle[0]
            cands.append((C.AI_BMB_UTIL * bias("air"), r0.id, "unit", "bmb", None, g.unit_cost(fid, r0.id, "bmb")))
        elif ftr_ok:
            r0 = ap_idle[0]
            cands.append((2.2 * bias("air"), r0.id, "unit", "ftr", None, g.unit_cost(fid, r0.id, "ftr")))
    # 해군: 육로로 불리하거나 닿지 않는 적 해안을 노린다(상륙함), 적 항구가 있으면 구축함
    if military and at_war:
        sea_t, enemy_ports, land_contact = _sea_targets(g, fid)
        ports_idle = [r for r in regs if r.b["port"] and r.id in idle_ids]
        n_lst = sum(a.units.get("lst", 0) for a in g.armies.values() if a.owner == fid)
        n_dd = sum(a.units.get("dd", 0) for a in g.armies.values() if a.owner == fid)
        unfavorable = threat and max(threat.values()) >= 1.0
        # 바다는 해역이 잘게 나뉘어도 육로보다 훨씬 빠르다: 적 해안이 닿으면 기본적으로 해군을 갖춘다
        want_navy = sea_t and (not land_contact or unfavorable or f.aggression >= 6
                               or g.rng.random() < C.AI_NAVY_P + 0.5 * max(0.0, bias("naval") - 1))
        has_port = any(r.b["port"] for r in regs)
        if want_navy and not has_port and f.money > 6000:
            coast = sorted([r for r in idle if g.world.regions[r.id].coastal],
                           key=lambda r: -threat.get(r.id, 0) - r.pop / 100)
            if coast:
                cost = C.SINGLE_BUILDINGS["port"]["cost"] * C.BUILD_COST_MULT
                cands.append((2.3 * bias("naval"), coast[0].id, "build", "port", None,
                              cost / C.SINGLE_BUILDINGS["port"]["turns"]))
        if sea_t and ports_idle and g.can_pay_oil(fid, C.UNITS["lst"]["oil"]) and f.money > 2000:
            if n_lst < 1 + len(regs) // C.AI_LST_PER_REG and (not land_contact or unfavorable
                                                               or g.rng.random() < C.AI_LST_P):
                r0 = ports_idle[0]
                cands.append((2.4 * bias("naval"), r0.id, "unit", "lst", None, g.unit_cost(fid, r0.id, "lst")))
            elif (n_dd < n_lst + 1 + (len(regs) // C.AI_DD_PER_REG if enemy_ports or not land_contact else 0)
                  and g.can_pay_oil(fid, C.UNITS["dd"]["oil"]) and f.money > 4000):
                r0 = ports_idle[-1]
                cands.append((2.0 * bias("naval"), r0.id, "unit", "dd", None, g.unit_cost(fid, r0.id, "dd")))
    # 질주 중 해안 방어: 항구 하나와 구축함(전쟁이 아니어도)
    if military and spr and not at_war:
        coast_idle = [r for r in idle if g.world.regions[r.id].coastal]
        ports_idle = [r for r in regs if r.b["port"] and r.id in idle_ids]
        n_dd = sum(a.units.get("dd", 0) for a in g.armies.values() if a.owner == fid)
        if coast_idle and not any(r.b["port"] for r in regs) and f.money > 6000:
            cost = C.SINGLE_BUILDINGS["port"]["cost"] * C.BUILD_COST_MULT
            cands.append((1.6, coast_idle[0].id, "build", "port", None, cost / C.SINGLE_BUILDINGS["port"]["turns"]))
        elif ports_idle and n_dd < 1 + len(regs) // 40 and g.can_pay_oil(fid, C.UNITS["dd"]["oil"]) and f.money > 4000:
            cands.append((1.6, ports_idle[0].id, "unit", "dd", None, g.unit_cost(fid, ports_idle[0].id, "dd")))
    # 3페이즈 견제(승리가 임박한 나라와 전쟁 중): 폭격기·구축함·상륙함, 낮은 가중치로 항공모함
    h_tgt, urg = EG.harass(g, f) if f.is_ai else (None, 0.0)
    if military and h_tgt is not None and D.at_war(g, fid, h_tgt):
        _harass_production(g, f, regs, idle, idle_ids, airports, cands, urg, h_tgt)
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
            p_tank = 0.35 * (1 + C.AI_P2_CONQ_TANK * conq_rich) * bias("tank") / bias("inf")
            if g.can_pay_oil(fid, C.UNITS["tank"]["oil"]) and f.money > 3000 and g.rng.random() < p_tank:
                key = "tank"
            elif g.rng.random() < (0.28 if at_war else 0.15) * bias("art") / bias("inf") and f.money > 3000:
                key = "art"                    # 전쟁 중엔 선제 폭격용 포병을 더
            per = g.unit_cost(fid, r.id, key)
            u = (1.5 + threat.get(r.id, 0)) * wts.get("military", 1) * bias(key)
            cands.append((u, r.id, "unit", key, None, per))
    # 정복 방향: 모아 둔 돈을 군비로 — 군 유지비가 세수의 30%가 될 때까지 위협이 큰 곳부터 전차·포병을 더 뽑는다
    if military and conq_rich > 0 and post != "crisis":
        mil_up = sum(C.UNITS[k]["upkeep"] * n for a in g.armies.values() if a.owner == fid
                     for k, n in a.units.items() if k in C.UNITS)
        room = C.AI_P2_CONQ_UPKEEP * income - mil_up
        n_extra = min(int(room // C.UNITS["tank"]["upkeep"]), C.AI_P2_CONQ_EXTRA + len(regs) // 30)
        if n_extra > 0:
            busy = {c[1] for c in cands if c[2] == "unit"}
            safe = min(C.CONSCRIPT_PENALTY) - 1
            pool = sorted([r for r in idle if r.id not in busy and g.drafted_turns(r.id) < safe],
                          key=lambda r: (-threat.get(r.id, 0), r.id))
            oil_ok = g.can_pay_oil(fid, C.UNITS["tank"]["oil"])
            for i, r in enumerate(pool[:n_extra]):
                key = "art" if i % 3 == 2 else ("tank" if oil_ok else "inf")
                cands.append(((1.2 + conq_rich) * bias(key), r.id, "unit", key, None, g.unit_cost(fid, r.id, key)))
    # 과학승리 단계: 과학이 목표일 때만(다른 방향은 그 방향에 돈을 모은다)
    sci_goal = f.is_ai and f.ai.get("victory_goal") == "science"
    step = g.science_next(fid) if (sci_goal and "science" in g.settings.victories) else None
    if step is not None and g.science_busy(fid, step) is None and big_ok:
        sc_turns = g.science_turns(fid)
        sc_total = g.science_step_cost(fid, step)
        sc_per = sc_total / sc_turns
        sm, si = 2.0 / bias("science"), 0.3 / bias("science")
        if ((f.money > sc_per * sm and income - upkeep > sc_per * si) or f.money > sc_total * 1.1
                or f.money > sc_per * C.AI_P3_SPRINT_START):    # 과학 방향: 2턴분만 있어도 착수(모자라면 멈췄다 이어서)
            sites = [r for r in regs if g.science_site_ok(fid, r.id, step) and not r.project and not r.occ
                     and not g.resisting(r)]
            if sites:
                # 위협이 적고 수도에 가까운 곳(유닛은 발사대까지 옮겨야 한다)
                dist = g.world.distances_from(f.capital, 30)
                best = min(sites, key=lambda r: (threat.get(r.id, 0), dist.get(r.id, 99)))
                if g.start_project(fid, best.id, "science", step)[0] and spr == "science":
                    best.project.priority = -1        # 질주: 승리 조건 공사에 돈을 먼저
            elif step in ("booster", "module", "budget"):
                # 공장(예산 편성은 은행) 5단계 지역이 없으면 가장 높은 곳부터 올린다
                bk = "bank" if step == "budget" else "factory"
                pool_f = [r for r in idle if r.b[bk] < 5]
                if pool_f:
                    r0 = max(pool_f, key=lambda r: (r.b[bk], r.pop))
                    lv = r0.b[bk] + 1
                    cost = R.prod_building_cost(bk, lv) * (g.mods(fid).mult("cost_factory") if bk == "factory" else 1)
                    turns = g.build_time(fid, bk, R.prod_building_turns(lv))
                    cands.append((3.0, r0.id, "build", bk, None, cost / turns))
    if big_ok:
        _econ_orders(g, f, regs, idle, cands, threat, income, upkeep, bias)
    cands.sort(key=lambda c: -c[0])
    used = set()
    for u, rid, kind, key, border, per in cands:
        if rid in used or u <= 0.05:
            continue
        # 적자인 1페이즈: 재정을 늘리는 생산 건물은 비축(비상금 위)으로도 짓는다
        prod_from_savings = (deficit and kind == "build" and key in C.PROD_PAYBACK_KEYS
                             and f.money - reserve >= per * 3)
        if per > avail and not (kind == "unit" and f.money > per * 2) and not prod_from_savings:
            continue
        ok, _ = g.start_project(fid, rid, kind, key, border=border)
        if ok:
            used.add(rid)
            avail -= per
        if avail <= 0:
            break
    if f.is_ai and PH.phase(f) >= 2:
        _fill_slots(g, f, [r for r in idle if r.id not in used and not r.project], post, reserve, income, upkeep, spr)


def _harass_production(g, f, regs, idle, idle_ids, airports, cands, urg, t):
    """견제 전쟁의 생산 후보: 폭격기(공항), 구축함·상륙함(항구, 대상 해안이 바다로 닿으면),
    공항과 항구가 함께 있는 지역에 항공모함(낮은 가중치, 폭격기를 태워 대상 앞바다에서 폭격)."""
    fid = f.id
    w = g.world
    units = lambda k: sum(a.units.get(k, 0) for a in g.armies.values() if a.owner == fid)
    n_bmb, n_dd, n_lst, n_cv = units("bmb"), units("dd"), units("lst"), units("cv")
    ap_idle = [r for r in airports if r.id in idle_ids]
    if ap_idle and n_bmb < 2 + len(regs) // 20 and g.can_pay_oil(fid, C.UNITS["bmb"]["oil"]) and f.money > 4000:
        cands.append((2.0 * urg + 0.5, ap_idle[0].id, "unit", "bmb", None, g.unit_cost(fid, ap_idle[0].id, "bmb")))
    t_regs = {r.id for r in g.regions_of(t)}
    seas = {s_ for r in regs if w.regions[r.id].coastal for s_ in w.regions[r.id].seas}
    seas |= {s2 for s_ in list(seas) for s2 in w.seas[s_].adj}
    if not any(v in t_regs for s_ in seas for v in w.seas[s_].coast):
        return                                    # 바다로 닿지 않는다
    ports = [r for r in regs if r.b["port"]]
    ports_idle = [r for r in ports if r.id in idle_ids]
    if not ports:
        coast = [r for r in idle if w.regions[r.id].coastal]
        if coast and f.money > 6000:
            cost = C.SINGLE_BUILDINGS["port"]["cost"] * C.BUILD_COST_MULT
            cands.append((1.5 * urg + 0.5, coast[0].id, "build", "port", None, cost / C.SINGLE_BUILDINGS["port"]["turns"]))
        return
    # 대상의 승리 거점이 해안이면 상륙함을 먼저(방어선을 돌아 거점에 상륙), 아니면 구축함(함포로 수비대를 깎는다)
    coast_key = any(EG.key_value(g, v) >= 6 for s_ in seas for v in w.seas[s_].coast if v in t_regs)
    lst_ok = ports_idle and g.can_pay_oil(fid, C.UNITS["lst"]["oil"]) and f.money > 2000 and n_lst < 1 + coast_key + len(regs) // 30
    dd_ok = ports_idle and g.can_pay_oil(fid, C.UNITS["dd"]["oil"]) and f.money > 4000 and n_dd < 2 + len(regs) // 30
    if lst_ok and (coast_key and n_lst <= n_dd or not dd_ok):
        cands.append((1.8 * urg + 0.5, ports_idle[-1].id, "unit", "lst", None, g.unit_cost(fid, ports_idle[-1].id, "lst")))
    elif dd_ok:
        cands.append((1.8 * urg + 0.4, ports_idle[0].id, "unit", "dd", None, g.unit_cost(fid, ports_idle[0].id, "dd")))
    # 항공모함: 폭격기가 있고 공항·항구가 함께 있는 지역(없으면 항구 지역에 공항)
    if n_cv == 0 and n_bmb >= 1 and f.money > 8000:
        both = [r for r in ports if r.b["airport"] and r.id in idle_ids]
        if both and g.can_pay_oil(fid, C.UNITS["cv"]["oil"]):
            cands.append((C.AI_P3_HARASS_CV * urg, both[0].id, "unit", "cv", None, g.unit_cost(fid, both[0].id, "cv")))
        elif not any(r.b["airport"] for r in ports) and ports_idle:
            cost = C.SINGLE_BUILDINGS["airport"]["cost"] * C.BUILD_COST_MULT
            cands.append((0.8 * C.AI_P3_HARASS_CV * urg, ports_idle[0].id, "build", "airport", None,
                          cost / C.SINGLE_BUILDINGS["airport"]["turns"]))


def _fill_slots(g, f, idle, post, reserve, income, upkeep, spr=""):
    """돈이 남는데 노는 땅(2페이즈): 자금 부족으로 공사가 멈추지 않는 범위에서 채운다.
    ① 경계 태세면 국경·해안 지역에 방어 시설 ② 발전소: 석탄·석유 채굴량만큼 ③ 공장: 발전·자체 전기 생산량만큼
    ④ 농장·어장·은행·채굴(완공 뒤 비용 없음)은 계속. 그래도 남는 땅은 생산 집중(plan_turn)."""
    fid = f.id
    if not idle or post == "crisis":
        return
    regs = g.regions_of(fid)
    all_committed = sum(r.project.per_turn for r in regs if r.project)
    net = income - upkeep - all_committed
    # 지금 공사 총비용을 다 대도 자금이 비상금 아래로 떨어지지 않을 만큼만(멈춤 방지): 여윳돈 절반 + 남는 순수입 12턴분
    budget = max(0.0, f.money - reserve) * C.AI_FILL_SAVINGS + max(0.0, net) * C.AI_FILL_NET_TURNS
    if spr in ("science", "economic"):
        # 질주: 승리 조건 공사 몇 턴분은 남겨 두고 나머지 여윳돈으로 지킨다
        big = sum(r.project.per_turn for r in regs if r.project and r.project.kind in ("science", "econ"))
        budget -= max(big, C.SCIENCE_COST_PER_TURN * C.MONEY_SCALE) * C.AI_P3_SPRINT_KEEP
    if budget <= 0:
        return
    pool = sorted(idle, key=lambda r: (-r.pop, r.id))
    used = set()

    def start(r, key, border=None, cost=None):
        nonlocal budget
        if cost is None or cost > budget:
            return False
        if g.start_project(fid, r.id, "build", key, border=border)[0]:
            used.add(r.id)
            budget -= cost
            return True
        return False

    # ① 경계(또는 3페이즈 질주): 국경·해안 지역 방어 시설(같은 단계면 방어선 우선, 3단계까지, 질주면 4단계)
    if post == "defend" or spr:
        top = C.AI_P3_SPRINT_DEF_LV if spr else C.AI_DEF_MAX_LEVEL
        for r in pool:
            if r.id in used:
                continue
            borders = [n for n in g.world.land_adj[r.id] if g.regions[n].owner not in (NEUTRAL, fid)]
            if g.info(r.id).coastal:
                borders.append("coast")
            if not borders:
                continue
            bkey = min(borders, key=lambda n: (r.lines.get(n, 0), D.opinion(g, fid, g.regions[n].owner) if n != "coast" else 0))
            opts = [(r.lines.get(bkey, 0), 0, "line", bkey), (r.b["shelter"], 1, "shelter", None), (r.b["aa"], 2, "aa", None)]
            lv, _, key, border = min(opts)
            if lv >= top:
                continue
            cost = R.def_building_cost(key, lv + 1) * (g.mods(fid).mult("cost_line") if key == "line" else 1)
            start(r, key, border, cost)
    # ② 발전소: 발전소 용량(단계 합)이 석탄·석유 채굴량에 닿을 때까지
    mined = g.energy_mined(fid)
    plants, facts = g.energy_sites(fid)
    room = mined["coal"] + mined["oil"] - sum(r.b["power"] for r in regs) - sum(
        1 for r in regs if r.project and r.project.key == "power")
    for r in sorted((r for r in pool if r.id not in used and r.b["power"] < 5),
                    key=lambda r: (not g.info(r.id).power_site, -r.b["power"], -r.pop, r.id)):
        if room <= 0:
            break
        if start(r, "power", cost=R.prod_building_cost("power", r.b["power"] + 1, g.info(r.id).power_site)):
            room -= 1
    # ③ 공장: 공장의 전기 소비(단계 합)가 전기 생산(자체 발전 + 발전소 변환)에 닿을 때까지
    cap = sum(r.b["power"] for r in plants)
    conv_oil = min(cap, mined["oil"])
    conv_coal = min(cap - conv_oil, mined["coal"])
    elec = mined["elec"] + C.POWER_ELEC["oil"] * conv_oil + C.POWER_ELEC["coal"] * conv_coal
    need = elec - sum(r.b["factory"] for r in regs) - sum(1 for r in regs if r.project and r.project.key == "factory")
    for r in sorted((r for r in pool if r.id not in used and r.b["factory"] < 5),
                    key=lambda r: (-r.b["factory"], -r.pop, r.id)):
        if need <= 0:
            break
        cost = R.prod_building_cost("factory", r.b["factory"] + 1) * g.mods(fid).mult("cost_factory")
        if start(r, "factory", cost=cost):
            need -= 1
    # ④ 완공 뒤 비용이 없는 생산 건물: 산출(·식량)이 가장 많이 느는 것
    tax = max(0.05, f.tax)
    for r in pool:
        if r.id in used:
            continue
        info = g.info(r.id)
        opts = []
        for key in ("farm", "fishery", "bank"):
            lv = r.b[key] + 1
            if lv > 5 or (key == "fishery" and not g.can_fish(r.id)):
                continue
            cost = R.prod_building_cost(key, lv)
            val = _delta_output(g, r.id, key) * tax + (C.FOOD_PER_G * C.MARKET_SELL["food"] if key != "bank" else 0)
            opts.append((val / cost, key, cost))
        if (info.is_oil or info.is_coal) and r.b["extract"] < 5:
            cost = R.prod_building_cost("extract", r.b["extract"] + 1)
            opts.append((C.MARKET_SELL["oil" if info.is_oil else "coal"] / cost, "extract", cost))
        if opts:
            _, key, cost = max(opts)
            start(r, key, cost=cost)
