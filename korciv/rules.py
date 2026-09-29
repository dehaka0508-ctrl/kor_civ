"""기획서의 공식들. 상태를 바꾸지 않는 순수 함수만 둔다."""
from __future__ import annotations

import math

from . import config as C


def g(level: int) -> float:
    """단계 배수 g(L) = L (1 + 0.2 (L - 1)). 1~5단계: 1.0, 2.4, 4.2, 6.4, 9.0"""
    if level <= 0:
        return 0.0
    return level * (1 + C.LEVEL_GROWTH * (level - 1))


def region_output(pop, farm, fishery, factory, bank, landmark, phi=1.0,
                  fish_mult=1.0, bank_mult=1.0, factory_mult=1.0) -> float:
    """Y = 30P + 150g(F) + 150g(S) + 1000g(M)φ + 600g(B) + 9000K"""
    return (C.POP_OUTPUT * pop
            + C.FARM_OUTPUT * g(farm)
            + C.FISH_OUTPUT * g(fishery) * fish_mult
            + C.FACTORY_OUTPUT * g(factory) * phi * factory_mult
            + C.BANK_OUTPUT * g(bank) * bank_mult
            + C.LANDMARK_OUTPUT * (1 if landmark else 0))


def food_output(farm, fishery, fish_mult=1.0) -> float:
    return C.FOOD_PER_G * (g(farm) + g(fishery) * fish_mult)


def prod_building_cost(key: str, level: int, power_site=False) -> float:
    base = C.PROD_BUILDINGS[key]["base"]
    cost = base * level ** 1.5
    if key == "power" and power_site:
        cost *= C.POWER_SITE_DISCOUNT
    return cost * C.MONEY_SCALE


def prod_building_turns(level: int) -> int:
    return C.PROD_TURNS_PER_LEVEL * level


def def_building_cost(key: str, level: int) -> float:
    return C.DEF_BUILDINGS[key]["base"] * level ** 1.5 * C.MONEY_SCALE


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


def annex_cost(pop: float) -> float:
    return (C.ANNEX_BASE_COST + C.ANNEX_COST_PER_POP * pop) * C.MONEY_SCALE


def rebellion_probability(h: float) -> float:
    """p(H) = 0.01 * 100^((-50-H)/50), H <= -50"""
    if h > C.REBEL_THRESHOLD:
        return 0.0
    return min(1.0, 0.01 * 100 ** ((C.REBEL_THRESHOLD - h) / 50))


def pop_growth_rate(h: float, g_max: float = C.G_MAX) -> float:
    """g_pop(H) = G_MAX (0.1 + 0.9 clamp((H-10)/40, 0, 1)), H<10 이면 0"""
    if h < C.POP_GROWTH_MIN_H:
        return 0.0
    x = max(0.0, min(1.0, (h - C.POP_GROWTH_MIN_H) / 40))
    return g_max * (0.1 + 0.9 * x)


def tax_happiness(t_pct: float, over10_mult=1.0, over15_mult=1.0) -> float:
    """0.1 (10 - t%). 감소분에 체제·지도자 배수 적용."""
    base = C.TAX_HAPPY_K * (10 - t_pct)
    if base >= 0:
        return base
    # 감소분을 10~15%, 15% 초과 구간으로 나눠 배수 적용
    part_10_15 = max(0.0, min(t_pct, 15) - 10) * C.TAX_HAPPY_K
    part_15 = max(0.0, t_pct - 15) * C.TAX_HAPPY_K
    return -(part_10_15 * over10_mult + part_15 * over10_mult * over15_mult)


def battle_damage(a: float, d: float, r: float) -> tuple[float, float]:
    """(방어측 피해, 공격측 피해) = 0.5 r A²/(A+D), 0.5 r D²/(A+D)"""
    if a + d <= 0:
        return 0.0, 0.0
    return C.DAMAGE_K * r * a * a / (a + d), C.DAMAGE_K * r * d * d / (a + d)


def surprise_chance(line_level: int, bonus: float = 0.0) -> float:
    return max(0.0, min(1.0, C.SURPRISE_BASE - C.SURPRISE_PER_LINE * line_level + bonus))


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
