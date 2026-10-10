"""기획서의 공식들. 상태를 바꾸지 않는 순수 함수만 둔다."""
from __future__ import annotations

import math

from . import config as C


def g(level: int) -> float:
    """단계 배수 g(L) = L (1 + 0.2 (L - 1)). 1~5단계: 1.0, 2.4, 4.2, 6.4, 9.0"""
    if level <= 0:
        return 0.0
    return level * (1 + C.LEVEL_GROWTH * (level - 1))


def factory_output(level: int, fuel=None) -> float:
    """공장: 연료 1개당 단계별 산출(1000/1200/1400/1600/2000), 단계 L이면 L개까지. fuel=None 이면 가득."""
    if level <= 0:
        return 0.0
    n = level if fuel is None else max(0, min(level, fuel))
    return C.FACTORY_UNIT_OUTPUT[min(level, 5) - 1] * n


def region_output(pop, farm, fishery, factory, bank, fuel=None,
                  fish_mult=1.0, bank_mult=1.0, factory_mult=1.0, pop_mult=1.0, prod_mult=1.0, farm_mult=1.0) -> float:
    """Y = 30P + 150g(F) + 150g(S) + 1000g(M)φ + 600g(B) (pop_mult: 생산 집중, prod_mult: 생산 건물분)"""
    return (C.POP_OUTPUT * pop * pop_mult
            + (C.FARM_OUTPUT * farm * farm_mult           # 농장·어장은 단계에 비례
               + C.FISH_OUTPUT * fishery * fish_mult
               + factory_output(factory, fuel) * factory_mult
               + C.BANK_OUTPUT * g(bank) * bank_mult) * prod_mult)


def food_output(farm, fishery, fish_mult=1.0) -> float:
    return C.FOOD_PER_G * (farm + fishery * fish_mult)


def prod_building_cost(key: str, level: int, power_site=False) -> float:
    if key in ("farm", "fishery"):           # 턴당 200/400/800/1400/2000 × 소요 턴
        return C.FOOD_BUILD_COST_TURN[level - 1] * prod_building_turns(level) * C.MONEY_SCALE
    base = C.PROD_BUILDINGS[key]["base"]
    cost = base * level ** 1.5 * C.BUILD_COST_MULT
    if key == "power" and power_site:
        cost *= C.POWER_SITE_DISCOUNT
    return cost * C.MONEY_SCALE


def prod_building_turns(level: int) -> int:
    return C.PROD_TURNS_PER_LEVEL * level


def def_building_cost(key: str, level: int) -> float:
    return C.DEF_BUILDINGS[key]["base"] * level ** 1.5 * C.BUILD_COST_MULT * C.MONEY_SCALE


def unhappy_output_mult(h: float) -> float:
    """행복도가 음수면 산출 감소: 처음엔 완만하고 낮을수록 가파르게(−100에서 −30%)."""
    if h >= 0:
        return 1.0
    x = min(1.0, -h / 100)
    return 1 - C.UNHAPPY_OUTPUT_MAX * x ** C.UNHAPPY_OUTPUT_EXP


def unhappy_combat_mult(h: float) -> float:
    """사기: 실질 평균 행복도가 −10 이하이면 산출 감소와 같은 곡선으로 전투력 감소."""
    if h > C.MORALE_H:
        return 1.0
    return unhappy_output_mult(h)


def conscript_penalty(n: int) -> float:
    """최근 10턴 중 군 생산에 쓴 턴 수 -> 행복도 감소량(6턴 1, 7턴 2, 8턴 4, 9턴 6, 10턴 10)."""
    return C.CONSCRIPT_PENALTY.get(min(n, C.CONSCRIPT_WINDOW), 0.0)


def science_cost_mult(step_index: int) -> float:
    """과학 단계 k(0부터) 비용 배수 1.1^k."""
    return C.SCIENCE_COST_GROWTH ** max(0, step_index)


def def_building_turns(level: int) -> int:
    return C.DEF_TURNS[level - 1]


def occupation_turns(pop: float) -> int:
    """T(P) = round(15^((P-10)/90)), P<=10 이면 1, P>=100 이면 15"""
    if pop <= 10:
        return 1
    if pop >= 100:
        return C.OCC_MAX_TURNS
    return max(1, int(math.floor(15 ** ((pop - 10) / 90) + 0.5)))


def enemy_occupation_turns(pop: float, happiness: float, time_mult=1.0) -> int:
    t = occupation_turns(pop) * (1 + happiness / 100)
    return max(1, int(math.floor(t * time_mult + 0.5)))


def region_value_parts(output, pop, levels, singles, oil, coal, power_self, power_site, extract,
                       n_specialty) -> dict:
    """지역 가치 점수의 구성(인구·건물·산출·자원·특산물)."""
    return {
        "산출": max(0.0, math.log2(max(output, 1) / 200)),
        "인구": 0.8 * math.log2(1 + max(pop, 0) / 5),
        "건물": min(3.0, 0.3 * levels + 0.5 * singles),
        "자원": min(3.0, 1.5 * oil + 1.0 * coal + 0.7 * power_self + 0.5 * power_site + 0.5 * extract),
        "특산물": 0.8 * n_specialty,
    }


def region_value(score: float) -> int:
    """점수 -> 가치 1~10."""
    return 1 + sum(1 for th in C.VALUE_THRESHOLDS if score >= th)


def value_turns(value: int, time_mult=1.0) -> int:
    """가치 1~10 -> 편입·점령 턴 1,2,3,4,6,8,10,13,16,20."""
    t = C.VALUE_TURNS[max(1, min(10, value)) - 1]
    if time_mult > 1:
        return max(1, int(math.floor(t * time_mult + 1e-9)))   # 늘어나는 쪽(수로왕 '연맹 체제')은 소수점 버림
    return max(1, int(math.floor(t * time_mult + 0.5)))


def joint_reduction(n: int) -> float:
    """동시에 편입하는 지역 수 n -> 소요 시간 감소율."""
    if n <= 1:
        return 0.0
    return C.JOINT_ANNEX_REDUCTION[min(n, max(C.JOINT_ANNEX_REDUCTION))]


def joint_turns(base_turns: int, n: int) -> int:
    return max(1, math.ceil(base_turns * (1 - joint_reduction(n)) - 1e-9))


def annex_cost(output: float, owned_regions: int = 0) -> float:
    base = C.ANNEX_BASE_COST + C.ANNEX_COST_OUTPUT * output
    return base * (1 + C.ANNEX_COST_PER_REGION * owned_regions) * C.MONEY_SCALE


def rebellion_probability(h: float) -> float:
    """p(H) = 0.01 * 100^((-50-H)/50), H <= -50"""
    if h > C.REBEL_THRESHOLD:
        return 0.0
    return min(1.0, 0.01 * 100 ** ((C.REBEL_THRESHOLD - h) / 50))


def pop_growth_rate(h: float, g_max: float = C.G_MAX) -> float:
    """g_pop(H) = G_MAX (0.1 + 0.9 clamp((H-5)/40, 0, 1)), H<5 이면 0"""
    if h < C.POP_GROWTH_MIN_H:
        return 0.0
    x = max(0.0, min(1.0, (h - C.POP_GROWTH_MIN_H) / 40))
    return g_max * (0.1 + 0.9 * x)


def tax_happiness(t_pct: float, over10_mult=1.0, over15_mult=1.0, base_pct=10.0) -> float:
    """0.1 (기준 − t%). 기준 세율은 10%(전제군주제 12%). 감소분에 체제·지도자 배수 적용.
    over10_mult(당 태종 '정관의 치')는 세율 TAX_OVER10_CAP%까지만: 그 위는 그때 줄어든 만큼만 덜 깎인다."""
    base = C.TAX_HAPPY_K * (base_pct - t_pct)
    if base >= 0:
        return base

    def seg(lo, hi):
        return max(0.0, min(t_pct, hi) - lo) if hi > lo else 0.0
    cap = max(base_pct, C.TAX_OVER10_CAP)
    mid = base_pct + 5
    # 감소분을 기준~기준+5%, 그 초과 구간으로 나누고, 각 구간을 상한 안·밖으로 다시 나눠 배수 적용
    p1_in = seg(base_pct, min(mid, cap))
    p1_out = seg(base_pct, mid) - p1_in
    p2_in = seg(mid, max(mid, cap))
    p2_out = seg(mid, float("inf")) - p2_in
    loss = (p1_in * over10_mult + p1_out) + (p2_in * over10_mult + p2_out) * over15_mult
    return -loss * C.TAX_HAPPY_K


def battle_damage(a: float, d: float, r: float) -> tuple[float, float]:
    """(방어측 피해, 공격측 피해) = 0.5 r A²/(A+D), 0.5 r D²/(A+D)"""
    if a + d <= 0:
        return 0.0, 0.0
    return C.DAMAGE_K * r * a * a / (a + d), C.DAMAGE_K * r * d * d / (a + d)


def surprise_chance(line_level: int, bonus: float = 0.0) -> float:
    return max(0.0, min(1.0, C.SURPRISE_BASE - C.SURPRISE_PER_LINE * line_level + bonus))


def surprise_mults(line_level: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """기습 (성공 시 (공격 피해, 반격), 실패 시 (공격 피해, 반격)). 방어선이 높을수록 실패 벌칙이 커진다."""
    k = C.SURPRISE_FAIL_PER_LINE * max(0, line_level)
    return C.SURPRISE_WIN, (max(0.1, C.SURPRISE_FAIL[0] - k), C.SURPRISE_FAIL[1] + k)


def bomb_building_chance(guns: bool, air: bool) -> float:
    """폭격으로 건물 1단계를 부술 확률: 포병·함포 30%, 폭격기 60%, 둘 다 90%."""
    if guns and air:
        return C.BOMB_HIT_BOTH
    if air:
        return C.BOMB_HIT_AIR
    return C.BOMB_HIT_GUN if guns else 0.0


def date_of_turn(turn: int) -> tuple[int, int, int]:
    """턴 1 = 2026년 1월 1주."""
    t = turn - 1
    year = C.START_YEAR + t // C.TURNS_PER_YEAR
    month = (t % C.TURNS_PER_YEAR) // C.TURNS_PER_MONTH + 1
    week = t % C.TURNS_PER_MONTH + 1
    return year, month, week


def date_label(turn: int) -> str:
    y, m, w = date_of_turn(turn)
    return f"{y}년 {m}월 {w}주 · 턴 {turn}"
