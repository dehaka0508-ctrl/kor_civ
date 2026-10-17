"""광역시(v1.2.19) 시스템 테스트."""
import math

import pytest

from korciv import config as C
from korciv import diplomacy as D
from korciv import metro as M
from korciv import rules as R
from korciv.state import NEUTRAL

from test_engine import _clear, _neutral_ai, _own, new_game


def _setup(n_extra=3, **kw):
    """플레이어 수도 서울 강남(S002)과 이웃 지역들을 광역시 조건에 맞춘다."""
    g = new_game(player_start="S002", n_enemies=1, **kw)
    _neutral_ai(g, 1)
    nb = sorted(g.world.land_adj["S002"])[:n_extra]
    _own(g, 0, nb)
    sel = ["S002"] + nb
    for r in sel:
        rr = g.regions[r]
        rr.resist, rr.project, rr.happy = None, None, 10.0
        rr.b["farm"] = 5
    g.regions["S002"].b["factory"] = 5
    g.regions[nb[0]].b["bank"] = 5
    g.player.money = 10 ** 7
    return g, sel


def test_designation_conditions_and_names():
    g, sel = _setup()
    ok, items = M.check(g, 0, "S002", sel)
    assert ok, items
    # 조건: 공업 단지가 없으면 안 됨
    g.regions["S002"].b["factory"] = 4
    ok, items = M.check(g, 0, "S002", sel)
    assert not ok and not dict((k, o) for k, o, _ in items)["공업 단지(공장 5단계)"]
    g.regions["S002"].b["factory"] = 5
    # 평균 행복도 0 미만이면 안 됨
    for r in sel:
        g.regions[r].happy = -5
    assert not M.check(g, 0, "S002", sel)[0]
    for r in sel:
        g.regions[r].happy = 10
    # 2칸 밖·남의 땅·떨어진 지역은 고를 수 없다
    far = next(r for r in g.world.order if r not in M.distances(g, "S002", 2))
    assert not M.check(g, 0, "S002", sel + [far])[0]
    # 이름: 수도가 중심이면 특별시, 비우면 중심 지역 이름
    assert M.default_name(g, 0, "S002") == g.info("S002").short + "특별시"
    assert M.full_name(g, 0, "S002", "한강") == "한강특별시"
    ok, msg = g.create_metro(0, "S002", sel, "")
    assert ok, msg
    m = M.of(g, "S002")
    assert m["name"] == g.info("S002").short + "특별시" and set(m["members"]) == set(sel)
    assert all(g.regions[r].metro == m["id"] for r in sel)
    assert not M.check(g, 0, "S002", sel)[0]                  # 이미 광역시


def test_pooled_levels_output_and_fuel():
    """농장·공장·탄광은 평균 단계(내림)를 구성 지역마다 적용 → 산출·연료가 '평균 단계 × 지역 수'."""
    g, sel = _setup()
    levels = [5, 4, 5, 4]                                     # 농장 합 18 → 평균 4.5 → 4
    for r, lv in zip(sel, levels):
        g.regions[r].b["farm"] = lv
    facs = [5, 3, 0, 2]                                       # 공장 합 10 → 평균 2.5 → 2
    for r, lv in zip(sel, facs):
        g.regions[r].b["factory"] = lv
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    assert [g.regions[r].b["farm"] for r in sel] == [4] * 4
    assert [g.regions[r].b["factory"] for r in sel] == [2] * 4
    assert sum(g.regions[r].b["factory"] for r in sel) == 2 * len(sel)          # 연료 최대 = 2단계 × 지역 수
    # 하나라도 하천 농장이면 전체가 하천 농장
    assert any(g.river_farm(r) for r in sel)
    assert all(g.farm_mult(0, r) == pytest.approx(g.mods(0).mult("output_farm") * C.RIVER_FARM_MULT) for r in sel)


def test_coal_pool_example():
    """탄광 2단계 + 3단계 → 광역 탄광 2단계, 석탄 4개(탄전 지역끼리만 평균)."""
    g = new_game(n_enemies=1, meet=True)
    _neutral_ai(g, 1)
    coal = [r for r in g.world.order if g.info(r).is_coal]
    a = next(r for r in coal if any(n in coal for n in g.world.land_adj[r]))
    b = next(n for n in sorted(g.world.land_adj[a]) if n in coal)
    _own(g, 0, [a, b])
    for r in (a, b):
        rr = g.regions[r]
        rr.resist, rr.project, rr.happy = None, None, 5
        rr.pop = max(rr.pop, 60)
        rr.b.update(farm=5, factory=5, bank=5)
    g.regions[a].b["extract"], g.regions[b].b["extract"] = 2, 3
    ok, msg = g.create_metro(0, a, [a, b])
    assert ok, msg
    assert g.regions[a].b["extract"] == 2 and g.regions[b].b["extract"] == 2
    assert sum(g.regions[r].b["extract"] for r in (a, b)) == 4


def test_metro_slot_build_upgrades_all_and_level6():
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    n = len(sel)
    opts = g.options(0, sel[1])                              # 어느 구성 지역에서 열어도 광역시 선택지
    o = next(o for o in opts if o["kind"] == "build" and o["key"] == "bank")
    lv = M.pool_level(g, M.of(g, "S002"), "bank") + 1
    assert o["level"] == lv and o["cost"] == pytest.approx(R.prod_building_cost("bank", lv) * n)
    ok, msg = g.start_project(0, sel[2], "build", "bank")
    assert ok, msg
    p = g.regions["S002"].project
    assert all(g.regions[r].project is p for r in sel) and len(g.projects_by_priority(0)) == 1
    for _ in range(p.turns):
        g._fund_projects()
        g._phase_projects(("build",))
    assert all(g.regions[r].b["bank"] == lv for r in sel) and all(g.regions[r].project is None for r in sel)
    # 6단계는 광역시만: 은행 6단계 산출 = 5단계 × 1.2, 첨단산업단지 연료 1개당 2000 × 1.1·6개까지
    for r in sel:
        g.regions[r].b["bank"] = 5
        g.regions[r].b["factory"] = 5
    o6 = next(o for o in g.options(0, "S002") if o["kind"] == "build" and o["key"] == "bank")
    assert o6["level"] == 6 and "종합금융본부" in o6["name"]
    assert R.g(6) == pytest.approx(R.g(5) * 1.2)
    assert R.factory_unit(6) == pytest.approx(2200) and R.factory_output(6) == pytest.approx(2200 * 6)
    assert R.region_output(0, 6, 0, 0, 0) == pytest.approx(R.region_output(0, 5, 0, 0, 0) * 1.2)
    plain = new_game(player_start="S002", n_enemies=1)
    plain.regions["S002"].b["bank"] = 5
    assert not any(o["kind"] == "build" and o["key"] == "bank" for o in plain.options(0, "S002"))


def test_metro_units_multiply_and_specialty_separate():
    g, sel = _setup()
    g.player.res["oil"] = 10
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    for r in sel:
        _clear(g, r)
    ok, msg = g.start_project(0, "S002", "unit", "inf")
    assert ok, msg
    p = g.regions["S002"].project
    for _ in range(p.turns):
        g._fund_projects()
        g._phase_projects(("unit",))
    assert sum(a.units.get("inf", 0) for a in g.armies_at("S002", 0)) == len(sel)   # 하나 생산 → 지역 수만큼


def test_dissolve_restores_levels_singles_and_armies():
    """해제: 묶기 전 단계 + (지금 − 묶은 시점 평균). 예) 묶기 전 2, 평균 3, 해제 때 5 → 4."""
    g, sel = _setup()
    farms = [2, 4, 3, 3]                                     # 평균 3
    for r, lv in zip(sel, farms):
        g.regions[r].b["farm"] = lv
        g.regions[r].b["fishery"] = 5                        # 식량 조건
    g.regions[sel[1]].b["airport"] = 1
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    assert all(g.regions[r].b["airport"] == 1 for r in sel)          # 하나라도 있으면 광역시 전체에
    for r in sel:
        g.regions[r].b["farm"] = 5                                   # 광역시에서 5단계까지 올림
    a = g.new_army(0, sel[3], {"inf": 2})
    ok, msg = g.dissolve_metro(0, sel[1])
    assert ok, msg
    assert [g.regions[r].b["farm"] for r in sel] == [min(5, lv + 2) for lv in farms]      # 2 → 4
    assert g.regions["S002"].b["airport"] == 1 and sum(g.regions[r].b["airport"] for r in sel) == 1
    assert a.loc == "S002" and all(g.regions[r].metro is None for r in sel)


def test_metro_defends_together_and_is_captured_whole():
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    for r in sel:
        _clear(g, r)
    other = next(r for r in g.world.order if g.regions[r].owner == NEUTRAL and r not in M.distances(g, "S002", 3))
    _own(g, 0, [other])                                       # 광역시를 잃어도 판이 끝나지 않게
    D.declare_war(g, 1, 0)
    g.new_army(0, sel[0], {"inf": 1})
    edge = sel[-1]
    # 다른 구성 지역에 있는 병력도 함께 지킨다
    assert g.hostile_units_at(1, edge)
    assert M.def_mult(g, edge) == pytest.approx(1 - 0.02 * (len(sel) - 1))
    for r in sel:
        _clear(g, r)
    # 지키는 병력이 없으면 들어서는 즉시 광역시 전체를 차지하고, 저항이 끝나면 해제
    g.new_army(1, edge, {"inf": 1})
    g.begin_occupation(1, edge)
    assert all(g.regions[r].owner == 1 for r in sel)
    m = M.of(g, edge)
    assert m is not None and m["owner"] == 1
    for _ in range(C.RESIST_TURNS + 1):
        g.end_turn()
        if M.of(g, edge) is None:
            break
    assert M.of(g, edge) is None and all(g.regions[r].metro is None for r in sel)


def test_metro_happiness_specialty_and_rebellion():
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    # 행복도는 하나: 폭격·특산물 효과는 중심에 모였다가 구성 지역 모두에 같은 값
    c = g.regions["S002"]
    c.supplied = {"쌀"}
    g._phase_happiness()
    assert len({round(g.regions[r].happy, 6) for r in sel}) == 1
    assert all(g.regions[r].supplied == c.supplied for r in sel)
    # 반란은 중심에서만 판정되고, 진압에 실패하면 해제되고 중심이 독립
    for r in sel:
        g.regions[r].happy = -90
        _clear(g, r)
    g.rng.random = lambda: 0.0
    g._phase_rebellion()
    assert g.pending_rebellions == ["S002"]
    g.rng.random = lambda: 0.999
    g.resolve_rebellion(0, "S002", "suppress")
    assert all(g.regions[r].metro is None for r in sel)
    assert g.regions["S002"].owner != 0


def test_exchange_counts_by_metro_size():
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    g.regions[sel[1]].econ.add("exchange")
    n, cap_ok = M.exchange_weight(g, 0)
    assert n == len(sel) and cap_ok                      # 수도가 든 광역시의 거래소 하나 = 지역 수만큼
    assert g.econ_ready(0, "sez")[0] == (len(sel) >= C.ECON_EXCHANGES)
    # 금융 권역: 광역 금융 단지(은행 평균 5단계 이상)면 구성 지역 모두가 금융 단지
    for r in sel:
        g.regions[r].b["bank"] = 5
    assert set(sel) <= g.finance_cluster(0)


def test_cancel_and_save_load_keep_metro():
    import pickle
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    ok, _ = g.start_project(0, "S002", "build", "farm")
    assert ok
    g2 = pickle.loads(pickle.dumps(g))
    p2 = g2.regions["S002"].project
    assert all(g2.regions[r].project is p2 for r in sel) and M.of(g2, sel[2])["name"] == M.of(g, "S002")["name"]
    ok, msg = g.cancel_project(0, sel[3])
    assert ok and all(g.regions[r].project is None for r in sel)
    assert g.idle_slots(0) == sum(1 for r in g.regions_of(0) if r.id not in sel and not r.project
                                  and not r.occ and not g.resisting(r) and not r.focus) + 1


def test_metro_annex_counts_as_joint_annex_capped_at_half():
    """광역시의 편입은 구성 지역 수만큼의 공동 편입(2곳 −33%, 3곳 −50%, …)으로 치되 최대 50% 감소."""
    for n_extra, red in ((1, 0.33), (3, 0.5)):
        g, sel = _setup(n_extra=n_extra)
        ok, _ = g.create_metro(0, "S002", sel)
        assert ok
        tgt = next(o for o in g.options(0, "S002") if o["kind"] == "annex")
        assert f"공동 {len(sel)}곳 −{red:.0%}" in tgt["name"]
        ok, msg = g.start_project(0, "S002", "annex", tgt["key"])
        assert ok, msg
        p = g.regions["S002"].project
        assert g.joint_count(0, tgt["key"]) == len(sel)
        assert g.project_left("S002") == math.ceil(p.turns * (1 - red) - 1e-9)
        g._fund_projects()
        g._advance_annexes()
        assert p.progress == pytest.approx(1 / (1 - red))
    # 광역시가 끼지 않은 공동 편입은 그대로(4곳 −60%)
    assert R.joint_reduction(4) == pytest.approx(0.6)
