"""광역시(v1.3.0) 시스템 테스트."""
import math

import pytest

from korciv import config as C
from korciv import diplomacy as D
from korciv import metro as M
from korciv import rules as R
from korciv import slots as S
from korciv.state import NEUTRAL, Project

from test_engine import _room, _clear, _neutral_ai, _own, new_game


def _setup(n_extra=3, **kw):
    """플레이어 수도 서울 강남(S002)과 이웃 지역들을 광역시 조건에 맞춘다."""
    g = new_game(player_start="S002", n_enemies=1, **kw)
    _neutral_ai(g, 1)
    nb = sorted(g.world.land_adj["S002"])[:n_extra]
    _own(g, 0, nb)
    sel = ["S002"] + nb
    _room(g, sel)
    for r in sel:
        rr = g.regions[r]
        rr.resist, rr.project, rr.happy = None, None, 10.0
        rr.b["farm"] = 5
        rr.b["admin"] = 5 if r == g.player.capital else 4
        rr.pop = min(rr.pop, 45) if r != g.player.capital else rr.pop
    g.regions["S002"].b["factory"] = 5
    g.regions[nb[0]].b["bank"] = 5
    g.player.techs.update(("farm", "fishery", "factory", "bank", "extract", "power"))
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
    # 3칸 밖·남의 땅·떨어진 지역은 고를 수 없다
    far = next(r for r in g.world.order if r not in M.distances(g, "S002", C.METRO_RANGE))
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


def _cards(b, stype):
    return [(c["key"], c["level"]) if c else None for c in b.slots.get(stype, [])]


def test_split_average_examples():
    """v1.3.16 합병 단계: 레벨 합 ÷ 지역 수 반올림(하나라도 있으면 최소 1), 평균 5 초과면 5단계 + 나머지 카드."""
    assert S.split_average(3, 4) == [1]
    assert S.split_average(10, 4) == [3]
    assert S.split_average(22, 4) == [5, 1]
    assert S.split_average(20, 4) == [5] and S.split_average(21, 4) == [5]
    assert S.split_average(1, 25) == [1] and S.split_average(0, 4) == []


def test_merged_slots_average_and_multiplier():
    """광역시 기본 슬롯은 늘 6칸(중심에), 건물마다 레벨 합 ÷ 지역 수를 반올림, 산출·연료는 지역 수 배."""
    g, sel = _setup()
    for r, lv in zip(sel, [5, 4, 5, 4]):                      # 농장 합 18 → 4.5 → 5
        g.regions[r].b["farm"] = lv
    for r, lv in zip(sel, [5, 3, 0, 2]):                      # 공장 합 10 → 2.5 → 3
        g.regions[r].b["factory"] = lv
    farm_sum = sum(g.regions[r].b.cap("farm") for r in sel)
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    cb = g.regions["S002"].b
    n = len(sel)
    assert len(cb.slots["base"]) == S.BASE_SLOT_MAX and cb.mult_of("base") == n
    assert cb["farm"] == S.split_average(farm_sum, n)[0] == 5 and cb["factory"] == 3
    assert cb["admin"] == 4                                   # 5 + 4 + 4 + 4 = 17 → 4.25 → 4
    assert all(not g.regions[r].b.slots["base"] and g.regions[r].b["farm"] == 0 for r in sel[1:])
    assert cb.cap("factory") == 3 * n and cb.cap("farm") == 5 * n          # 연료 칸·농장 산출 = 단계 × 지역 수
    assert g.admin_output("S002") == pytest.approx(C.ADMIN_OUTPUT[4] * n * g.mods(0).mult("admin_building_output")
                                                   * g.mods(0).mult("admin_output")
                                                   + (g.mods(0).add("admin_each") + g.mods(0).add("capital_admin"))
                                                   * g.mods(0).mult("admin_output"), rel=1e-6)
    # 다른 구성 지역에서 열어도 같은 광역 슬롯(중심)과 그 지역의 기타 슬롯
    summ = g.slot_summary(sel[2])
    assert [c for t, _, c in summ if t == "base"] == cb.slots["base"]
    assert g.slot_counts(sel[2])[1] == sum(len(cb.slots[t]) for t in M.MERGE_TYPES) + len(g.regions[sel[2]].b.slots["etc"])


def test_merge_plan_extra_card_only_when_room():
    """평균이 5를 넘으면 5단계 하나 + (평균 − 5)를 반올림한 카드. 남는 칸이 없으면 더 주지 않는다."""
    g = new_game(n_enemies=1)
    sel = [r for r in g.world.order if g.regions[r].owner == NEUTRAL][:4]
    for r in sel:
        g.regions[r].__dict__["b"] = S.Buildings({"base": 6})
    for r, extra in zip(sel, (1, 1, 0, 0)):                   # 농장 합 22 → [5, 1]
        b = g.regions[r].b
        b.place("farm", 5)
        if extra:
            b.place("farm", extra)
        b.place("admin", 2)
    plan = M.merge_plan(g, sel)
    holder = type("B", (), {"slots": plan["slots"]})()
    assert _cards(holder, "base") == [("admin", 2), ("farm", 5), ("farm", 1), None, None, None]
    for r in sel:                                             # 종류가 6가지면 덤 카드는 빠진다
        b = g.regions[r].b
        for k in ("edu", "factory", "bank", "academy"):
            b.place(k, 1)
    plan = M.merge_plan(g, sel)
    keys = [c["key"] for c in plan["slots"]["base"]]
    assert len(keys) == 6 and keys.count("farm") == 1 and plan["slots"]["base"][keys.index("farm")]["level"] == 5


def test_merge_plan_river_coast_and_port():
    """하천·해안 슬롯: 그 슬롯을 가진 구성 지역이 1곳이면 1칸, 2곳 이상이면 2칸, 산출은 그 지역 수 배.
    항구가 하나라도 있었으면 해안에 항구 칸을 따로."""
    g = new_game(n_enemies=1)
    coast = [r for r in g.world.order if g.info(r).coastal][:3]
    inland = next(r for r in g.world.order if not g.info(r).coastal)
    sel = coast + [inland]
    for r in sel:
        g.regions[r].__dict__["b"] = S.Buildings({"base": 2, "river": 0 if r == coast[2] else 1,
                                                  "coast": 1 if r in coast else 0})
    b0 = g.regions[coast[0]].b
    b0.slots["coast"].append(None)
    b0.place("port", 1, ("coast", 1))
    b0.place("fishery", 4, ("coast", 0))
    g.regions[coast[1]].b.place("fishery", 3, ("coast", 0))
    g.regions[coast[2]].b.place("power", 2, ("coast", 0))
    g.regions[inland].b.place("fishery", 2, ("river", 0))
    plan = M.merge_plan(g, sel)
    holder = type("B", (), {"slots": plan["slots"]})()
    assert plan["mult"] == {"base": 4, "river": 3, "coast": 3}
    assert _cards(holder, "river") == [("fishery", 1), None]                        # 2 ÷ 3 → 1
    assert _cards(holder, "coast") == [("fishery", 2), ("power", 1), ("port", 1)]  # 7 ÷ 3 → 2, 2 ÷ 3 → 1, 항구 칸
    one = M.merge_plan(g, [coast[0], coast[2]])
    assert len(one["slots"]["river"]) == 1 and one["mult"]["river"] == 1           # 하천 지역 1곳 → 1칸


def test_merged_extract_coal():
    """탄광 2단계 + 3단계(2곳) → 합 5 ÷ 2 = 2.5 → 광역 탄광 3단계 ×2 = 석탄 6."""
    g = new_game(n_enemies=1, meet=True)
    _neutral_ai(g, 1)
    coal = [r for r in g.world.order if g.info(r).is_coal and not g.info(r).is_oil]
    a = next(r for r in coal if any(n in coal for n in g.world.land_adj[r]))
    b = next(n for n in sorted(g.world.land_adj[a]) if n in coal)
    _own(g, 0, [a, b])
    _room(g, [a, b])
    for r in (a, b):
        rr = g.regions[r]
        rr.resist, rr.project, rr.happy = None, None, 5
        rr.pop = max(rr.pop, 60)
        rr.b.update(farm=5, factory=5, bank=5, admin=4)
    g.player.capital = a
    g.regions[a].b["admin"] = 5
    for rr in g.regions_of(0):
        if rr.id not in (a, b):
            rr.b["admin"] = 4
    g.regions[a].b["extract"], g.regions[b].b["extract"] = 2, 3
    ok, msg = g.create_metro(0, a, [a, b])
    assert ok, msg
    cb = g.regions[a].b
    assert cb["extract"] == 3 and cb.mult_of("base") == 2 and g.regions[b].b["extract"] == 0
    m = g.mods(0)
    assert g.extract_amount(0, g.regions[a], "coal") == pytest.approx(
        (3 * 2 + 2 * m.add("extract3_extra")) * m.mult("output_extract"))
    assert g.extract_amount(0, g.regions[b], "coal") == 0
    assert g.blevel(b, "extract") == 3 and g.slot_kind_name(a, "extract") == "탄광"


def test_metro_slot_build_and_level6():
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    n = len(sel)
    cb = g.regions["S002"].b
    pos = cb.primary("bank")
    lv = cb["bank"] + 1
    o = next(o for o in g.options(0, sel[1]) if o["kind"] == "build" and o["key"] == "bank" and o.get("slot") == pos)
    assert o["site"] == "S002" and o["mult"] == n and o["level"] == lv
    assert o["cost"] == pytest.approx(g.card_cost(0, "S002", "bank", lv)[0] * n)
    assert g.building_effect(0, "S002", o).startswith(f"지역 {n}곳 각각 ")
    ok, msg = g.start_project(0, sel[2], "build", "bank", site="S002", slot=pos)
    assert ok, msg
    p = g.regions["S002"].project
    assert all(g.regions[r].project is p for r in sel) and len(g.projects_by_priority(0)) == 1
    for _ in range(p.turns):
        g._fund_projects()
        g._phase_projects(("build",))
    assert cb["bank"] == lv and all(g.regions[r].project is None for r in sel)
    assert all(g.regions[r].b["bank"] == 0 and g.blevel(r, "bank") == lv for r in sel[1:])
    # 6단계는 광역 슬롯 카드만: 은행 6단계 산출 = 5단계 × 1.2, 첨단산업단지 연료 1개당 2000 × 1.1·6개까지
    cb.set_card(pos, 5)
    o6 = next(o for o in g.options(0, "S002") if o["kind"] == "build" and o["key"] == "bank" and o.get("slot") == pos)
    assert o6["level"] == 6 and g.card_max("S002", "bank") == 6
    assert R.g(6) == pytest.approx(R.g(5) * 1.2)
    assert R.factory_unit(6) == pytest.approx(2200) and R.factory_output(6) == pytest.approx(2200 * 6)
    assert R.region_output(0, 6, 0, 0, 0) == pytest.approx(R.region_output(0, 5, 0, 0, 0) * 1.2)
    plain = new_game(player_start="S002", n_enemies=1)
    plain.regions["S002"].b["bank"] = 5
    assert not any(o["kind"] == "build" and o["key"] == "bank" and o["level"] > 5 for o in plain.options(0, "S002"))
    # 최대 건설: 같은 광역 칸에서 6단계까지 이어서
    cb.set_card(pos, 4)
    ok, msg = g.start_project_max(0, "S002", "build", "bank", site="S002", slot=pos)
    assert ok, msg
    for _ in range(200):
        p = g.regions["S002"].project
        if p is None:
            break
        g._fund_projects()
        g._phase_projects(("build",))
    assert cb.card(pos)["level"] == 6


def test_metro_units_multiply():
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
    """해제: 구성 지역마다 묶기 전 카드로 돌아가고, 광역 카드가 오른 만큼 같은 건물 카드가 함께 오른다.
    예) 농장 2·4·3·3(평균 3) → 광역 농장 3 → 5로 올리고 해제하면 4·5·5·5."""
    g, sel = _setup()
    farms = [2, 4, 3, 3]
    for r, lv in zip(sel, farms):
        g.regions[r].b["farm"] = lv
    g.regions[sel[1]].b["airport"] = 1
    pre = {r: _cards(g.regions[r].b, "base") for r in sel}
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    assert all(g.regions[r].b["airport"] == 1 for r in sel)          # 하나라도 있으면 광역시 전체에
    cb = g.regions["S002"].b
    assert cb["farm"] == 3
    cb["farm"] = 5                                                   # 광역시에서 5단계까지 올림
    a = g.new_army(0, sel[3], {"inf": 2})
    ok, msg = g.dissolve_metro(0, sel[1])
    assert ok, msg
    assert [g.regions[r].b["farm"] for r in sel] == [min(5, lv + 2) for lv in farms]      # 2 → 4
    for r in sel:                                                    # 농장 말고는 묶기 전 카드 그대로
        assert [c for c in _cards(g.regions[r].b, "base") if not c or c[0] != "farm"] == \
            [c for c in pre[r] if not c or c[0] != "farm"]
    assert not getattr(cb, "xmult", None) and cb.mult_of("base") == 1
    assert g.regions["S002"].b["airport"] == 1 and sum(g.regions[r].b["airport"] for r in sel) == 1
    assert a.loc == "S002" and all(g.regions[r].metro is None for r in sel)


def test_dissolve_new_building_and_shared_project_refund():
    """묶은 뒤 새로 지은 건물은 해제할 때 그 건물이 없던 구성 지역의 빈 칸에도 생기고(사관학교는 중심에만),
    광역 슬롯 공사는 50% 환급하고 취소."""
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    cb = g.regions["S002"].b
    e = cb.empty("base")
    assert len(e) >= 2
    cb.place("edu", 2, ("base", e[0]))
    cb.place("academy", 1, ("base", e[1]))
    ok, msg = g.start_project(0, "S002", "build", "farm", site="S002", slot=cb.primary("farm"))
    assert ok, msg
    p = g.regions["S002"].project
    p.paid = 1000.0
    money = g.player.money
    ok, _ = g.dissolve_metro(0, "S002")
    assert ok and g.player.money == pytest.approx(money + 1000 * C.PROJECT_REFUND)
    assert all(g.regions[r].project is None for r in sel)
    assert all(g.regions[r].b["edu"] == 2 for r in sel if g.regions[r].b.empty("base") or g.regions[r].b["edu"])
    assert g.regions["S002"].b["academy"] == 1 and all(g.regions[r].b["academy"] == 0 for r in sel[1:])


def _outside(g, sel, tile):
    """tile 과 (원래 지도에서) 맞닿은 광역시 밖 지역 하나."""
    return sorted(n for n in M.base_world(g).land_adj[tile] if n not in sel)[0]


def test_metro_defends_together_and_loses_only_the_attacked_tile():
    """v1.3.21: 적국 광역시는 구성 지역 하나를 골라 공격한다. 광역시 병력이 함께 지키고(방어 배수 그대로),
    이기면 그 칸 하나만 넘어가며 광역시는 남는다(건물 단계 그대로, 지역 수 배수만 다시). 저항 기간 안에
    되찾으면 원상복구, 지나서 되찾으면 별개의 지역."""
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    for r in sel:
        _clear(g, r)
    D.declare_war(g, 1, 0)
    g.new_army(0, sel[0], {"inf": 1})
    edge = sel[-1]
    assert g.hostile_units_at(1, edge)
    assert M.def_mult(g, edge) == pytest.approx(1 - 0.02 * (len(sel) - 1))
    for r in sel:
        _clear(g, r)
    cb = g.regions["S002"].b
    rows = {t: [dict(c) if c else None for c in cb.slots[t]] for t in M.MERGE_TYPES}
    src = _outside(g, sel, edge)
    _own(g, 1, [src])
    _clear(g, src)
    a = g.new_army(1, src, {"inf": 2})
    ok, _ = g.order_army(a.id, edge)                      # 구성 지역을 골라 명령(광역시 칸으로 들어간다)
    assert ok and a.order["path"] == ["S002"] and a.order["tile"] == edge
    g._phase_move()
    g._phase_attack()
    m = M.of(g, "S002")
    assert g.regions[edge].owner == 1 and a.loc == edge
    assert all(g.regions[r].owner == 0 for r in sel if r != edge)
    assert m["members"] == [r for r in sel if r != edge] and g.regions[edge].metro is None
    assert {t: [dict(c) if c else None for c in cb.slots[t]] for t in M.MERGE_TYPES} == rows   # 광역 카드 단계 그대로
    assert cb.mult_of("base") == len(sel) - 1                                                # 배수만 다시
    assert g.regions[edge].b.slots["base"]                                                   # 떼어 낸 칸은 자기 카드
    assert edge in g.world.land_adj["S002"] and "S002" in g.world.land_adj[edge]
    # 저항 기간 안에 되찾으면 다시 광역시로(원상복구)
    g.remove_army(a)
    b = g.new_army(0, "S002", {"inf": 2})
    ok, msg = g.act_now(b.id, edge)
    assert ok and g.regions[edge].owner == 0, msg
    m = M.of(g, edge)
    assert m is not None and sorted(m["members"]) == sorted(sel) and cb.mult_of("base") == len(sel)
    assert {t: [dict(c) if c else None for c in cb.slots[t]] for t in M.MERGE_TYPES} == rows
    assert not any(g.regions[edge].b.slots.get(t) for t in M.MERGE_TYPES)
    # 다시 빼앗기고 저항 기간이 지나서 되찾으면 별개의 지역
    for x in list(g.armies.values()):
        if x.loc in sel or x.loc == edge:
            g.remove_army(x)
    c = g.new_army(1, src, {"inf": 2})
    g.note_entry(1, "S002", src, edge)
    g.capture_now(c.id, edge)
    assert g.regions[edge].owner == 1 and M.of(g, edge) is None
    g.turn += C.RESIST_TURNS + 1
    M.phase(g)
    g.remove_army(c)
    d = g.new_army(0, "S002", {"inf": 2})
    g.act_now(d.id, edge)
    assert g.regions[edge].owner == 0 and M.of(g, edge) is None


def test_metro_center_lost_moves_center_and_keeps_metro():
    g, sel = _one_region_metro()
    for r in sel:
        _clear(g, r)
    other = next(r for r in g.world.order if g.regions[r].owner == NEUTRAL and r not in M.distances(g, "S002", 3))
    _own(g, 0, [other])
    cb = g.regions["S002"].b
    rows = {t: [dict(c) if c else None for c in cb.slots[t]] for t in M.MERGE_TYPES}
    g.transfer_region("S002", 1)                           # 중심 칸을 잃어도 광역시는 남는다
    m = M.of(g, sel[1])
    assert m is not None and "S002" not in m["members"] and m["center"] in sel[1:]
    nb = g.regions[m["center"]].b
    assert {t: [dict(c) if c else None for c in nb.slots[t]] for t in M.MERGE_TYPES} == rows
    assert nb.mult_of("base") == len(sel) - 1
    assert g.world.land_adj["S002"] and not g.world.land_adj[sel[1]] or m["center"] == sel[1]
    # 수도를 잃으면 남은 땅으로 천도
    assert g.player.capital != "S002"


def test_metro_post_annex_adds_member_by_designation_rules():
    """광역시 편입(사후): 맞닿은 내 지역을 지정 조건대로 더한다 — 광역 카드는 레벨 합 ÷ 지역 수로 다시 평균."""
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel[:-1])
    assert ok
    m = M.of(g, "S002")
    new = sel[-1]
    assert new in M.annex_candidates(g, 0, m["id"])
    ok, items = M.check_annex(g, 0, m["id"], new)
    assert ok, items
    n0 = len(m["members"])
    ok, msg = g.annex_to_metro(0, m["id"], new)
    assert ok, msg
    assert new in m["members"] and g.regions[new].metro == m["id"] and len(m["members"]) == n0 + 1
    cb = g.regions["S002"].b
    assert cb.mult_of("base") == n0 + 1 and not g.regions[new].b.slots["base"]
    assert "S002" in g.world.land_adj.get(next(n for n in M.base_world(g).land_adj[new] if n not in m["members"]), {"S002"})
    # 해제하면 편입한 지역도 자기 카드를 되찾는다
    ok, _ = g.dissolve_metro(0, "S002")
    assert ok and g.regions[new].b.slots["base"]


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
    # 반란은 중심에서만 판정되고, 진압에 실패하면 중심 칸만 반군에게 넘어가고 광역시는 남는다(v1.3.21)
    for r in sel:
        g.regions[r].happy = -90
        _clear(g, r)
    g.rng.random = lambda: 0.0
    g._phase_rebellion()
    assert g.pending_rebellions == ["S002"]
    g.rng.random = lambda: 0.999
    g.resolve_rebellion(0, "S002", "suppress")
    assert g.regions["S002"].owner != 0 and g.regions["S002"].metro is None
    m = M.of(g, sel[1])
    assert m is not None and sorted(m["members"]) == sorted(sel[1:]) and g.is_rebel(g.regions["S002"].owner)


def test_exchange_counts_by_metro_size():
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    g.regions[sel[1]].econ.add("exchange")
    n, cap_ok = M.exchange_weight(g, 0)
    assert n == len(sel) and cap_ok                      # 수도가 든 광역시의 거래소 하나 = 지역 수만큼
    assert g.econ_ready(0, "sez")[0] == (len(sel) >= C.ECON_EXCHANGES)
    # 금융 권역: 광역 시장 카드가 5단계(복합 무역 센터)면 구성 지역 모두가 금융 단지
    g.regions["S002"].b["bank"] = 5
    assert set(sel) <= g.finance_cluster(0)
    g.player.techs.add("aerospace")
    assert all(g.science_site_ok(0, r, "budget") for r in sel)          # 과학 '예산 편성'도 어느 구성 지역에서나


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
        # v1.3.0: 행동 탭 선택지·착수 알림의 턴 수도 줄어든 값, 작업 이름에는 바뀌는 '공동 n곳'을 넣지 않는다
        assert tgt["eff_turns"] == g.project_left("S002") < tgt["turns"]
        assert f"({g.project_left('S002')}턴" in msg and p.name == f"편입: {g.info(tgt['key']).name}"
        g._fund_projects()
        g._advance_annexes()
        assert p.progress == pytest.approx(1 / (1 - red))
    # 광역시가 끼지 않은 공동 편입은 그대로(4곳 −60%)
    assert R.joint_reduction(4) == pytest.approx(0.6)


def test_border_line_group_takes_whole_metro_slot():
    """v1.3.0 QA: 국경 방어선 일괄 건설이 광역시 구성 지역 일부에만 작업을 넣어 슬롯이 갈라지던 문제.
    구성 지역 하나라도 대상이면 광역시 모두가 함께 묶음 공사를 하고, 턴 수는 광역시를 한 슬롯으로 나눈다."""
    g, sel = _setup()
    ok, msg = g.create_metro(0, "S002", sel, "")
    assert ok, msg
    m = M.of(g, "S002")
    # 광역시 바깥 이웃 하나를 적국 땅으로: 구성 지역 가운데 일부만 그 나라와 맞닿는다
    outer = sorted({n for r in sel for n in g.world.land_adj[r]} - set(sel))
    enemy = outer[0]
    _own(g, 1, [enemy])
    touching = [r for r in sel if enemy in g.world.land_adj[r]]
    assert 0 < len(touching) < len(sel)
    ok, _ = g.start_project(0, "S002", "unit", "inf")              # 광역시 슬롯 하나에 진행 중 작업
    assert ok
    plan = g.border_line_plan(0, 1, 2)
    assert set(m["members"]) <= set(plan["lines"])
    assert all(plan["lines"][r] == [] for r in m["members"] if r not in touching)
    assert plan["slots"] == len({M.center_of(g, r) for r in plan["lines"]})
    ok, msg = g.build_border_lines(0, 1, 2)
    assert ok, msg
    ps = {id(g.regions[r].project) for r in m["members"]}
    assert len(ps) == 1 and g.regions["S002"].project.group is not None
    p = g.regions["S002"].project
    for _ in range(p.turns):
        g._fund_projects()
        g._phase_projects(("build",))
    assert all(g.regions[r].project is None for r in m["members"])
    assert all(g.regions[r].lines.get(enemy, 0) >= 2 for r in touching)


def test_feasible_reports_why_designation_is_impossible():
    """v1.3.0: 행동 탭 [광역자치단체 지정]은 조건을 채울 길이 없으면 비활성(이유를 툴팁으로)."""
    g, sel = _setup()
    ok, why = M.feasible(g, 0, "S002")
    assert ok and not why
    g.regions["S002"].b["factory"] = 4
    ok, why = M.feasible(g, 0, "S002")
    assert not ok and any("공업 단지" in w for w in why)
    g.regions["S002"].b["factory"] = 5
    for r in sel:
        g.regions[r].happy = -20
    ok, why = M.feasible(g, 0, "S002")
    assert not ok and any("행복도" in w for w in why)
    # 혼자뿐인 지역(같이 묶을 내 지역이 없음)
    g2 = new_game(player_start="S002", n_enemies=1)
    ok, why = M.feasible(g2, 0, "S002")
    assert not ok and any("함께 묶을" in w for w in why)
    # 가능하다고 본 경우 실제로 모두 고르면 지정 조건을 채운다(이 설정에서)
    g3, sel3 = _setup()
    assert M.feasible(g3, 0, "S002")[0] and M.check(g3, 0, "S002", sel3)[0]


def _own_ring(g, k):
    """S002 에서 육상 k칸 안의 지역을 모두 플레이어 땅으로(광역시 후보가 되게)."""
    d = M.distances(g, "S002", k)
    _own(g, 0, [r for r in d if r != "S002"])
    for r in d:
        rr = g.regions[r]
        rr.resist, rr.project, rr.happy, rr.occ = None, None, 10.0, None
        rr.b["farm"] = 5
        rr.b["admin"] = 5 if r == g.player.capital else 4
        rr.pop = min(rr.pop, 45) if r != g.player.capital else rr.pop
    return d


def test_metro_range_three_and_at_most_25_regions():
    """v1.3.0: 중심에서 육상 3칸(3차 인접)까지, 구성 지역은 중심 포함 25곳까지(서울 25개 구)."""
    assert C.METRO_RANGE == 3 and C.METRO_MAX_REGIONS == 25
    g, _ = _setup()
    d = _own_ring(g, 4)
    cands = M.candidates(g, 0, "S002")
    assert {r for r in d if d[r] <= 3} == set(cands)                 # 3칸까지는 후보, 4칸은 아님
    assert any(d[r] == 3 for r in cands) and not any(d[r] == 4 for r in cands)
    assert len(cands) > C.METRO_MAX_REGIONS
    # [모두]: 이어진 후보를 가까운 순으로 25곳까지
    pick = M.auto_pick(g, 0, "S002")
    assert pick[0] == "S002" and len(pick) == C.METRO_MAX_REGIONS == len(set(pick))
    assert set(pick) <= set(cands) and M._connected(g, "S002", pick)
    assert max(d[r] for r in pick) <= min(d[r] for r in cands if r not in pick)   # 가까운 곳부터
    ok, items = M.check(g, 0, "S002", pick)
    assert ok, [i for i in items if not i[1]]
    # 26곳은 안 된다
    extra = next(r for r in cands if r not in pick and any(n in pick for n in g.world.land_adj[r]))
    ok, items = M.check(g, 0, "S002", pick + [extra])
    assert not ok and not dict((k, o) for k, o, _ in items)["구성 지역(2~25곳)"]
    assert dict((k, d_) for k, _, d_ in items)["구성 지역(2~25곳)"] == "26곳 — 1곳을 빼야 함"
    assert not g.create_metro(0, "S002", pick + [extra])[0]
    ok, msg = g.create_metro(0, "S002", pick)
    assert ok, msg
    assert len(M.of(g, "S002")["members"]) == C.METRO_MAX_REGIONS


def test_feasible_population_counts_only_top_25():
    """지정 가능 여부(버튼 활성)의 인구는 인구가 많은 25곳(중심 포함)까지만 더한다."""
    g, _ = _setup()
    d = _own_ring(g, 3)
    regs = sorted((g.regions[r] for r in d if r != "S002"), key=lambda r: -r.pop)
    for r in regs:
        r.pop = 1.0
    g.regions["S002"].pop = 1.0
    for r in regs[:C.METRO_MAX_REGIONS - 1]:
        r.pop = 3.0                                     # 25곳 합 1 + 24×3 = 73만
    for r in regs[C.METRO_MAX_REGIONS - 1:]:
        r.pop = 2.9                                     # 나머지를 다 더하면 100만을 넘지만 25곳까지만 묶을 수 있다
    assert sum(g.regions[r].pop for r in d) >= C.METRO_MIN_POP
    ok, why = M.feasible(g, 0, "S002")
    assert not ok and any("인구" in w for w in why)


def test_metro_etc_slots_stay_per_region():
    """v1.3.16: 기타 슬롯(댐·원전·특산물 시설)은 합치지 않는다 — 지역마다 그대로, 비용도 한 지역 몫."""
    g, _ = _setup()
    d = _own_ring(g, 3)
    spec = sorted(r for r in d if g.info(r).specialty and r != "S002")[:2]
    assert len(spec) == 2
    sel = set(M.auto_pick(g, 0, "S002")[:8])
    for r in spec:
        sel.add(r)
        cur = r
        while d[cur] > 0:
            cur = min((n for n in g.world.land_adj[cur] if n in d and d[n] == d[cur] - 1), key=str)
            sel.add(cur)
    sel = ["S002"] + sorted(sel - {"S002"})
    assert len(sel) <= C.METRO_MAX_REGIONS
    _room(g, sel)
    g.regions[spec[0]].b["specialty"] = 3
    g.regions[spec[1]].b["specialty"] = 1
    ok, msg = g.create_metro(0, "S002", sel)
    assert ok, msg
    assert [g.regions[r].b["specialty"] for r in spec] == [3, 1]
    assert all(any(c and c["key"] == "specialty" for c in g.regions[r].b.slots["etc"]) for r in spec)
    opts = [o for o in g.options(0, "S002") if o["kind"] == "build" and o["key"] == "specialty"]
    assert {o["site"] for o in opts} == {spec[1]} and not any(o.get("mult") for o in opts)
    o = opts[0]
    assert o["slot"][0] == "etc" and o["cost"] == pytest.approx(g.card_cost(0, spec[1], "specialty", 2)[0])
    ok, msg = g.start_project(0, "S002", "build", "specialty", site=spec[1], slot=o["slot"])
    assert ok, msg
    p = g.regions["S002"].project
    for _ in range(p.turns):
        g._fund_projects()
        g._phase_projects(("build",))
    assert g.regions[spec[1]].b["specialty"] == 2
    ok, _ = g.dissolve_metro(0, "S002")
    assert ok and [g.regions[r].b["specialty"] for r in spec] == [3, 2]


def test_migrate_legacy_metro_merges_slots():
    """예전 세이브(v1.3.9까지)의 광역시: 불러오면 광역 슬롯으로 합치고, 예전 통합 건물 공사는 낸 돈을 모두 돌려준다."""
    import pickle
    g, sel = _setup()
    ok, _ = g.create_metro(0, "S002", sel)
    assert ok
    m = M.of(g, "S002")
    M.unmerge(g, m)                                       # 예전 모습: 구성 지역마다 카드, 광역 슬롯 표시 없음
    for k in ("slot_merge", "pre_slots", "merged"):
        m.pop(k)
    m["merge"]["farm"] = 5
    p = Project(kind="build", key="farm", level=6, turns=10, per_turn=100.0, paid=500.0, metro=m["id"], site="S002",
                pool="farm")
    for r in sel:
        g.regions[r].project = p
    money = g.player.money
    g2 = pickle.loads(pickle.dumps(g))
    m2 = M.of(g2, "S002")
    assert m2["slot_merge"] and "farm" not in m2["merge"]
    assert len(g2.regions["S002"].b.slots["base"]) == S.BASE_SLOT_MAX and g2.regions["S002"].b.mult_of("base") == len(sel)
    assert all(g2.regions[r].project is None for r in sel) and g2.player.money == pytest.approx(money + 500)
    M.migrate(g2)                                         # 두 번 불러도 그대로
    assert g2.regions["S002"].b.mult_of("base") == len(sel)


def test_metro_extract_split_by_resource():
    """광역 채굴 카드: 탄전·유전 구성 지역이 함께 있으면 그 수의 비율로 석탄·석유를 나눠 캔다."""
    g, sel = _setup()
    a, b = sel[1], sel[2]
    real = g.info

    class _Info:
        def __init__(self, info, coal, oil):
            self._i, self.is_coal, self.is_oil = info, coal, oil
            self.oil = 0

        def __getattr__(self, k):
            return getattr(self._i, k)
    g.info = lambda rid: (_Info(real(rid), True, False) if rid == a else
                          _Info(real(rid), False, True) if rid == b else real(rid))
    g.regions[a].b["extract"] = 4
    g.regions[b].b["extract"] = 2                         # 합 6 ÷ 4 = 1.5 → 광역 채굴 2단계 ×4
    ok, msg = g.create_metro(0, "S002", sel)
    assert ok, msg
    cb = g.regions["S002"].b
    assert cb["extract"] == 2 and M.extract_res(g, "S002") == ("oil", "coal")
    m = g.mods(0)
    assert g.extract_amount(0, g.regions["S002"], "oil") == pytest.approx(2 * 2 * m.mult("output_extract"))
    assert g.extract_amount(0, g.regions["S002"], "coal") == pytest.approx(2 * 2 * m.mult("output_extract"))
    mined = g.energy_mined(0)
    assert mined["oil"] >= 4 * m.mult("output_extract") - 1e-9 and mined["coal"] >= 4 * m.mult("output_extract") - 1e-9
    assert g.building_tech("S002", "extract") == ("extract",)


def test_metro_action_tab_shows_merged_slots(monkeypatch, tmp_path):
    """행동 탭(v1.3.16): 광역시 어느 구성 지역을 골라도 중심의 광역 슬롯(×n)과 그 지역의 기타 슬롯을 보여 주고,
    빈 광역 칸을 누르면 중심에 짓는 선택지(비용 n배)를 펼친다. 지정 창은 합친 슬롯 구성을 미리 보여 준다."""
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from korciv.ui import app as appmod, slot_cards as SC, theme
    monkeypatch.setattr(appmod, "PREFS_PATH", str(tmp_path / "prefs.json"))
    theme._fonts.clear()
    theme._text_cache.clear()
    app = appmod.App(width=1280, height=800)
    try:
        g, sel = _setup()
        app.game, app.world = g, g.world
        app.reset_ui()
        app.scene = "main"
        app.start_metro_pick("S002")                       # 지정 창: 광역 슬롯 미리보기
        app.metro_pick["sel"] = set(sel[1:])
        app.gui.begin([])
        app.frame()
        assert M.plan_lines(g, "S002", M.preview(g, "S002", sel)["plan"])[0].startswith("기본 6칸 ×4")
        app.cancel_metro_pick()
        ok, msg = g.create_metro(0, "S002", sel)
        assert ok, msg
        rid = sel[2]
        app.select(rid)
        app.left_open, app.left_tab, app.tab = True, "region", "action"
        app.gui.begin([])
        app.frame()
        summary, _, cells = SC._cells(app, rid)
        cb = g.regions["S002"].b
        assert [c for t, _, c in summary if t == "base"] == cb.slots["base"]
        idx = cb.empty("base")[0]
        layout, _ = SC.grid_layout(cells, 20, 120, 330)
        rect = dict(layout)[("base", idx)]
        app.gui.begin([])
        app.gui.mouse = rect.center
        app.gui.clicked = True
        SC.draw_slot_grid(app, 20, 120, 330, rid, mine=True, select=True)
        assert app.slot_sel == (rid, "base", idx)
        app.gui.begin([])
        app.frame()                                          # 펼친 선택지(중심의 광역 칸)
        choices = g.slot_choices(0, g.slot_site(rid, "base"), ("base", idx), g.options(0, rid))
        assert choices and all(o["site"] == "S002" for o in choices)
        assert all(o.get("mult") == len(sel) for o in choices if o["key"] not in C.SINGLE_BUILDINGS)
        assert SC.slot_panel_height(app, rid, ("base", idx), g.options(0, rid)) > SC.PANEL_ROW * 3
        for dark in (True, False):
            app.theme.set_dark(dark)
            app.gui.begin([])
            app.frame()
    finally:
        theme._fonts.clear()
        theme._text_cache.clear()
        pygame.quit()


def test_ai_metro_orders_use_merge_plan():
    """AI 광역시 지정(v1.3.10 AI)도 광역 슬롯 합병 결과로 5단계 거점이 남는지 보고 지정한다."""
    from korciv import ai_economy as AE
    g, sel = _setup()
    f = g.factions[0]
    f.is_ai = True
    for r in sel:
        g.regions[r].b["factory"] = 5
        g.regions[r].b["bank"] = 5
        g.regions[r].project, g.regions[r].queue = None, []
    period = max(4, round(8 / AE.preference(g, 0, "metro")))
    while g.turn % period != 0:
        g.turn += 1
    assert AE.metro_orders(g, f, {})
    m = M.of(g, "S002")
    assert m and m["slot_merge"]
    cb = g.regions["S002"].b
    assert cb["factory"] == 5 and cb["bank"] == 5 and cb.mult_of("base") == len(m["members"])


def _one_region_metro():
    g, sel = _setup()
    ok, msg = g.create_metro(0, "S002", sel)
    assert ok, msg
    return g, sel


def test_metro_is_one_region_for_output_happiness_value_and_focus():
    """v1.3.17: 광역시는 지정한 뒤 모든 면에서 하나의 지역 — 산출·행정·과학은 광역시 전체를 한 번에(중심 칸이 대표),
    행복도·지역 가치·생산 집중은 어느 구성 지역에서 봐도 같다. 해제하면 다시 지역마다."""
    g, sel = _one_region_metro()
    pop = sum(g.regions[r].pop for r in sel)
    assert M.total_pop(g, sel[2]) == pytest.approx(pop)
    assert all(g.calc_output(r) == 0 for r in sel[1:]) and g.calc_output("S002") > 0
    assert all(g.admin_output(r) == 0 and g.science_output(r) == 0 for r in sel[1:])
    assert len({round(g.eff_happy(g.regions[r]), 9) for r in sel}) == 1
    assert len({g.region_value(r)[0] for r in sel}) == 1
    assert g.density_growth(sel[3]) == g.density_growth("S002")
    ok, _ = g.set_focus(0, sel[2], True)
    assert ok and all(g.regions[r].focus for r in sel)
    # 위인: 광역시 어디에 있어도 광역시 전체에(더하는 효과는 한 번)
    g.great_people.append({"id": 999, "kind": "scientist", "owner": 0, "loc": sel[3], "name": "시험"})
    assert g.great_person_bonus("S002", "science_mult") == pytest.approx(1.3)
    g.great_people[-1]["kind"] = "chancellor"
    assert g.great_person_bonus("S002", "admin_add") == 30 and g.great_person_bonus(sel[1], "admin_add") == 0
    ok, _ = g.dissolve_metro(0, "S002")
    assert ok and all(g.calc_output(r) > 0 for r in sel)


def test_any_member_hit_hits_the_whole_metro():
    """구성 지역 어디가 폭격·지진·침수·산불·파괴 공작을 당해도 광역시 전체(광역 카드)에 한 번 일어난다."""
    g, sel = _one_region_metro()
    cb = g.regions["S002"].b
    edge = sel[2]
    # 폭격: 중심이 아닌 구성 지역을 쳐도 광역 카드가 대상
    targets = g.bomb_targets(edge)
    assert ("S002", "b", "farm") in targets
    D.declare_war(g, 1, 0)
    a = g.new_army(1, next(n for n in g.base_world.land_adj[edge] if n not in sel), {"art": 2})
    g.rng.random = lambda: 0.29
    g.rng.choice = lambda seq: ("S002", "b", "farm") if ("S002", "b", "farm") in seq else seq[0]
    farm = cb["farm"]
    g._bombard(a, edge, {"art": 2})
    assert cb["farm"] == farm - 1
    # 의열단(파괴 공작)
    g.rng.choice = lambda seq: next(c for c in seq if c[0] == "S002" and c[2] == "farm")
    g._sabotage(g.regions[sel[3]])
    assert cb["farm"] == farm - 2
    # 지진: 구성 지역이 진앙이어도 광역시 전체가 한 번(카드마다 1단계)
    g.rng.random = lambda: 0.0
    g.earthquake(sel[3], 5)
    assert cb["farm"] == farm - 3 and all(g.regions[r].quake_until == g.turn + 1 for r in sel)
    # 침수: 광역시 전체가 침수, 복구는 한 번
    g.set_flooded(sel[1])
    assert all(g.regions[r].flooded for r in sel) and g.calc_output("S002") == 0
    for r in sel:
        _clear(g, r)
    reps = [o for o in g.options(0, sel[2]) if o["kind"] == "repair"]
    assert len(reps) == 1 and reps[0]["site"] == "S002"
    ok, msg = g.start_project(0, sel[2], "repair", reps[0]["key"])
    assert ok, msg
    g._fund_projects()
    g._phase_projects(("repair",))
    assert not any(g.regions[r].flooded for r in sel)
    # 산불: 어느 구성 지역에 붙어도 광역시 하나가 타고, 피해·행복도(흔적)는 광역시 전체
    g.ignite(sel[1])
    assert g.fires == {"S002"} and set(sel) <= g.fire_burned
    before = g.eff_happy(g.regions[sel[3]])
    g.disaster_damage()
    assert g.eff_happy(g.regions[sel[3]]) < before
    assert len({round(g.eff_happy(g.regions[r]), 9) for r in sel}) == 1


def test_metro_is_one_cell_on_the_map():
    """v1.3.18: 광역시를 지정하면 지도를 다시 그린 것처럼 광역시가 한 칸 — 바깥 이웃과 바로 맞닿고(구성 지역 칸은
    그래프에서 빠짐), 부대·방어선·시야도 광역시 칸 하나로. 해제하면 원래 지도와 방어선으로 돌아간다."""
    import pickle
    g, sel = _setup()
    edge = sel[2]
    base_lines = {n: 2 for n in g.base_world.land_adj[edge] if n not in sel}
    g.regions[edge].lines = dict(base_lines)
    a = g.new_army(0, edge, {"inf": 2})
    ok, msg = g.create_metro(0, "S002", sel)
    assert ok, msg
    w = g.world
    assert w is not g.base_world and a.loc == "S002"
    outer = {n for r in sel for n in g.base_world.land_adj[r]} - set(sel)
    assert w.land_adj["S002"] == outer and all(not w.land_adj[r] for r in sel[1:])
    assert all("S002" in w.land_adj[n] and not (set(sel[1:]) & w.land_adj[n]) for n in outer)
    assert g.new_army(0, sel[3], {"inf": 1}).loc == "S002"          # 구성 지역 칸에 만들어도 광역시 칸에
    # 방어선: 광역시의 바깥 경계마다 하나
    hub = g.regions["S002"]
    assert all(hub.lines.get(n, 0) >= 2 for n in base_lines) and not g.regions[edge].lines
    assert {o["border"] for o in g.options(0, sel[1]) if o["key"] == "line"} <= outer | {"coast"}
    # 이동: 바깥 이웃끼리는 광역시 칸을 지나 두 걸음(원래 지도에서 멀리 떨어진 두 이웃이어도)
    a1, a2 = sorted(outer)[0], sorted(outer)[-1]
    _own(g, 0, [a1, a2])
    for r in ["S002", a1, a2]:
        for x in list(g.armies_at(r)):
            if x.owner != 0:
                g.remove_army(x)            # 시험 판: 넘겨받은 땅에 남은 중립 수비대
    mover = g.new_army(0, a1, {"inf": 1})
    route = g.plan_route(mover, a2)
    assert route and len(route) <= 2 and (len(route) == 1 or route[0] == "S002")
    assert g.plan_route(mover, sel[3]) == ["S002"] or "S002" in (g.plan_route(mover, sel[3]) or [])
    # 시야: 광역시 칸이 보이면 구성 지역 칸도 모두
    assert all(g.is_visible(0, r) for r in sel)
    # 저장·불러오기 뒤에도 같은 지도
    g2 = pickle.loads(pickle.dumps(g))
    assert g2.world.land_adj["S002"] == outer and g2.base_world is not g2.world
    # 해제: 원래 지도, 방어선은 묶기 전 + 바뀐 만큼
    hub.lines[sorted(base_lines)[0]] = 3
    ok, _ = g.dissolve_metro(0, "S002")
    assert ok and g.world is g.base_world
    lines = g.regions[edge].lines
    assert lines[sorted(base_lines)[0]] == 3 and all(lines[n] == 2 for n in sorted(base_lines)[1:])
