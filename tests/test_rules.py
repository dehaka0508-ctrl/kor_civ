import pytest

from korciv import config as C
from korciv import rules as R
from korciv.data import load_world


def test_level_multiplier():
    assert [R.g(l) for l in range(1, 6)] == pytest.approx([1.0, 2.4, 4.2, 6.4, 9.0])


def test_start_outputs_match_design_doc():
    w = load_world()
    n = w.name_to_id

    def y(name):
        r = w.regions[n[name]]
        return R.region_output(r.pop0, r.farm, r.fishery, r.factory, r.bank, False, 1.0)

    assert y("서울 강남구") == pytest.approx(3096)
    assert y("경북 김천시") == pytest.approx(2356)
    assert y("강원 인제군") == pytest.approx(243)
    total = sum(R.region_output(r.pop0, r.farm, r.fishery, r.factory, r.bank, False) for r in w.regions.values())
    assert total == pytest.approx(743016, rel=1e-3)


def test_building_costs():
    costs = [round(R.prod_building_cost("farm", l), -1) for l in range(1, 6)]
    assert costs == [400, 1130, 2080, 3200, 4470]
    assert round(R.prod_building_cost("factory", 5), -1) == 16770
    assert round(R.def_building_cost("line", 3)) == 1559
    assert [R.prod_building_turns(l) for l in range(1, 6)] == [2, 4, 6, 8, 10]


def test_occupation_turns():
    assert R.occupation_turns(10) == 1
    assert R.occupation_turns(30) == 2
    assert R.occupation_turns(50) == 3
    assert R.occupation_turns(70) == 6
    assert R.occupation_turns(90) == 11
    assert R.occupation_turns(120) == 15
    assert R.enemy_occupation_turns(70, -40) == 4


def test_rebellion_probability():
    assert R.rebellion_probability(-49) == 0
    assert R.rebellion_probability(-50) == pytest.approx(0.01)
    assert R.rebellion_probability(-75) == pytest.approx(0.10)
    assert R.rebellion_probability(-100) == pytest.approx(1.0)


def test_battle_example_10_vs_10_infantry():
    a = 10 * C.UNITS["inf"]["atk"]
    d = 10 * C.UNITS["inf"]["df"]
    dd, ad = R.battle_damage(a, d, 1.0)
    assert dd / C.UNITS["inf"]["hp"] == pytest.approx(2.27, abs=0.01)
    assert ad / C.UNITS["inf"]["hp"] == pytest.approx(3.27, abs=0.01)


def test_pop_growth_and_tax_happiness():
    assert R.pop_growth_rate(9) == 0
    assert R.pop_growth_rate(10) == pytest.approx(C.G_MAX * 0.1)
    assert R.pop_growth_rate(60) == pytest.approx(C.G_MAX)
    assert R.tax_happiness(0) == pytest.approx(1.0)
    assert R.tax_happiness(20) == pytest.approx(-1.0)
    assert R.tax_happiness(50) == pytest.approx(-4.0)
    assert R.tax_happiness(20, over10_mult=0.7) == pytest.approx(-0.7)


def test_surprise_chance_and_dates():
    assert R.surprise_chance(0) == pytest.approx(0.9)
    assert R.surprise_chance(5) == pytest.approx(0.15)
    assert R.date_label(1) == "2026년 1월 1주 · 턴 1"
    assert R.date_label(10) == "2026년 3월 2주 · 턴 10"
    assert R.date_label(49) == "2027년 1월 1주 · 턴 49"


def test_region_value_turn_table():
    assert [R.value_turns(v) for v in range(1, 11)] == [1, 2, 3, 4, 6, 8, 10, 13, 16, 20]
    assert R.value_turns(10, 1.2) == 24          # 가야 수로왕 +20%
    assert R.region_value(0.0) == 1 and R.region_value(99) == 10
    big = sum(R.region_value_parts(7000, 100, 8, 1, 0, 0, 0, 1, 0, 1).values())
    small = sum(R.region_value_parts(250, 2.5, 1, 0, 0, 0, 0, 0, 0, 0).values())
    assert R.region_value(big) >= 9 and R.region_value(small) <= 2
    # 자원·특산물도 가치를 올린다
    base = R.region_value_parts(800, 5, 2, 0, 0, 0, 0, 0, 0, 0)
    rich = R.region_value_parts(800, 5, 2, 0, 1, 1, 0, 0, 0, 1)
    assert sum(rich.values()) > sum(base.values()) + 3
    # 편입 비용: 산출에 비례하고 보유 지역이 많을수록 비싸다
    assert R.annex_cost(1000, 100) == pytest.approx(R.annex_cost(1000, 0) * 2)   # 1%/지역
