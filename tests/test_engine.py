import math
import pickle

import pytest

from korciv import config as C
from korciv import diplomacy as D
from korciv import rules as R
from korciv.game import Game
from korciv.state import NEUTRAL, Settings


def _meet_all(g):
    """조우 처리(무역·외교는 조우한 나라끼리만)."""
    ids = [f.id for f in g.factions]
    for f in g.factions:
        f.met = set(ids) - {f.id}
    return g


def new_game(meet=True, **kw):
    """meet: 모든 나라가 서로 조우한 상태로 시작(외교 행동은 조우가 먼저라서)."""
    kw.setdefault("seed", 5)
    g = Game(Settings(**kw))
    g.set_player_government("philosopher")
    return _meet_all(g) if meet else g


def test_setup():
    g = new_game(n_enemies=3, player_start="S002")
    assert len(g.factions) == 4
    assert g.player.capital == "S002"
    assert g.regions["S002"].owner == 0
    assert g.player.money == 3000
    assert g.player.res["food"] == pytest.approx(55.2 * 5)
    assert sum(1 for a in g.armies.values() if a.owner == NEUTRAL) == 427 - 4
    starts = [f.capital for f in g.factions]
    assert len(set(starts)) == 4


def test_island_start_gets_landing_ship():
    g = new_game(player_start="S228")
    assert any(a.units.get("lst") for a in g.armies_at("S228", 0))
    assert g.regions["S228"].b["port"] == 1


def test_annex_completes_and_absorbs_garrison():
    g = new_game(player_start="S002", n_enemies=1)
    target = "S025" if "S025" in g.world.land_adj["S002"] else sorted(g.world.land_adj["S002"])[0]
    target = min(g.world.land_adj["S002"], key=lambda r: g.regions[r].pop)
    ok, msg = g.start_project(0, "S002", "annex", target)
    assert ok, msg
    turns = g.regions["S002"].project.turns
    for _ in range(turns):
        g.player.money += 10_000
        g.end_turn()
    assert g.regions[target].owner == 0
    assert any(a.owner == 0 for a in g.armies_at(target))


def test_cancel_refund_and_stall():
    g = new_game(player_start="S002", n_enemies=1)
    ok, _ = g.start_project(0, "S002", "build", "bank")
    assert ok
    g.player.money = 1e6
    g.end_turn()
    paid = g.regions["S002"].project.paid
    money = g.player.money
    g.cancel_project(0, "S002")
    assert g.player.money == pytest.approx(money + paid * 0.5)
    g.start_project(0, "S002", "build", "bank")
    g.player.money = 0
    g._fund_projects()
    assert g.regions["S002"].project.stalled


def test_energy_cannot_be_bought_but_sold():
    g = new_game()
    f = g.player
    m0, o0 = f.money, f.res["oil"]
    assert g.market_buy(0, "oil", 3) == (0, 0.0) and g.max_buyable(0, "coal") == 0
    assert f.money == m0 and f.res["oil"] == o0
    f.res["coal"] = 5                                   # 이번 턴 확보량에서 판다
    k, gain = g.market_sell(0, "coal", 2)
    assert k == 2 and gain > 0
    assert g.market_buy(0, "food", 1)[0] == 1


def test_tax_lock(monkeypatch):
    from korciv.leaders import LEADER_BY_KEY
    monkeypatch.setitem(LEADER_BY_KEY["cus"], "fx", {"tax_lock": 4})
    g = new_game(player_leader="cus")
    assert g.set_tax(0, 0.15)[0]
    ok, _ = g.set_tax(0, 0.12)
    assert not ok


def test_jeongjo_industry_build_time():
    from korciv.rules import prod_building_turns
    g = new_game(player_leader="jjo")
    base = prod_building_turns(1)
    assert g.build_time(0, "factory", 10) == 12 and g.build_time(0, "power", 10) == 12
    assert g.build_time(0, "extract", 10) == 12
    assert g.build_time(0, "bank", 10) == 10 and base > 0


def test_kimdj_friendship_backlash():
    g = new_game(player_start="S002", n_enemies=3, player_leader="kdj")
    g.dip.op[(3, 1)] = -60
    assert any(e[2] < 0 for e in D.friendship_effects(g, 0, 1))      # '노벨 평화상'에는 반감 면제 없음


def _neutral_ai(g, *fids):
    """시드에 따라 달라지는 AI 지도자·체제 효과를 없앤다."""
    for fid in fids:
        g.factions[fid].leader, g.factions[fid].gov = "cus", "philosopher"
    g._mods.clear()


def test_war_and_peace():
    g = new_game(n_enemies=2)
    _neutral_ai(g, 1, 2)
    ok, _ = D.declare_war(g, 0, 1)
    assert ok and D.at_war(g, 0, 1)
    assert D.opinion(g, 1, 0) <= -99
    assert g.player.war_weary == pytest.approx(15)        # 선포한 쪽 전쟁 피로 +15
    assert g.factions[1].war_weary == pytest.approx(10)   # 당한 쪽 +10
    D.make_peace(g, 0, 1)
    assert not D.at_war(g, 0, 1)
    assert D.has_nonaggr(g, 0, 1)
    ok, _ = D.declare_war(g, 0, 1)
    assert not ok


def test_trade_gift_and_demand():
    g = _meet_all(new_game(n_enemies=2))
    g.power = {f.id: 1.0 for f in g.factions}         # 국력 차이로 요구를 받아들이지 않게
    offer = D.empty_offer()
    offer["give"]["money"] = 500
    res, _, _ = D.respond_offer(g, 1, 0, offer)
    assert res == "accept"
    offer = D.empty_offer()
    offer["take"]["money"] = 500
    res, _, _ = D.evaluate_offer(g, 1, 0, offer)
    assert res == "reject"


def test_combat_capture_neutral():
    g = new_game(player_start="S002", n_enemies=1)
    target = min(g.world.land_adj["S002"], key=lambda r: g.regions[r].pop)
    army = g.armies_at("S002", 0)[0]
    army.units["inf"] = 6
    ok, msg = g.order_army(army.id, target)
    assert ok, msg
    g.end_turn()
    r = g.regions[target]
    assert (r.occ and r.occ["by"] == 0) or r.owner == 0


def test_rebellion_resolution_paths():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    r.happy = -80
    cost = g.rebellion_accept_cost(0, "S002")
    assert cost == pytest.approx(g.gdp(0) * 80 * C.REBEL_PAY_GDP)     # GDP × (−행복도) 비례
    g.player.money = cost - 1
    g.pending_rebellions = ["S002"]
    msg = g.resolve_rebellion(0, "S002", "pay")
    assert "부족" in msg and r.happy == -80 and g.pending_rebellions == ["S002"]   # 돈이 모자라면 그대로 남는다
    g.player.money = cost + 5
    tax0 = g.player.tax
    msg = g.resolve_rebellion(0, "S002", "tax")              # 예전 '세율 인하'도 이제 돈 지급
    assert "지불" in msg and r.happy == pytest.approx(-60) and g.player.tax == tax0
    assert g.player.money == pytest.approx(5) and not g.pending_rebellions
    g.rng.seed(0)
    for a in g.armies_at("S002", 0):
        a.units["inf"] = 0
    msg = g.resolve_rebellion(0, "S002", "suppress")
    assert "실패" in msg
    assert not g.player.alive  # 영토 1칸에서 진압 실패 → 멸망


def test_save_load_roundtrip():
    g = new_game()
    for _ in range(3):
        g.end_turn()
    g2 = pickle.loads(pickle.dumps(g))
    assert g2.turn == g.turn and g2.world is not None
    g2.end_turn()


@pytest.mark.parametrize("seed", [1, 2])
def test_ai_simulation_invariants(seed):
    g = Game(Settings(n_enemies=5, seed=seed, all_ai=True))
    for _ in range(120):
        g.end_turn()
        if g.game_over:
            break
    alive = set(g.alive_ids())
    for r in g.regions.values():
        assert r.owner == NEUTRAL or r.owner in alive
        assert -100 <= r.happy <= 100
        assert r.pop > 0
    for a in g.armies.values():
        assert not a.empty()
        assert a.owner == NEUTRAL or a.owner in alive
    for f in g.factions:
        assert math.isfinite(f.money)
    assert len(g.factions) <= C.MAX_FACTIONS
    for f in g.factions:
        assert len([c for c in g.factions if c.alive and c.rebel_of == f.id]) <= C.REBEL_MAX_PER_PARENT


def _fail_suppression(g, fid, rid):
    g.rng.seed(0)
    for a in g.armies_at(rid, fid):
        a.units["inf"] = 0
    g.regions[rid].happy = -90
    return g.resolve_rebellion(fid, rid, "suppress")


def _own(g, fid, rids):
    for rid in rids:
        g.transfer_region(rid, fid)


def _room(g, rids):
    """면적과 무관한 기존 엔진 테스트에서 건설할 수 있는 넓은 시험 부지를 만든다."""
    import copy
    from dataclasses import replace
    g.world = copy.copy(g.world)
    g.world.regions = dict(g.world.regions)
    for rid in rids:
        g.world.regions[rid] = replace(g.info(rid), area_km2=1000.0)


def test_rebel_region_becomes_capital_and_inherits_state():
    g = new_game(player_start="S002", n_enemies=1)
    near = sorted(g.world.land_adj["S002"])[:3]
    _own(g, 0, near)
    rid = near[0]
    r = g.regions[rid]
    _room(g, [rid])
    r.b["bank"] = 3
    r.sci.add("lab")
    pop, b = r.pop, dict(r.b)
    g.start_project(0, rid, "build", "farm")
    msg = _fail_suppression(g, 0, rid)
    nf = g.factions[-1]
    assert "분리독립" in msg
    assert r.owner == nf.id and nf.capital == rid and nf.rebel_of == 0
    assert r.pop == pop and r.b == b and not r.sci      # 과학·경제 시설은 빼앗기면 쓸 수 없다(독립은 바로 철거)
    assert r.project and r.project.key == "farm"
    assert D.at_war(g, 0, nf.id)
    # 첫 24턴 행복도 하한 0
    r.h_delta = -500
    g._phase_happiness()
    assert r.happy >= 0
    g.turn = nf.happy_floor_until
    r.h_delta = -500
    g._phase_happiness()
    assert r.happy < 0


def test_rebel_limit_three_per_parent_and_sibling_opinion():
    g = new_game(player_start="S002", n_enemies=1)
    rids = sorted(g.world.land_adj["S002"])[:5]
    _own(g, 0, rids)
    govs = ["absolute", "constitutional", "presidential"]
    made = []
    for i, rid in enumerate(rids[:3]):
        _fail_suppression(g, 0, rid)
        made.append(g.factions[-1])
        made[-1].gov = govs[i]
    assert len(g.rebel_children(0)) == 3
    n = len(g.factions)
    msg = _fail_suppression(g, 0, rids[3])
    assert len(g.factions) == n and "합류" in msg
    assert g.regions[rids[3]].owner in {f.id for f in made}


def test_sibling_opinion_by_government():
    from korciv.leaders import gov_similar
    assert gov_similar("absolute", "constitutional")      # 군주정
    assert gov_similar("presidential", "parliamentary")   # 민주정
    assert not gov_similar("presidential", "fascist")
    g = new_game(player_start="S002", n_enemies=1)
    rids = sorted(g.world.land_adj["S002"])[:3]
    _own(g, 0, rids)
    _fail_suppression(g, 0, rids[0])
    a = g.factions[-1]
    _fail_suppression(g, 0, rids[1])
    b = g.factions[-1]
    expected = C.REBEL_SIBLING_OPINION if gov_similar(a.gov, b.gov) else -C.REBEL_SIBLING_OPINION
    assert D.opinion(g, b.id, a.id) == expected and D.opinion(g, a.id, b.id) == expected


def test_specialty_auto_lowest_happiness_first_and_manual():
    g = new_game(player_start="S002", n_enemies=1)
    rids = sorted(g.world.land_adj["S002"])[:3]
    _own(g, 0, rids)
    regs = [g.regions[r] for r in ["S002"] + rids]
    for i, r in enumerate(regs):
        r.happy = [30, -20, 10, 0][i]
    f = g.player
    f.specialty = {"가": 1, "나": 1}
    g._distribute_specialties(f, regs)
    low = min(regs, key=lambda r: r.happy)
    assert low.supplied == {"가", "나"}           # 행복도 가장 낮은 지역부터
    assert low.h_delta == 0                        # 1회성 증가 없음(턴당 +0.1/종은 행복도 단계에서)
    # 수동: 가장 행복한 지역에 '가' 고정, 낮은 지역은 '나' 제외
    high = max(regs, key=lambda r: r.happy)
    g.set_specialty(0, high.id, "가", "pin")
    g.set_specialty(0, low.id, "나", "block")
    f.specialty = {"가": 1, "나": 1}
    for r in regs:
        r.h_delta = 0
    g._distribute_specialties(f, regs)
    assert "가" in high.supplied and "나" not in low.supplied
    assert low.supplied == set()                  # 두 종류 모두 중단


def test_science_victory_chain():
    g = new_game(player_start="S002", n_enemies=1)
    f = g.player
    sci = lambda rid: [o for o in g.options(0, rid) if o["kind"] == "science"]
    other = sorted(g.world.land_adj["S002"])[0]
    _own(g, 0, [other])
    assert [o["key"] for o in sci("S002")] == ["lab"] and not sci(other)       # 1단계는 수도에서만
    base = sci("S002")[0]
    assert base["turns"] == C.SCIENCE_TURNS and base["per_turn"] == pytest.approx(C.SCIENCE_COST_PER_TURN)
    ok, _ = g.start_project(0, "S002", "science", "lab")
    assert ok
    p = g.regions["S002"].project
    g.regions["S002"].project = None
    g._complete_project(f, g.regions["S002"], p)
    assert f.science == ["lab"] and "lab" in g.regions["S002"].sci
    # 2단계: 산맥과 맞닿은 지역에서만, 비용 ×1.1
    mtn = next(r for r in g.world.order if r in g.world.mountain_regions and g.regions[r].owner == NEUTRAL)
    flat = next(r for r in g.world.order if r not in g.world.mountain_regions and g.regions[r].owner == NEUTRAL
                and g.world.land_adj[r])
    _own(g, 0, [mtn, flat])
    assert [o["key"] for o in sci(mtn)] == ["observatory"] and not sci(flat)
    assert sci(mtn)[0]["per_turn"] == pytest.approx(C.SCIENCE_COST_PER_TURN * C.SCIENCE_COST_GROWTH)
    # 3단계 예산 편성은 은행 5단계(금융 단지) 지역에서만, 다른 단계처럼 ×1.1^2
    f.science = ["lab", "observatory"]
    assert not sci(flat)
    g.regions[flat].b["bank"] = 5
    assert [o["key"] for o in sci(flat)] == ["budget"]
    assert sci(flat)[0]["per_turn"] == pytest.approx(C.SCIENCE_COST_PER_TURN * C.SCIENCE_COST_GROWTH ** 2)
    ok, _ = g.start_project(0, flat, "science", "budget")
    assert ok
    p = g.regions[flat].project
    g.regions[flat].project = None
    g._complete_project(f, g.regions[flat], p)
    assert "budget" in g.regions[flat].sci and f.science[-1] == "budget"
    g.regions[flat].b["bank"] = 0
    # 5·6단계는 공장 5단계, 7단계는 석유 지역
    f.science = ["lab", "observatory", "budget", "pad"]
    assert not sci(flat)
    g.regions[flat].b["factory"] = 5
    assert [o["key"] for o in sci(flat)] == ["booster"]
    f.science += ["booster", "module"]
    oil = next(r for r in g.world.order if g.world.regions[r].is_oil)
    _own(g, 0, [oil])
    g.regions[oil].b["extract"] = 4
    assert not sci(oil)                                   # 석유 지역이라도 정유공장 5단계가 아니면 불가
    g.regions[oil].b["extract"] = 5
    assert [o["key"] for o in sci(oil)] == ["propellant"]
    # 유닛을 잃으면 그 단계를 다시 만들 수 있다(다음 단계와 함께)
    assert g.science_available(0) == ["propellant", "booster", "module"]
    f.science.append("propellant")
    assert g.science_available(0) == ["booster", "module", "propellant"]
    # 발사: 세 유닛을 발사대 지역에 모으고 턴을 마치면 승리
    pad = next(r for r in g.world.order if g.world.regions[r].coastal and g.regions[r].owner == NEUTRAL)
    _own(g, 0, [pad])
    g.regions[pad].sci.add("pad")
    g.regions[g.factions[0].capital].sci |= {"lab", "observatory", "budget"}   # 시설이 모두 살아 있어야 발사
    for k in C.SCIENCE_UNITS[:2]:
        g.add_units(0, pad, k, 1)
    assert g.launch_ready(0) is None
    g.add_units(0, pad, "propellant", 1)
    assert g.launch_ready(0) == pad
    assert len([a for a in g.armies_at(pad, 0) if g.is_science_army(a)]) == 1      # 과학 유닛끼리만 한 부대
    g.end_turn()
    assert g.game_over and g.winner == ((0,), "science")


def test_science_units_cannot_fight():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    a = g.add_units(0, "S002", "booster", 1)
    reach = g.reachable(a)
    assert tgt not in reach                                   # 중립 땅으로는 못 간다
    _own(g, 0, [tgt])
    for x in g.armies_at(tgt):
        g.remove_army(x)
    reach = g.reachable(a)
    assert reach[tgt]["action"] == "move"
    assert g.unit_cost(0, "S002", "inf") > 0 and "booster" not in {o["key"] for o in g.options(0, "S002")
                                                                    if o["kind"] == "unit"}


def test_science_leaders():
    g = new_game(player_start="S002", n_enemies=1, player_leader="sen")
    assert g.science_turns(0) == 12                                                # 첨성대
    g = new_game(player_start="S002", n_enemies=1, player_leader="gon")
    assert g.science_step_cost(0, "lab") == pytest.approx(
        C.SCIENCE_COST_PER_TURN * C.SCIENCE_TURNS * 1.25)                          # 영전 공사


def test_production_focus_bonus():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    base = g.calc_output("S002", full=True)
    g.set_focus(0, "S002", True)
    assert g.calc_output("S002", full=True) == pytest.approx(
        base + 30 * r.pop * C.FOCUS_POP_BONUS * (1 + C.CAPITAL_OUTPUT_BONUS))     # 수도 산출 +10%
    g.start_project(0, "S002", "build", "farm")          # 건설 중에는 효과 없음
    assert g.calc_output("S002", full=True) == pytest.approx(base)
    assert g.idle_slots(0) == 0


def test_spending_priority_order():
    g = new_game(player_start="S002", n_enemies=1)
    rids = ["S002"] + sorted(g.world.land_adj["S002"])[:2]
    _own(g, 0, rids[1:])
    for rid in rids:
        ok, _ = g.start_project(0, rid, "build", "bank")
        assert ok
    per = g.regions["S002"].project.per_turn
    g.player.money = per * 1.5            # 한 건만 낼 수 있음
    g.set_priority_order(0, [rids[2], rids[0], rids[1]])
    g._fund_projects()
    assert g.regions[rids[2]].project.funded
    assert g.regions[rids[0]].project.stalled and g.regions[rids[1]].project.stalled


def test_river_fishery_and_coast_bonus():
    g = new_game(player_start="S002", n_enemies=1)
    n = g.world.name_to_id
    inland_river = n["경북 상주시"]            # 낙동강 도하 경계, 내륙
    assert not g.info(inland_river).coastal and g.can_fish(inland_river)
    assert g.fish_mult(0, inland_river) == pytest.approx(C.RIVER_FISH_MULT)
    assert not g.can_fish(n["충북 증평군"])      # 해안도 강도 아님
    # 해역의 해안 지역을 모두 가지면 바다 어장 +20%
    sea = "SEA4"
    for rid in g.world.seas[sea].coast:
        g.regions[rid].owner = 0
    coast = g.world.seas[sea].coast[0]
    assert g.coast_controller(sea) == 0
    assert g.fish_mult(0, coast) == pytest.approx(1 + C.COAST_FISH_BONUS) == pytest.approx(1.2)
    assert C.COAST_NAVAL_DEF == pytest.approx(0.10)


def test_peace_nonaggression_locked_24_turns():
    g = new_game(n_enemies=2)
    D.declare_war(g, 0, 1)
    D.make_peace(g, 0, 1)
    assert D.peace_left(g, 0, 1) == 24
    ok, msg = D.break_nonaggr(g, 0, 1)
    assert not ok and "강화" in msg
    ok, _ = D.declare_war(g, 0, 1)
    assert not ok
    g.turn += 24
    assert D.peace_left(g, 0, 1) == 0


def test_no_sea_annex():
    g = new_game(player_start="S002", n_enemies=1)
    n = g.world.name_to_id
    busan, jeju_s = n["부산 중구"], n["제주 서귀포시"]
    _own(g, 0, [busan])
    g.regions[busan].b["port"] = 1
    g.new_army(0, "SEA11", {"lst": 1})                 # 상륙함이 있어도 해로 편입은 없다
    g.new_army(0, busan, {"lst": 1})
    targets = {t["target"] for t in g.annex_targets(0, busan)}
    assert targets <= set(g.world.land_adj[busan]) and jeju_s not in targets


def test_multi_turn_route_moves_automatically():
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    dist = w.distances_from("S002", 8)
    far = next(r for r, d in sorted(dist.items(), key=lambda kv: -kv[1])
               if not w.is_sea(r) and d >= 5 and w.regions[r].island == "")
    # 가는 길의 지역을 모두 자국 영토로
    prev, q = {"S002": None}, [ "S002"]
    while q:
        u = q.pop(0)
        for v in w.land_adj[u]:
            if v not in prev:
                prev[v] = u
                q.append(v)
    path, u = [], far
    while u != "S002":
        path.append(u)
        u = prev[u]
    _own(g, 0, path)
    for rid in path:
        for a in list(g.armies_at(rid)):
            g.remove_army(a)
    army = g.new_army(0, "S002", {"inf": 3})
    assert far not in g.reachable(army)
    ok, msg = g.order_army(army.id, far)
    assert ok and army.goto == far, msg
    for _ in range(len(path)):
        g.player.money += 10_000
        g.end_turn()
        if army.loc == far:
            break
    assert army.loc == far and army.goto is None


def test_neutral_turns_follow_region_value():
    g = new_game(player_start="S002", n_enemies=1)
    vals = [g.region_value(r)[0] for r in g.world.order]
    assert min(vals) == 1 and max(vals) == 10
    assert len(set(vals)) == 10
    for t in g.annex_targets(0, "S002"):
        assert t["turns"] == C.VALUE_TURNS[t["value"] - 1]
        assert t["cost"] == pytest.approx(g.annex_cost(0, t["target"]))
    tgt = min(g.world.land_adj["S002"], key=lambda r: -g.region_value(r)[0])
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    g.begin_occupation(0, tgt)
    assert g.regions[tgt].occ["need"] == g.neutral_turns(0, tgt)


def test_government_opinion_baseline():
    from korciv.leaders import gov_opinion_bias as bias
    assert bias("absolute", "constitutional") == 10          # 군주정끼리
    assert bias("presidential", "parliamentary") == 10       # 민주정끼리
    assert bias("absolute", "socialist") == -10              # 군주제 → 사회주의
    assert bias("socialist", "presidential") == -10          # 사회주의 → 민주주의
    assert bias("presidential", "absolute") == -10           # 민주주의 → 군주제
    assert bias("socialist", "absolute") == 0                # 한 방향만
    g = new_game(n_enemies=2, ai_leaders=["sej", "jjo"], player_leader="cus")   # 우호도 효과가 없는 지도자
    g.factions[1].gov, g.factions[2].gov = "absolute", "socialist"
    g.dip.op[(1, 2)] = 0.0
    g.hegemon = None                                         # 패권 견제로 비패권국끼리 가까워지지 않게
    for _ in range(300):
        D.update_turn(g)
    assert D.opinion(g, 1, 2) == pytest.approx(-10, abs=3)   # 기본값으로 수렴


def _border_setup(aggr, gov="presidential"):
    """플레이어(0) 수도 옆 지역들을 AI(1)에게 주고, AI 병력을 국경에 둔다."""
    from korciv import ai as AI
    g = new_game(player_start="S002", n_enemies=1)
    g.turn = 40
    ai_f = g.factions[1]
    ai_f.aggression, ai_f.gov, ai_f.leader = aggr, gov, "cus"   # 지도자 효과 없이
    g._mods.clear()
    border = sorted(g.world.land_adj["S002"])[:2]
    _own(g, 1, border)
    for rid in border:
        for a in list(g.armies_at(rid)):
            g.remove_army(a)
    g.new_army(1, border[0], {"inf": 12, "tank": 2})
    g._visible = {}
    return g, AI, border


def test_ai_war_needs_opinion_below_aggression_threshold():
    g, AI, _ = _border_setup(aggr=2)
    f = g.factions[1]
    g.dip.op[(1, 0)] = -20.0          # 싫어하지만 평화적인 지도자에게는 아직 참을 만하다
    AI._consider_war(g, f)
    assert not D.at_war(g, 0, 1)
    g.dip.op[(1, 0)] = -95.0          # 참다참다 못해
    for r in g.regions_of(1):
        r.happy = -25.0
    AI._consider_war(g, f)
    assert not D.at_war(g, 0, 1)      # 하지만 민심(실질 행복도 −20 미만)이 무너져 있으면 참는다
    for r in g.regions_of(1):
        r.happy = 40.0                # 민심에 여유가 있으면
    AI._consider_war(g, f)
    assert D.at_war(g, 0, 1)

    g, AI, _ = _border_setup(aggr=9, gov="fascist")
    g.dip.op[(1, 0)] = 0.0            # 아주 호전적인 지도자는 필요하면 바로
    AI._consider_war(g, g.factions[1])
    assert D.at_war(g, 0, 1)


def test_ai_keeps_fighting_when_front_is_favorable():
    g, AI, border = _border_setup(aggr=5)
    D.declare_war(g, 1, 0)
    g.turn += 8
    # 플레이어가 AI 지역 하나를 빼앗았다
    g.transfer_region(border[1], 0)
    assert D.war_info(g, 1, 0)["lost"] == 1
    ok, why = D.treaty_check(g, 1, 0, "peace")
    assert not ok and "역전" in why            # 다른 전선에서 우세 → 계속 싸운다
    # 병력을 잃고 영토 대부분을 빼앗기면 강화를 받아들인다
    for a in [a for a in g.armies.values() if a.owner == 1]:
        g.remove_army(a)
    g.new_army(0, "S002", {"inf": 20, "tank": 5})
    g._visible = {}
    g.factions[1].ai.pop("intel", None)
    g.turn += 20
    ok, why = D.treaty_check(g, 1, 0, "peace")
    assert ok, why


def test_joint_annex_speeds_up():
    from korciv import rules as R
    assert [R.joint_reduction(n) for n in range(1, 7)] == [0, 0.33, 0.5, 0.6, 0.7, 0.7]
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    # 서로 다른 내 지역 3곳이 같은 중립 지역에 맞닿도록
    tgt = next(v for v in w.order if g.regions[v].owner == NEUTRAL and g.region_value(v)[0] >= 5
               and len([n for n in w.land_adj[v] if g.regions[n].owner == NEUTRAL]) >= 3)
    mine = sorted(n for n in w.land_adj[tgt] if g.regions[n].owner == NEUTRAL)[:3]
    _own(g, 0, mine)
    base = g.neutral_turns(0, tgt)
    for i, rid in enumerate(mine):
        ok, msg = g.start_project(0, rid, "annex", tgt)
        assert ok, msg
        if i == 1:
            opt = next(o for o in g.options(0, mine[2]) if o["kind"] == "annex" and o["key"] == tgt)
            assert "공동 3곳" in opt["name"]
    assert g.project_left(mine[0]) == R.joint_turns(base, 3)
    turns = 0
    while g.regions[tgt].owner != 0 and turns < base + 2:
        g.player.money += 50_000
        g.end_turn()
        turns += 1
    assert g.regions[tgt].owner == 0
    assert turns <= R.joint_turns(base, 3) < base
    assert all(g.regions[r].project is None for r in mine)


def test_net_includes_project_spending():
    g = new_game(player_start="S002", n_enemies=1)
    ok, _ = g.start_project(0, "S002", "build", "bank")
    assert ok
    per = g.regions["S002"].project.per_turn
    before = g.player.money
    g.end_turn()
    last = g.player.last
    assert last["spend"]["build"] == pytest.approx(per)
    assert last["net"] == pytest.approx(last["tax"] + last["sell"] + last["refund"]
                                        - last["upkeep"] - last["buy"] - per)
    assert g.player.money - before == pytest.approx(last["net"])


def test_hijacked_annex_cancelled_and_refunded():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    ok, _ = g.start_project(0, "S002", "annex", tgt)
    g.player.money += 50_000
    g._fund_projects()
    paid = g.regions["S002"].project.paid
    assert paid > 0
    # AI(1)가 이 편입을 하던 중 플레이어가 먼저 차지하면 AI 작업 취소·환급·우호도 하락
    ai_src = next(n for n in g.world.land_adj[tgt] if n != "S002")
    _own(g, 1, [ai_src])
    g.regions[ai_src].project = None
    ok, msg = g.start_project(1, ai_src, "annex", tgt)
    assert ok, msg
    g.factions[1].money += 50_000
    g._fund_projects()
    ai_paid = g.regions[ai_src].project.paid
    money = g.factions[1].money
    op = D.opinion(g, 1, 0)
    g.transfer_region(tgt, 0)
    assert g.regions[ai_src].project is None
    assert g.factions[1].money == pytest.approx(money + ai_paid)
    assert D.opinion(g, 1, 0) == pytest.approx(op + C.OP_HIJACK + C.OP_LAND_GRAB)   # 가로채기 + 영토 경쟁


def test_food_bought_before_projects():
    g = new_game(player_start="S002", n_enemies=1)
    f = g.player
    f.res["food"] = 0
    ok, _ = g.start_project(0, "S002", "build", "bank")
    per = g.regions["S002"].project.per_turn
    short = -g.expected_food_balance(f)
    assert short > 0
    f.money = per + 5        # 식량을 사면 공사비가 모자란다
    g._fund_projects()
    assert f.res["food"] >= short - 1e-6
    assert g.regions["S002"].project.stalled


def test_war_weariness_separate_from_happiness():
    g = new_game(n_enemies=2)
    _neutral_ai(g, 1, 2)
    cap = g.regions[g.player.capital]
    cap.happy = 0.0
    g.player.tax = 0.10
    D.declare_war(g, 0, 1)
    g._phase_happiness()
    assert cap.happy == pytest.approx(0, abs=0.01)         # 전쟁이 행복도를 직접 깎지 않는다
    assert g.player.war_weary == pytest.approx(15.5)       # 선포 +15, 전쟁 중 턴당 +0.5
    assert g.factions[1].war_weary == pytest.approx(10.5)  # 당한 쪽 +10, 턴당 +0.5
    assert g.eff_happy(cap) == pytest.approx(-15.5)       # 실질 행복도 = 행복도 − 전쟁 피로도
    assert g.avg_happiness(0) == pytest.approx(-15.5) and g.avg_happiness(0, effective=False) == pytest.approx(0)
    for _ in range(400):
        g._phase_happiness()
    assert g.player.war_weary == C.WAR_WEARY_MAX
    D.make_peace(g, 0, 1)
    g._phase_happiness()
    assert g.player.war_weary == pytest.approx(C.WAR_WEARY_MAX - 1)   # 평시 턴당 1 회복


def test_warmonger_reputation():
    """전쟁광 평판: 1년 안의 첫 선포는 영향 없음, 두 번째부터 −10, 그 뒤로 5씩 더."""
    g = new_game(n_enemies=4)
    before = {c: D.opinion(g, c, 0) for c in (2, 3)}
    assert D.warmonger_penalty(g, 0) == 0
    D.declare_war(g, 0, 1)
    for c in (2, 3):
        assert D.opinion(g, c, 0) == pytest.approx(before[c])
    D.make_peace(g, 0, 1)
    g.turn += 30                                   # 직전 전쟁이 끝난 지 1년이 안 됐다
    before = D.opinion(g, 3, 0)
    D.declare_war(g, 0, 2)
    assert D.opinion(g, 3, 0) == pytest.approx(before - 10)
    assert D.warmonger_penalty(g, 0) == -15        # 또 선포하면 −15
    D.make_peace(g, 0, 2)
    g.turn += C.WARMONGER_WINDOW + 1
    assert D.warmonger_penalty(g, 0) == 0          # 1년이 지나면 처음처럼(영향 없음)


def test_allied_defense_counts_as_defender_weariness():
    g = new_game(n_enemies=3)
    for f in g.factions:
        f.gov = "philosopher"
    g._mods.clear()
    g.dip.nonaggr[D.pair(1, 2)] = g.turn + 24
    g.dip.alliance[D.pair(1, 2)] = g.turn
    D.declare_war(g, 0, 1)
    assert D.at_war(g, 2, 0)
    assert g.factions[2].war_weary == pytest.approx(10)       # 방어 동맹 참전은 당한 쪽 기준
    assert D.war_weary_rate(g, 2) == pytest.approx(0.5)
    assert D.war_weary_rate(g, 0) == pytest.approx(0.5)
    assert g.player.war_weary == pytest.approx(25)            # 선포 15 + 동맹 참전 상대 10


def _captured(g, rid, by=0, frm=1):
    _own(g, frm, [rid])
    g.regions[rid].happy = 30.0
    for a in list(g.armies_at(rid)):
        g.remove_army(a)
    D.declare_war(g, by, frm)
    g.new_army(by, rid, {"inf": 3})
    g.complete_occupation(by, rid)
    return g.regions[rid]


def test_captured_region_resists_then_recovers():
    g = new_game(player_start="S002", n_enemies=1)
    rid = sorted(g.world.land_adj["S002"])[0]
    rr = _captured(g, rid)
    g.player.war_weary = 0.0
    assert rr.owner == 0 and g.resisting(rr)
    assert g.eff_happy(rr) == C.RESIST_HAPPY
    assert g.rebellion_chance(0, rid) == 0
    ok, why = g.start_project(0, rid, "unit", "inf")
    assert not ok and "저항" in why
    g._phase_resources(g.player)
    assert rr.output == 0 and rr.food == 0
    assert g.retake_bonus(1, rid) and not g.retake_bonus(0, rid)
    A0, _, _ = g.combat_strength(1, [g.new_army(1, sorted(g.world.land_adj[rid])[0], {"inf": 5})], rid)
    g.regions[rid].resist = None
    A1, _, _ = g.combat_strength(1, [g.new_army(1, sorted(g.world.land_adj[rid])[0], {"inf": 5})], rid)
    assert A0 == pytest.approx(A1 * (1 + C.RESIST_RETAKE_ATK))
    g2 = new_game(player_start="S002", n_enemies=1)
    rr = _captured(g2, rid)
    g2.player.war_weary = 0.0
    g2.turn += C.RESIST_TURNS                       # 회복 시작: −100에서 점령 직전 행복도(30)로
    h1 = g2.eff_happy(rr)
    assert -100 < h1 < 30 and not g2.resisting(rr)
    g2.turn += C.RESIST_RECOVER_TURNS // 2
    assert h1 < g2.eff_happy(rr) < 30
    g2.turn = rr.resist["turn"] + C.RESIST_TURNS + C.RESIST_RECOVER_TURNS
    assert g2.eff_happy(rr) == pytest.approx(rr.happy)
    assert g2.rebellion_chance(0, rid) == 0          # 36턴 동안 반란 없음
    g2.turn = rr.resist["turn"] + C.RESIST_NO_REBEL_TURNS
    assert g2.resist_phase(rr)[0] is None


def test_unhappy_army_fights_worse():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    a = g.new_army(0, "S002", {"inf": 5})
    A0, _, _ = g.combat_strength(0, [a], tgt)
    g.player.war_weary = 60.0                     # 실질 평균 행복도 −60
    g._morale = {}
    A1, _, _ = g.combat_strength(0, [a], tgt)
    assert A1 == pytest.approx(A0 * R.unhappy_output_mult(-60 + g.avg_happiness(0, effective=False)), rel=1e-3)
    assert A1 < A0


def test_conscription_fatigue():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    for _ in range(6):
        g._phase_conscription({"S002"})
    assert r.conscript == 0                         # 6턴까지는 감소 없음
    g._phase_conscription({"S002"})
    assert r.conscript == 1                         # 7턴 1
    for _ in range(3):
        g._phase_conscription({"S002"})
    assert r.conscript == 8                         # 10턴 내내 징집
    base = g.eff_happy(r)
    for _ in range(6):                              # 10 → 4턴: 아직 회복 없음
        g._phase_conscription(set())
    assert r.conscript == 8
    g._phase_conscription(set())                    # 3턴 이하: 빠르게 회복
    assert r.conscript == pytest.approx(8 - C.CONSCRIPT_RECOVERY)
    assert g.eff_happy(r) > base


def test_leader_roster_and_categories():
    from korciv.leaders import LEADERS, LEADER_CATEGORIES, LEADER_BY_KEY, MULT_KEYS, ADD_KEYS
    keys = [k for _, _, ks in LEADER_CATEGORIES for k in ks]
    assert len(keys) == len(set(keys)) == len(LEADERS) - 1 == 46
    assert LEADER_BY_KEY["jum"]["name"] == "동명성왕" and LEADER_BY_KEY["sej"]["name"] == "세종대왕"
    for l in LEADERS:
        # 김구는 디버프가 없다(임시정부 하나)
        assert len(l["fx"]) >= (0 if l["key"] == "cus" else 1 if l["key"] == "kgu" else 2)
    # 새 지도자로 게임을 시작해도 효과가 적용된다
    g = new_game(player_start="S002", n_enemies=5, player_leader="yis",
                 ai_leaders=["yan", "kan", "toy", "taj", "ito"])
    assert g.mods(0).mult("naval_power") == pytest.approx(1.3)
    assert {f.leader for f in g.factions} == {"yis", "yan", "kan", "toy", "taj", "ito"}



def test_honggildong_no_monarchy():
    import random
    from korciv.leaders import ai_pick_government, banned_govs
    assert banned_govs("gil") == {"absolute", "constitutional"}
    assert banned_govs("sej") == set()
    rng = random.Random(1)
    picks = {ai_pick_government(rng, a, 0, 0, banned=banned_govs("gil"))
             for a in range(11) for _ in range(30)}
    assert not picks & {"absolute", "constitutional"}
    g = Game(Settings(seed=5, player_start="S002", n_enemies=1, player_leader="gil"))
    g.set_player_government("absolute")
    assert g.player.gov == "philosopher"
    assert g.mods(0).add("surprise") == 0
    # 신출귀몰: 같은 턴에 한 국가의 두 지역 이상을 공격하면 공격력 +10%
    g = _meet_all(Game(Settings(seed=5, player_start="S002", n_enemies=1, player_leader="gil")))
    g.set_player_government("philosopher")
    t1, t2 = sorted(g.world.land_adj["S002"])[:2]
    _own(g, 1, [t1, t2])
    D.declare_war(g, 0, 1)
    a = g.new_army(0, "S002", {"inf": 5})
    b = g.new_army(0, "S002", {"inf": 5})
    g.order_army(a.id, t1)
    s1 = g.combat_strength(0, [a], t1)[0]
    g.order_army(b.id, t2)
    assert g.multi_attack_on(0, t1)
    assert g.combat_strength(0, [a], t1)[0] == pytest.approx(s1 * 1.20)


def test_wanggeon_far_output():
    g = new_game(player_start="S002", n_enemies=1, player_leader="wan")
    near = g.near_capital(0)
    assert "S002" in near and g.world.land_adj["S002"] <= near
    far = next(r for r in g.world.order if r not in near and g.world.land_adj[r])
    _own(g, 0, [far])
    m = g.mods(0)
    base = g.calc_output(far)
    g.factions[0].leader = "cus"
    g._mods.pop(0, None)
    assert base == pytest.approx(g.calc_output(far) * 0.95)
    assert m.value("far_output") == 0.05

def test_science_cost_grows():
    g = new_game(player_start="S002", n_enemies=1)
    costs = [g.science_step_cost(0, k) for k in C.SCIENCE_STEPS]
    assert costs == pytest.approx([costs[0] * C.SCIENCE_COST_GROWTH ** k for k in range(len(C.SCIENCE_STEPS))])   # 연료 ≈ 1.77배
    assert costs[0] == pytest.approx(80_000 * C.SCIENCE_TURNS)


def test_no_peace_victory():
    assert "peace" not in C.VICTORY_TYPES and "peace" not in Settings().victories


def test_bombard_breaks_buildings():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    D.declare_war(g, 0, 1)
    rr = g.regions[tgt]
    rr.b = {k: 0 for k in rr.b}
    rr.b.update(factory=2, port=1)
    rr.lines = {}
    a = g.new_army(0, "S002", {"art": 2})
    g.rng.random = lambda: 0.29                    # 포병 30% 판정 통과
    g._bombard(a, tgt, {"art": 2})
    assert rr.b["factory"] == 1 and rr.b["port"] == 1   # 생산·방어 건물만
    g.rng.random = lambda: 0.31
    g._bombard(a, tgt, {"art": 2})
    assert rr.b["factory"] == 1


def test_assault_can_break_line():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    g.new_army(1, tgt, {"inf": 2})
    g.regions[tgt].lines = {"S002": 2}
    D.declare_war(g, 0, 1)
    att = g.new_army(0, "S002", {"inf": 20})
    g.rng.random = lambda: 0.1                      # 25% 판정 통과
    g._ground_battle(0, [att], tgt, "assault", [att])
    rr = g.regions[tgt]
    lines = rr.lost_def["lines"] if rr.lost_def else rr.lines   # 점령되면 방어선은 꺼진 채로 보관(v1.3.0)
    assert lines["S002"] == 1


def test_unhappy_region_output_penalty():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    r.happy = 0
    base = g.calc_output("S002", full=True)
    r.happy = -100
    assert g.calc_output("S002", full=True) == pytest.approx(base * 0.7)


def test_ai_tax_responds_to_finance_and_happiness():
    from korciv import ai as AI
    g = new_game(n_enemies=1)
    f = g.factions[1]
    f.tax = 0.10
    f.money = -500
    f.last["net"] = -200
    AI._tax(g, f)
    assert f.tax > 0.10                     # 재정 위기: 올린다
    f.money = 1_000_000
    f.last["net"] = 500
    t = f.tax
    AI._tax(g, f)
    assert f.tax < t                        # 넉넉하면 민심에 투자
    for r in g.regions_of(1):
        r.happy = -60
    t = f.tax
    AI._tax(g, f)
    assert f.tax < t                        # 반란 위험: 내린다


def test_ai_builds_defense_on_hostile_border_more_when_rich():
    from korciv import ai as AI
    g, AI, border = _border_setup(aggr=2)
    f = g.factions[1]
    g.dip.op[(1, 0)] = -80.0
    counts = {}
    for money in (300, 200_000):
        n = 0
        for i in range(60):
            for rid in border:
                g.regions[rid].project = None
                g.regions[rid].lines = {}
            f.money = money
            AI._slots(g, f, {})
            n += sum(1 for rid in border if g.regions[rid].project and g.regions[rid].project.key == "line")
        counts[money] = n
    assert counts[200_000] > counts[300] >= 0
    assert counts[200_000] > 0


def test_ai_victory_goal_yearly():
    from korciv import ai as AI
    g = new_game(n_enemies=2)
    f = g.factions[1]
    AI.set_strategy(g, f)
    goal, turn = f.ai["victory_goal"], f.ai["goal_turn"]
    assert goal in g.settings.victories
    g.turn += 12
    AI.set_strategy(g, f)
    assert f.ai["goal_turn"] == turn        # 1년이 지나기 전엔 유지
    g.turn += C.TURNS_PER_YEAR
    AI.set_strategy(g, f)
    assert f.ai["goal_turn"] == g.turn


def _contest_setup():
    """플레이어(0) 수도 S002 옆 중립 지역 하나를, 그 옆 다른 지역을 가진 세력 1과 함께 노린다."""
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    other = next(n for n in sorted(g.world.land_adj[tgt]) if n != "S002" and g.regions[n].owner == NEUTRAL)
    _own(g, 1, [other])
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    return g, tgt, other


def test_occupation_not_cancelled_by_other_army():
    g, tgt, other = _contest_setup()
    _neutral_ai(g, 1)                       # 점령 속도 보정이 있는 지도자가 뽑혀도 같은 조건
    g.new_army(0, tgt, {"inf": 2})
    g.begin_occupation(0, tgt)
    need = g.regions[tgt].occs[0]["need"]
    g._phase_claims()
    g.new_army(1, tgt, {"inf": 2})          # 다른 세력(전쟁 아님) 병력이 들어와 점령을 시작
    g.begin_occupation(1, tgt)
    assert set(g.regions[tgt].occs) == {0, 1}
    assert g.regions[tgt].occs[0]["progress"] == 1     # 원래 점령은 그대로
    for _ in range(need):
        g._phase_claims()
        if g.regions[tgt].owner != NEUTRAL:
            break
    assert g.regions[tgt].owner == 0                    # 먼저 다 채운 쪽
    assert not g.armies_at(tgt, 1)                      # 진 쪽 병력은 귀환


def test_annex_allowed_while_other_occupies_and_occupation_wins_tie():
    g, tgt, other = _contest_setup()
    g.new_army(0, tgt, {"inf": 2})
    g.begin_occupation(0, tgt)
    assert any(t["target"] == tgt for t in g.annex_targets(1, other))   # 다른 세력이 점령 중이어도 편입 가능
    ok, msg = g.start_project(1, other, "annex", tgt)
    assert ok, msg
    occ = g.regions[tgt].occs[0]
    p = g.regions[other].project
    occ["need"] = occ["progress"] + 1                   # 같은 턴에 둘 다 완료되게
    p.turns = p.progress + 1
    g.regions["S002"].pop, g.regions[other].pop = 10.0, 80.0
    g.factions[1].money = 1e6
    g._fund_projects()
    g._phase_claims()
    assert g.regions[tgt].owner == 0                    # 같은 턴: 병력이 있는 무력 점령이 편입보다 먼저


def test_simultaneous_occupation_goes_to_bigger_force():
    g, tgt, other = _contest_setup()
    _neutral_ai(g, 1)
    g.new_army(0, tgt, {"inf": 4})                      # 최대 체력 40
    g.begin_occupation(0, tgt)
    g.new_army(1, tgt, {"tank": 1})                     # 최대 체력 50 (유닛 수는 적어도 규모가 크다)
    g.begin_occupation(1, tgt)
    rr = g.regions[tgt]
    assert g.occ_force(0, tgt) == 40 and g.occ_force(1, tgt) == 50
    for fid in (0, 1):
        rr.occs[fid]["need"] = rr.occs[fid]["progress"] + 1
    g._phase_claims()
    assert rr.owner == 1


def test_empty_enemy_region_taken_at_once():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    g.regions[tgt].happy = 50.0
    D.declare_war(g, 0, 1)
    g.new_army(0, tgt, {"inf": 1})
    g.begin_occupation(0, tgt)
    rr = g.regions[tgt]
    assert rr.owner == 0 and not rr.occs and g.resisting(rr)   # 게이지 없이 즉시, 저항 시작


def test_priority_auto_sort_and_market_max():
    g = new_game(player_start="S002", n_enemies=1)
    near = sorted(g.world.land_adj["S002"])[:3]
    _own(g, 0, near)
    g.factions[0].money = 1e6
    g.factions[0].res["oil"] = 1                        # 이번 턴 석유
    assert g.start_project(0, near[0], "unit", "tank")[0]
    assert g.start_project(0, near[1], "build", "bank")[0]
    t = next(o for o in g.annex_targets(0, "S002"))
    assert g.start_project(0, "S002", "annex", t["target"])[0]
    g.sort_priority(0, "unit")
    assert g.projects_by_priority(0)[0].project.kind == "unit"
    g.sort_priority(0, "annex")
    assert g.projects_by_priority(0)[0].project.kind == "annex"
    g.sort_priority(0, "short")
    lefts = [g.project_left(r.id) for r in g.projects_by_priority(0)]
    assert lefts == sorted(lefts)
    f = g.factions[0]
    f.money = 1000.0
    n = g.max_buyable(0, "food")
    assert g.buy_cost(0, "food", n) <= 1000 < g.buy_cost(0, "food", n + 1)
    bought, spent = g.market_buy(0, "food", n)
    assert bought == n and spent == pytest.approx(g.buy_cost(0, "food", n))


def test_ai_army_leaves_neutral_occupation_when_country_in_crisis():
    from korciv import ai as AI
    g = new_game(player_start="S002", n_enemies=1)
    f = g.factions[1]
    cap = f.capital
    neutral = next(n for n in sorted(g.world.land_adj[cap]) if g.regions[n].owner == NEUTRAL)
    for a in list(g.armies_at(neutral)):
        g.remove_army(a)
    army = g.new_army(1, neutral, {"inf": 11})
    g.begin_occupation(1, neutral)
    assert 1 in g.regions[neutral].occs
    # 평시: 점령을 계속하되(1개만 남기면 속도는 같다), 나머지는 다음 일을 하러 간다
    AI._army_orders(g, f, AI.threat_map(g, 1))
    stay = [a for a in g.armies_at(neutral, 1) if not a.order]
    assert 1 in g.regions[neutral].occs and sum(a.count() for a in stay) == 1
    # 전쟁에서 땅을 잃는 중: 중립 땅 점령을 버리고 움직인다
    D.declare_war(g, 0, 1)
    g.dip.wars[D.pair(0, 1)]["taken"][0] = 1
    AI._army_orders(g, f, AI.threat_map(g, 1))
    assert army.order is not None and army.order.get("target", army.order.get("path", [None])[-1]) != neutral


def test_battle_breakdown_lists_sides_and_factors():
    g = new_game(player_start="S002", n_enemies=1, player_leader="tae")
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    g.new_army(1, tgt, {"inf": 4})
    g.regions[tgt].lines = {"S002": 2}
    D.declare_war(g, 0, 1)
    a = g.new_army(0, "S002", {"inf": 8})
    bd = g.battle_breakdown(a, tgt, "assault")
    assert bd["att_units"] == {"inf": 8} and bd["def_units"] == {1: {"inf": 4}}
    labels = [l for l, _ in bd["att_factors"]] + [l for l, _ in bd["def_factors"]]
    assert any("백전백승" in l for l in labels) and any("방어선 2단계" in l for l in labels)
    assert len(g.battle_breakdown(a, tgt, "surprise")["outcomes"]) == 2


def test_coalition_not_resigned_when_already_together():
    g = new_game(n_enemies=2)
    g.dip.alliance[D.pair(1, 2)] = g.turn - 30
    g.dip.op[(1, 2)] = g.dip.op[(2, 1)] = 100.0
    D.sign_treaty(g, 1, 2, "coalition")
    assert D.same_coalition(g, 1, 2)
    ok, why = D.treaty_check(g, 1, 2, "coalition")
    assert not ok and "이미" in why


def test_alliance_kept_until_opinion_30_and_coalition_at_60():
    g = new_game(n_enemies=2)
    p = D.pair(1, 2)
    g.dip.alliance[p] = g.turn
    g.dip.op[(1, 2)] = g.dip.op[(2, 1)] = 31.0
    D.update_turn(g)
    assert p in g.dip.alliance                     # 체결 문턱(65)보다 낮아도 30 초과면 유지
    assert D.opinion(g, 1, 2) > C.ALLIANCE_LEAVE
    g.dip.op[(1, 2)] = 20.0
    D.update_turn(g)
    assert D.opinion(g, 1, 2) <= C.ALLIANCE_LEAVE
    assert p not in g.dip.alliance                 # 30 이하면 파기(불가침으로)
    g.hegemon = None
    g.dip.alliance[p] = g.turn - C.COALITION_ALLIANCE_TURNS
    g.dip.op[(1, 2)] = g.dip.op[(2, 1)] = 60.0
    ok, why = D.treaty_check(g, 1, 2, "coalition")
    assert ok, why
    g.dip.alliance[p] = g.turn - C.COALITION_ALLIANCE_TURNS + 1
    assert not D.treaty_check(g, 1, 2, "coalition")[0]


def test_time_victory_and_socialist_rule():
    import random as _r
    from korciv.leaders import ai_pick_government
    g = new_game(n_enemies=2, max_turns=5)
    assert "time" in g.settings.victories
    sc = g.time_scores()
    assert abs(sum(sc.values()) - 100) < 1e-6
    for _ in range(6):
        g.end_turn()
        if g.game_over:
            break
    assert g.game_over and g.winner[1] == "time"
    # 공장·은행이 모두 0이면 사회주의 가산 없음
    rng = _r.Random(3)
    picks = [ai_pick_government(rng, 6.0, 0, 0) for _ in range(2000)]
    rng = _r.Random(3)
    picks_f = [ai_pick_government(rng, 6.0, 2, 0) for _ in range(2000)]
    assert picks.count("socialist") < picks_f.count("socialist")


def _war_pair():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    D.declare_war(g, 0, 1)
    return g, tgt


def test_fighters_support_attack_and_defense():
    g, tgt = _war_pair()
    g.new_army(1, tgt, {"inf": 3})
    att = g.new_army(0, "S002", {"inf": 5})
    A0, _, _ = g.combat_strength(0, [att], tgt)
    g.regions["S002"].b["airport"] = 1
    g.new_army(0, "S002", {"ftr": 2})                  # 공격 측 공항 전투기(대상에서 1칸)
    A1, _, _ = g.combat_strength(0, [att], tgt)
    if C.AIR_GROUND_SUPPORT:
        assert A1 == pytest.approx(A0 + 2 * C.FTR_SUPPORT_ATK * g.morale(0))
    else:
        assert A1 == pytest.approx(A0)                 # 공군은 지상전(돌격·기습)에 끼지 않는다
    D0, _, _ = g.defense_strength(0, tgt, "S002", "assault")
    far = next(n for n in sorted(g.world.land_adj[tgt]) if n != "S002")
    _own(g, 1, [far])
    g.regions[far].b["airport"] = 1
    g.new_army(1, far, {"ftr": 3})
    D1, _, _ = g.defense_strength(0, tgt, "S002", "assault")
    assert D1 > D0 if C.AIR_GROUND_SUPPORT else D1 == pytest.approx(D0)
    g._ground_battle(0, [att], tgt, "assault", [att])   # 지원 전투기도 피해를 나눠 입을 수 있다(오류 없이)


def test_retake_during_resistance_restores_without_new_resistance():
    g, tgt = _war_pair()
    rr = g.regions[tgt]
    rr.happy = 35.0
    g.new_army(0, tgt, {"inf": 1})
    g.complete_occupation(0, tgt)                       # 0이 빼앗음 → 저항
    assert g.resisting(rr) and rr.resist["h0"] == 35.0
    g.complete_occupation(1, tgt)                       # 원래 주인 1이 저항 중에 되찾음
    assert rr.owner == 1 and rr.resist is None and rr.happy == pytest.approx(35.0)


def _single_bld_target():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = next(r for r in g.world.order if g.world.regions[r].coastal and g.world.regions[r].seas
               and g.regions[r].owner == NEUTRAL)
    _own(g, 1, [tgt])
    _clear(g, tgt)
    D.declare_war(g, 0, 1)
    rr = g.regions[tgt]
    for k in rr.b:
        rr.b[k] = 0
    rr.lines.clear()
    fl = g.new_army(0, g.world.regions[tgt].seas[0], {"dd": 3})
    return g, tgt, rr, fl


def test_single_level_buildings_destroyed_10pct_by_bombard():
    """v1.3.0: 항구·공항·사관학교(1단계가 최대)는 일반 건물 피해(−1단계) 대상이 아니고, 폭격당할 때마다 각각
    10% 확률로 파괴된다(v1.3.0 전에는 함포가 항구를 먼저 골라 30% 확률로 없앴다). 의열단은 여전히 대상 아님."""
    g, tgt, rr, fl = _single_bld_target()
    singles = ("port", "airport", "academy")
    rr.b.update(port=1, airport=1, academy=1, factory=3)
    g.rng.random = lambda: 0.15                   # 일반 건물 피해(함포 30%)는 나고, 10% 파괴는 안 남
    g._bombard(fl, tgt, {"dd": 3})
    assert all(rr.b[k] == 1 for k in singles) and rr.b["factory"] == 2
    g.rng.random = lambda: 0.05                   # 10% 안: 셋 다 각각 파괴
    g._bombard(fl, tgt, {"dd": 3})
    assert all(rr.b[k] == 0 for k in singles) and rr.b["factory"] == 1
    rr.b.update(port=1, airport=1, academy=1, factory=2)
    assert g._sabotage(rr) and all(rr.b[k] == 1 for k in singles)      # 의열단은 공장만
    # 실제 무작위로: 폭격 한 번에 항구가 파괴될 확률 ≈ 10%
    g2, tgt2, rr2, fl2 = _single_bld_target()
    n, lost = 1500, 0
    for _ in range(n):
        rr2.b["port"] = 1
        g2._bombard(fl2, tgt2, {"dd": 3})
        lost += rr2.b["port"] == 0
    assert 0.07 < lost / n < 0.13


def test_ai_keeps_capital_garrison():
    from korciv import ai as AI
    g, tgt = _war_pair()
    f = g.factions[0]
    f.is_ai = True
    cap = f.capital
    for a in list(g.armies_at(cap)):
        g.remove_army(a)
    g.new_army(0, cap, {"inf": 10})
    need = AI.capital_min_garrison(g, f, AI.threat_map(g, 0))
    AI._army_orders(g, f, AI.threat_map(g, 0))
    stay = sum(a.count() for a in g.armies_at(cap, 0) if not a.order or a.order.get("type") == "bombard")
    assert need >= 2 and stay >= need


def _lead(g, fid, key):
    g.factions[fid].leader = key
    g._mods.pop(fid, None)


def test_unique_debuffs_setup_and_economy():
    base = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    onjo = new_game(player_start="S002", n_enemies=1, player_leader="onz")
    assert onjo.regions["S002"].pop == pytest.approx(base.regions["S002"].pop * 0.9)      # 십제
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    r = g.regions["S002"]
    r.b["bank"], r.b["factory"], r.b["farm"] = 2, 2, 2
    # 세종 '고기 없이는 못살아': 전국 특산물 생산 10개당 1개 감소(9개까지는 그대로)
    spec = [x for x in g.world.order if g.world.regions[x].specialties][:5]
    _own(g, 0, spec)
    for lk in ("cus", "sej"):
        _lead(g, 0, lk)
        for lv in (3, 2):
            for x in spec:
                g.regions[x].b["specialty"] = lv
                g.regions[x].resist = None
            made = sum(len(g.world.regions[x].specialties) * lv for x in spec)
            have = sum(g.specialty_made(g.player).values())
            assert have == made - (made // 10 if lk == "sej" else 0)
    _lead(g, 0, "egg")                                                              # 교대 계승
    g.turn = 48
    opts = g.options(0, "S002")
    assert all(not o["ok"] for o in opts if o["kind"] in ("build", "unit", "science"))
    g.turn = 49
    assert any(o["ok"] for o in g.options(0, "S002") if o["kind"] == "build")
    _lead(g, 0, "taj")                                                               # 소수민족
    others = [x for x in g.world.order if g.regions[x].owner == NEUTRAL][:44]
    _own(g, 0, others)
    assert g.minority_penalty(0) == pytest.approx(0.3 * (g.region_count(0) - 40))


def test_unique_debuffs_diplomacy_and_rebels():
    g = new_game(player_start="S002", n_enemies=2, player_leader="jan")
    g.dip.nonaggr[D.pair(0, 1)] = g.turn + 99
    g.dip.op[(1, 0)] = 100
    ok, why = D.treaty_check(g, 1, 0, "alliance")
    assert not ok and "골품의 벽" in why
    # 궁예: 반란군 보병 +2, 견훤: 반란 세력이 가장 강한 적국과 동맹
    res = {}
    for lk in ("cus", "gun", "dog"):
        g = new_game(player_start="S002", n_enemies=2, player_leader=lk)
        near = sorted(g.world.land_adj["S002"])[:2]
        _own(g, 0, near)
        D.declare_war(g, 1, 0)
        nf, _ = g._spawn_rebel(0, near[0], 24)
        res[lk] = (sum(a.units.get("inf", 0) for a in g.armies_at(near[0], nf.id)), D.allied(g, nf.id, 1))
    assert res["gun"][0] == res["cus"][0] + 2
    assert res["dog"][1] and not res["cus"][1]
    # 연개소문: 수도 함락 후 12턴 반란 확률 ×3
    g = new_game(player_start="S002", n_enemies=1, player_leader="yon")
    near = sorted(g.world.land_adj["S002"])[:2]
    _own(g, 0, near)
    g.regions[near[0]].happy = -80
    p0 = g.rebellion_chance(0, near[0])
    g.transfer_region("S002", 1)
    assert g.player.capital_fall_turn == g.turn
    assert g.rebellion_chance(0, near[0]) == pytest.approx(min(1.0, p0 * 2))
    g.turn += C.CAPITAL_FALL_TURNS
    assert g.rebellion_chance(0, near[0]) == pytest.approx(p0)


def test_unique_debuffs_combat():
    g = new_game(player_start="S002", n_enemies=1, player_leader="sen")
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    g.new_army(1, tgt, {"inf": 5})
    D.declare_war(g, 1, 0)
    d1 = g.defense_strength(1, "S002", tgt, "assault")[0]
    _lead(g, 0, "cus")
    d0 = g.defense_strength(1, "S002", tgt, "assault")[0]
    assert d1 == pytest.approx(d0 * 0.85) and d0 > 0                                      # 대야성 함락
    _lead(g, 0, "sen")
    g.turn += C.AMBUSH_TURNS
    assert g.defense_strength(1, "S002", tgt, "assault")[0] == pytest.approx(d0)
    # 당 태종: 방어선이 있는 지역 공격 −15%
    _lead(g, 1, "tai")
    a = g.armies_at(tgt, 1)
    g.regions["S002"].lines.clear()                     # 시작 방어선 제거
    s0 = g.combat_strength(1, a, "S002")[0]
    g.regions["S002"].lines[tgt] = 1
    assert g.combat_strength(1, a, "S002")[0] == pytest.approx(s0 * 0.85)
    # 광개토대왕: 저항 기간 +50%
    _lead(g, 1, "ggt")
    g.complete_occupation(1, "S002")
    assert g.regions["S002"].resist["resist"] == 6           # 4 × 1.5


def test_unique_debuffs_occupation_upkeep_naval():
    g = new_game(player_start="S002", n_enemies=1, player_leader="ito")
    D.declare_war(g, 0, 1)
    rid = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [rid])
    g.complete_occupation(0, rid)
    rr = g.regions[rid]
    a = g.new_army(0, rr.id, {"inf": 5})
    assert g.resisting(rr)
    g._phase_guerrilla()                                                                    # 정미의병
    assert a.id not in g.armies or a.units.get("inf", 0) < 5 or a.dmg.get("inf", 0) > 0
    assert any("의병 습격" in e["text"] for e in g.events) or a.dmg.get("inf", 0) > 0
    # 히데요시: 수도와 육로로 이어지지 않은 곳의 부대 유지비 2배
    g = new_game(player_start="S002", n_enemies=1, player_leader="toy")
    far = next(r for r in g.world.order if g.regions[r].owner == NEUTRAL
               and r not in g.supply_linked(0) and g.world.land_adj[r])
    for x in list(g.armies.values()):
        if x.owner == 0:
            g.remove_army(x)
    g.new_army(0, "S002", {"inf": 2})
    u0 = g.upkeep(0)
    g.new_army(0, far, {"inf": 2})
    assert g.upkeep(0) == pytest.approx(u0 * 3)
    # 이순신: 해전에서 지면 12턴 해군 버프 비활성
    g = new_game(player_start="S002", n_enemies=1, player_leader="yis")
    assert g.lead_mult(0, "naval_power") == pytest.approx(1.3)
    sid = next(iter(g.world.seas))
    D.declare_war(g, 0, 1)
    f0 = g.new_army(0, sid, {"dd": 1})
    f1 = g.new_army(1, sid, {"dd": 6})
    g._naval_battle(sid, 0, [f0], 1, [f1])
    assert g.naval_buff_off(0) and g.lead_mult(0, "naval_power") == pytest.approx(1.0)
    g.turn += 12
    assert not g.naval_buff_off(0)
    # 쿠빌라이: 상륙 돌격 ×0.75, 해전 −15%
    _lead(g, 0, "kan")
    assert g.mods(0).value("amphib_extra") == 0.75 and g.mods(0).mult("naval_power") == pytest.approx(0.85)
    assert "일본 원정 실패" in g.fx_source(0, "naval_power")


def test_friendship_declaration():
    g = new_game(player_start="S002", n_enemies=3)
    p, a, b, c = 0, 1, 2, 3
    g.dip.op[(a, p)] = -20
    g.dip.op[(c, a)] = -50                       # c 는 a 와 적대
    ok, why = D.friendship_check(g, p, a)
    assert ok
    eff = D.friendship_effects(g, p, a)
    assert (a, p, C.DECL_FRIEND_BONUS, False) in eff and (c, p, C.DECL_FRIEND_ENEMY, False) in eff
    before_c = D.opinion(g, c, p)
    assert D.declare_friendship(g, p, a)[0]
    assert D.opinion(g, a, p) == pytest.approx(-20 + 10)        # 한 번 +10(기한 없음)
    assert D.opinion(g, c, p) == pytest.approx(before_c - 5)
    assert not D.friendship_check(g, p, a)[0]    # 쿨타임
    assert D.decl_cooldown(g, "friend", p, a) == C.DECL_FRIEND_COOLDOWN == 12
    g.turn += C.DECL_FRIEND_COOLDOWN
    assert D.opinion(g, a, p) == pytest.approx(-10)     # 기한이 끝나도 그대로
    assert D.friendship_check(g, p, a)[0]
    g.dip.op[(b, p)] = -40
    assert not D.friendship_check(g, p, b)[0]    # 우호도 −30 미만은 거절
    D.declare_war(g, p, c)
    assert not D.friendship_check(g, p, c)[0]


def test_denounce_rules():
    g = new_game(player_start="S002", n_enemies=4)
    p, a, b, c, d = 0, 1, 2, 3, 4
    for x in (a, b, c, d):
        for y in (a, b, c, d, p):
            if x != y:
                g.dip.op[(x, y)] = 0.0
    g.dip.op[(c, a)] = -60                       # c 는 a 를 적대
    assert D.denounce(g, p, a)[0]
    assert D.opinion(g, a, p) == pytest.approx(-15)
    assert D.opinion(g, b, a) == pytest.approx(-2) and D.opinion(g, d, a) == pytest.approx(-2)
    assert D.opinion(g, c, p) == pytest.approx(5)       # 적의 적: +5
    assert not D.denounce_check(g, p, a)[0]      # 같은 대상 쿨타임
    D.denounce(g, p, b)
    assert D.opinion(g, d, p) == pytest.approx(0)
    D.denounce(g, p, d)                          # 24턴 안 3번째: 모든 세력 −3
    assert D.opinion(g, c, p) == pytest.approx(5 - 3)
    assert D.opinion(g, a, p) == pytest.approx(-15 - 3)


def test_hp_pool_split_merge_heal():
    g = new_game(player_start="S002", n_enemies=1)
    for x in list(g.armies.values()):
        if x.owner == 0:
            g.remove_army(x)
    a = g.new_army(0, "S002", {"inf": 3})
    hp = C.UNITS["inf"]["hp"]
    a.dmg["inf"] = 3 * hp - 16                   # 남은 체력 16/30
    b, _ = g.split_army(a.id, {"inf": 1})
    assert b.hp_left("inf") == 5 and a.hp_left("inf") == 11      # 5/10, 11/20
    ok, _ = g.merge_armies(a.id, b.id)
    assert ok and a.units["inf"] == 3 and a.hp_left("inf") == 16
    # 싸운 적 없는 부대는 매 턴 유닛 1개당 체력 1 회복(v1.3.0)
    g.end_turn()
    assert a.hp_left("inf") == pytest.approx(16 + C.HEAL_PER_UNIT * 3)
    # 이동한 턴에도 회복한다
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 0, [tgt])
    for x in g.armies_at(tgt):
        g.remove_army(x)
    left = a.hp_left("inf")
    g.order_army(a.id, tgt)
    g.end_turn()
    assert a.hp_left("inf") == pytest.approx(left + C.HEAL_PER_UNIT * 3)
    # 전투에 휘말리면 그 턴과 다음 턴은 회복하지 않고, 2턴이 지나면 다시 회복
    g.apply_damage([a], 5.0)
    left = a.hp_left("inf")
    assert a.last_combat == g.turn
    g.end_turn()
    assert a.hp_left("inf") == pytest.approx(left)
    g.end_turn()
    assert a.hp_left("inf") == pytest.approx(left)
    g.end_turn()
    assert a.hp_left("inf") == pytest.approx(min(a.hp_max("inf"), left + C.HEAL_PER_UNIT * a.units["inf"]))
    assert a.hp_left("inf") > left


def test_ai_leader_bias():
    from korciv import ai
    g = new_game(player_start="S002", n_enemies=2, player_leader="cus", ai_leaders=["yis", "sej"])
    assert ai.leader_bias(g, 1, "naval") > 1.0 and ai.leader_bias(g, 1, "naval") <= 1.15
    assert ai.leader_bias(g, 2, "bank") > 1.0
    _lead(g, 1, "gun")
    assert ai.leader_bias(g, 1, "assault") > 1.0
    _lead(g, 1, "tai")
    assert ai.leader_bias(g, 1, "assault") < 1.0           # 안시성: 방어선 공격 불리
    _lead(g, 1, "cus")
    assert ai.leader_bias(g, 1, "naval") == 1.0


def test_scenic_bonus_and_specialty_per_turn():
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    n = w.name_to_id
    sc = n["서울 성동구"]                          # 서울숲
    assert w.regions[sc].scenic == "서울숲"
    nb = sorted(w.land_adj[sc])[0]
    _own(g, 0, [sc, nb])
    assert g.scenic_bonus(g.regions[sc]) >= C.SCENIC_HAPPY
    base = g.scenic_bonus(g.regions[nb])
    assert base >= C.SCENIC_HAPPY                  # 같은 나라의 인접 지역도 +5
    _own(g, 1, [sc])
    assert g.scenic_bonus(g.regions[nb]) == base - C.SCENIC_HAPPY   # 경관 지역을 잃으면 사라짐
    assert w.regions[n["광주 동구"]].scenic == "" and w.regions[n["전남 화순군"]].scenic == "무등산 입석대"
    # 특산물: 공급받는 종류마다 턴당 +0.1
    r = g.regions["S002"]
    r.happy = 0.0
    r.supplied = {"a", "b"}
    g.player.tax = 0.10
    g._phase_happiness()
    assert r.happy == pytest.approx(0.2 * C.HAPPY_DECAY, abs=0.02)


def test_pop_focus():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    r.happy = 0.0
    ok, _ = g.set_pop_focus(0, "S002", True)
    assert not ok                                  # 실질 행복도 5 미만
    r.happy = 20.0
    assert g.set_pop_focus(0, "S002", True)[0] and r.pop_focus and not r.focus
    p0 = r.pop
    g.player.war_weary = 40                        # 전쟁 피로는 인구 성장에 영향 없음(이주 문턱 −30 위)
    expect = p0 * (C.POP_FOCUS_GROWTH * g.growth_scale(r.id) + R.pop_growth_rate(g.growth_happy(r), g.density_growth(r.id)))
    g._phase_population()
    assert r.pop - p0 == pytest.approx(expect)
    g.player.war_weary = 80                        # 이주는 전쟁 피로 포함 실질 행복도(−60)로 판정
    p1 = r.pop
    g._phase_population()
    assert r.pop == pytest.approx(p1 * (1 + C.POP_FOCUS_GROWTH * g.growth_scale(r.id) + R.pop_growth_rate(g.growth_happy(r), g.density_growth(r.id)))
                                  * (1 + C.MIGRATION_POP))
    g.set_focus(0, "S002", True)
    assert r.focus and not r.pop_focus             # 집중은 하나만


def test_crowd_penalty_tiers():
    g = new_game(player_start="S002", n_enemies=1)
    small = next(rid for rid in g.world.order if g.info(rid).pop0 <= 10)
    big = next(rid for rid in g.world.order if g.info(rid).pop0 > 60)
    _own(g, 0, [small, big])
    rs, rb = g.regions[small], g.regions[big]
    for rr in (rs, rb):
        capacity = g.population_capacity(rr.id)
        rr.pop = capacity * .99
        assert g.crowd_penalty(rr) == 0
        rr.pop = capacity
        assert g.crowd_penalty(rr) == -2
        # -4는 전체 사용 면적이 총면적의 110%인 경계다.
        _, _, built = g.area_usage(rr.id)
        rr.pop = (g.info(rr.id).area_km2 * 1.11 - built) / C.POP_AREA_PER_10K[rr.b['housing']]
        assert g.crowd_penalty(rr) == -4
        h = g.eff_happy(rr)
        rr.pop = capacity * .9
        assert g.eff_happy(rr) == pytest.approx(h + 4)


def test_energy_coal_fields_and_plants_start():
    g = new_game(player_start="S002", n_enemies=1)
    n = g.world.name_to_id
    assert g.regions[n["강원 태백시"]].b["extract"] == 1          # ① 탄광 가동: 1단계
    paju = n["경기 파주시"]
    assert g.regions[paju].b["extract"] == 0 and g.world.regions[paju].is_coal   # ② 석탄층: 0단계, 건설 가능
    assert not g.world.regions["S002"].is_coal
    assert g.regions[n["충남 당진시"]].b["power"] == 1           # 현실 발전소 1단계
    assert g.regions["S002"].b["power"] == 0
    _own(g, 0, [paju])
    opt = next(o for o in g.options(0, paju) if o["key"] == "extract")
    assert opt["ok"]
    assert not any(o["key"] == "extract" for o in g.options(0, "S002"))   # 유전·탄전이 없으면 아예 안 나옴
    assert not any(o["key"] == "liquefy" for o in g.options(0, "S002"))


def _energy_setup():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    r.b["factory"], r.b["power"] = 3, 2
    f = g.player
    f.res.update(coal=0, oil=0, elec=0)
    return g, r, f


def test_energy_plan_auto_and_flow():
    g, r, f = _energy_setup()
    assert R.factory_output(5) == 10000 and R.factory_output(3, 2) == 2800
    f.auto_energy = True                                       # AI 방식: 매 턴 자동
    f.res.update(coal=3, oil=1)                                # 이번 턴 확보량(쌓이지 않는다)
    plan = g.energy_plan(0)
    # 발전소(2단계)에 석유 먼저, 그다음 석탄: 석탄 2.2 + 석유 4.4 = 6.6 → 전국 합계의 정수 부분 6
    assert plan["plants"]["S002"] == {"coal": 1, "oil": 1, "elec_out": pytest.approx(6.6)}
    assert plan["elec_gen_int"] == 6
    fu = plan["factories"]["S002"]
    assert fu["units"] == 3 and fu["elec"] == 3                # 공장은 전기부터
    assert plan["after"] == pytest.approx({"oil": 0, "coal": 2, "elec": 3})
    sell0 = f.trade_sell
    g._phase_resources(f)
    assert all(f.res[k] == 0 for k in C.ENERGY)                 # 남는 것은 쌓이지 않고
    assert f.last["energy"]["sold"] == {"coal": 2, "elec": 3}   # 턴 종료 때 시장 판매가로 팔린다
    assert f.trade_sell - sell0 == pytest.approx(2 * g.sell_price(0, "coal") + 3 * g.sell_price(0, "elec"))
    assert r.fuel_used == 3
    assert r.output == pytest.approx(g.calc_output("S002", full=True))


def test_assign_energy_command_priority():
    g, r, f = _energy_setup()
    assert not f.auto_energy                                   # 플레이어는 명령 버튼으로 배정
    other = sorted(g.world.land_adj["S002"])[0]
    _own(g, 0, [other])
    g.regions[other].resist = None
    r.b["factory"], r.b["power"] = 3, 1
    g.regions[other].b["factory"], g.regions[other].b["power"] = 5, 0
    f.res.update(coal=50, oil=50, elec=0)                      # 석탄·석유 재고는 배정에 쓰지 않는다
    g.energy_mined = lambda fid: {"coal": 3, "oil": 1, "elec": 0}   # 턴당 생산량 기준
    units, cap = g.assign_energy(0)
    # ① 발전소에 석유 1 → 전기 4 ③ 전기는 단계 높은 공장(5단계)부터 ④ 석탄 ⑤ 석유(남은 것 없음)
    assert r.energy["p"] == {"coal": 0, "oil": 1}
    assert g.regions[other].energy["f"] == {"coal": 1, "oil": 0, "elec": 4}
    assert r.energy["f"] == {"coal": 2, "oil": 0, "elec": 0}
    assert (units, cap) == (7, 8) and not f.auto_energy
    f.res.update(coal=0, oil=0, elec=0)                        # 배정은 다음에 누를 때까지 그대로(재고만큼만 쓰임)
    assert g.regions[other].energy["f"]["elec"] == 4


def test_energy_manual_assignment():
    g, r, f = _energy_setup()
    f.res.update(coal=5, oil=0, elec=0)
    g.set_auto_energy(0, False)
    g.set_energy(0, "S002", "p", "coal", 2)                    # 발전소: 석탄 2 → 전기 4
    g.set_energy(0, "S002", "f", "elec", 3)
    g.set_energy(0, "S002", "f", "coal", 3)                    # 합계는 단계(3)까지
    assert r.energy["f"]["coal"] == 0
    plan = g.energy_plan(0)
    assert plan["plants"]["S002"] == {"coal": 2, "oil": 0, "elec_out": pytest.approx(4.4)}   # 2단계: 석탄 1 → 2.2
    assert plan["factories"]["S002"]["elec"] == 3 and plan["after"]["elec"] == 1
    assert plan["after"]["coal"] == 3


def test_units_pay_oil_with_coal():
    g, r, f = _energy_setup()
    f.res.update(oil=1, coal=2)
    assert g.can_pay_oil(0, 2)
    g.pay_oil(0, 2)                                            # 석유 1 + 석탄 2(= 석유 1)
    assert f.res["oil"] == 0 and f.res["coal"] == 0
    assert not g.can_pay_oil(0, 1)


def test_impossible_facilities_hidden():
    """지을 수 없는 어장·특산물·지하자원·항구는 선택지에 아예 나오지 않는다."""
    from korciv.game import Game
    from korciv.state import Settings
    g = Game(Settings(seed=3, n_enemies=1))
    pid = g.player_id
    for rid in list(g.regions)[:200]:
        info = g.info(rid)
        keys = {o["key"] for o in g.options(pid, rid) if o["kind"] == "build"}
        assert ("fishery" in keys) == (g.can_fish(rid) and g.regions[rid].b["fishery"] < 5) or g.regions[rid].b["fishery"] >= 5
        if not info.specialty:
            assert "specialty" not in keys
        if not (info.is_oil or info.is_coal):
            assert "extract" not in keys
        if not info.coastal:
            assert "port" not in keys
            assert not any(o["kind"] == "unit" and C.UNITS[o["key"]]["kind"] == "naval" for o in g.options(pid, rid))


def test_defensive_war_weariness_not_in_rebellion():
    g = new_game(player_start="S002", n_enemies=2)
    near = sorted(g.world.land_adj["S002"])[0]
    _own(g, 0, [near])
    r = g.regions[near]
    r.happy = -30
    D.declare_war(g, 1, 0)                          # 선포당함
    for _ in range(5):
        D.add_war_weary(g, 0, D.war_weary_rate(g, 0), defensive=D.war_weary_defensive(g, 0))
    f = g.player
    assert f.war_weary > 0 and f.war_weary_def == pytest.approx(f.war_weary)
    assert g.rebel_happy(r) == pytest.approx(g.eff_happy(r) + f.war_weary)
    assert g.eff_happy(r) < g.rebel_happy(r)
    D.declare_war(g, 0, 2)                          # 내가 선포한 전쟁: 그 피로는 반란 판정에도 들어간다
    w0, d0 = f.war_weary, f.war_weary_def
    D.add_war_weary(g, 0, 5, defensive=D.war_weary_defensive(g, 0))
    assert f.war_weary_def == pytest.approx(d0) and f.war_weary == pytest.approx(w0 + 5)
    D.add_war_weary(g, 0, -f.war_weary / 2)         # 회복은 같은 비율로
    assert f.war_weary_def == pytest.approx(d0 / 2)


def test_start_capital_lines_but_not_rebels():
    g = new_game(player_start="S002", n_enemies=2)
    for f in g.factions:
        r = g.regions[f.capital]
        assert all(r.lines.get(n) == 1 for n in g.world.land_adj[f.capital])
        if g.world.regions[f.capital].coastal:
            assert r.lines.get("coast") == 1
    near = sorted(g.world.land_adj["S002"])[0]
    _own(g, 0, [near])
    g.regions[near].lines.clear()
    nf, _ = g._spawn_rebel(0, near, 10)
    assert not any(g.regions[near].lines.values())


def test_econ_conquest_diplomatic_victory():
    # 정복: 2/3 이상 + 반란 가능 지역 없음
    g = new_game(player_start="S002", n_enemies=1)
    need = math.ceil(len(g.regions) * 2 / 3)
    free = [r for r in g.world.order if g.regions[r].owner == NEUTRAL][:need]
    _own(g, 0, free)
    for r in g.regions_of(0):
        r.happy, r.resist = 0.0, None
    st = g.conquest_status(0)
    assert st["have"] >= need and st["risky"] == 0 and st["ok"]
    g.regions[free[0]].happy = -90
    assert not g.conquest_status(0)["ok"] and g.conquest_status(0)["risky"] == 1
    g.regions[free[0]].happy = 0.0
    g._check_victory()
    assert g.winner == ((0,), "conquest")
    # 외교: 살아 있는 모든 나라가 한 연합
    g = new_game(player_start="S002", n_enemies=2)
    g.dip.coalitions[1] = {"members": {0, 1, 2}, "since": g.turn}
    g._check_victory()
    assert g.game_over and set(g.winner[0]) == {0, 1, 2} and g.winner[1] == "diplomatic"


def test_dangun_one_buff_one_debuff():
    from korciv.leaders import LEADER_BY_KEY
    fx = LEADER_BY_KEY["dan"]["fx"]
    assert fx == {"happy_turn": 0.10, "cost_noninf": 0.20}
    g = new_game(player_start="S002", n_enemies=1, player_leader="dan")
    g.player.war_weary = 10.0
    g._phase_happiness()
    assert g.player.war_weary == pytest.approx(9.0)          # 회복은 기본 1/턴


def test_unit_table_v14():
    s = C.UNIT_STAT_SCALE
    spec = {"inf": (250, 1, 0, 1, 1), "art": (500, 2, 0, 1.5, 1), "tank": (750, 3, 1, 2, 5),
            "lst": (500, 2, 1, 0, 2), "dd": (1000, 3, 1, 2, 5), "cv": (1500, 4, 2, 0, 10),
            "ftr": (750, 3, 1, 3, 3), "bmb": (1000, 3, 1, 4, 2)}
    for k, (cost, turns, oil, atk, hp) in spec.items():
        u = C.UNITS[k]
        power = max(u["atk"], u["bomb"], u.get("intercept", 0))
        assert (u["cost"], u["turns"], u["oil"], power / s, u["hp"] / s) == (cost, turns, oil, atk, hp), k
    assert "stl" not in C.UNITS
    assert C.UNITS["ftr"]["atk"] == 0                     # 전투기는 공격 불가(방어·요격만)
    from korciv.state import Army
    lst = Army(1, 0, "x", {"lst": 1, "inf": 2, "art": 1, "tank": 1}, {})
    assert lst.cargo_used() == 8 and lst.cargo_cap() == 8
    cv = Army(2, 0, "x", {"cv": 1, "ftr": 2, "bmb": 2}, {})
    assert cv.air_used() == 4 and cv.air_cap() == 6        # 항모 1척에 함재기 6대(v1.3.0)


def test_assault_damage_order_and_random_bombard():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    for x in g.armies_at(tgt):
        g.remove_army(x)
    d = g.new_army(1, tgt, {"tank": 2, "inf": 3, "art": 1})
    lost = g.apply_damage([d], 60, order=C.ASSAULT_DAMAGE_ORDER)
    assert lost == {"tank": 1} and d.units["inf"] == 3 and d.dmg["tank"] == pytest.approx(10)
    lost = g.apply_damage([d], 60, order=C.ASSAULT_DAMAGE_ORDER)
    assert lost == {"tank": 1, "inf": 2}
    # 폭격: 무작위 분배(총 피해는 보존)
    e = g.new_army(1, tgt, {"inf": 10, "tank": 2})
    hp0 = sum(e.hp_left(k) for k in e.units)
    g.apply_damage([e], 37, spread="random")
    assert sum(e.hp_left(k) for k in e.units) == pytest.approx(hp0 - 37)


def test_bombard_ranges_and_interception():
    g = new_game(player_start="S002", n_enemies=1)
    two = next(v for v in g.land_within("S002", 2) if v not in g.world.land_adj["S002"])
    _own(g, 1, [two])
    D.declare_war(g, 0, 1)
    art = g.new_army(0, "S002", {"art": 2})
    assert g._can_bombard(art, two)                       # 포병은 2칸까지
    # 요격: 대공포 3단계 + 전투기 1대 → 폭격기 피해 0.5 × r × (30 + 30)
    g.regions[two].b["aa"] = 3
    g.new_army(1, two, {"ftr": 1})
    ad, aa, ftr = g.air_defense(0, two)
    assert (ad, aa, ftr) == (30, 3, 0)                    # v1.3.0: 공항이 없는 곳의 전투기는 요격하지 않는다
    g.regions[two].b["airport"] = 1
    ad, aa, ftr = g.air_defense(0, two)
    assert (ad, aa, ftr) == (60, 3, 1)
    g.regions["S002"].b["airport"] = 1
    b = g.new_army(0, "S002", {"bmb": 5})
    assert g._can_bombard(b, two)
    g._bombard(b, two, g._bombard_units(b, two))
    lost_hp = 5 * C.UNITS["bmb"]["hp"] - b.hp_left("bmb") if b.id in g.armies else 5 * C.UNITS["bmb"]["hp"]
    assert 0.5 * 0.85 * 60 - 1e-6 <= lost_hp <= 0.5 * 1.15 * 60 + 1e-6


def test_econ_share_counts_neutral_and_rebel_weary_mult():
    g = new_game(player_start="S002", n_enemies=1)
    assert g.world_gdp() == pytest.approx(sum(g.gdp(f) for f in g.alive_ids()) + g.neutral_gdp())
    assert g.neutral_gdp() > 10 * g.gdp(0)                # 초반엔 중립 땅이 대부분
    near = sorted(g.world.land_adj["S002"])[0]
    _own(g, 0, [near])
    r = g.regions[near]
    r.happy, r.resist = -10.0, None
    g.player.war_weary, g.player.war_weary_def = 20.0, 5.0
    assert g.rebel_happy(r) == pytest.approx(g.eff_happy(r) + 20 - 15 * 1.2)
    assert C.SCIENCE_COST_PER_TURN == 80_000


def test_display_names_and_flag_number_input():
    from korciv.data import display_short, load_world
    from korciv.ui.modals import parse_byte
    assert display_short("영등포구") == "영등포" and display_short("중구") == "중구"
    assert display_short("선봉구역") == "선봉" and display_short("중구역") == "중구역"
    assert display_short("세종시") == "세종" and display_short("울릉군") == "울릉"
    w = load_world()
    assert w.regions[w.name_to_id["서울 영등포구"]].name == "서울 영등포"
    assert w.name_to_id["서울 영등포"] == w.name_to_id["서울 영등포구"]
    assert w.regions[w.name_to_id["부산 중구"]].name == "부산 중구"
    assert [parse_byte(x) for x in ("0", "128", "255", "256", "999", "", "-3", "1a", " 7 ")] == \
        [0, 128, 255, 255, 255, 0, 0, 0, 7]


def test_science_progress_text():
    from korciv.ui.panels import science_progress_text
    g = new_game(player_start="S002", n_enemies=1)
    assert science_progress_text(g, 0) == "0/8 · 항공우주연구소 건설(수도)"
    g.player.science = ["lab", "observatory"]
    assert science_progress_text(g, 0) == "2/8 · 예산 편성 진행(시장 5단계 지역)"
    g.player.science = ["lab", "observatory", "budget", "pad"]
    assert science_progress_text(g, 0) == "4/8 · 로켓 추진체 생산(공장 5단계 지역)"
    g.player.science = list(C.SCIENCE_STEPS)
    for k in C.SCIENCE_UNITS:
        g.add_units(0, "S002", k, 1)
    assert science_progress_text(g, 0) == "7/8 · 발사대에 부품 3종(추진체·탑승 모듈·연료) 집결"



def test_starts_six_apart_market_upkeep_power_sites():
    for seed in range(15):
        g = Game(Settings(seed=seed, n_enemies=9, all_ai=True))
        caps = [f.capital for f in g.factions]
        assert all(g._land_dist(a, b, 6) >= 6 for i, a in enumerate(caps) for b in caps[i + 1:])
    g = new_game(player_start="S002", n_enemies=1)
    assert (C.MARKET_BUY["elec"], C.MARKET_SELL["elec"], C.MARKET_SELL["food"]) == (20, 10, 2)
    g.player.money = 1000
    assert g.max_buyable(0, "oil") == 0 and g.max_buyable(0, "coal") == 0
    k, _ = g.market_buy(0, "elec", 2)
    assert k == 2
    for k, u in C.UNITS.items():
        if not u.get("science"):
            assert u["upkeep"] / (u["cost"] * u["turns"]) == pytest.approx(5 / 250)
    w = g.world
    site = next(r for r in w.order if w.regions[r].power_site)
    assert g.regions[site].b["power"] == 1 and w.regions[site].power_source.startswith("화력(")
    assert R.prod_building_cost("power", 2, True) == R.prod_building_cost("power", 2, False)


def test_new_dams_and_power_text():
    from korciv.data import load_world
    from korciv.ui.panels import power_text
    w = load_world()
    n = w.name_to_id
    assert power_text(w.regions[n["충북 충주"]]) == "수력(충주댐) 1/턴"
    assert power_text(w.regions[n["부산 기장"]]) == "원자력(고리) 2/턴"
    assert power_text(w.regions[n["강원 춘천"]]) == "수력(소양강댐) 1/턴"
    for info in w.regions.values():                 # 수력 1, 원자력 2
        if info.power_source.startswith("수력"):
            assert info.power_self == 1
        elif info.power_source.startswith("원자력"):
            assert info.power_self == 2
    for nm, dam in (("경기 가평", "청평댐"), ("경기 남양주", "팔당댐"), ("경북 안동", "안동댐"), ("경남 합천", "합천댐"),
                    ("전북 임실", "섬진강댐"), ("대전 대덕", "대청댐")):
        assert dam in w.regions[n[nm]].power_source


def test_allies_share_met():
    g = new_game(player_start="S002", n_enemies=3, fog=2)
    g.player.met = {1}
    g.factions[1].met = {0, 3}
    g.dip.alliance[D.pair(0, 1)] = g.turn
    g._update_fog()
    assert 3 in g.player.met


def test_claim_pop_is_sum_of_touching_regions():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    near = [n for n in sorted(g.world.land_adj[tgt]) if n != "S002"][:1]
    _own(g, 0, near)
    mine = [n for n in g.world.land_adj[tgt] if g.regions[n].owner == 0]
    assert len(mine) >= 2
    assert g.claim_pop(0, tgt) == pytest.approx(sum(g.regions[n].pop for n in mine))


def test_joint_annex_left_turns_shared():
    g = new_game(player_start="S002", n_enemies=1)
    src2 = tgt = None
    for t in sorted(g.world.land_adj["S002"]):
        nb = [n for n in sorted(g.world.land_adj[t]) if n in g.world.land_adj["S002"] and g.regions[n].owner == NEUTRAL]
        if g.regions[t].owner == NEUTRAL and nb:
            src2, tgt = t, nb[0]
            break
    _own(g, 0, [src2])
    g.regions[src2].resist = None
    for a in g.armies_at(src2):
        g.remove_army(a)
    g.player.money = 1e9
    assert g.start_project(0, "S002", "annex", tgt)[0]
    g.end_turn()
    assert g.start_project(0, src2, "annex", tgt)[0]          # 나중에 합류해도
    assert g.project_left(src2) == g.project_left("S002")      # 공유 진행도·공동 감소율로 같은 남은 턴


def test_board_land_on_lst_and_air_on_cv():
    g = new_game(player_start="S002", n_enemies=1)
    n = g.world.name_to_id
    port = n["부산 중구"]
    _own(g, 0, [port])
    g.regions[port].b["port"] = 1
    inf = g.new_army(0, port, {"inf": 2, "tank": 1})
    assert g.boarding_target(inf.id) is None                     # 상륙함이 없으면 탑승 불가
    fleet = g.new_army(0, port, {"lst": 1})
    assert g.boarding_target(inf.id) is fleet
    ok, msg, f = g.board(inf.id)
    assert ok and f.units == {"lst": 1, "inf": 2, "tank": 1} and inf.id not in g.armies
    big = g.new_army(0, port, {"tank": 2})                        # 수송 칸(8) 초과
    ok, msg, _ = g.board(big.id)
    assert not ok and "칸" in msg
    cv = g.new_army(0, port, {"cv": 1})
    air = g.new_army(0, port, {"ftr": 2, "bmb": 1})
    assert g.boarding_target(air.id) is cv
    assert g.board(air.id)[0] and cv.units == {"cv": 1, "ftr": 2, "bmb": 1}


def test_production_level_names():
    g = new_game(player_start="S002", n_enemies=1)
    assert g.build_label("S002", "factory", 5) == "공업 단지 건설"
    assert g.build_label("S002", "farm", 3) == "농장 건설"
    assert g.build_label("S002", "fishery", 1) == "낚시터 건설"
    assert g.build_label("S002", "bank", 4) == "상업 업무 지구 건설"
    assert g.build_label("S002", "power", 2) == "발전소 2단계"


def test_government_v190():
    from korciv.leaders import GOV_BY_KEY
    assert GOV_BY_KEY["fascist"]["fx"]["start_opinion"] == -5
    assert GOV_BY_KEY["socialist"]["fx"]["output_bank"] == -0.20
    assert GOV_BY_KEY["presidential"]["fx"]["war_weary_rate"] == 0.20
    g = new_game(player_start="S002", n_enemies=1)
    g.set_player_government("absolute")
    # 기준 세율 12%: 12%에서 행복도 변화 없음, 10%면 +0.2
    assert g.tax_base(0) == 12
    assert g.tax_happy(0, 12) == pytest.approx(0.0)
    assert g.tax_happy(0, 10) == pytest.approx(0.2)
    assert g.tax_happy(0, 22) == pytest.approx(-1.0)
    # 수도에서 3칸 밖 지역 산출 −5%
    near3 = g.near_capital(0, 3)
    far = next(r for r in g.world.order if r not in near3 and g.world.land_adj[r])
    mid = next(r for r in near3 - g.near_capital(0, 2))
    _own(g, 0, [far, mid])
    y_far, y_mid = g.calc_output(far), g.calc_output(mid)
    g.set_player_government("philosopher")
    g._mods.pop(0, None)
    assert y_far == pytest.approx(g.calc_output(far) * 0.95)
    assert y_mid == pytest.approx(g.calc_output(mid))


def test_half_year_ranking_schedule():
    g = new_game(player_start="S002", n_enemies=2)
    for x in (1, 2):                                   # 가만히 있는 플레이어가 멸망하지 않게(게임 종료 방지)
        g.dip.nonaggr[D.pair(0, x)] = 10 ** 6
    # AI 하나가 97턴 전에 정복승리로 판을 끝내는 경우가 있다(해시 순서에 따라 가끔): 발표 일정만 보므로 끈다
    g.settings.victories = [v for v in g.settings.victories if v != "conquest"]
    seen = []
    while g.turn <= 2 * C.TURNS_PER_YEAR + 1:
        assert not g.game_over
        g.end_turn()
        if g.new_ranking:
            seen.append(g.new_ranking)
    # 첫해는 발표 없음, 2년 차 1주차(49턴)·25주차(73턴), 3년 차 1주차(97턴)
    assert seen == [49, 73, 97]
    assert g.ranking_label(49) == f"{C.START_YEAR}년 하반기"
    assert g.ranking_label(73) == f"{C.START_YEAR + 1}년 상반기"
    row = g.rankings[49][0]
    assert set(row) >= {"fid", "regions", "pop", "happy", "gdp", "gdp_share", "science"}
    assert 0 < row["gdp_share"] < 1


def test_gift_opinion_follows_income():
    g = _meet_all(new_game(n_enemies=2))
    inc = D.gift_income(g, 1)
    assert inc >= g.gdp(1) * C.TAX_DEFAULT * g.factions[1].income_mult - 1e-6
    f = g.factions[1]
    f.aggression, f.gov = 5.0, "philosopher"            # 5 + 5 = 10 → 세수 1턴분당 +3
    assert D.gift_rate(g, 1) == pytest.approx(3.0)
    f.last["net"] = -500                               # 적자여도 푼돈 선물로 우호도가 크게 오르지 않는다
    assert D.gift_opinion(g, 1, 5) < 1                  # 예전 버그: +25
    assert D.gift_opinion(g, 1, inc * 2) == pytest.approx(6.0)
    assert D.gift_opinion(g, 1, inc * 100) == C.OP_GIFT_MAX
    # 호전성 10 기준, 1 높을 때마다 −0.05: 5.5 + 전제군주제 7.5 = 13 → 2.85 (소수 둘째 자리 아래 절사)
    f.aggression, f.gov = 5.5, "absolute"
    assert D.gift_rate(g, 1) == pytest.approx(2.85)
    assert D.gift_opinion(g, 1, inc) == 2.85
    assert D.gift_opinion(g, 1, inc / 3) == 0.95                # 0.95 (0.9499.. 이 아니라)
    f.aggression, f.gov = 1.0, "parliamentary"          # 1 + 1.5 = 2.5 → 3.375 → 3.37
    assert D.gift_opinion(g, 1, inc) == 3.37
    f.last["tax"] = 0                                  # 세율 0%여도 GDP × 10% 기준
    assert D.gift_income(g, 1) == pytest.approx(max(1.0, g.gdp(1) * C.TAX_DEFAULT * f.income_mult))
    # 식량 선물은 주는 쪽의 시장 판매가로 환산(턴당 100개 × 12턴)
    offer = D.empty_offer()
    offer["give"]["food"] = 100
    assert D.gift_value(g, offer["give"], 0) == pytest.approx(100 * g.sell_price(0, "food") * C.CONTRACT_TURNS)
    f.aggression, f.gov = 5.0, "philosopher"
    op0 = D.opinion(g, 1, 0)
    offer = D.empty_offer()
    offer["give"]["money"] = D.gift_income(g, 1)
    D.respond_offer(g, 1, 0, offer)
    assert D.opinion(g, 1, 0) == pytest.approx(op0 + 3, abs=0.01)


def test_alliance_needs_only_opinion():
    g = new_game(n_enemies=2)
    _neutral_ai(g, 1, 2)
    p = D.pair(0, 1)
    g.dip.op[(1, 0)] = C.ALLIANCE_MIN + 1
    # 우호 → 불가침·통행권 → 동맹 → 연합: 앞 단계가 없으면 건너뛸 수 없다
    ok, why = D.treaty_check(g, 1, 0, "nonaggr")
    assert not ok and "우호 선언" in why
    ok, _ = D.declare_friendship(g, 0, 1)
    assert ok and D.declared_friends(g, 0, 1)
    ok, why = D.treaty_check(g, 1, 0, "alliance")
    assert not ok and "조약" in why
    ok, why = D.treaty_check(g, 1, 0, "nonaggr")
    assert ok, why
    D.sign_treaty(g, 0, 1, "nonaggr")
    g.hegemon = None
    assert not D.enemies(g, 0)                              # 공동의 적·견제 대상 없음
    ok, why = D.treaty_check(g, 1, 0, "alliance")
    assert ok, why
    D.sign_treaty(g, 0, 1, "alliance")
    g.turn += C.COALITION_ALLIANCE_TURNS
    g.dip.op[(1, 0)] = C.COALITION_MIN
    ok, why = D.treaty_check(g, 1, 0, "coalition")
    assert ok, why


def _finance_setup(g, fid=0, n=C.ECON_CLUSTER):
    """수도에서 맞닿아 뻗는 n곳(수도 포함)을 내 땅으로 만들고 은행 5단계로."""
    cap = g.factions[fid].capital
    plan, frontier = [cap], [cap]
    while len(plan) < n:
        u = frontier.pop(0)
        for v in sorted(g.world.land_adj[u]):
            if v not in plan and len(plan) < n:
                plan.append(v)
                frontier.append(v)
    _own(g, fid, [r for r in plan if g.regions[r].owner != fid])
    for r in plan:
        g.regions[r].b["bank"] = 5
        g.regions[r].resist = None
    return plan


def _finish(g, fid, rid, kind, key):
    ok, msg = g.start_project(fid, rid, kind, key)
    assert ok, msg
    p = g.regions[rid].project
    g.regions[rid].project = None
    g._complete_project(g.factions[fid], g.regions[rid], p)


def test_econ_victory_chain():
    g = new_game(player_start="S002", n_enemies=3)
    _neutral_ai(g, 1, 2, 3)
    cap = g.player.capital
    assert g.econ_stage(0) == 0 and not g.econ_available(0)
    plan = _finance_setup(g, 0, C.ECON_CLUSTER - 1)
    assert len(g.finance_cluster(0)) == C.ECON_CLUSTER - 1 and not g.econ_available(0)
    plan = _finance_setup(g)
    assert g.finance_cluster(0) == set(plan) and g.econ_stage(0) == 1
    # 맞닿지 않은 금융 단지는 권역이 아니다
    far = next(r for r in g.world.order if r not in plan and not set(g.world.land_adj[r]) & set(plan)
               and g.regions[r].owner == NEUTRAL and g.world.land_adj[r])
    _own(g, 0, [far])
    g.regions[far].b["bank"] = 5
    assert far not in g.finance_cluster(0) and not g.econ_site_ok(0, far, "exchange")
    # ② 증권거래소: 금융 권역에서, 수도 포함 3곳이면 경제특구
    opts = [o for o in g.options(0, cap) if o["kind"] == "econ"]
    assert [o["key"] for o in opts] == ["exchange"] and opts[0]["per_turn"] == pytest.approx(C.ECON["exchange"]["per_turn"])
    g.player.money = 1e9
    for rid in plan[:2]:
        _finish(g, 0, rid, "econ", "exchange")
    assert g.econ_stage(0) == 1 and "sez" not in g.econ_available(0)
    _finish(g, 0, plan[2], "econ", "exchange")
    assert g.econ_stage(0) == 2 and "sez" in g.econ_available(0)
    # 증권거래소: 그 지역 은행 산출 +10%
    rr = g.regions[plan[0]]
    with_ex = g.calc_output(plan[0], full=True)
    rr.econ.discard("exchange")
    without = g.calc_output(plan[0], full=True)
    rr.econ.add("exchange")
    assert with_ex > without
    # ③ 경제특구(수도)
    assert not g.econ_site_ok(0, plan[1], "sez") and g.econ_site_ok(0, cap, "sez")
    _finish(g, 0, cap, "econ", "sez")
    assert g.econ_stage(0) == 3
    # ④ 국제금융센터: 우호 선언 이상 2개국 + 증권거래소 지역
    assert not g.econ_ready(0, "ifc")[0]
    for x in (1, 2):
        g.dip.op[(x, 0)] = 0
        assert D.declare_friendship(g, 0, x)[0]
    assert g.econ_ready(0, "ifc")[0] and not g.econ_site_ok(0, far, "ifc") and g.econ_site_ok(0, plan[1], "ifc")
    _finish(g, 0, plan[1], "econ", "ifc")
    assert g.econ_stage(0) == 4
    assert D.gift_opinion(g, 1, D.gift_income(g, 1) * 2, 0) > D.gift_opinion(g, 1, D.gift_income(g, 1) * 2)
    # ⑤ 기축통화: 우호 선언 이상 3개국, 그중 동맹 1곳 이상
    g.dip.op[(3, 0)] = 0
    assert D.declare_friendship(g, 0, 3)[0]
    ok, why = g.econ_ready(0, "currency")
    assert not ok and "동맹 0/1" in why
    g.dip.nonaggr[D.pair(0, 1)] = g.turn + 24
    g.dip.alliance[D.pair(0, 1)] = g.turn
    assert g.econ_ready(0, "currency")[0]
    _finish(g, 0, cap, "econ", "currency")
    assert g.game_over and g.winner == ((0,), "economic")


def test_econ_pause_refund_restart_and_capture():
    g = new_game(player_start="S002", n_enemies=1)
    plan = _finance_setup(g)
    cap = g.player.capital
    for rid in plan[:3]:
        g.regions[rid].econ.add("exchange")
    g.player.money = 1e9
    ok, _ = g.start_project(0, cap, "econ", "sez")
    assert ok
    p = g.regions[cap].project
    p.progress, p.paid = 5, 5 * p.per_turn
    money = g.player.money
    g.regions[plan[1]].econ.discard("exchange")          # 조건이 깨짐 → 중단·50% 환급, 진행도는 사라짐
    g._check_econ_projects(g.player)
    assert g.regions[cap].project is None
    assert g.player.money == pytest.approx(money + 0.5 * 5 * p.per_turn)
    assert not [o for o in g.options(0, cap) if o["kind"] == "econ" and o["key"] == "sez"]
    g.regions[plan[1]].econ.add("exchange")              # 조건이 돌아오면 처음부터
    opt = next(o for o in g.options(0, cap) if o["kind"] == "econ" and o["key"] == "sez")
    assert opt["turns"] == C.ECON["sez"]["turns"]
    assert g.start_project(0, cap, "econ", "sez")[0] and g.regions[cap].project.progress == 0
    # 완공한 건물은 조건이 깨져도 남지만, 점령당하면 사라진다
    g.regions[plan[2]].b["bank"] = 0
    assert "exchange" in g.regions[plan[2]].econ
    g.transfer_region(plan[2], 1)
    assert not g.regions[plan[2]].econ


def test_econ_alerts_only_for_others_and_threat():
    g = new_game(player_start="S002", n_enemies=2, fog=2)
    _neutral_ai(g, 1, 2)
    g.econ_alert(0, "내 알림")
    assert not [e for e in g.events if e["kind"] == "alert"]
    g.econ_alert(1, f"{g.factions[1].name}이(가) 기축통화 지정을 시작했습니다.")
    e = [e for e in g.events if e["kind"] == "alert"][-1]
    txt = g.event_for_player(e)
    assert txt and (g.UNKNOWN_NAME in txt) != g.has_met(0, 1)
    # 승리에 가까운 나라 견제: 과학 7단계 완료 → 견제 1, 관계없는 AI의 우호도가 깎이고 전쟁 문턱이 쉬워진다
    from korciv import ai as AI
    thr0 = AI.war_op_threshold(g, g.factions[1], 0)
    g.player.science = list(C.SCIENCE_STEPS)
    g._vthreat = {}
    assert g.victory_threat(0) == pytest.approx(1.0)
    assert AI.war_op_threshold(g, g.factions[1], 0) == pytest.approx(thr0 + C.VICTORY_THREAT_WAR)
    g.dip.op[(1, 0)] = g.dip.op[(2, 0)] = 0.0
    D.declare_friendship(g, 0, 2)
    D.update_turn(g)
    assert D.opinion(g, 1, 0) < D.opinion(g, 2, 0)


def test_declared_friendship_persists_until_broken():
    g = new_game(player_start="S002", n_enemies=2)
    _neutral_ai(g, 1, 2)
    g.dip.op[(1, 0)] = g.dip.op[(2, 0)] = 0.0
    assert D.declare_friendship(g, 0, 1)[0] and D.declare_friendship(g, 0, 2)[0]
    g.turn += C.DECL_FRIEND_TURNS + 5
    D.update_turn(g)
    assert D.declared_friends(g, 0, 1) and D.econ_partners(g, 0) == (2, 0)
    g.turn += C.DECL_COOLDOWN
    D.denounce(g, 0, 1)
    assert not D.declared_friends(g, 0, 1)
    D.declare_war(g, 2, 0)
    assert not D.declared_friends(g, 0, 2)


def test_ai_econ_goal_saves_for_next_step():
    from korciv import ai as AI
    g = new_game(player_start="S002", n_enemies=1)
    plan = _finance_setup(g)
    assert AI.econ_saving_target(g, 0) == 0.0                       # 1단계: 증권거래소는 바로 짓는다
    for rid in plan[:3]:
        g.regions[rid].econ.add("exchange")
    spec = C.ECON["sez"]
    assert AI.econ_saving_target(g, 0) == pytest.approx(spec["per_turn"] * spec["turns"] * 1.1)
    g.regions[g.player.capital].econ.add("sez")
    assert AI.econ_saving_target(g, 0) == pytest.approx(C.ECON["ifc"]["per_turn"] * C.ECON["ifc"]["turns"] * 1.1)


def test_new_leaders_v117():
    from korciv.leaders import LEADER_BY_KEY, LEADER_CATEGORIES
    cats = {cid: ks for cid, _, ks in LEADER_CATEGORIES}
    assert "sun" in cats["footprints"] and {"kgc", "kwb"} <= set(cats["uncrowned"])
    assert {"yyl", "mac", "sta", "mao"} <= set(cats["invaders"])
    assert [LEADER_BY_KEY[k]["aggr"] for k in ("sun", "kgc", "kwb", "yyl", "mac", "sta", "mao")] == [6, 4, 7, 8, 9, 7, 8]
    # 모든 수도 산출 +10%, 발해 선왕은 +5%
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    cap = g.player.capital
    y = g.calc_output(cap, full=True)
    g.player.capital = next(r for r in g.world.land_adj[cap])
    assert y == pytest.approx(g.calc_output(cap, full=True) * 1.10)
    g.player.capital = cap
    _lead(g, 0, "sun")
    assert g.calc_output(cap, full=True) == pytest.approx(y / 1.10 * 1.05)
    # 해동성국: 20곳을 넘을 때마다 전 지역 산출 +2% (최대 +10%)
    assert g.haedong_steps(0) == 0
    free = [r for r in g.world.order if g.regions[r].owner == NEUTRAL][:40]
    _own(g, 0, free)
    assert g.haedong_steps(0) == 2.0                      # 41곳
    assert g.calc_output(cap, full=True) == pytest.approx(y / 1.10 * 1.05 * 1.04)
    # 스탈린 농장 +15%, 마오쩌둥 식량 −15%
    r = g.regions[cap]
    r.b["farm"] = 3
    _lead(g, 0, "cus")
    f0 = g.food_prod(0, r)
    _lead(g, 0, "sta")
    river = C.RIVER_FARM_MULT if g.river_farm(cap) else 1.0
    assert g.food_prod(0, r) == pytest.approx(R.food_output(3 * 1.15 * river, r.b["fishery"], g.fish_food_mult(0, cap)))
    _lead(g, 0, "mao")
    assert g.food_prod(0, r) == pytest.approx(f0 * 0.85)


def test_new_leader_combat_effects():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    _neutral_ai(g, 1)
    g.regions["S002"].lines.clear()
    g.regions[tgt].lines.clear()
    D.declare_war(g, 0, 1)
    # 마오쩌둥 '국공내전': 보병 10 이상 돌격 +30%
    _lead(g, 0, "mao")
    a9 = g.new_army(0, "S002", {"inf": 9})
    s9 = g.combat_strength(0, [a9], tgt)[0]
    a9.units["inf"] = 10
    s10 = g.combat_strength(0, [a9], tgt)[0]
    assert s10 == pytest.approx(s9 / 9 * 10 * 1.3)
    # 맥아더: 상륙 감소 없이 +20%
    _lead(g, 0, "mac")
    assert g.amphib_mult(0) == pytest.approx(1.2)
    _lead(g, 0, "cus")
    assert g.amphib_mult(0) == pytest.approx(C.AMPHIBIOUS)
    # 맥아더 '자기과신': 병력이 적으면 받는 피해 +10% / 스탈린 '대숙청': 지면 피해 +3
    small = g.new_army(0, "S002", {"inf": 1})
    big = [g.new_army(1, tgt, {"inf": 5})]
    _lead(g, 0, "mac")
    dd, ad = g._leader_battle_mods(0, 1, [small], big, "S002", tgt, 10.0, 10.0)
    assert (dd, ad) == (10.0, pytest.approx(11.0))
    _lead(g, 0, "sta")
    dd, ad = g._leader_battle_mods(0, 1, [small], big, "S002", tgt, 5.0, 10.0)
    assert ad == pytest.approx(10.0 + 3)
    # 강감찬 '귀주대첩': 강을 건너 온 적 피해 +50% (방어측)
    river = next(((a, b) for k, t in g.world.terrain.items() if t["kind"] == "도하" for a, b in [tuple(k)]), None)
    _lead(g, 1, "kgc")
    _lead(g, 0, "cus")
    dd, ad = g._leader_battle_mods(0, 1, [small], [small], river[0], river[1], 5.0, 10.0)
    assert ad == pytest.approx(15.0)
    # 강감찬 '문신의 신중함': 기습 명령은 돌격으로
    _lead(g, 0, "kgc")
    a = g.new_army(0, "S002", {"inf": 3})
    ok, _ = g.order_army(a.id, tgt, mode="surprise")
    assert ok and a.order["mode"] == "assault"
    # 김원봉 '현상금': 잃은 유닛 생산비의 50%를 상대가 얻는다
    _lead(g, 0, "kwb")
    m1 = g.factions[1].money
    g._score_units(1, 0, {"inf": 2})
    assert g.factions[1].money == pytest.approx(m1 + C.UNITS["inf"]["cost"] * C.UNITS["inf"]["turns"] * 2 * 0.5)
    # 김원봉 '의열단': 건물 1단계 낮추기
    for k in g.regions[tgt].b:
        g.regions[tgt].b[k] = 0
    g.regions[tgt].b["factory"] = 2
    note = g._sabotage(g.regions[tgt])
    assert "의열단" in note and g.regions[tgt].b["factory"] == 1


def test_yelu_tribute_and_cession():
    g = new_game(player_start="S002", n_enemies=2, player_leader="yyl")
    _neutral_ai(g, 1, 2)
    g.dip.op[(1, 0)] = g.dip.op[(2, 0)] = 0.0
    assert D.declare_friendship(g, 0, 1)[0] and D.declare_friendship(g, 0, 2)[0]
    got = g.specialty_made(g.player).get(C.TRIBUTE_SPECIALTY, 0)
    assert got == 2                                       # 우호 선언 2곳 → 공물 2
    # 강동 6주: 강화하면 상대와 맞닿은 내 지역 1곳(수도 제외)이 넘어간다
    cap = g.player.capital
    mine = sorted(g.world.land_adj[cap])[:2]
    _own(g, 0, mine)
    enemy = next(n for n in g.world.land_adj[mine[0]] if n != cap and n not in mine)
    _own(g, 1, [enemy])
    D.declare_war(g, 1, 0)
    n0 = g.region_count(0)
    D.make_peace(g, 0, 1)
    assert g.region_count(0) == n0 - 1 and g.regions[cap].owner == 0


def test_leader_lines_complete():
    from korciv import dialogue as DLG
    from korciv.leaders import LEADERS
    for l in LEADERS:
        if l["key"] == "cus":
            continue
        for k in DLG.KINDS:
            assert DLG.line(l["key"], k), (l["name"], k)


def test_dialogue_triggers():
    g = new_game(player_start="S002", n_enemies=3, fog=2)
    _neutral_ai(g, 1, 2, 3)
    for f in g.factions[1:]:
        f.leader = "sta"                          # 대사가 있는 지도자
    g._mods.clear()
    g.dialogues.clear()
    kinds = lambda: [(d["kind"], d["fid"]) for d in g.dialogues]
    # 조우: 시야에 새 세력이 들어오면(게임 시작 때 제외)
    g.player.contact.discard(1)
    g.new_army(1, g.player.capital, {"inf": 1})
    g._update_fog()
    assert ("meet", 1) in kinds()
    n = len(g.dialogues)
    g._update_fog()
    assert len(g.dialogues) == n                    # 한 번만 인사
    g.dialogues.clear()
    g.player.met |= {1, 2, 3}
    g.dip.op[(1, 0)] = g.dip.op[(2, 0)] = 0.0
    D.declare_friendship(g, 0, 1)
    D.sign_treaty(g, 0, 2, "alliance")
    D.declare_war(g, 3, 0)
    D.make_peace(g, 0, 3)
    g.turn += C.DECL_COOLDOWN
    D.denounce(g, 2, 0)
    assert kinds() == [("friend", 1), ("alliance", 2), ("war", 3), ("peace", 3), ("denounce", 2)]
    g.dialogues.clear()
    g.eliminate(3, by=0)
    g.eliminate(0, by=1)
    assert kinds() == [("defeated", 3), ("victory", 1)]
    # AI끼리의 일·전원 AI 게임에서는 쌓지 않는다
    g2 = new_game(player_start="S002", n_enemies=2, all_ai=True)
    D.declare_war(g2, 1, 0)
    assert not g2.dialogues


def test_greeting_needs_contact_even_without_fog():
    """안개 '없음'·'지도 공개'여도 인사는 실제 시야(안개 최대와 같은 판정)에 들어와야."""
    for fog in (0, 1):
        g = new_game(player_start="S002", n_enemies=2, fog=fog)
        far = [f.id for f in g.factions[1:] if f.capital not in g._compute_visible(0)
               and not any(a.loc in g._compute_visible(0) for a in g.armies.values() if a.owner == f.id)]
        assert far
        g.dialogues.clear()
        g._update_fog()
        assert not [d for d in g.dialogues if d["kind"] == "meet"]   # 다 보여도 멀면 인사 없음
        g.new_army(far[0], g.player.capital, {"inf": 1})
        g._update_fog()
        assert ("meet", far[0]) in [(d["kind"], d["fid"]) for d in g.dialogues], fog


# ---------------------------------------------------------------- v0.20.0 패치
def test_v120_leader_changes():
    from korciv.leaders import LEADER_BY_KEY, Mods
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    base_tank = g.unit_cost(0, "S002", "tank")
    base_inf = g.unit_cost(0, "S002", "inf")
    _lead(g, 0, "dan")                                   # 단군: 보병 외 생산비 +20%
    assert g.unit_cost(0, "S002", "tank") == pytest.approx(base_tank * 1.2)
    assert g.unit_cost(0, "S002", "inf") == pytest.approx(base_inf)
    assert g.mods(0).add("happy_turn") == pytest.approx(0.10)
    # 광해군 '폐모살제': 정치체제 버프 50%, 디버프는 그대로
    m = Mods("hae", "absolute")
    assert m.add("tax_base") == pytest.approx(1.0) and m.value("far_output_gov") == 0.05
    assert Mods("hae", "parliamentary").mult("output_bank") == pytest.approx(1.05)
    assert Mods("hae", "fascist").mult("cost_mil") == pytest.approx(0.925)
    assert Mods("hae", "fascist").add("start_opinion") == -5
    assert Mods("cus", "parliamentary").mult("output_bank") == pytest.approx(1.1)
    assert LEADER_BY_KEY["jun"]["fx"]["output_bank"] == -0.08
    assert LEADER_BY_KEY["mac"]["fx"]["outnumbered_dmg"] == 0.10
    assert g.fx_source(0, "cost_noninf").endswith("'신화 시대'")
    _lead(g, 0, "kgu")
    assert g.fx_source(0, "provisional_gov").endswith("'임시정부'")


def test_kimdaejung_early_output():
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    y = g.calc_output("S002", full=True)
    _lead(g, 0, "kdj")
    g.turn = 10
    assert g.calc_output("S002", full=True) == pytest.approx(y * 0.8)
    g.turn = 11
    assert g.calc_output("S002", full=True) == pytest.approx(y)


def test_geunchogo_port_income():
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    rid = next(r for r in g.world.order if g.world.regions[r].coastal and g.regions[r].owner == NEUTRAL)
    _own(g, 0, [rid])
    g.regions[rid].b["port"] = 1
    g.regions[rid].happy = 50.0
    y = g.calc_output(rid, full=True)
    _lead(g, 0, "gcg")
    from korciv import rules as R
    assert g.calc_output(rid, full=True) == pytest.approx(y + C.BANK_OUTPUT * R.g(3))   # 은행 3단계 = 2,520


def test_kimgu_provisional_government():
    g = new_game(player_start="S002", n_enemies=2, player_leader="kgu")
    _neutral_ai(g, 1, 2)
    host, foe = 1, 2
    _own(g, host, [r for r in g.world.order if g.regions[r].owner == NEUTRAL][:30])
    D.add_opinion(g, 0, host, 50)
    D.add_opinion(g, 0, foe, -50)
    D.declare_war(g, foe, 0)
    g.transfer_region(g.player.capital, foe)            # 마지막 지역을 잃는다
    assert g.player.alive and g.player.provisional_used
    cap = g.player.capital
    assert g.regions[cap].owner == 0 and cap != g.factions[host].capital
    assert D.allied(g, 0, host) and D.declared_friends(g, 0, host)
    assert sum(a.units.get("inf", 0) for a in g.armies.values() if a.owner == 0) >= C.PROVISIONAL_INF
    # 두 번째는 없다
    g.transfer_region(cap, foe)
    assert not g.player.alive


def test_peace_weariness_relief():
    g = new_game(n_enemies=2)
    _neutral_ai(g, 1, 2)
    D.declare_war(g, 0, 1)
    w = g.dip.wars[D.pair(0, 1)]
    w["taken"] = {0: 3, 1: 1}
    w["kills"] = {0: 5, 1: 2}
    g.player.war_weary = 40.0
    g.factions[1].war_weary = 30.0
    D.make_peace(g, 0, 1)
    assert g.player.war_weary == pytest.approx(20.0)    # 땅 −10, 유닛 −10
    assert g.factions[1].war_weary == pytest.approx(30.0)
    # 처치 수는 전투에서 기록된다
    D.declare_war(g, 0, 2)
    g._score_units(0, 2, {"inf": 3})
    assert g.dip.wars[D.pair(0, 2)]["kills"] == {0: 3}


def test_starts_spread_and_no_random_islands():
    from korciv.state import Settings
    isl = set()
    for seed in range(12):
        g = Game(Settings(n_enemies=7, seed=seed, all_ai=True))
        caps = [f.capital for f in g.factions]
        for i, a in enumerate(caps):
            assert g.world.regions[a].island != "무연륙 섬"
            for b in caps[i + 1:]:
                need = 7 if {g.world.regions[a].do8, g.world.regions[b].do8} & set(C.START_WIDE_DO8) else 6
                assert g._land_dist(a, b, need) >= need
        isl |= {r for r in g.world.order if g.world.regions[r].island == "무연륙 섬"}
    assert len(isl) == 3
    # 직접 고르면 섬에서도 시작할 수 있다
    jeju = next(r for r in isl if "서귀포" in g.world.regions[r].name)
    g = new_game(player_start=jeju, n_enemies=3)
    assert g.player.capital == jeju


# ---------------------------------------------------------------- AI 1페이즈(확장기)
def test_ai_phase1_transition_and_free_ratio():
    from korciv import ai_phase as PH
    g = new_game(player_start="S002", n_enemies=2)
    f = g.factions[1]
    assert PH.update(g, f) == 1 and f.ai["phase"] == 1
    assert f.ai["nadj"] > 0 and 0 < f.ai["free"] <= 1
    assert PH.free_ratio(0, 30) == 0 and PH.free_ratio(6, 30) == 1.0 and PH.free_ratio(3, 30) == 0.5
    # 빈 땅이 모두 사라져도 최소 체류(12턴) 전에는 그대로, 그 뒤 2페이즈
    for r in g.regions.values():
        if r.owner == NEUTRAL:
            r.owner = 2
    g.turn = 5
    assert PH.update(g, f) == 1 and f.ai["nadj"] == 0
    g.turn = 20
    assert PH.update(g, f) == 2 and f.ai["phase_turn"] == 20
    # 96턴이 지나면 무조건 2페이즈
    f2 = g.factions[2]
    g.turn = C.AI_P1_MAX_TURN
    f2.ai["phase_turn"] = 0
    assert PH.update(g, f2) == 2
    assert PH.phase(g.player) == 2                       # 플레이어는 기존 판단(페이즈 없음)


def test_ai_phase1_prefers_land_over_war():
    from korciv import ai
    g = new_game(player_start="S002", n_enemies=1)
    _neutral_ai(g, 1)
    f = g.factions[1]
    f.ai.update(phase=1, free=1.0)
    D.declare_war(g, 0, 1)
    base = ai.war_assessment(g, 1, 0)["desire"]
    f.ai["free"] = 0.0
    assert ai.war_assessment(g, 1, 0)["desire"] == pytest.approx(base - C.AI_P1_PEACE)


def test_ai_phase1_rally_point():
    from korciv import ai
    g = new_game(player_start="S002", n_enemies=1)
    fid = 1
    rally = ai._p1_rally(g, fid, set())
    assert rally is not None and g.regions[rally].owner == fid
    assert any(g.regions[n].owner == NEUTRAL for n in g.world.land_adj[rally])
    # 맞닿은 빈 땅을 모두 편입 중이면 집결지 없음
    annexing = {n for r in g.regions_of(fid) for n in g.world.land_adj[r.id] if g.regions[n].owner == NEUTRAL}
    assert ai._p1_rally(g, fid, annexing) is None


def test_ai_phase1_deficit_builds_production():
    from korciv import ai
    g = new_game(player_start="S002", n_enemies=1, ai_starts=["S049"])   # 대구 중구(시작 위치를 고정)
    fid = 1
    f = g.factions[fid]
    _room(g, [f.capital])
    _neutral_ai(g, fid)
    # 편입 가중치를 낮춰 생산 건물이 1순위가 되게 하고, 적자일 때 비축으로 짓는지 본다
    f.ai.update(phase=1, free=1.0, weights={"military": 0.5, "economy": 1, "expansion": 0.5, "defense": 1})
    f.money = 50_000
    f.last.update(tax=100.0, upkeep=400.0)               # 세수 < 유지비: 적자
    for r in g.regions_of(fid):
        r.project = None
    ai._slots(g, f, {}, military=False)
    kinds = [r.project.kind for r in g.regions_of(fid) if r.project]
    assert "build" in kinds                              # 적자면 비축으로 생산 건물부터


# ---------------------------------------------------------------- AI 2페이즈(경쟁기)
def _p2_game(n=3):
    from korciv.state import Settings
    g = _meet_all(Game(Settings(n_enemies=n, seed=7, all_ai=True)))
    for f in g.factions:
        f.ai.update(phase=2, phase_turn=0)
    _neutral_ai(g, *[f.id for f in g.factions])
    return g


def test_ai_p2_path_scores_follow_situation():
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    base = ST.path_scores(g, f, {})["scores"]
    # 석유 지역이 있으면 과학 점수가 오른다
    oil = next(r for r in g.world.order if g.info(r).is_oil and g.regions[r].owner == NEUTRAL)
    _own(g, 0, [oil])
    assert ST.path_scores(g, f, {})["scores"]["science"] > base["science"]
    # 나보다 훨씬 약한 이웃이 있으면 정복 점수가 전력 차이에 비례해 오른다
    weak = {1: {"p": 10.0, "ratio": 1.5, "host": 0.2, "share": 1.0, "mass": 0.0, "T": 0.1, "regions": 10}}
    weaker = {1: dict(weak[1], ratio=3.0)}
    s1 = ST.path_scores(g, f, weak)["scores"]["conquest"]
    s2 = ST.path_scores(g, f, weaker)["scores"]["conquest"]
    assert s2 > s1 > ST.path_scores(g, f, {})["scores"]["conquest"]
    # 강하고 적대적인 이웃이 있으면 정복 점수가 깎인다
    scary = {1: dict(weak[1]), 2: {"p": 999.0, "ratio": 0.3, "host": 0.6, "share": 0.5, "mass": 0, "T": 2, "regions": 50}}
    assert ST.path_scores(g, f, scary)["scores"]["conquest"] < s1


def test_ai_p2_econ_follows_gdp_rank():
    """경제 점수는 '돈'(반기 랭킹 GDP 순위)을 따른다: 1위 ×1.3 → 꼴찌 ×0.3, 1~2위가 다음 단계를 감당하면 ×1.25."""
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]

    def ranked(top):
        g.rankings = {g.turn: [{"fid": x.id, "gdp": (1000 if x.id == 0 else 10 * (x.id + 1)) if top
                                else (1 if x.id == 0 else 100 * (x.id + 1)), "science": 0, "econ": 0}
                               for x in g.factions if x.alive]}
    ranked(False)
    f.last["tax"], f.last["upkeep"] = 0, 0
    last = ST.path_scores(g, f, {})["scores"]["economic"]
    ranked(True)
    first = ST.path_scores(g, f, {})["scores"]["economic"]
    assert first > 3 * last                          # 순위 배수 1.3/0.3 ≈ 4.3배에 계단 가점까지
    f.last["tax"] = 10 ** 7                         # 다음 단계를 순수입으로 감당할 수 있다
    assert ST.path_scores(g, f, {})["scores"]["economic"] == pytest.approx(first * C.AI_P2_ECON_RICH, rel=0.01)
    assert "감당 가능" in ST.path_scores(g, f, {})["why"]["economic"]


def test_ai_p2_gdp_top_picks_conquest_or_econ_by_aggression():
    """GDP 1위는 정복과 경제 중 호전성에 맞는 쪽을 고른다(돈으로 군대를 빨리 올릴 수 있다). 과학·외교는 고르지 않는다."""
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    g.rankings = {g.turn: [{"fid": x.id, "gdp": 1000 if x.id == 0 else 10, "science": 0, "econ": 0}
                           for x in g.factions if x.alive]}
    f.last["tax"], f.last["upkeep"] = 0, 0
    f.gov = None

    def scores(aggr):
        f.aggression = aggr
        return ST.path_scores(g, f, {})["scores"]
    hawk, dove = scores(9), scores(2)
    assert hawk["conquest"] > hawk["economic"] and dove["economic"] > dove["conquest"]
    assert hawk["science"] == hawk["diplomatic"] == dove["science"] == dove["diplomatic"] == 0
    # 2위부터는 예전처럼: 약한 이웃이 없으면 정복은 어렵다
    g.rankings = {g.turn: [{"fid": x.id, "gdp": 500 if x.id == 0 else 1000 if x.id == 1 else 10, "science": 0, "econ": 0}
                           for x in g.factions if x.alive]}
    second = scores(9)
    assert second["conquest"] < hawk["conquest"] and second["science"] > 0

def test_ai_conquest_artillery_behind_front():
    """정복 방향 전쟁: 최전선 부대의 포병은 떨어져 바로 뒤 칸(적과 맞닿지 않고 적 땅이 2칸 안)으로 물러나 받친다."""
    from korciv import ai
    g = _p2_game()
    w = g.world
    y, x, z = next((y, x, z) for y in w.order if not w.is_sea(y) for x in w.land_adj[y] for z in w.land_adj[y]
                   if z != x and x not in w.land_adj[z])
    _own(g, 1, [x])
    _own(g, 0, [y, z] + [n for n in w.land_adj[z] if n != y])
    for n in w.land_adj[z]:
        assert n == y or g.regions[n].owner == 0
    for a in [a for a in g.armies.values() if a.loc in (x, y, z)]:
        del g.armies[a.id]
    g.new_army(1, x, {"inf": 1})
    g.new_army(0, y, {"inf": 3, "art": 2})
    D.declare_war(g, 0, 1)
    f = g.factions[0]
    f.ai["victory_goal"] = "conquest"
    ai._army_orders(g, f, {y: 1.0})
    arts = [a for a in g.armies.values() if a.owner == 0 and a.units.get("art")]
    assert arts and all(set(a.units) == {"art"} for a in arts)
    assert any(a.order and a.order["type"] == "move" and a.order["path"][-1] == z for a in arts)

def test_ai_p2_econ_skipped_when_richer_rival_ahead():
    """반기 랭킹에서 나보다 GDP가 높은 나라가 경제 단계도 앞서 있으면 격차만큼 exp(−k × 격차)로 줄어든다."""
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    rows = lambda e: [{"fid": x.id, "gdp": 500 if x.id == 0 else 1000 if x.id == 1 else 10, "science": 0,
                       "econ": e if x.id == 1 else 0} for x in g.factions if x.alive]
    g.rankings = {g.turn: rows(0)}
    base = ST.path_scores(g, f, {})["scores"]["economic"]
    assert base > 0
    g.rankings = {g.turn: rows(1)}                    # 1단계 + GDP 2배: 격차 2
    near = ST.path_scores(g, f, {})["scores"]["economic"]
    assert near == pytest.approx(base * math.exp(-2 * C.AI_P2_ECON_BEHIND_K), rel=0.01)
    g.rankings = {g.turn: rows(4)}                    # 격차가 벌어질수록 0에 가깝다
    assert ST.path_scores(g, f, {})["scores"]["economic"] < near / 4

def test_ai_p2_science_early_when_sites_ready():
    """산지·해안·석유·공장 4단계 이상을 모두 갖추면 과학 점수 × AI_P2_SCI_EARLY."""
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    w = g.world
    free = lambda pred: next(r for r in w.order if g.regions[r].owner == NEUTRAL and pred(r))
    _own(g, 0, [free(lambda r: g.info(r).is_oil), free(lambda r: g.info(r).coastal),
                free(lambda r: r in w.mountain_regions)])
    for r in g.regions_of(0):
        r.b["factory"] = min(r.b["factory"], 3)
    g.rankings = {g.turn: [{"fid": x.id, "gdp": 100 if x.id == 0 else 1000, "science": 0, "econ": 0}
                           for x in g.factions if x.alive]}
    assert not ST.science_ready(g, 0)
    g.regions_of(0)[0].b["factory"] = 4
    assert ST.science_ready(g, 0)
    after = ST.path_scores(g, f, {})
    ready = ST.science_ready
    ST.science_ready = lambda g, fid: False           # 같은 공장 단계에서 가점만 뺀 점수
    try:
        before = ST.path_scores(g, f, {})
    finally:
        ST.science_ready = ready
    assert after["scores"]["science"] == pytest.approx(before["scores"]["science"] * C.AI_P2_SCI_EARLY, rel=0.01)
    assert "조건 완비" in after["why"]["science"] and "조건 완비" not in before["why"]["science"]

def test_ai_bomb_value_science_units():
    """폭격 대상 가치: 보이는 적의 과학 유닛 1개당 + AI_SCI_UNIT_BOMB(낮은 적극성)."""
    from korciv import ai
    g = _p2_game()
    rid = g.regions_of(1)[0].id
    D.declare_war(g, 0, 1)
    g.is_visible = lambda fid, loc: True
    base = ai._bomb_value(g, 0, rid, None)
    g.new_army(1, rid, {"booster": 1, "module": 1})
    assert ai._bomb_value(g, 0, rid, None) == pytest.approx(base + 2 * C.AI_SCI_UNIT_BOMB)

def test_ai_econ_zone_defense():
    """경제 3페이즈: 금융 권역 둘레 내 지역에 수비대, 권역 지역에 방공호·방어선 후보."""
    from korciv import ai
    g = _p2_game()
    f = g.factions[0]
    cap = f.capital
    near = [n for n in g.world.land_adj[cap] if g.regions[n].owner == NEUTRAL]
    _own(g, 0, near + [m for n in near for m in g.world.land_adj[n] if g.regions[m].owner == NEUTRAL][:6])
    zone = ai.finance_plan(g, 0)
    for rid in zone:
        g.regions[rid].b["bank"] = 5
    f.ai["phase"] = 3
    f.ai["p3"] = {"kind": "economic", "turn": g.turn}
    z, ring = ai.econ_zone(g, f)
    assert z == g.finance_cluster(0) and ring and not (ring & z)
    guards = ai.key_guards(g, f, {})
    assert all(guards.get(r, 0) >= 1 for r in ring if r != f.capital)
    for rid in z:
        g.regions[rid].project = None
    cands = []
    ai._econ_zone_defense(g, f, set(z), cands, False)
    assert cands and all(c[1] in z and c[3] in ("shelter", "line") for c in cands)

def test_ai_econ_sprints_when_only_currency_left():
    """경제 3페이즈: 기축통화 하나만 남으면 경쟁자와 견주지 않고 질주."""
    from korciv import ai_endgame as EG
    g = _p2_game()
    f = g.factions[0]
    f.ai["phase"] = 3
    f.ai["p3"] = {"kind": "economic", "turn": g.turn}
    g.econ_stage = lambda fid: C.ECON_STAGES - 1 if fid == 0 else 0
    assert EG.assess(g, f)["sprint"] and EG.sprint(f) == "economic"
    f.ai["p3"] = {"kind": "economic", "turn": g.turn}
    g.econ_stage = lambda fid: 2
    EG.assess(g, f)
    assert EG.sprint(f) == "" or f.ai["p3"]["eta"] <= (1 + C.AI_P3_TOL) * f.ai["p3"]["rival_eta"]

def test_observatory_bombed_blocks_science_until_rebuilt():
    """폭격이 건물을 맞히면 천체관측소가 파괴될 수 있다: 과학 단계에서 빠져, 다른 단계를 다 마쳤어도 다시 지어야 발사."""
    from korciv import ai
    g = _p2_game()
    f = g.factions[1]
    rid = g.regions_of(1)[0].id
    rr = g.regions[rid]
    rr.sci.add("observatory")
    f.science = list(C.SCIENCE_STEPS)
    D.declare_war(g, 0, 1)
    g.is_visible = lambda fid, loc: True
    assert ai._bomb_value(g, 0, rid, None) >= C.AI_SCI_OBS_BOMB          # 시야에 든 적 관측소는 폭격 대상
    a = g.new_army(0, rid, {"bmb": 1})
    g.air_defense = lambda fid, tgt: (0, 0, 0)
    g.rng.random = lambda: 0.0                                          # 건물 명중·관측소 50% 모두 통과
    g._bombard(a, rid, {"bmb": 1})
    assert "observatory" not in rr.sci and "observatory" not in f.science
    assert g.science_next(1) == "observatory" and g.launch_ready(1) is None

def test_ai_fill_idle_slots_when_rich():
    """돈이 남는 2페이즈 AI는 노는 땅에 완공 뒤 비용이 없는 생산 건물을 채운다. 경계면 국경·해안 방어 시설부터."""
    from korciv import ai
    g = _p2_game()
    f = g.factions[0]
    f.money = 10 ** 6
    idle = [r for r in g.regions_of(0) if not r.project]
    ai._fill_slots(g, f, idle, "normal", 200, 1000, 0)
    assert all(r.project and r.project.kind == "build" for r in idle)
    g2 = _p2_game()
    f2 = g2.factions[0]
    f2.money = 0
    idle2 = [r for r in g2.regions_of(0) if not r.project]
    ai._fill_slots(g2, f2, idle2, "normal", 200, 0, 0)          # 돈이 없으면 손대지 않는다(멈춤 방지)
    assert not any(r.project for r in idle2)


def test_ai_poverty_tilts_to_diplomacy():
    from korciv import ai_strategy as ST
    g = _p2_game()
    rows = [{"fid": x.id, "gdp": 100 * (x.id + 1), "science": 0, "econ": 0} for x in g.factions if x.alive]
    g.rankings = {g.turn: rows}
    assert ST.poverty(g, 0) == 1.0 and ST.poverty(g, g.factions[-1].id) == 0.0


def test_ai_unhappy_loss_penalty():
    """행복도 때문에 산출·전투력이 떨어질수록 전쟁을 덜 한다. 적자면 2배."""
    from korciv import ai
    g = _p2_game()
    f = g.factions[0]
    f.last["net"] = 10
    assert ai._unhappy_loss_penalty(g, f, 0, C.AI_WAR_LOSS_K) == 0
    p = ai._unhappy_loss_penalty(g, f, -50, C.AI_WAR_LOSS_K)
    assert p == pytest.approx(C.AI_WAR_LOSS_K * 0.075)
    f.last["net"] = -10
    assert ai._unhappy_loss_penalty(g, f, -50, C.AI_WAR_LOSS_K) == pytest.approx(p * C.AI_UNHAPPY_SHAKY)


def test_ai_p2_path_inertia_and_log():
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    s = ST.state(f)
    s["path"] = "science"
    s["scores"] = {}
    g.rng.seed(1)
    res = ST.path_scores(g, f, {})["scores"]
    best = max(res, key=res.get)
    ST.choose_path(g, f, {})
    # 관성: 새 방향이 1.25배를 넘지 않으면 그대로
    if res[best] < C.AI_P2_SWITCH * res["science"] * 0.95:
        assert s["path"] == "science"
    assert s["last_eval"] == g.turn


def test_ai_p2_anchor_for_three_borders():
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    sc = {o: {"p": 50.0 * o, "ratio": 1.0, "host": 0.2, "share": 0.33, "mass": 0, "T": 0.2, "regions": 20} for o in (1, 2, 3)}
    a = ST.choose_anchor(g, f, sc)
    assert a in (1, 2, 3)
    assert ST.choose_anchor(g, f, {1: sc[1], 2: sc[2]}) in (1, 2)      # 국경 2곳이면 위협이 없어도(포위 방지)
    assert ST.choose_anchor(g, f, {1: sc[1]}) is None                   # 이웃이 하나뿐이면 둘러싸일 일이 없다


def test_ai_friendship_prefers_neighbor_when_encircled():
    """국경을 맞댄 나라가 여럿이면 강약과 상관없이 이웃과의 우호 선언에 가점."""
    from korciv import ai
    g = _p2_game(n=4)
    f = g.factions[0]
    adj = [n for n in g.world.land_adj[f.capital] if g.regions[n].owner == NEUTRAL]
    g.transfer_region(adj[0], 1, "편입")
    g.transfer_region(adj[1], 2, "편입")
    far = next(x for x in (3, 4) if x not in
               {g.regions[n].owner for r in g.regions_of(0) for n in g.world.land_adj[r.id]})
    for x in (1, 2, far):
        g.dip.op[(0, x)] = 40.0
        g.dip.op[(x, 0)] = 40.0
    g.dip.op[(0, 2)] = 39.0                    # 이웃 둘 중에서는 1을 고르게
    old = C.AI_FRIEND_DECL_P
    try:
        C.AI_FRIEND_DECL_P = 10.0
        ai._social(g, f)
    finally:
        C.AI_FRIEND_DECL_P = old
    assert D.declared_friends(g, 0, 1) and not D.declared_friends(g, 0, far)


def test_ai_p2_posture_and_crisis_stops_big_projects():
    from korciv import ai, ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    assert ST.posture(g, f, {}) == "normal"
    assert ST.posture(g, f, {1: {"T": 2.0}}) == "defend"
    D.declare_war(g, 1, 0)
    g.dip.wars[D.pair(0, 1)]["taken"] = {1: 10}
    g.dip.wars[D.pair(0, 1)]["regs0"] = {0: 20, 1: 20}
    assert ST.posture(g, f, {1: {"T": 0.1, "ratio": 2.0}}) == "crisis"
    # 위기: 과학 단계를 새로 시작하지 않는다
    s = ST.state(f)
    s.update(posture="crisis", path="science", scan={}, mil_ok=False)
    f.ai["victory_goal"] = "science"
    f.money = 10 ** 7
    for r in g.regions_of(0):
        r.project = None
    ai._slots(g, f, {}, military=False)
    assert not any(r.project and r.project.kind == "science" for r in g.regions_of(0))


def test_ai_only_goal_builds_victory_projects():
    """과학·경제 단계는 그 방향일 때만 짓는다: 돈이 아주 많아도 정복 방향은 손대지 않는다."""
    from korciv import ai, ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    s = ST.state(f)
    s.update(posture="normal", path="conquest", scan={}, mil_ok=True)
    f.ai["victory_goal"] = "conquest"
    f.money = 10 ** 8

    def run():
        for r in g.regions_of(0):
            r.project = None
        ai._slots(g, f, {}, military=False)
        return {r.project.kind for r in g.regions_of(0) if r.project}
    assert not run() & {"science", "econ"}
    s["path"] = f.ai["victory_goal"] = "science"
    assert "science" in run()

def test_ai_p2_two_front_blocks_new_war():
    from korciv import ai, ai_strategy as ST
    g = _p2_game()
    p2 = {"scan": {1: {"T": 0.1, "mass": 0.0}, 2: {"T": 1.0, "mass": 0.0}}}
    assert ai.p2_war_gate(g, 0, p2, 1, 1.5) == "양면 전선"       # 위협 이웃 2가 무방비로 남아 있다
    assert ai.p2_war_gate(g, 0, p2, 1, 3.0) is None               # 압도적이면 예외
    g.dip.nonaggr[D.pair(0, 2)] = g.turn + 24
    assert ai.p2_war_gate(g, 0, p2, 1, 1.5) is None               # 2와 불가침이면 괜찮다
    p2 = {"scan": {1: {"T": 0.1, "mass": 2.0}}}
    assert ai.p2_war_gate(g, 0, p2, 1, 1.5) == "국경 병력"        # 상대가 국경에 병력을 모았다
    assert ai.p2_war_gate(g, 0, p2, 1, 2.5) is None
    f = g.factions[0]
    ai._p2_block(f, "양면 전선")
    assert ST.state(f)["blocks"]["양면 전선"] == 1


def test_ai_gift_raises_opinion():
    g = _p2_game()
    before = D.opinion(g, 1, 0)
    g.factions[0].money = 10 ** 6
    need = D.gift_needed(g, 1, 10, 0)
    v = D.ai_gift(g, 0, 1, need)
    assert v == pytest.approx(10, abs=0.1) and D.opinion(g, 1, 0) == pytest.approx(before + v)


def test_ai_p2_hopeless_turns_to_diplomacy_with_strongest(monkeypatch):
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    why = {k: "" for k in ST.PATHS}
    low = {"scores": {"conquest": 0.1, "science": 0.15, "economic": 0.12, "diplomatic": 0.0}, "why": why}
    monkeypatch.setattr(ST, "path_scores", lambda *a, **k: low)
    for o, n in ((1, 2), (2, 3), (3, 30)):               # 3번이 가장 강하다
        g.new_army(o, g.factions[o].capital, {"inf": n})
    g.settings.fog = 0                                    # 모두 만나 본 것으로
    assert ST.choose_path(g, f, {}) == "diplomatic"
    s = ST.state(f)
    assert s["hopeless"] and s["patron"] == 3 and s["log"][-1][2] == "diplomatic"
    # 48턴 안에는 점수가 좋아져도 외교에 전념
    hi = {"scores": {"conquest": 0.5, "science": 0.2, "economic": 0.1, "diplomatic": 0.0}, "why": why}
    monkeypatch.setattr(ST, "path_scores", lambda *a, **k: hi)
    g.turn += C.AI_P2_HOPELESS_MIN - 1
    assert ST.choose_path(g, f, {}) == "diplomatic"
    # 그 뒤, 최고점이 문턱(0.18)을 넘어도 ×1.25(0.225)를 넘기 전에는 그대로
    g.turn += 1
    mid = {"scores": {"conquest": 0.21, "science": 0.15, "economic": 0.1, "diplomatic": 0.0}, "why": why}
    monkeypatch.setattr(ST, "path_scores", lambda *a, **k: mid)
    assert ST.choose_path(g, f, {}) == "diplomatic"
    monkeypatch.setattr(ST, "path_scores", lambda *a, **k: hi)
    assert ST.choose_path(g, f, {}) == "conquest" and not s["hopeless"] and "patron" not in s
    # 동맹을 맺을 수 없는 지도자(장보고)는 외교로 가지 않는다
    s.clear()
    _lead(g, 0, "jan")
    monkeypatch.setattr(ST, "path_scores", lambda *a, **k: low)
    assert ST.choose_path(g, f, {}) != "diplomatic"


def test_ai_choose_patron_is_strongest_known_not_at_war():
    from korciv import ai_strategy as ST
    g = _p2_game()
    f = g.factions[0]
    for o, n in ((1, 2), (2, 30), (3, 5)):
        g.new_army(o, g.factions[o].capital, {"inf": n})
    g.settings.fog = 0                                   # 모두 보인다(만나 본 것으로)
    assert ST.choose_patron(g, f) == 2
    D.declare_war(g, 2, 0)
    assert ST.choose_patron(g, f) in (1, 3)              # 싸우는 나라는 빼고


def test_ai_p2_court_builds_relation():
    from korciv import ai
    g = _p2_game()
    f = g.factions[0]
    f.money = 10 ** 7
    f.last.update(tax=50_000.0, upkeep=0.0)
    before = D.opinion(g, 0, 1)
    ai._p2_court(g, f, 1, "coalition", C.AI_P2_PATRON_OP)
    assert D.opinion(g, 0, 1) >= before + C.AI_P2_PATRON_OP - 1e-9
    assert D.declared_friends(g, 0, 1)                   # 첫 단계: 우호 선언
    g.turn += 1
    op = D.opinion(g, 1, 0)
    ai._p2_court(g, f, 1, "coalition", C.AI_P2_PATRON_OP)
    assert D.opinion(g, 1, 0) > op                       # 다음 단계 문턱까지 선물



def test_ai_diplomatic_path_gifts_from_savings():
    """외교 방향은 모아 둔 돈으로 선물한다(다른 방향은 순수입 몇 턴분까지)."""
    from korciv import ai

    def gain(goal):
        g = _p2_game()
        f = g.factions[0]
        f.ai["victory_goal"] = goal
        f.money = 10 ** 7
        f.last.update(tax=1_000.0, upkeep=0.0)
        g.factions[1].last["tax"] = 100_000.0            # 받는 쪽이 부자: 우호도 1에 세수 1/3턴분
        D.declare_friendship(g, 0, 1)
        op = D.opinion(g, 1, 0)
        ai._p2_court(g, f, 1, "coalition", 0)
        return D.opinion(g, 1, 0) - op
    assert gain("diplomatic") > gain("conquest") > 0


def test_lost_science_project_resume_or_refund():
    """점령으로 멈춘 과학·경제 공사: 저항·회복 기간 안에 되찾으면 이어서, 다른 나라에 넘어가거나 기간이 지나면 50% 환급."""
    from korciv.state import Project
    g = Game(Settings(n_enemies=2, seed=7, all_ai=True))
    _neutral_ai(g, 0, 1, 2)
    D.declare_war(g, 1, 0)
    cap = g.factions[0].capital
    rid = next(n for n in g.world.land_adj[cap] if g.regions[n].owner == NEUTRAL)
    _own(g, 0, [rid])
    rr = g.regions[rid]
    rr.project = Project(kind="science", key="lab", turns=15, progress=5, per_turn=110_000, paid=550_000)
    g.complete_occupation(1, rid)
    assert rr.project is None and rr.lost_project["fid"] == 0
    g.complete_occupation(0, rid)                                   # 저항 중 탈환: 그대로 이어서
    assert rr.project is not None and rr.project.paid == 550_000 and rr.lost_project is None
    # 다시 빼앗기고, 기간 안에 되찾지 못하면 50% 환급
    g.complete_occupation(1, rid)
    money = g.factions[0].money
    rr.resist["turn"] -= C.RESIST_TURNS + C.RESIST_RECOVER_TURNS
    g._phase_happiness()
    assert rr.lost_project is None and g.factions[0].money == pytest.approx(money + 550_000 * C.LOST_PROJECT_REFUND)


def test_coalition_war_needs_consent_and_all_join():
    from korciv import ai
    g = _meet_all(Game(Settings(n_enemies=3, seed=7, all_ai=True)))
    _neutral_ai(g, 0, 1, 2, 3)
    g.dip.coalitions[1] = {"members": {0, 1}, "leader": 0, "start": 0}
    for a, b in ((0, 3), (1, 3)):
        g.dip.op[(a, b)] = 50.0
    # 회원 1이 대상(3)을 좋게 보면 동의하지 않는다
    ok, msg = D.declare_war(g, 0, 3)
    assert not ok and "동의" in msg and not D.at_war(g, 0, 3)
    g.dip.op[(1, 3)] = -40.0
    assert ai.coalition_war_consent(g, 1, 0, 3)
    ok, _ = D.declare_war(g, 0, 3)
    assert ok and D.at_war(g, 0, 3) and D.at_war(g, 1, 3)        # 연합 전원 참전
    # 동맹(연합 포함)이 공격당하면 모두 자동 참전
    D.make_peace(g, 0, 3)
    D.make_peace(g, 1, 3)
    g.dip.nonaggr.clear()
    g.dip.peace_until = {} if hasattr(g.dip, "peace_until") else None
    ok, _ = D.declare_war(g, 2, 0)
    assert ok and D.at_war(g, 2, 1)


def test_ai_phase3_entry_by_goal():
    """3페이즈: 노리는 승리 조건의 문턱(정복 2/N 지역, 과학 3단계, 경제 2단계)을 넘으면 들어가고 방향을 고정한다."""
    from korciv import ai_phase as PH
    g = _p2_game(n=3)
    f = g.factions[0]
    f.ai["p2"] = {"path": "science"}
    f.science = ["lab", "observatory", "budget"]
    assert PH.update(g, f) == 3 and PH.p3_kind(f) == "science"
    f2 = g.factions[1]
    f2.ai["p2"] = {"path": "conquest"}
    need = PH.conquest_need(g) * len(g.regions)
    assert PH.update(g, f2) == 2
    extra = [r for r in g.world.order if g.regions[r].owner == NEUTRAL][:int(need) + 1]
    _own(g, 1, extra)
    assert PH.update(g, f2) == 3 and PH.p3_kind(f2) == "conquest"


def test_ai_phase3_sprint_when_ahead():
    """3페이즈: 내 승리 ETA 가 다른 나라 가장 빠른 ETA 의 1.2배 안이면 질주."""
    from korciv import ai_endgame as EG
    g = _p2_game(n=3)
    f = g.factions[0]
    f.ai.update(phase=3, p3={"kind": "science", "turn": 0})
    f.science = list(C.SCIENCE_STEPS[:6])
    for r in g.regions_of(0):
        r.output = 10 ** 6                              # 돈은 넉넉하다
    p = EG.assess(g, f)
    assert p["eta"] < p["rival_eta"] and p["sprint"] and EG.sprint(f) == "science"
    g.factions[1].science = list(C.SCIENCE_STEPS)          # 남이 훨씬 앞서면 질주하지 않는다
    p["eval"] = -99
    assert not EG.assess(g, f)["sprint"]


def test_ai_harass_imminent_winner():
    """승리가 임박한 나라(ETA 150턴 안)가 나보다 앞서면 견제 대상(2페이즈도). 6턴마다 위급도를 다시 계산."""
    from korciv import ai_endgame as EG
    g = _p2_game(n=3)
    f = g.factions[0]
    leader = g.factions[1]
    leader.science = list(C.SCIENCE_STEPS[:6])
    leader.money = 10 ** 8
    w = EG.watch(g, f)
    assert w["harass"] == 1 and w["urgency"] > 0.5
    assert EG.harass(g, f) == (1, w["urgency"])
    leader.science = []
    leader.money = 0
    assert EG.watch(g, f)["harass"] == 1                       # 6턴 안에는 다시 계산하지 않는다
    g.turn += C.AI_P3_EVAL_TURNS
    assert EG.watch(g, f)["harass"] is None


def test_ai_diplomatic_follower_rides_conqueror():
    """외교 3페이즈: 정복을 노리는 강국에 기대고, 강국의 전쟁에 동의하며, 강국과 서로 동맹을 깨지 않는다."""
    from korciv import ai, ai_endgame as EG, ai_strategy as ST
    g = _p2_game(n=3)
    f, pat = g.factions[0], g.factions[1]
    f.ai.update(phase=3, p3={"kind": "diplomatic", "turn": 0})
    pat.ai["p2"] = {"path": "conquest"}
    g.new_army(1, pat.capital, {"inf": 40})
    g.settings.fog = 0
    ai.follower_update(g, f)
    assert ST.state(f)["patron"] == 1 and EG.follower_patron(g, f) == 1
    assert EG.conquest_minded(g, 1)
    assert ai.coalition_war_consent(g, 0, 1, 2)            # 강국의 전쟁에는 함께한다
    assert ai.loyal(g, 1, 0) and ai.loyal(g, 0, 1)


def test_key_region_value_and_guards():
    """승리 거점: 발사대 10·증권거래소 6. 과학·경제 3페이즈는 거점마다 수비대 2를 둔다."""
    from korciv import ai, ai_endgame as EG
    g = _p2_game(n=3)
    f = g.factions[0]
    cap = f.capital
    a, b = [n for n in g.world.land_adj[cap] if g.regions[n].owner == NEUTRAL][:2]
    _own(g, 0, [a, b])
    g.regions[a].sci.add("pad")
    g.regions[b].econ.add("exchange")
    g.turn += 1                                      # 거점 가치 캐시는 턴마다
    assert EG.key_value(g, a) == 10 and EG.key_value(g, b) == 6 and EG.key_value(g, cap) == 4
    f.ai.update(phase=3, p3={"kind": "science", "turn": 0})
    guards = ai.key_guards(g, f, {})
    assert guards == {a: C.AI_KEY_GUARD, b: C.AI_KEY_GUARD}



def test_captured_victory_buildings_off_then_revived_or_demolished():
    """빼앗긴 과학·경제 시설: 꺼져서 누구도 못 쓰고, 저항·회복 중 되찾으면 되살아나며, 못 되찾으면 철거되어
    그 단계를 다시 지어야 한다(철거 전에는 다시 지을 수 없다)."""
    g = Game(Settings(n_enemies=2, seed=7, all_ai=True))
    _neutral_ai(g, 0, 1, 2)
    D.declare_war(g, 1, 0)
    f = g.factions[0]
    cap = f.capital
    rid = next(n for n in g.world.land_adj[cap] if g.regions[n].owner == NEUTRAL)
    _own(g, 0, [rid])
    rr = g.regions[rid]
    rr.sci.add("lab")
    rr.econ.add("exchange")
    f.science = ["lab"]
    g.complete_occupation(1, rid)
    assert not rr.sci and not rr.econ and rr.lost_bld["fid"] == 0          # 빼앗은 나라도 못 쓴다
    assert "lab" in f.science and g.science_next(0) == "observatory"        # 철거 전에는 다시 짓지 않는다
    assert "exchange" in [k for k in ("exchange",) if g.lost_buildings(0, k)]
    g.complete_occupation(0, rid)                                            # 저항 중 탈환: 되살아난다
    assert rr.sci == {"lab"} and rr.econ == {"exchange"} and rr.lost_bld is None
    g.complete_occupation(1, rid)
    rr.resist["turn"] -= C.RESIST_TURNS + C.RESIST_RECOVER_TURNS
    g._phase_happiness()                                                     # 기간이 지나 철거
    assert rr.lost_bld is None and not rr.sci and "lab" not in f.science
    assert g.science_next(0) == "lab"                                        # 다시 지어야 한다


def test_harass_urgency_scales_with_opinion():
    """견제 위급도는 우호도가 낮을수록 크다."""
    from korciv import ai_endgame as EG
    vals = []
    for op in (60.0, -60.0):
        g = _p2_game(n=3)
        f = g.factions[0]
        leader = g.factions[1]
        leader.science = list(C.SCIENCE_STEPS[:6])
        leader.money = 10 ** 8
        g.dip.op[(0, 1)] = op
        vals.append(EG.watch(g, f)["urgency"])
    assert vals[1] > vals[0]


def test_suro_power_elec_and_fuel_annex():
    from korciv import ai as AI
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    assert (g.power_elec(0, "coal"), g.power_elec(0, "oil")) == (2, 4)
    _lead(g, 0, "sur")
    assert (g.power_elec(0, "coal"), g.power_elec(0, "oil")) == (3, 5)
    # 발전소 실제 변환도 +1
    rid = "S002"
    g.regions[rid].b["power"] = 1
    g.factions[0].res["coal"] = 5
    g.factions[0].res["oil"] = 0
    g.factions[0].auto_energy = True
    plan = g.energy_plan(0)
    assert plan["plants"][rid]["elec_out"] == 3
    # 편입 성향은 디버프로 줄지 않는다
    assert AI.leader_bias(g, 0, "annex") == 1.0


def test_chain_build_continues_to_max():
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    g.player.money = 1e8
    rr = g.regions["S002"]
    _room(g, [rr.id])
    lv0 = rr.b["farm"]
    ok, msg = g.start_project_max(0, "S002", "build", "farm")
    assert ok and rr.project.chain and "이어서" in msg
    for _ in range(80):
        if rr.b["farm"] >= 5 and not rr.project:
            break
        g.end_turn()
        g.player.money = 1e8
    assert rr.b["farm"] == 5 and lv0 < 5
    assert not (rr.project and rr.project.key == "farm")


def test_start_message_uses_level_names_and_unchecks_focus():
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    g.player.money = 1e8
    rr = g.regions["S002"]
    g.set_focus(0, "S002", True)
    lv = rr.b["factory"] + 1
    ok, msg = g.start_project(0, "S002", "build", "factory")
    assert ok and msg.startswith(g.build_label("S002", "factory", lv))
    assert not rr.focus


def test_small_resource_gift_still_raises_opinion():
    g = _meet_all(new_game(player_start="S002", n_enemies=2))
    g.factions[1].last["tax"] = 1e7                    # 세수가 아주 큰 나라
    for k in ("food", "specialty"):
        g.player.res.update(food=500)
        g.player.specialty = {"쌀": 5}
        g.dip.rejected.clear()
        o = D.empty_offer()
        o["give"][k] = 1
        b = D.opinion(g, 1, 0)
        assert D.respond_offer(g, 1, 0, o)[0] == "accept"
        assert D.opinion(g, 1, 0) >= b + 0.01 - 1e-9, k


# ------------------------------------------------------------------ v0.45.0 자원 흐름·계약·거래
def _mined(g, table):
    """세력별 턴당 채굴량을 고정한다."""
    orig = g.energy_mined
    g.energy_mined = lambda fid: dict(table[fid]) if fid in table else orig(fid)


def test_resources_do_not_accumulate():
    g = new_game(player_start="S002", n_enemies=1)
    _mined(g, {0: {"oil": 2, "coal": 3, "elec": 1}})
    f = g.player
    for _ in range(3):
        g.end_turn()
        assert {k: f.res[k] for k in C.ENERGY} == {"oil": 2, "coal": 3, "elec": 1}   # 이번 턴 생산량만
    f.specialty = {"쌀": 99}
    g.end_turn()
    assert sum(f.specialty.values()) == sum(g.specialty_made(f).values())             # 특산물도 쌓이지 않는다


def test_resource_trade_is_12_turn_contract():
    g = new_game(player_start="S002", n_enemies=1)
    _neutral_ai(g, 1)
    _mined(g, {0: {"oil": 0, "coal": 5, "elec": 0}, 1: {"oil": 0, "coal": 0, "elec": 0}})
    g._refresh_pools()
    offer = D.empty_offer()
    offer["give"]["coal"] = 2
    offer["take"]["money"] = 0
    offer["give"]["money"] = 0
    D.execute_offer(g, 0, 1, offer)
    cs = D.contracts_between(g, 0, 1)
    assert len(cs) == 1 and cs[0]["n"] == 2 and cs[0]["left"] == C.CONTRACT_TURNS - 1   # 이번 턴분은 바로
    assert g.player.res["coal"] == 3 and g.factions[1].res["coal"] == 2
    for _ in range(C.CONTRACT_TURNS - 1):
        g.end_turn()
        assert g.factions[1].res["coal"] == 2 and g.player.res["coal"] == 3
    g.end_turn()
    assert not D.contracts_between(g, 0, 1) and g.factions[1].res["coal"] == 0   # 12턴이 지나면 끝


def test_trade_accept_raises_both_opinions_by_count():
    g = new_game(player_start="S002", n_enemies=2)
    _neutral_ai(g, 1, 2)
    _mined(g, {1: {"oil": 0, "coal": 4, "elec": 0}})
    g._refresh_pools()
    a0, b0 = D.opinion(g, 1, 2), D.opinion(g, 2, 1)
    D.make_trade(g, 1, 2, "coal", 3, 50.0, proposer=1)
    assert D.opinion(g, 1, 2) == pytest.approx(a0 + 3) and D.opinion(g, 2, 1) == pytest.approx(b0 + 3)
    g.end_turn()                                       # 받는 턴마다 개당 50을 낸다
    assert D.contracts_between(g, 1, 2)[0]["last_q"] == 3


def test_energy_gift_opinion_uses_factory_output():
    g = new_game(player_start="S002", n_enemies=1, player_leader="cus")
    _neutral_ai(g, 1)
    _lead(g, 1, "cus")
    cap = g.factions[1].capital
    rr = g.regions[cap]
    rr.b["factory"], rr.b["power"] = 3, 0
    _mined(g, {1: {"oil": 0, "coal": 0, "elec": 0}})
    side = D.empty_offer()["give"]
    side["coal"] = 2
    # 받는 쪽 공장 3단계에 석탄 2 → 산출 2 × 1400, × 기준 세율 10% × 12턴
    assert D.gift_value(g, side, 0, 1) == pytest.approx(2 * C.FACTORY_UNIT_OUTPUT[2] * C.TAX_DEFAULT * C.CONTRACT_TURNS)
    rr.b["factory"] = 0
    assert D.gift_value(g, side, 0, 1) == 0                     # 공장이 없으면 우호도도 오르지 않는다


def test_spec_price_rises_when_unhappy():
    g = new_game(player_start="S002", n_enemies=1)
    for r in g.regions_of(0):
        r.happy = 0.0
    p0 = D.spec_price(g, 0)
    for r in g.regions_of(0):
        r.happy = -50.0
    p_low = D.spec_price(g, 0)
    for r in g.regions_of(0):
        r.happy = 50.0
    p_high = D.spec_price(g, 0)
    assert p_high < p0 < p_low and p_low == pytest.approx(p0 * math.e, rel=0.05)


def test_ai_sells_surplus_to_ai_with_factory_room():
    from korciv import ai as AI
    g = _meet_all(new_game(player_start="S002", n_enemies=2))
    _neutral_ai(g, 1, 2)
    for fid in (1, 2):
        _lead(g, fid, "cus")
        g.dip.op[(1, 2)] = g.dip.op[(2, 1)] = 10.0
    g.regions[g.factions[1].capital].b["factory"] = 0
    g.regions[g.factions[2].capital].b.update(factory=4, power=0)
    _mined(g, {1: {"oil": 0, "coal": 4, "elec": 0}, 2: {"oil": 0, "coal": 0, "elec": 0},
               0: {"oil": 0, "coal": 0, "elec": 0}})
    g._refresh_pools()
    while (g.turn + 1) % C.AI_TRADE_EVERY:
        g.turn += 1
    AI._trade_offers(g, g.factions[1])
    cs = D.contracts_between(g, 1, 2)
    assert cs and cs[0]["from"] == 1 and cs[0]["res"] == "coal" and cs[0]["price"] > g.sell_price(1, "coal")


def test_ai_trade_offer_to_player_is_queued():
    from korciv import ai as AI
    g = _meet_all(new_game(player_start="S002", n_enemies=1))
    _neutral_ai(g, 1)
    _lead(g, 1, "cus")
    g.dip.op[(1, 0)] = g.dip.op[(0, 1)] = 10.0
    g.regions[g.factions[1].capital].b["factory"] = 0
    g.regions["S002"].b.update(factory=4, power=0)
    _mined(g, {1: {"oil": 0, "coal": 4, "elec": 0}, 0: {"oil": 0, "coal": 0, "elec": 0}})
    g._refresh_pools()
    while (g.turn + 1) % C.AI_TRADE_EVERY:
        g.turn += 1
    AI._trade_offers(g, g.factions[1])
    prop = [p for p in g.pending_proposals if p["kind"] == "trade"]
    assert prop and prop[0]["sell"] and prop[0]["res"] == "coal"


def test_occ_contest_reinforcement_target():
    from korciv import ai as AI
    g, tgt, other = _contest_setup()
    g.new_army(0, tgt, {"inf": 1})
    g.begin_occupation(0, tgt)
    g.new_army(1, tgt, {"tank": 2})
    g.begin_occupation(1, tgt)
    rr = g.regions[tgt]
    rr.occs[0]["progress"] = rr.occs[1]["progress"]
    rr.occs[0]["need"] = rr.occs[1]["need"]
    imp = AI.occ_importance(g, 0, tgt)
    got = AI.occ_contests(g, 0)
    if imp >= C.AI_OCC_CONTEST_MIN:
        assert got.get(tgt) == 100 - 10 + 1                         # 상대 100 vs 나 10
    else:
        assert tgt not in got


def test_unhappy_ai_offers_to_buy_specialty_from_neighbor():
    from korciv import ai as AI
    g = _meet_all(new_game(player_start="S002", n_enemies=1))
    _neutral_ai(g, 1)
    _lead(g, 1, "cus")
    _lead(g, 0, "cus")
    nb = sorted(g.world.land_adj["S002"])[:2]
    _own(g, 1, nb)                                     # 1은 플레이어와 맞닿은 이웃
    for r in g.regions_of(1):
        r.happy, r.resist, r.supplied = -60.0, None, set()
    spec = next(x for x in g.world.order if g.world.regions[x].specialties and g.regions[x].owner == NEUTRAL)
    _own(g, 0, [spec])
    g.regions[spec].resist = None
    g.regions[spec].b["specialty"] = 3
    g.dip.op[(1, 0)] = g.dip.op[(0, 1)] = 10.0
    g.factions[1].money = 1e6
    g._refresh_pools()
    while (g.turn + 1) % C.AI_TRADE_EVERY:
        g.turn += 1
    AI._trade_offers(g, g.factions[1])
    prop = [p for p in g.pending_proposals if p["kind"] == "trade" and p["res"] == "specialty"]
    assert prop and not prop[0]["sell"]
    st = prop[0]["nego"]                                  # v1.3.0: 협상으로 — 처음 부르는 값은 유보 가격(최고가)보다 낮다
    assert st["status"] == "open" and prop[0]["price"] == st["price"] <= st["R"]
    assert st["R"] > D.spec_price(g, 1)                   # 반란 문턱이 가까우면 특산물 값보다 비싸게라도 산다


def test_surplus_food_modes():
    g = new_game(player_start="S002", n_enemies=1)
    f = g.player
    regs = g.regions_of(0)
    cons = sum(r.pop for r in regs) * C.FOOD_PER_POP
    g.food_prod = lambda fid, r: (2 * cons / len(regs)) if fid == 0 else 0.0   # 생산 = 소비 × 2
    for mode in ("store", "sell", "ration"):
        g.set_food_mode(0, mode)
        f.res["food"] = 100.0
        m0 = f.money
        g._phase_resources(f)
        if mode == "store":
            assert f.res["food"] == pytest.approx(100 + cons)
        elif mode == "sell":
            assert f.res["food"] == pytest.approx(100, abs=1) and f.money - m0 == pytest.approx(
                math.floor(cons) * 2 * g.mods(0).mult("market_sell"), rel=0.01)
        else:
            assert f.res["food"] == pytest.approx(100) and f.ration_bonus == pytest.approx(C.POP_FOCUS_GROWTH)


def _battle_setup():
    g = new_game(player_start="S002", n_enemies=1)
    _neutral_ai(g, 1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    g.new_army(1, tgt, {"inf": 2})
    D.declare_war(g, 0, 1)
    a = g.new_army(0, "S002", {"inf": 8, "tank": 2})
    return g, a, tgt


def test_player_battle_is_immediate_and_locks_army():
    g, a, tgt = _battle_setup()
    hp0 = sum(x.count() for x in g.armies_at(tgt, 1))
    ok, msg = g.attack_now(a.id, tgt, "assault")
    assert ok and "돌격" in msg
    assert sum(x.count() for x in g.armies_at(tgt, 1)) < hp0 or g.regions[tgt].owner == 0   # 턴 종료 전에 이미 싸웠다
    assert g.army_acted(a.id)
    # 이번 턴에는 합치기·분리·이동·공격 모두 불가
    assert not g.order_army(a.id, "S002")[0]
    assert g.split_army(a.id, {"inf": 1})[0] is None
    b = g.new_army(0, a.loc, {"inf": 1})
    assert not g.merge_player(b.id, a.id)[0]
    assert not g.attack_now(a.id, tgt)[0]
    g.end_turn()
    assert not g.army_acted(a.id) and not g.fought                # 다음 턴엔 다시 명령 가능


def test_ai_still_fights_at_turn_end():
    g, a, tgt = _battle_setup()
    ai_army = g.new_army(1, tgt, {"inf": 6})
    ai_army.order = {"type": "attack", "target": "S002", "mode": "assault", "path": ["S002"]}
    n0 = sum(x.count() for x in g.armies_at("S002", 0))
    g._phase_attack()                                            # AI 공격은 지금처럼 턴 종료 단계에서
    assert not g.fought and sum(x.count() for x in g.armies_at("S002", 0)) <= n0
    assert any(e["kind"] == "battle" for e in g.events)


def test_trade_needs_contact():
    g = new_game(player_start="S002", n_enemies=1)
    g.settings.fog = 1
    g.factions[0].met = set()
    g.factions[1].met = set()
    o = D.empty_offer()
    o["give"]["money"] = 10
    assert D.evaluate_offer(g, 1, 0, o)[0] == "reject"
    from korciv import ai as AI
    assert 0 not in AI.trade_partners(g, 1)


def test_diplomacy_needs_contact():
    """조우하지 않은 나라와는 선전포고·우호·비난·조약·선물 모두 불가."""
    g = new_game(meet=False, player_start="S002", n_enemies=2)
    for f in g.factions:
        f.met = set()
    assert not D.declare_war(g, 1, 0)[0] and not D.at_war(g, 0, 1)
    assert not D.friendship_check(g, 1, 0)[0]
    assert not D.denounce_check(g, 0, 1)[0]
    assert not D.treaty_check(g, 1, 0, "nonaggr")[0]
    assert D.ai_gift(g, 1, 2, 100) == 0.0
    _meet_all(g)
    assert D.declare_war(g, 1, 0)[0]
    # 동맹 자동 참전도 조우한 나라끼리만
    g2 = new_game(meet=False, player_start="S002", n_enemies=2)
    for f in g2.factions:
        f.met = set()
    g2.factions[0].met, g2.factions[1].met = {1}, {0}
    g2.dip.alliance[D.pair(1, 2)] = 0
    assert D.declare_war(g2, 0, 1)[0]
    assert not D.at_war(g2, 2, 0)


def test_eliminate_gives_victory_weariness_relief():
    g, tgt = _war_pair()
    g.player.war_weary = 50.0
    g.eliminate(1, by=0)
    assert g.player.war_weary == pytest.approx(50.0 - C.PEACE_WEARY_TERRITORY - C.PEACE_WEARY_KILLS)


def test_capture_empty_enemy_region_now():
    g, tgt = _war_pair()
    a = g.new_army(0, "S002", {"inf": 2})
    ok, msg = g.capture_now(a.id, tgt)
    assert ok and g.regions[tgt].owner == 0 and a.loc == tgt and g.army_acted(a.id)
    # 이미 행동한 부대는 다시 못 움직인다
    nxt = next(n for n in g.world.land_adj[tgt] if g.regions[n].owner == 1) if any(
        g.regions[n].owner == 1 for n in g.world.land_adj[tgt]) else None
    if nxt:
        assert not g.capture_now(a.id, nxt)[0]


def test_artillery_and_air_no_ground_combat():
    """포병·공군은 돌격·기습 공격력 0, 방어에서도 0: 포병만 있는 곳은 쉽게 떨어진다."""
    g, tgt = _war_pair()
    g.new_army(1, tgt, {"art": 3})
    att = g.new_army(0, "S002", {"art": 4})
    assert g.combat_strength(0, [att], tgt)[0] == 0
    assert g.defense_strength(0, tgt, "S002", "assault")[0] == 0
    inf = g.new_army(0, "S002", {"inf": 3})
    ok, _ = g.attack_now(inf.id, tgt, "assault")
    assert ok and not any(x.owner == 1 for x in g.armies_at(tgt))


def test_split_at_sea_keeps_land_units_with_ships():
    g = new_game(player_start="S002", n_enemies=1)
    sea = g.info("S002").seas[0] if g.info("S002").seas else next(s for s in g.world.seas)
    a = g.new_army(0, sea, {"lst": 2, "inf": 2, "dd": 1})
    assert g.split_army(a.id, {"inf": 1})[0] is None
    assert g.split_army(a.id, {"lst": 1})[0] is None
    b, _ = g.split_army(a.id, {"dd": 1})
    assert b is not None


def test_priority_pin():
    g = new_game(player_start="S002", n_enemies=1)
    from korciv.state import Project
    rids = [r.id for r in g.regions_of(0)][:1] + sorted(g.world.land_adj["S002"])[:2]
    _own(g, 0, rids)
    for i, rid in enumerate(rids):
        g.regions[rid].project = Project(kind="build", key="farm", level=1, per_turn=10, turns=3, priority=i + 1)
    last = rids[-1]
    assert g.toggle_pin(0, last)
    assert g.projects_by_priority(0)[0].id == last
    g.sort_priority(0, "short")
    assert g.projects_by_priority(0)[0].id == last
    g.set_priority_order(0, rids)                     # 끌어서 바꿔도 고정한 작업이 맨 위
    assert g.projects_by_priority(0)[0].id == last
    assert not g.toggle_pin(0, last)


def test_econ_need_majority_when_few_nations():
    g = new_game(player_start="S002", n_enemies=3)
    assert g.econ_need(0, C.ECON_CURRENCY_FRIENDS) == 2      # 다른 나라 3 → 과반 2
    g2 = new_game(player_start="S002", n_enemies=6)
    assert g2.econ_need(0, C.ECON_CURRENCY_FRIENDS) == C.ECON_CURRENCY_FRIENDS


def test_building_total_for_maxed_buildings():
    g = new_game(player_start="S002", n_enemies=1)
    rr = g.regions["S002"]
    rr.b["bank"] = C.PROD_BUILDINGS["bank"]["max"]
    assert "산출" in g.building_total(0, "S002", "bank")
    assert not any(o["kind"] == "build" and o["key"] == "bank" for o in g.options(0, "S002"))


def test_friendship_declaration_opinion_per_turn_during_cooldown():
    """우호 선언 뒤 쿨타임 12턴 동안 서로 매 턴 우호도 +0.1, 그 뒤에는 없다."""
    g = new_game(player_start="S002", n_enemies=2)
    _neutral_ai(g, 1, 2)
    for x, y in ((1, 2), (2, 1)):
        g.dip.op[(x, y)] = D.op_baseline(g, x, y)
    assert D.declare_friendship(g, 1, 2)[0]
    import copy
    ref = copy.deepcopy(g)
    _dc = D._dip_attr(ref, "declared")
    _dc.clear()                                       # 선언이 없는 같은 상태와 비교
    D.update_turn(g)
    D.update_turn(ref)
    for x, y in ((1, 2), (2, 1)):
        assert D.opinion(g, x, y) - D.opinion(ref, x, y) == pytest.approx(C.DECL_FRIEND_TURN * C.OPINION_DECAY)
    g.turn += C.DECL_FRIEND_COOLDOWN
    ref = copy.deepcopy(g)
    D._dip_attr(ref, "declared").clear()
    D.update_turn(g)
    D.update_turn(ref)
    assert D.opinion(g, 1, 2) == pytest.approx(D.opinion(ref, 1, 2))


def test_land_grab_only_for_neutral_land_and_halved():
    """영토 경쟁(−1)은 중립 땅을 먼저 차지할 때만. 전쟁으로 빼앗은 땅은 해당 없음."""
    g = new_game(player_start="S002", n_enemies=2)
    _neutral_ai(g, 1, 2)
    w = g.world
    rid = next(n for n in sorted(w.land_adj["S002"]) if g.regions[n].owner == NEUTRAL)
    side = next(n for n in sorted(w.land_adj[rid]) if n != "S002" and g.regions[n].owner == NEUTRAL)
    _own(g, 1, [side])
    before = D.opinion(g, 1, 0)
    g.transfer_region(rid, 0)                         # 중립 땅: 영토 경쟁
    assert D.opinion(g, 1, 0) == pytest.approx(before + C.OP_LAND_GRAB) and C.OP_LAND_GRAB == -1
    _own(g, 2, [rid])
    D.declare_war(g, 0, 2)
    before = D.opinion(g, 1, 0)
    g.transfer_region(rid, 0)                         # 전쟁으로 빼앗은 땅: 해당 없음
    assert D.opinion(g, 1, 0) == pytest.approx(before)


def test_ai_does_not_join_annex_rival_ahead():
    from korciv import ai
    g = new_game(player_start="S002", n_enemies=1)
    rid = next(n for n in sorted(g.world.land_adj["S002"]) if g.regions[n].owner == NEUTRAL)
    assert not g.rival_ahead(1, rid)
    g.regions[rid].occs[0] = {"by": 0, "progress": 2, "need": 6, "seq": 1}
    assert g.rival_ahead(1, rid) and not g.rival_ahead(0, rid)
    g.regions[rid].occs[1] = {"by": 1, "progress": 3, "need": 6, "seq": 2}
    assert not g.rival_ahead(1, rid) and g.rival_ahead(0, rid)


def test_power_plant_level_rates_and_national_floor():
    """발전소 석탄 1개당 전기: 단계별 2·2.2·2.4·2.6·3, 석유는 두 배. 발전소별 소수점을 합친 뒤 버린다."""
    g = new_game(player_start="S002", n_enemies=1)
    for lv, e in zip(range(1, 6), (2, 2.2, 2.4, 2.6, 3)):
        assert g.power_elec(0, "coal", lv) == pytest.approx(e)
        assert g.power_elec(0, "oil", lv) == pytest.approx(2 * e)
    near = sorted(g.world.land_adj["S002"])[:1]
    _own(g, 0, near)
    for rid in ["S002"] + near:
        g.regions[rid].resist = None
        g.regions[rid].b["power"] = 2
    f = g.player
    f.auto_energy = True
    f.res.update(coal=2, oil=0, elec=0)              # 두 발전소에 석탄 1개씩: 2.2 + 2.2 = 4.4 → 4
    plan = g.energy_plan(0)
    assert plan["elec_gen"] == pytest.approx(4.4) and plan["elec_gen_int"] == 4
    assert g.elec_from_fuel(0, 0, 2) == (4, 0, 2)


def test_friendship_suppresses_ai_war_then_expires():
    """우호 선언 직후 그 나라에 선전포고할 확률 100% 감소 → 12턴째 약 50%, 12턴이 지나면 감소 없음."""
    g = new_game(player_start="S002", n_enemies=2)
    _neutral_ai(g, 1, 2)
    assert D.friend_war_block(g, 1, 2) == 0.0
    assert D.declare_friendship(g, 1, 2)[0]
    assert D.friend_war_block(g, 1, 2) == pytest.approx(1.0)
    vals = []
    for _ in range(C.DECL_FRIEND_COOLDOWN):
        vals.append(D.friend_war_block(g, 1, 2))
        g.turn += 1
    assert all(a > b for a, b in zip(vals, vals[1:])) and 0.5 < vals[-1] < 0.55
    assert D.friend_war_block(g, 1, 2) == 0.0
    from korciv import ai
    g.turn -= C.DECL_FRIEND_COOLDOWN
    assert all(ai._friend_blocks(g, 1, 2) for _ in range(20))     # 직후에는 언제나 막는다


def test_ai_front_spreads_along_war_border():
    """전쟁 중 AI: 전선 칸마다 최소 1, 후방 큰 부대는 모자란 전선 칸으로 나눠 보낸다."""
    from korciv import ai
    g = _p2_game()
    w = g.world
    cap = g.factions[0].capital
    near = sorted(w.land_adj[cap])
    _own(g, 0, near[:2])
    for n in near[:2]:                                   # 수도와는 맞닿지 않은 칸을 적에게(수도는 후방)
        _own(g, 1, [x for x in sorted(w.land_adj[n]) if g.regions[x].owner == NEUTRAL
                    and x != cap and x not in w.land_adj[cap]][:1])
    D.declare_war(g, 0, 1)
    front = ai.war_front(g, 0)
    assert len(front) >= 2
    need = ai.front_need(g, 0, front, 3 * len(front))
    assert all(need[c] >= 1 for c in front)
    small = ai.front_need(g, 0, front, 1)
    assert sum(small.values()) == 1
    # 후방의 큰 부대 하나는 모자란 전선 칸마다 나뉘어 간다
    for a in [a for a in g.armies.values() if a.owner == 0 or a.loc in front]:
        g.remove_army(a)
    rear = cap
    assert rear not in front
    big = g.new_army(0, rear, {"inf": 2 * len(front) + 2})
    need = ai.front_need(g, 0, front, ai._front_count(big))
    cover = {}
    assert ai._fill_front(g, 0, big, set(front), need, cover)
    sent = [a for a in g.armies.values() if a.owner == 0 and (a.order or a.goto)]
    assert len(sent) >= 2                               # 한 덩어리로 가지 않는다


def test_incheon_ongjin_no_island_bonus():
    """인천 옹진은 연륙 섬: 시작해도 상륙함·항구 보너스 없음."""
    rid = next(r for r, i in new_game().world.regions.items() if i.name == "인천 옹진")
    g = new_game(player_start=rid, n_enemies=2)
    assert g.player.capital == rid
    assert not any(a.units.get("lst") for a in g.armies_at(rid, 0)) and not g.regions[rid].b["port"]
    assert g.region_value(rid)[0] < 6 and g.region_value(g.world.name_to_id["황남 옹진군"])[0] < 6


def test_sea_fishery_food_bonus_and_river_nerf():
    """바다 어장은 단계당 식량 15·산출 150, 하천 어장은 ×0.8(12·120)."""
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    sea = next(r for r in w.order if w.regions[r].coastal)
    river = next(r for r in w.order if not w.regions[r].coastal and r in w.river_regions)
    _own(g, 0, [sea, river])
    assert g.fish_food_mult(0, sea) == pytest.approx(g.fish_mult(0, sea))
    assert g.fish_food_mult(0, river) == pytest.approx(C.RIVER_FISH_MULT)
    for rid in (sea, river):
        g.regions[rid].b["farm"], g.regions[rid].b["fishery"] = 0, 2
    assert g.food_prod(0, g.regions[sea]) == pytest.approx(15 * 2 * g.fish_mult(0, sea))
    assert g.food_prod(0, g.regions[river]) == pytest.approx(12 * 2)


def test_neutral_garrison_by_population_and_annex_gives_one():
    from korciv.game import neutral_garrison
    # 인구 20만 이하 1, 40만 이하 2, 60만 이하 3 …(v1.3.0, 올림)
    assert [neutral_garrison(p) for p in (0, 3, 15, 20, 20.1, 29, 31, 40, 40.5, 60, 120)] == \
        [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 8]
    g = new_game(player_start="S002", n_enemies=1)
    big = max((r for r in g.world.order if g.regions[r].owner == NEUTRAL), key=lambda r: g.world.regions[r].pop0)
    gar = [a for a in g.armies_at(big) if a.owner == NEUTRAL]
    assert gar[0].units["inf"] == neutral_garrison(g.world.regions[big].pop0) > 1
    g._take_garrison(big, 0)                              # 편입: 보병 1만 넘겨받는다
    assert [a.units for a in g.armies_at(big)] == [{"inf": 1}] and g.armies_at(big)[0].owner == 0
    assert [a.units for a in g.armies_at("S002", 0)] == [{"inf": 1}]   # 시작 지역도 보병 1


def test_route_through_unowned_land_one_step_per_turn():
    """영토 밖(빈 중립 땅)도 여러 턴 자동 이동: 영토 밖에서는 턴당 1칸."""
    g = new_game(player_start="S002", n_enemies=1)
    for a in [a for a in g.armies.values() if a.owner == NEUTRAL]:
        g.remove_army(a)
    w = g.world
    n1 = next(n for n in sorted(w.land_adj["S002"]) if g.regions[n].owner == NEUTRAL)
    n2 = next(n for n in sorted(w.land_adj[n1]) if g.regions[n].owner == NEUTRAL and n not in w.land_adj["S002"]
              and n != "S002")
    n3 = next(n for n in sorted(w.land_adj[n2]) if g.regions[n].owner == NEUTRAL
              and n not in w.land_adj[n1] and n not in (n1, "S002"))
    a = g.new_army(0, n1, {"inf": 2})
    assert g.plan_route(a, n3) is not None
    ok, _ = g.order_army(a.id, n3)
    assert ok and a.goto == n3 and len(a.order["path"]) == 1          # 영토 밖에서는 이번 턴 한 칸
    assert a.order["path"][0] in w.land_adj[n1] and a.order["path"][0] != n3


def test_unit_batch_production_repeats():
    """군 유닛 n개 연속 생산: 하나가 완성되면 다음 것을 바로 착수, 다 만들면 멈춘다."""
    g = new_game(player_start="S002", n_enemies=1)
    f = g.player
    f.money = 10_000_000
    ok, msg = g.start_units(0, "S002", "inf", 3)
    assert ok and g.regions["S002"].project.repeat == 2
    before = sum(a.units.get("inf", 0) for a in g.armies_at("S002", 0))
    for _ in range(40):
        g.pending_proposals.clear()
        g.pending_rebellions.clear()
        g.end_turn()
        if not g.regions["S002"].project:
            break
    assert sum(a.units.get("inf", 0) for a in g.armies_at("S002", 0)) == before + 3
    assert g.regions["S002"].project is None


def test_rally_within_n_cells():
    """n칸 이내 병력 집결: 육상 n칸 안의 내 육군을 이 지역으로(멀면 자동 이동), 범위 밖·공격 중 부대는 빼고."""
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    ring1 = sorted(w.land_adj["S002"])[:2]
    _own(g, 0, ring1)
    far = next(n for n in sorted(w.land_adj[ring1[0]]) if n != "S002" and n not in w.land_adj["S002"])
    _own(g, 0, [far])
    for a in [a for a in g.armies.values() if a.loc in ring1 + [far]]:
        g.remove_army(a)
    a1 = g.new_army(0, ring1[0], {"inf": 2})
    a2 = g.new_army(0, ring1[1], {"tank": 1})
    a3 = g.new_army(0, far, {"inf": 1})
    assert {a.id for a in g.rally_candidates(0, "S002", 1)} == {a1.id, a2.id}
    k, u = g.rally(0, "S002", 2)
    assert k == 3 and u == 4
    # v1.3.0: 플레이어 집결은 바로 움직인다(자국 영토 2칸 안이라 모두 이번 턴에 도착)
    assert all(a.loc == "S002" and not a.order and g.army_acted(a.id) for a in (a1, a2, a3))


def test_coalition_peace_does_not_drag_player_in():
    """연합 회원(AI)이 강화해도 플레이어는 끌려 들어가지 않는다: 상대가 강화를 제안하고 플레이어가 고른다."""
    g = new_game(player_start="S002", n_enemies=3)
    _neutral_ai(g, 1, 2, 3)
    g.dip.coalitions[1] = {"members": {0, 1}, "since": 0}
    D.declare_war(g, 3, 0)
    assert D.at_war(g, 0, 3) and D.at_war(g, 1, 3)
    g.pending_proposals.clear()
    D.make_peace(g, 1, 3)
    assert not D.at_war(g, 1, 3) and D.at_war(g, 0, 3)
    assert g.pending_proposals == [{"from": 3, "kind": "peace"}]
    D.sign_treaty(g, 3, 0, "peace")                 # 플레이어가 수락하면 그때 강화
    assert not D.at_war(g, 0, 3)


def test_peace_cancels_orders_into_former_enemy_and_evicts():
    """강화하면 상대 땅으로 가던 명령은 취소되고, 남은 명령·옛 세이브로 남은 부대도 그 땅에 머물지 못한다."""
    g = new_game(player_start="S002", n_enemies=1)
    _neutral_ai(g, 1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    D.declare_war(g, 0, 1)
    a = g.new_army(0, "S002", {"inf": 2})
    ok, _ = g.order_army(a.id, tgt)                     # 빈 적 땅으로 이동 명령
    assert ok and a.order
    D.make_peace(g, 0, 1)                               # 플레이어가 강화를 수락
    assert a.order is None
    a.order = {"type": "move", "path": [tgt]}            # 남은 명령이 있어도
    g._exec_move(a, [tgt])
    assert a.loc == "S002"                              # 들어가지 않는다
    a.loc = tgt                                          # 이미 들어가 있던 부대(옛 세이브)
    g.evict_trespassers()
    assert g.regions[a.loc].owner == 0


def test_river_farm_bonus():
    """농장은 단계당 식량 12·산출 120, 하천에 맞닿은 지역의 농장은 15·150."""
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    riv = next(r for r in w.order if r in w.river_regions and g.regions[r].owner == NEUTRAL)
    dry = next(r for r in w.order if r not in w.river_regions and g.regions[r].owner == NEUTRAL)
    _own(g, 0, [riv, dry])
    for rid in (riv, dry):
        g.regions[rid].b.update(farm=3, fishery=0)
    assert g.food_prod(0, g.regions[riv]) == pytest.approx(15 * 3)
    assert g.food_prod(0, g.regions[dry]) == pytest.approx(12 * 3)
    assert g.farm_mult(0, riv) == pytest.approx(1.25) and g.farm_mult(0, dry) == pytest.approx(1.0)
    assert R.region_output(0, 1, 0, 0, 0, farm_mult=g.farm_mult(0, riv)) == pytest.approx(150)
    assert R.region_output(0, 1, 0, 0, 0) == pytest.approx(120)
    assert R.region_output(0, 0, 1, 0, 0) == pytest.approx(150)
    assert R.region_output(0, 0, 1, 0, 0, fish_mult=C.RIVER_FISH_MULT) == pytest.approx(120)


def _port_fleet(g, units):
    """중립 해안 지역 하나를 플레이어 땅(항구)으로 만들고 그곳에 함대를 둔다."""
    coast = next(r for r in g.world.order if g.world.regions[r].coastal and g.regions[r].owner == NEUTRAL)
    _own(g, 0, [coast])
    g.regions[coast].b["port"] = 1
    for a in list(g.armies_at(coast)):
        g.remove_army(a)
    return g.new_army(0, coast, units)


def test_split_fleet_keeps_cargo_within_capacity():
    """QA: 짐을 실은 함대에서 상륙함·항모를 떼면 실린 유닛이 사라지거나, 구축함이 상륙함 없이 보병을 싣고 가면 안 된다."""
    g = new_game(player_start="S002", n_enemies=1)
    fl = _port_fleet(g, {"lst": 1, "dd": 1, "inf": 4})
    b, msg = g.split_army(fl.id, {"lst": 1})                 # 남는 쪽(구축함+보병)이 실을 칸이 없다
    assert b is None and msg and fl.units == {"lst": 1, "dd": 1, "inf": 4}
    b, msg = g.split_army(fl.id, {"dd": 1, "inf": 4})        # 떼어 낸 쪽(구축함+보병)이 실을 칸이 없다
    assert b is None and msg and fl.units == {"lst": 1, "dd": 1, "inf": 4}
    b, _ = g.split_army(fl.id, {"inf": 4})                   # 항구에서 하역은 된다
    assert b is not None and b.units == {"inf": 4} and fl.units == {"lst": 1, "dd": 1}
    cv = _port_fleet(g, {"cv": 1, "dd": 1, "ftr": 3})
    b, msg = g.split_army(cv.id, {"cv": 1})                  # 항모를 떼면 구축함에 전투기가 남는다
    assert b is None and cv.units == {"cv": 1, "dd": 1, "ftr": 3}


def test_suppress_loss_keeps_damage_within_hp():
    """QA: 반란 진압 성공으로 병력이 줄면 피해 기록도 함께 줄어 남은 유닛 최대 체력을 넘지 않는다."""
    import random
    for s in range(12):
        g = new_game(player_start="S002", n_enemies=1)
        rid = g.player.capital
        for a in list(g.armies_at(rid, 0)):
            g.remove_army(a)
        a = g.new_army(0, rid, {"inf": 3})
        a.dmg = {"inf": 25.0}
        g.rng = random.Random(s)
        g.suppress_chance = lambda fid, r: 1.0
        g.pending_rebellions.append(rid)
        g.resolve_rebellion(0, rid, "suppress")
        if a.id in g.armies:
            assert a.dmg.get("inf", 0) <= a.hp_max("inf") + 1e-9


def test_specialty_pin_over_limit_keeps_previous_state():
    """QA: 고정이 최대 종류 수에 막히면 그 종류의 기존 '제외' 상태를 지우지 않는다."""
    g = new_game(player_start="S002", n_enemies=1)
    rid = g.player.capital
    for i in range(C.SPECIALTY_MAX_TYPES):
        assert g.set_specialty(0, rid, f"k{i}", "pin")[0]
    g.set_specialty(0, rid, "x", "block")
    ok, _ = g.set_specialty(0, rid, "x", "pin")
    assert not ok and "x" in g.regions[rid].spec_block


def _conquest_ready(n_enemies=2):
    g = new_game(player_start="S002", n_enemies=n_enemies)
    need = math.ceil(len(g.regions) * C.CONQUEST_SHARE)
    free = [r for r in g.world.order if g.regions[r].owner == NEUTRAL][:need]
    _own(g, 0, free)
    for r in g.regions_of(0):
        r.happy, r.resist = 0.0, None
    return g


def test_conquest_victory_waits_for_peace():
    """v1.3.0: 정복승리 조건을 채워도 전쟁 중이면 불발, 강화로 전쟁이 끝나는 순간 승리."""
    g = _conquest_ready()
    for b in (1, 2):
        g.dip.wars.pop(D.pair(0, b), None)
    D.declare_war(g, 1, 0)
    D.declare_war(g, 2, 0)
    st = g.conquest_status(0)
    assert st["met"] and st["wars"] == 2 and not st["ok"]
    g._check_victory()
    assert not g.game_over
    D.make_peace(g, 0, 1)
    assert not g.game_over                          # 아직 2와 전쟁 중
    D.make_peace(g, 0, 2)
    assert g.game_over and g.winner == ((0,), "conquest")
    # 다른 나라끼리의 전쟁은 상관없다
    g = _conquest_ready()
    for a, b in ((0, 1), (0, 2), (1, 2)):
        g.dip.wars.pop(D.pair(a, b), None)
    D.declare_war(g, 1, 2)
    assert g.conquest_status(0)["ok"]
    g._check_victory()
    assert g.winner == ((0,), "conquest")


def test_ai_peace_desire_around_conquest_ready():
    """조건을 채운 AI는 강화를 서두르고(강화하면 승리), 그 상대 AI는 강화를 꺼린다(강화해 주면 상대가 승리)."""
    from korciv import ai as AI
    g = _conquest_ready(n_enemies=2)
    for b in (1, 2):
        g.dip.wars.pop(D.pair(0, b), None)
    D.declare_war(g, 1, 0)
    a1 = AI.war_assessment(g, 1, 0)
    assert "강화하면 상대가 정복승리" in a1["con"]
    g.settings.victories = tuple(v for v in g.settings.victories if v != "conquest")
    a1_off = AI.war_assessment(g, 1, 0)
    assert a1_off["desire"] == pytest.approx(a1["desire"] + C.AI_CONQ_DENY_PEACE)
    g.settings.victories = tuple(g.settings.victories) + ("conquest",)
    # 0 을 AI 로 보면 강화 욕구가 크게 오른다
    g.factions[0].is_ai = True
    a0 = AI.war_assessment(g, 0, 1)
    assert a0["pro"][0] == "강화하면 정복승리"
    g.settings.victories = tuple(v for v in g.settings.victories if v != "conquest")
    assert AI.war_assessment(g, 0, 1)["desire"] == pytest.approx(a0["desire"] - C.AI_CONQ_READY_PEACE)


def test_science_steps_hidden_when_science_victory_off():
    """QA: 과학승리를 끈 판에서는 과학 단계를 지을 수 없다(경제승리를 끄면 경제 단계가 숨는 것과 같게)."""
    g = Game(Settings(seed=5, n_enemies=1, player_start="S002", victories=("conquest", "time")))
    g.set_player_government("presidential")
    assert not [o for o in g.options(0, "S002") if o["kind"] == "science"]
    g = Game(Settings(seed=5, n_enemies=1, player_start="S002"))
    g.set_player_government("presidential")
    assert [o for o in g.options(0, "S002") if o["kind"] == "science"]


def test_victory_checked_after_turn_start_rebellion(monkeypatch):
    """리뷰 M-02: 턴 시작 반란으로 마지막 상대가 사라지면(세력 수 한도 → 중립) 그 턴에 바로 정복승리."""
    from korciv import ai as AI
    g = new_game(player_start="S002", n_enemies=1)
    monkeypatch.setattr(C, "MAX_FACTIONS", len(g.factions))
    for rid in [r.id for r in g.regions_of(1)][1:]:
        g.transfer_region(rid, NEUTRAL)
    last = g.regions_of(1)[0]
    last.happy = -200
    for a in list(g.armies_at(last.id, 1)):
        g.remove_army(a)
    g.rebellion_chance = lambda fid, rid: 1.0 if fid == 1 else 0.0
    g.suppress_chance = lambda fid, rid: 0.0
    monkeypatch.setattr(AI, "handle_rebellion", lambda g_, fid, rid: g_.resolve_rebellion(fid, rid, "suppress"))
    g.pending_proposals.clear()
    g.end_turn()
    assert g.alive_ids() == [0]
    assert g.game_over and g.winner == ((0,), "conquest")


def test_time_victory_turn_unchanged():
    """리뷰 M-02 회귀: 반란 뒤 다시 하는 승리 판정은 시간 종료를 앞당기지 않는다(max_turns 턴을 마칠 때 승리)."""
    g = new_game(n_enemies=2, max_turns=5, victories=("time",))
    for _ in range(4):
        g.pending_proposals.clear()
        g.pending_rebellions.clear()
        g.end_turn()
    assert not g.game_over and g.turn == 5
    g.pending_proposals.clear()
    g.pending_rebellions.clear()
    g.end_turn()
    assert g.game_over and g.winner[1] == "time" and g.turn == 6


# ---------------------------------------------------------------- v1.3.0: 수송·공군·체력 비례·즉시 실행
def _clear(g, *rids):
    for r in rids:
        for a in list(g.armies_at(r)):
            g.remove_army(a)


def test_cargo_load_unload_at_port():
    """상륙함 [승선]·[하선]: 부대 합치기와 따로, 칸만큼만 싣고(무거운 것부터) 피해 기록도 함께 옮긴다."""
    g = new_game(player_start="S002", n_enemies=1)
    port = g.world.name_to_id["부산 중구"]
    _own(g, 0, [port])
    g.regions[port].b["port"] = 1
    _clear(g, port)
    fl = g.new_army(0, port, {"lst": 1, "dd": 1})
    land = g.new_army(0, port, {"inf": 4, "tank": 2})
    land.dmg = {"tank": 25.0}                                   # 전차 2대 중 반 대 몫 피해
    assert not g.merge_player(fl.id, land.id)[0]                # 합치기로는 싣지 않는다
    took, msg = g.load_cargo(fl.id, land.id)
    assert took == {"tank": 2} and fl.cargo_used() == 8 and "승선" in msg   # 칸 8: 전차 2(4칸씩)만
    assert land.units == {"inf": 4} and fl.dmg.get("tank") == pytest.approx(25.0)
    made, msg = g.unload_cargo(fl.id, {"tank": 1})
    assert made and made[0].loc == port and made[0].units == {"tank": 1} and "하선" in msg
    assert fl.units == {"lst": 1, "dd": 1, "tank": 1}
    assert not g.army_acted(made[0].id)                         # 움직이지 않은 함대에서 항구에 내리면 바로 움직일 수 있다


def test_cargo_landing_from_sea():
    """바다에서 [하선]: 맞닿은 내 해안에 상륙, 빈 적 땅은 점령 시작. 상륙한 병력은 이번 턴 더 움직이지 못한다."""
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    sea = next(s for s in w.seas if len(w.seas[s].coast) >= 3)
    coast = sorted(w.seas[sea].coast)
    mine, empty_enemy = coast[0], coast[1]
    _own(g, 0, [mine])
    g.transfer_region(empty_enemy, 1)
    _clear(g, mine, empty_enemy)
    D.declare_war(g, 0, 1)
    fl = g.new_army(0, sea, {"lst": 1, "inf": 3})
    t = g.landing_targets(fl)
    assert t.get(mine) == "land" and t.get(empty_enemy) == "capture"
    made, _ = g.unload_cargo(fl.id, {"inf": 1}, mine)
    assert made[0].loc == mine and g.army_acted(made[0].id) and g.army_acted(fl.id)
    made, msg = g.unload_cargo(fl.id, None, empty_enemy)   # 이번 턴 이미 상륙한 함대 → 빈 적 땅 상륙은 다음 턴
    assert not made
    g.moved = set()
    made, msg = g.unload_cargo(fl.id, None, empty_enemy)
    assert made and made[0].loc == empty_enemy
    assert g.regions[empty_enemy].owner == 0 or 0 in g.regions[empty_enemy].occs


def test_carrier_aircraft_only_unload_at_port():
    """함재기: 항구에 정박했을 때만 [이함]해 육상으로 내린다."""
    g = new_game(player_start="S002", n_enemies=1)
    port = g.world.name_to_id["부산 중구"]
    _own(g, 0, [port])
    g.regions[port].b["port"] = 1
    _clear(g, port)
    cv = g.new_army(0, port, {"cv": 1})
    air = g.new_army(0, port, {"ftr": 2, "bmb": 1})
    took, msg = g.load_cargo(cv.id, air.id)
    assert took == {"ftr": 2, "bmb": 1} and "탑재" in msg and air.id not in g.armies
    sea = g.world.regions[port].seas[0]
    cv.loc = sea
    made, msg = g.unload_cargo(cv.id, {"ftr": 1})
    assert not made and "항구" in msg
    cv.loc = port
    made, msg = g.unload_cargo(cv.id, {"ftr": 1})
    assert made and made[0].domain() == "air" and made[0].loc == port and "이함" in msg


def test_air_units_rules():
    """공군: 어디서든 생산, 한 칸씩 이동(공항에서는 다른 공항으로 한 번에, 통행권 나라 공항 포함), 폭격·요격은 공항에서만."""
    g = new_game(player_start="S002", n_enemies=2)
    w = g.world
    g.player.res["oil"] = 10
    assert any(o["kind"] == "unit" and o["key"] == "ftr" and o["ok"] for o in g.options(0, "S002"))   # 공항 없이 생산
    near = sorted(w.land_adj["S002"])
    _own(g, 0, near)
    _clear(g, "S002", *near)
    a = g.new_army(0, "S002", {"bmb": 2})
    reach = g.reachable(a)
    assert all(v in w.land_adj["S002"] for v, o in reach.items() if o["action"] == "move")   # 공항이 없으면 한 칸씩
    assert not any(o["action"] == "bombard" for o in reach.values())
    far = next(r for r in w.order if g.regions[r].owner == 1)
    g.regions["S002"].b["airport"] = 1
    g.regions[far].b["airport"] = 1
    assert far not in g.reachable(a)                           # 통행권이 없는 나라 공항은 안 된다
    g.dip.passage[D.pair(0, 1)] = g.turn + 10
    assert g.reachable(a).get(far, {}).get("action") == "move"   # 통행권이 있으면 그 나라 공항으로 한 번에
    D.declare_war(g, 0, 2)
    tgt = next(v for v in g.land_within("S002", 2) if g.regions[v].owner not in (0, 1))
    g.transfer_region(tgt, 2)
    assert g.reachable(a).get(tgt, {}).get("action") == "bombard"   # 공항에서는 폭격 가능
    ok, msg = g.act_now(a.id, near[0])
    assert ok and a.loc == near[0] and g.army_acted(a.id)
    g.moved = set()
    assert not any(o["action"] == "bombard" for o in g.reachable(a).values())   # 공항 없는 곳에서는 폭격 불가


def test_combat_strength_scales_with_remaining_hp():
    """전투력은 남은 체력에 비례: 체력이 절반 남은 보병은 같은 조건에서 피해도 절반."""
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    g.transfer_region(tgt, 1)
    _clear(g, tgt)
    D.declare_war(g, 0, 1)
    full = g.new_army(0, "S002", {"inf": 1})
    half = g.new_army(0, "S002", {"inf": 1})
    half.dmg = {"inf": 5.0}
    a_full = g.combat_strength(0, [full], tgt)[0]
    a_half = g.combat_strength(0, [half], tgt)[0]
    assert a_half == pytest.approx(a_full / 2)
    d1 = g.new_army(1, tgt, {"inf": 2})
    d_full = g.defense_strength(0, tgt, None, "surprise")[0]
    d1.dmg = {"inf": 10.0}                                      # 2대 중 1대 몫 피해 → 방어력 절반
    assert g.defense_strength(0, tgt, None, "surprise")[0] == pytest.approx(d_full / 2)
    s1 = g.new_army(0, "S002", {"dd": 1})
    p_full = g._naval_power(0, [s1], next(iter(g.world.seas)))
    s1.dmg = {"dd": 25.0}
    assert g._naval_power(0, [s1], next(iter(g.world.seas))) == pytest.approx(p_full / 2)


def test_act_now_moves_immediately_and_once_per_turn():
    """플레이어 명령은 바로 실행: 이동·빈 적 땅 점령·폭격. 한 턴에 한 번, 움직인 부대도 합치기·분리는 된다."""
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    near = sorted(w.land_adj["S002"])
    _own(g, 0, near[:1])
    _clear(g, "S002", *near)
    a = g.new_army(0, "S002", {"inf": 4})
    ok, msg = g.act_now(a.id, near[0])
    assert ok and a.loc == near[0] and not a.order and g.army_acted(a.id)
    assert not g.act_now(a.id, "S002")[0]                      # 이번 턴 두 번째 이동은 불가
    b, _ = g.split_army(a.id, {"inf": 2})                       # 움직인 부대도 나눌 수 있고, 나눈 쪽도 더 못 움직인다
    assert b and g.army_acted(b.id)
    c = g.new_army(0, near[0], {"inf": 1})
    ok, msg = g.merge_player(c.id, a.id)                        # v1.3.0: 움직인 부대는 이번 턴 합칠 수 없다
    assert not ok and "행동" in msg and not g.mergeable(c, a)
    # 병력 없는 적 땅: 바로 들어가 점령
    enemy = near[1]
    g.transfer_region(enemy, 1)
    _clear(g, enemy)
    D.declare_war(g, 0, 1)
    d = g.new_army(0, "S002", {"inf": 2})
    ok, msg = g.act_now(d.id, enemy)
    assert ok and d.loc == enemy and (g.regions[enemy].owner == 0 or 0 in g.regions[enemy].occs)
    # 적 병력이 있으면 바로 싸우지 않는다(전투 확인 창으로)
    e = g.new_army(1, near[2], {"inf": 1})
    g.transfer_region(near[2], 1)
    f = g.new_army(0, "S002", {"inf": 2})
    ok, msg = g.act_now(f.id, near[2])
    assert not ok and f.loc == "S002" and not g.army_acted(f.id) and e.id in g.armies
    # 포병 폭격도 바로
    art = g.new_army(0, "S002", {"art": 2})
    hp0 = e.hp_left("inf")
    ok, msg = g.act_now(art.id, near[2], force_bombard=True)
    assert ok and g.army_acted(art.id) and (e.id not in g.armies or e.hp_left("inf") < hp0)
    g.end_turn()
    assert not g.army_acted(a.id)                              # 다음 턴에는 다시 움직인다


def _path_to(prev, r):
    out = []
    while prev[r] is not None:
        out.append(r)
        r = prev[r]
    return out[::-1]


def test_player_goto_continues_at_turn_start():
    """한 턴에 못 가는 곳: 첫 구간은 바로, 다음 구간은 다음 턴이 시작될 때 바로 간다(턴 종료 때가 아니라)."""
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    from collections import deque
    prev, q = {"S002": None}, deque(["S002"])                  # 육상 최단 경로 6칸
    while q:
        u = q.popleft()
        for v in sorted(w.land_adj[u]):
            if v not in prev:
                prev[v] = u
                q.append(v)
    far = next(r for r in w.order if r in prev and len(_path_to(prev, r)) == 6)
    route = _path_to(prev, far)
    _own(g, 0, route)                                           # 길 전체를 내 땅으로(중립 수비대를 피해)
    _clear(g, "S002", *route)
    a = g.new_army(0, "S002", {"inf": 1})
    ok, msg = g.act_now(a.id, far)
    assert ok and a.goto == far and a.loc != "S002" and g.army_acted(a.id)
    loc1 = a.loc
    g.pending_proposals.clear()
    g.end_turn()
    assert a.loc != loc1 and g.army_acted(a.id)                # 턴 시작에 바로 다음 구간


# ---- v1.3.0: QA 후속 수정
def test_energy_reassigned_every_turn_start():
    """[매 턴 자동 배정](기본 켜짐): 턴이 시작될 때 [자동 배정]을 다시 해 새 공장에도 연료가 들어간다."""
    g, r, f = _energy_setup()
    assert f.energy_each_turn
    r.b["factory"], r.b["power"] = 0, 0
    g.assign_energy(0)
    g.energy_supply = lambda fid: {"coal": 4, "oil": 0, "elec": 0}
    r.b["factory"] = 2                                         # 새로 지은 공장
    assert not (r.energy or {}).get("f")
    g._auto_assign_energy()
    assert r.energy["f"]["coal"] == 2
    # 끄면 배정은 그대로 두고, 새 공장·발전소가 생기면 알려 준다
    f.energy_each_turn = False
    r.energy = {}
    g._auto_assign_energy()
    assert r.energy == {}
    n0 = len(g.events)
    r.b["power"] = 1
    g._auto_assign_energy()
    assert r.energy == {} and any("연료를 배정" in e["text"] for e in g.events[n0:])


def test_cancel_unit_refunds_happiness_not_oil():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    g.player.money = 10 ** 6
    g.player.res["oil"] = 10
    r.project = None
    h0 = r.h_delta
    ok, msg = g.start_project(0, "S002", "unit", "tank")
    assert ok, msg
    oil_after = g.player.res["oil"]
    assert r.h_delta == pytest.approx(h0 + C.UNIT_START_HAPPY["heavy"])
    ok, msg = g.cancel_project(0, "S002")
    assert ok and "행복도" in msg
    assert r.h_delta == pytest.approx(h0) and g.player.res["oil"] == oil_after   # 석유는 돌려주지 않는다


def test_only_one_capital_move_at_a_time():
    g = new_game(player_start="S002", n_enemies=1)
    a, b = sorted(g.world.land_adj["S002"])[:2]
    _own(g, 0, [a, b])
    for rid in (a, b):
        g.regions[rid].resist = None
        g.regions[rid].project = None
    g.player.money = 10 ** 8
    ok, msg = g.start_project(0, a, "capital", "capital")
    assert ok, msg
    opt = next(o for o in g.options(0, b) if o["kind"] == "capital")
    assert not opt["ok"] and "천도 진행 중" in opt["why"]
    ok, msg = g.start_project(0, b, "capital", "capital")
    assert not ok


def test_last_survivor_wins_even_without_conquest_victory():
    g = new_game(n_enemies=1)
    g.settings.victories = ["science", "time"]
    for f in g.factions[1:]:
        f.alive = False
    g._check_victory()
    assert g.game_over and g.winner == ((0,), "conquest")


def test_artillery_and_bombers_form_their_own_armies():
    """v1.3.0: 포병·폭격기는 같은 병종끼리만 한 부대 — 합치기·생산·하선·예전 세이브 모두."""
    g = new_game(player_start="S002", n_enemies=1)
    _clear(g, "S002")
    inf = g.new_army(0, "S002", {"inf": 2})
    art = g.new_army(0, "S002", {"art": 1})
    ok, msg = g.merge_player(inf.id, art.id)
    assert not ok and "포병" in msg and not g.mergeable(inf, art)
    art2 = g.new_army(0, "S002", {"art": 2})
    assert g.mergeable(art, art2) and g.merge_player(art.id, art2.id)[0] and art.units == {"art": 3}
    # 생산: 포병은 보병 부대에 섞이지 않고 포병 부대에 더해진다
    made = g.add_units(0, "S002", "art", 1)
    assert made.id == art.id and art.units == {"art": 4} and inf.units == {"inf": 2}
    made = g.add_units(0, "S002", "tank", 1)
    assert made.id == inf.id and inf.units == {"inf": 2, "tank": 1}
    # 공군: 폭격기와 전투기는 따로
    ftr = g.new_army(0, "S002", {"ftr": 1})
    bmb = g.new_army(0, "S002", {"bmb": 1})
    assert not g.merge_player(ftr.id, bmb.id)[0]
    # 예전 세이브의 섞인 부대는 병종별로 나뉜다(피해 기록·자동 이동 목적지도 함께)
    mixed = g.new_army(0, "S002", {"inf": 3, "art": 2})
    mixed.dmg = {"art": 4.0, "inf": 2.0}
    mixed.goto = sorted(g.world.land_adj["S002"])[0]
    g2 = pickle.loads(pickle.dumps(g))
    parts = [a for a in g2.armies_at("S002", 0) if a.goto]
    assert sorted(tuple(sorted(a.units.items())) for a in parts) == [(("art", 2),), (("inf", 3),)]
    assert next(a for a in parts if "art" in a.units).dmg == {"art": 4.0}


def test_cargo_unloads_artillery_as_separate_army():
    g = new_game(player_start="S002", n_enemies=1)
    fl = _port_fleet(g, {"lst": 1})
    fl.units.update(inf=2, art=1)
    fl.dmg = {"art": 3.0}
    made, msg = g.unload_cargo(fl.id)
    assert sorted(tuple(sorted(a.units)) for a in made) == [("art",), ("inf",)]
    assert next(a for a in made if "art" in a.units).dmg == {"art": 3.0}


def test_artillery_army_bombards_enemy_units_and_moves_elsewhere():
    """포병만인 부대: 맞닿은 적 병력도 공격 대신 포격 대상, 병력이 없는 곳은 이동으로(move_only)."""
    g, tgt = _war_pair()
    _clear(g, "S002")
    e = g.new_army(1, tgt, {"inf": 2})
    art = g.new_army(0, "S002", {"art": 3})
    reach = g.reachable(art)
    assert reach[tgt]["action"] == "bombard"
    pv = g.preview_bombard(art, tgt)
    assert pv and pv["dmg"] == pytest.approx(3 * C.UNITS["art"]["bomb"] * g.mods(0).mult("bomb_art")
                                             / (1 + C.SHELTER_K * g.regions[tgt].b["shelter"]) * g.morale(0))
    assert pv["def_hp"] == pytest.approx(e.hp_left("inf")) and pv["intercept"] == 0
    hp0 = e.hp_left("inf")
    ok, msg = g.act_now(art.id, tgt, force_bombard=True)
    assert ok and g.army_acted(art.id) and art.loc == "S002" and (e.id not in g.armies or e.hp_left("inf") < hp0)
    # 병력이 없는 적 땅: move_only 면 포격이 아니라 들어가 차지한다
    g.end_turn()
    _clear(g, tgt)
    if g.regions[tgt].owner != 1:
        g.transfer_region(tgt, 1)
    art = next(a for a in g.armies_at("S002", 0) if a.units.get("art"))
    ok, msg = g.act_now(art.id, tgt, move_only=True)
    assert ok and art.loc == tgt


def test_amphibious_survivors_never_stranded_at_sea():
    """퍼저(sim seed 43005): 상륙 돌격에서 상륙함을 잃었거나 구축함 함대가 먼저 잡히면 살아남은 병력이
    바다 위에 육군만 남던 문제 — 칸이 있는 함대로, 모자라면 실을 수 있는 만큼만 돌아간다."""
    g = new_game(player_start="S002", n_enemies=1)
    sea = next(iter(g.world.seas))
    dd = g.new_army(0, sea, {"dd": 1})                       # 먼저 만든(작은 id) 구축함 함대
    fl = g.new_army(0, sea, {"lst": 1})
    x = g.new_army(0, sea, {"tank": 2, "inf": 2})             # 칸 10 > 상륙함 1척 8
    g._reboard(x)
    assert x.id not in g.armies and dd.units == {"dd": 1}
    assert fl.cargo_used() <= fl.cargo_cap() and fl.units.get("inf") == 2 and fl.units.get("tank") == 1
    assert not [a for a in g.armies.values() if a.loc == sea and a.domain() == "land"]
    y = g.new_army(0, sea, {"inf": 1})
    g.remove_army(fl)
    g._reboard(y)                                            # 실을 함대가 없으면 잃는다
    assert y.id not in g.armies and dd.units == {"dd": 1}


def test_captured_defenses_go_dark_and_return():
    """v1.3.0: 점령된 방어선·방공호·대공포는 저항·회복 동안 꺼지고, 옛 주인이 그 안에 되찾으면 그대로,
    기간이 지나면 1단계씩 깎여 새 주인 것이 된다."""
    g = new_game(player_start="S002", n_enemies=1)
    rid = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [rid])
    rr = g.regions[rid]
    rr.lines = {"S002": 3, sorted(g.world.land_adj[rid])[-1]: 2}
    rr.b["shelter"], rr.b["aa"] = 2, 1
    lines0 = dict(rr.lines)
    rr = _captured(g, rid)                                   # 0번이 1번 땅을 점령
    assert rr.owner == 0 and rr.lines == {} and rr.b["shelter"] == 0 and rr.b["aa"] == 0
    assert rr.lost_def["fid"] == 1 and rr.lost_def["lines"] == lines0
    # 저항 중 옛 주인이 되찾으면 그대로 되살아난다
    for a in list(g.armies_at(rid)):
        g.remove_army(a)
    g.new_army(1, rid, {"inf": 3})
    g.complete_occupation(1, rid)
    assert rr.owner == 1 and rr.lines == lines0 and rr.b["shelter"] == 2 and rr.lost_def is None
    # 다시 빼앗기고 기간이 지나면 1단계씩 깎여 새 주인 것
    for a in list(g.armies_at(rid)):
        g.remove_army(a)
    g.new_army(0, rid, {"inf": 3})
    g.complete_occupation(0, rid)
    assert rr.owner == 0 and rr.lost_def
    rr.resist["turn"] -= rr.resist["resist"] + rr.resist["recover"]
    g._phase_happiness()
    assert rr.lost_def is None and rr.lines == {b: lv - 1 for b, lv in lines0.items()}
    assert rr.b["shelter"] == 1 and rr.b["aa"] == 0
    assert C.DEF_TURNS == [1, 2, 3, 4, 5]


def _line_group_setup():
    """플레이어(0)가 S002와 그 이웃 둘을, 세력 1이 그 바깥 이웃들을 가진 판."""
    g = new_game(player_start="S002", n_enemies=1)
    nb = sorted(g.world.land_adj["S002"])
    mine = ["S002"] + nb[:2]
    _own(g, 0, nb[:2])
    theirs = sorted({n for r in mine for n in g.world.land_adj[r]} - set(mine))
    _own(g, 1, theirs)
    for rid in mine:
        rr = g.regions[rid]
        rr.project, rr.resist, rr.occs = None, None, {}
        rr.lines = {}
    g.player.money = 10 ** 8
    return g, mine, theirs


def test_build_border_lines_one_group_project():
    """v1.3.0: 국경 방어선 일괄 건설은 '○○국 방어선' 묶음 공사 한 건 — 턴 = 모든 단계 건설 턴 합 ÷ 지역 수(올림),
    비용은 묶음 전체로 매 턴 한꺼번에, 진행 중이던 작업은 중단(50% 환급), 지출 우선순위에서 한 줄."""
    g, mine, theirs = _line_group_setup()
    assert any(o == 1 for o, *_ in g.border_nations(0))
    # 진행 중이던 작업: 하나는 생산(행복도 환급), 하나는 건설
    ok, _ = g.start_project(0, mine[1], "unit", "inf")
    assert ok
    g.regions[mine[1]].project.paid = 100.0
    plan = g.border_line_plan(0, 1, 2)
    regs = plan["lines"]
    assert set(regs) <= set(mine) and len(regs) >= 2 and mine[1] in plan["interrupt"]
    edges = sum(len(v) for v in regs.values())
    t_sum = edges * sum(g.build_time(0, "line", R.def_building_turns(lv)) for lv in (1, 2))
    assert plan["turns_sum"] == t_sum and plan["turns"] == math.ceil(t_sum / len(regs))
    cost = edges * sum(R.def_building_cost("line", lv) * g.mods(0).mult("cost_line") for lv in (1, 2))
    assert plan["total"] == pytest.approx(cost) and plan["per_turn"] == pytest.approx(cost / plan["turns"])
    money0 = g.player.money
    ok, msg = g.build_border_lines(0, 1, 2)
    assert ok, msg
    p = g.regions[next(iter(regs))].project
    assert p.name == f"{g.fname(1)} 방어선" and all(g.regions[r].project is p for r in regs)
    assert g.player.money == pytest.approx(money0 + 50.0)            # 중단한 생산: 낸 비용 50% 환급
    rows = [r for r in g.projects_by_priority(0) if r.project is p]
    assert len(rows) == 1                                           # 우선순위 목록에서 한 건
    # 한 턴에 묶음 전체 비용 한 번
    m0 = g.player.money
    g._fund_projects()
    assert m0 - g.player.money == pytest.approx(p.per_turn)
    g._phase_projects(("build",))
    assert p.progress == 1
    for _ in range(p.turns - 1):
        g._fund_projects()
        g._phase_projects(("build",))
    for rid, bs in regs.items():
        assert g.regions[rid].project is None
        assert all(g.regions[rid].lines[b] == 2 for b in bs)
    assert p.paid == pytest.approx(cost)
    assert not g.border_line_plan(0, 1, 2)["lines"]


def test_border_line_group_stalls_as_one_and_cancels_together():
    g, mine, theirs = _line_group_setup()
    ok, _ = g.build_border_lines(0, 1, 3)
    assert ok
    p = g.regions[mine[0]].project
    regs = g.group_regions(p)
    g.player.money = p.per_turn * 0.5                               # 묶음 전체 비용이 모자라면 전부 정지
    g._fund_projects()
    g._phase_projects(("build",))
    assert p.stalled and p.progress == 0
    g.player.money = 10 ** 8
    g._fund_projects()
    g._phase_projects(("build",))
    paid = p.paid
    m0 = g.player.money
    ok, msg = g.cancel_project(0, regs[-1])
    assert ok and all(g.regions[r].project is None for r in regs)
    assert g.player.money == pytest.approx(m0 + paid * C.PROJECT_REFUND)


def test_border_line_group_member_lost_or_moved_to_new_group():
    import pickle
    g, mine, theirs = _line_group_setup()
    ok, _ = g.build_border_lines(0, 1, 2)
    assert ok
    p = g.regions[mine[0]].project
    regs = g.group_regions(p)
    assert len(regs) >= 2
    g._fund_projects()
    g._phase_projects(("build",))
    # 저장·불러오기 뒤에도 같은 작업 하나를 함께 가리킨다
    g2 = pickle.loads(pickle.dumps(g))
    p2 = g2.regions[regs[0]].project
    assert all(g2.regions[r].project is p2 for r in regs) and len(g2.projects_by_priority(0)) == 1
    # 대상 지역 하나를 빼앗기면 그 지역 몫만큼 턴당 비용이 줄고 나머지는 계속 짓는다
    lost = regs[-1]
    share = p.group["cost"][lost] / sum(p.group["cost"].values())
    per0, paid0 = p.per_turn, p.paid
    g.transfer_region(lost, 1)
    assert g.regions[lost].project is None and lost not in p.group["lines"]
    assert p.per_turn == pytest.approx(per0 * (1 - share)) and p.paid == pytest.approx(paid0 * (1 - share))
    rest = g.group_regions(p)
    assert rest and all(g.regions[r].project is p for r in rest)


def test_second_border_group_takes_region_from_first():
    """다른 나라 쪽 묶음 공사가 같은 지역을 쓰면 그 지역만 앞 묶음에서 빠지고(그 몫 50% 환급) 앞 묶음은 계속된다."""
    g = new_game(player_start="S002", n_enemies=2)
    nb = sorted(g.world.land_adj["S002"])
    _own(g, 0, nb[:1])
    mine = ["S002", nb[0]]
    outer = sorted({n for r in mine for n in g.world.land_adj[r]} - set(mine))
    _own(g, 1, outer[::2])
    _own(g, 2, outer[1::2])
    for rid in mine:
        rr = g.regions[rid]
        rr.project, rr.resist, rr.occs, rr.lines = None, None, {}, {}
    g.player.money = 10 ** 8
    assert g.build_border_lines(0, 1, 2)[0]
    p1 = g.regions["S002"].project
    both = [r for r in g.group_regions(p1) if any(g.regions[n].owner == 2 for n in g.world.land_adj[r])]
    assert both
    g._fund_projects()
    g._phase_projects(("build",))
    ok, msg = g.build_border_lines(0, 2, 2)
    assert ok and "중단" in msg
    p2 = g.regions[both[0]].project
    assert p2 is not p1 and p2.name == f"{g.fname(2)} 방어선"
    assert both[0] not in p1.group["lines"]
    assert all(g.regions[r].project is p1 for r in g.group_regions(p1))


def test_border_line_turns_example_from_request():
    """요청 예: 4개 지역에서 3단계 방어선 5개(각 3턴) → 총 15턴 ÷ 4 = 3.75 → 4턴."""
    assert math.ceil(15 / 4 - 1e-9) == 4
    g, mine, theirs = _line_group_setup()
    for rid in mine:
        for n in g.world.land_adj[rid]:
            g.regions[rid].lines[n] = 2                     # 2 → 3단계만 남게
    plan = g.border_line_plan(0, 1, 3)
    edges = sum(len(v) for v in plan["lines"].values())
    t3 = g.build_time(0, "line", R.def_building_turns(3))
    assert plan["turns_sum"] == edges * t3
    assert plan["turns"] == math.ceil(edges * t3 / len(plan["lines"]) - 1e-9)


def test_sold_electricity_is_delivered_in_full_before_allocation():
    """v1.3.0: 판매 계약은 배정보다 먼저 — 발전소에서 나올 전기를 판 경우에도 '1/3만 오갔다'처럼 덜 가지 않고,
    그만큼 공장에 덜 들어간다. 확보량이 모자라면 부족분은 턴 끝에 시장가로 사서 메운다."""
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    r.b["power"], r.b["factory"] = 2, 3
    g.energy_mined = lambda fid: {"coal": 3, "oil": 0, "elec": 0} if fid == 0 else {"coal": 0, "oil": 0, "elec": 0}
    g._refresh_pools()
    g.assign_energy(0)
    gen = g.energy_plan(0)["elec_gen_int"]
    assert gen >= 3
    buyer = g.factions[1]
    buyer.money = 10 ** 6
    e0 = buyer.res.get("elec", 0)
    c = D.make_trade(g, 0, 1, "elec", 3, 5.0, 1)
    assert c["last_q"] == 3 and buyer.res["elec"] == e0 + 3          # 발전 전이어도 전부 보낸다
    plan = g.energy_plan(0)
    assert plan["factories"]["S002"]["elec"] <= max(0, gen - 3)       # 판 전기는 공장에 들어가지 않는다
    money0 = g.player.money
    g._phase_resources(g.player)
    assert "covered" not in g.player.last["energy"]                  # 발전으로 충분하면 사지 않는다
    # 석유를 유닛에 써 버린 뒤 석유 계약: 부족분은 시장가로 사서 메운다
    g.energy_mined = lambda fid: {"coal": 0, "oil": 2, "elec": 0} if fid == 0 else {"coal": 0, "oil": 0, "elec": 0}
    g._refresh_pools()
    g.player.res["oil"] = 0.0
    c2 = D.make_trade(g, 0, 1, "oil", 2, 5.0, 1)
    assert c2["last_q"] == 2
    m0 = g.player.money
    g._phase_resources(g.player)
    assert g.player.last["energy"]["covered"] == {"oil": 2}
    assert g.player.money <= m0 - 2 * C.MARKET_BUY["oil"] * C.MONEY_SCALE + 1e-6


# ---- v1.3.0 거래 협상
def _nego_game():
    g = _meet_all(new_game(player_start="S002", n_enemies=1))
    _neutral_ai(g, 1)
    g.dip.op[(1, 0)] = g.dip.op[(0, 1)] = 10.0
    return g


def test_nego_player_buys_ai_surplus_with_counters():
    from korciv import negotiation as NG
    g = _nego_game()
    g.regions[g.factions[1].capital].b.update(factory=0, power=0)
    _mined(g, {1: {"oil": 0, "coal": 6, "elec": 0}, 0: {"oil": 0, "coal": 0, "elec": 0}})
    g._refresh_pools()
    assert NG.surplus(g, 1, "coal") == 6
    st = NG.start(g, 1, 0, "coal", 3, ai_sells=True)
    assert st["status"] == "open" and 1 <= st["rounds"] <= 4 and st["price"] >= st["R"]
    # 같은 턴에 다시 열어도 유보 가격이 같다(다시 열어 운을 시험할 수 없다)
    assert NG.start(g, 1, 0, "coal", 3, ai_sells=True)["R"] == st["R"]
    kind, _ = NG.player_offer(g, st, 3, 1)                     # 터무니없는 값 → 역제의(또는 결렬)
    assert kind in ("counter", "final", "broken")
    if kind != "broken":
        assert st["price"] >= st["R"] - 1                      # 유보 가격 아래로는 내려가지 않는다
        g.player.money = 10 ** 6
        ok, msg = NG.accept_ai_price(g, st)
        assert ok and st["status"] == "done"
        c = D.contracts_between(g, 0, 1)[-1]
        assert c["from"] == 1 and c["to"] == 0 and c["n"] == 3 and c["price"] == st["price"]


def test_nego_selling_beyond_surplus_needs_factory_value():
    """AI 는 남는 양을 넘겨 팔려면 평균 공장 산출 × 세율보다 비싸야 한다."""
    from korciv import negotiation as NG
    g = _nego_game()
    cap = g.regions[g.factions[1].capital]
    cap.b.update(factory=3, power=0)
    _mined(g, {1: {"oil": 0, "coal": 4, "elec": 0}, 0: {"oil": 0, "coal": 0, "elec": 0}})
    g._refresh_pools()
    sur = NG.surplus(g, 1, "coal")
    assert sur == 1
    R_small, n1, _ = NG.reserve(g, 1, 0, "coal", 1, True)
    R_big, n3, _ = NG.reserve(g, 1, 0, "coal", 3, True)
    assert n1 == 1 and n3 == 3
    assert R_big >= NG.avg_factory_unit(g, 1) * 0.9 and R_big > R_small


def test_nego_ai_buys_only_with_empty_factory_and_below_value():
    """플레이어가 AI 에게 팔 때: AI 에 빈 공장이 없으면 안 사고, 산출 × 세율보다 비싸면 절대 사지 않는다."""
    from korciv import negotiation as NG
    g = _nego_game()
    cap = g.regions[g.factions[1].capital]
    cap.b.update(factory=0, power=0)
    _mined(g, {1: {"oil": 0, "coal": 0, "elec": 0}, 0: {"oil": 0, "coal": 5, "elec": 0}})
    g._refresh_pools()
    st = NG.start(g, 1, 0, "coal", 2, ai_sells=False)
    assert st["status"] == "refused" and "빈 공장" in st["why"]
    cap.b["factory"] = 3
    g.factions[1].money = 10 ** 6
    st = NG.start(g, 1, 0, "coal", 2, ai_sells=False)
    assert st["status"] == "open"
    val = NG.buy_unit_value(g, 1, "coal", 2)
    assert st["R"] < val and st["price"] <= st["R"]
    # 값을 계속 높게 부르면 결국 결렬되고, 이번 턴에는 다시 열 수 없다
    for _ in range(6):
        kind, _ = NG.player_offer(g, st, 2, int(val * 2) + 5)
        if kind == "broken":
            break
    assert st["status"] == "broken" and NG.start(g, 1, 0, "coal", 2, ai_sells=False)["status"] == "refused"
    D.update_turn(g)
    assert NG.start(g, 1, 0, "coal", 2, ai_sells=False)["status"] == "open"   # 다음 턴엔 다시


def test_nego_specialty_rules():
    """특산물: AI 는 반란이 가까울수록 비싸게 사고, 행복도가 높고 돈이 급하면 싸게 판다."""
    from korciv import negotiation as NG
    g = _nego_game()
    for r in g.regions_of(1):
        r.resist, r.supplied = None, set()
    g.factions[1].money = 10 ** 6
    for r in g.regions_of(1):
        r.happy = 0.0
    calm, _, _ = NG.reserve(g, 1, 0, "specialty", 1, False)
    for r in g.regions_of(1):
        r.happy = -45.0
    near, _, _ = NG.reserve(g, 1, 0, "specialty", 1, False)
    assert near > calm
    # 판매: 남는 특산물, 행복도 높음 + 돈 급함 → 더 싸게
    spec = next(x for x in g.world.order if g.world.regions[x].specialties and g.regions[x].owner == NEUTRAL)
    _own(g, 1, [spec])
    g.regions[spec].resist = None
    g.regions[spec].b["specialty"] = 3
    g._refresh_pools()
    for r in g.regions_of(1):
        r.happy = 0.0
    g.factions[1].money = 10 ** 6
    p1, _, _ = NG.reserve(g, 1, 0, "specialty", 1, True)
    for r in g.regions_of(1):
        r.happy = 40.0
    g.factions[1].money = 0
    p2, _, _ = NG.reserve(g, 1, 0, "specialty", 1, True)
    assert p1 is not None and p2 is not None and p2 < p1


def test_ai_to_ai_trade_deals_when_reserves_overlap():
    from korciv import negotiation as NG
    g = _meet_all(new_game(player_start="S002", n_enemies=2, all_ai=True))
    a, b = 1, 2
    g.dip.op[(a, b)] = g.dip.op[(b, a)] = 30.0
    g.regions[g.factions[a].capital].b.update(factory=0, power=0)
    g.regions[g.factions[b].capital].b.update(factory=4, power=0)
    _mined(g, {a: {"oil": 0, "coal": 4, "elec": 0}, b: {"oil": 0, "coal": 0, "elec": 0},
               0: {"oil": 0, "coal": 0, "elec": 0}})
    g._refresh_pools()
    g.factions[b].money = 10 ** 6
    c = NG.ai_deal(g, a, b, "coal", 3)
    assert c is not None and c["from"] == a and c["to"] == b and c["price"] > 0


# ---- v1.3.0 편의·시인성
def test_same_faction_annex_and_occupation_do_not_compete():
    """편입 중인 중립 지역에 병력을 넣어도 자기 자신과 경쟁하지 않는다(같은 턴에 끝나도 '경쟁' 알림 없음)."""
    g = new_game(player_start="S002", n_enemies=1)
    tgt = next(n for n in sorted(g.world.land_adj["S002"]) if g.regions[n].owner == NEUTRAL)
    g.player.money = 10 ** 7
    g.regions["S002"].project = None
    ok, msg = g.start_project(0, "S002", "annex", tgt)
    assert ok, msg
    for a in list(g.armies_at(tgt)):
        g.remove_army(a)
    g.new_army(0, tgt, {"inf": 3})
    g.begin_occupation(0, tgt)
    rr = g.regions[tgt]
    rr.occs[0]["progress"] = rr.occs[0]["need"] - 1               # 둘 다 이번 턴에 끝나게
    p = g.regions["S002"].project
    p.progress = p.turns - 1
    n0 = len(g.events)
    g._fund_projects()
    g._phase_claims()
    assert rr.owner == 0
    assert not any("같은 턴에 점령·편입" in e["text"] for e in g.events[n0:])
    assert g.regions["S002"].project is None                      # 남은 편입은 전액 환급으로 정리


def test_pick_order_moved_merge_and_rally_exclusions():
    g = new_game(player_start="S002", n_enemies=1)
    _clear(g, "S002")
    big = g.new_army(0, "S002", {"tank": 2})                      # 최대 체력 합 100
    small = g.new_army(0, "S002", {"inf": 2})                     # 20
    other = g.new_army(0, "S002", {"inf": 5})                     # 50
    order = sorted(g.armies_at("S002", 0), key=g.army_pick_key)
    assert [a.id for a in order] == [big.id, other.id, small.id]
    g.moved_armies().add(big.id)                                  # 행동한 부대는 뒤로
    order = sorted(g.armies_at("S002", 0), key=g.army_pick_key)
    assert order[0].id == other.id and order[-1].id == big.id
    ok, msg = g.merge_player(other.id, big.id)                    # 행동한 부대는 합칠 수 없다
    assert not ok and not g.mergeable(other, big) and g.mergeable(other, small)
    # 집결: 중립 지역을 점령 중인 병력은 부르지 않는다
    tgt = next(n for n in sorted(g.world.land_adj["S002"]) if g.regions[n].owner == NEUTRAL)
    _clear(g, tgt)
    occ = g.new_army(0, tgt, {"inf": 2})
    g.begin_occupation(0, tgt)
    assert 0 in g.regions[tgt].occs
    assert occ.id not in {a.id for a in g.rally_candidates(0, "S002", 2)}


def test_energy_flow_tracks_contracts_and_unit_fuel():
    g = new_game(player_start="S002", n_enemies=1)
    g.energy_mined = lambda fid: {"oil": 3, "coal": 4, "elec": 0} if fid == 0 else {"oil": 0, "coal": 0, "elec": 0}
    g._refresh_pools()
    f = g.player
    assert f.sent == {} and f.recv == {} and f.unit_fuel == {}
    g.factions[1].money = 10 ** 6
    D.make_trade(g, 0, 1, "coal", 2, 5.0, 1)
    assert f.sent == {"coal": 2} and g.factions[1].recv == {"coal": 2}
    f.res["oil"] = -1.0                                           # 판매로 석유가 음수여도 석탄을 이상하게 쓰지 않는다
    g.pay_oil(0, 1)
    assert f.res["oil"] == -1.0 and f.unit_fuel == {"coal": C.OIL_AS_COAL}


def test_foreign_land_is_loaded_for_the_map():
    from korciv.data import load_world
    w = load_world()
    names = {land["name"] for land in w.foreign["lands"]}
    assert {"중국", "러시아", "일본"} <= names
    assert all(len(r) >= 3 for land in w.foreign["lands"] for r in land["polys"])


def test_v1214_air_distance_bomber_and_fighter_ranges():
    """v1.3.0: 폭격기 4칸·전투기 요격 3칸. 육지↔바다는 2칸으로 센다(태안-경기만-옹진 = 4칸)."""
    g = new_game(player_start="S002", n_enemies=1)
    w = g.world
    assert w.air_distances("S146", 6)["N111"] == 4 and w.distances_from("S146", 6)["N111"] == 2
    d = w.air_distances("S002", 5)
    four = next(v for v, x in sorted(d.items()) if x == 4 and not w.is_sea(v))
    five = next(v for v, x in sorted(d.items()) if x == 5 and not w.is_sea(v))
    _own(g, 1, [four, five])
    _clear(g, "S002", four, five)
    D.declare_war(g, 0, 1)
    g.regions["S002"].b["airport"] = 1
    b = g.new_army(0, "S002", {"bmb": 2})
    assert g._can_bombard(b, four) and not g._can_bombard(b, five)
    # 요격: 대상에서 항공 거리 3칸 안 공항의 전투기만
    for r in g.regions.values():
        r.b["airport"] = 0
    g.regions[four].b["aa"] = 0
    dt = w.air_distances(four, 4)
    three = next(v for v, x in sorted(dt.items()) if x == 3 and not w.is_sea(v))
    far = next(v for v, x in sorted(dt.items()) if x == 4 and not w.is_sea(v))
    f3 = g.new_army(1, three, {"ftr": 1})
    g.regions[three].b["airport"] = 1
    assert g.air_defense(0, four)[2] == 1
    g.remove_army(f3)
    g.new_army(1, far, {"ftr": 1})
    g.regions[far].b["airport"] = 1
    assert g.air_defense(0, four)[2] == 0
    # 폭격한 부대·폭격당한 부대는 전투한 것으로 친다(회복 지연)
    g.regions["S002"].b["airport"] = 1
    tgt_army = g.new_army(1, four, {"inf": 3})
    g._bombard(b, four, g._bombard_units(b, four))
    assert b.last_combat == g.turn and tgt_army.last_combat == g.turn


def test_v1214_simultaneous_occupation_uses_remaining_hp():
    """같은 턴에 무력 점령이 끝나면 주둔 병력의 남은 체력 합이 큰 쪽이 차지한다."""
    g, tgt, other = _contest_setup()
    _neutral_ai(g, 1)
    a = g.new_army(0, tgt, {"inf": 4})                  # 최대 40이지만
    a.dmg["inf"] = 25                                   # 남은 체력 15
    g.begin_occupation(0, tgt)
    g.new_army(1, tgt, {"inf": 2})                      # 남은 체력 20
    g.begin_occupation(1, tgt)
    rr = g.regions[tgt]
    assert g.occ_force(0, tgt) == 15 and g.occ_force(1, tgt) == 20
    for fid in (0, 1):
        rr.occs[fid]["need"] = rr.occs[fid]["progress"] + 1
    g._phase_claims()
    assert rr.owner == 1


def test_v1214_start_airports_and_ports():
    g = new_game(player_start="S002", n_enemies=1)
    airports = ("S058 S089 S037 S228 S045 S126 S171 N031 N001 N195 N161 N134 N054 N151 N069").split()
    ports = ("S041 S059 S169 S075 S084 S154 S168 N036 N112 N151 N042 N001 N131 S209 S228 S229").split()
    for rid in airports:
        assert g.regions[rid].b["airport"] == 1, rid
    for rid in ports:
        assert g.regions[rid].b["port"] == 1, rid
    assert sum(r.b["airport"] for r in g.regions.values()) == len(airports)
    assert sum(r.b["port"] for r in g.regions.values()) == len(ports)


def test_v1214_paid_capital_move_gives_border_lines_but_forced_move_does_not():
    g = new_game(player_start="S002", n_enemies=1)
    a, b = sorted(g.world.land_adj["S002"])[:2]
    _own(g, 0, [a, b])
    for rid in (a, b):
        g.regions[rid].resist = None
        g.regions[rid].project = None
        g.regions[rid].lines.clear()
    g.player.money = 10 ** 8
    ok, msg = g.start_project(0, a, "capital", "capital")
    assert ok, msg
    rr = g.regions[a]
    p = rr.project
    rr.project = None
    g._complete_project(g.player, rr, p)
    assert g.player.capital == a
    assert all(rr.lines.get(n) == C.START_LINE_LEVEL for n in g.world.land_adj[a])
    assert rr.lines.get("coast") == (C.START_LINE_LEVEL if g.world.regions[a].coastal else None)
    # 수도를 빼앗겨 강제로 옮긴 곳은 방어선을 받지 않는다
    for rid in [r.id for r in g.regions_of(0) if r.id not in (a, b)]:
        g.transfer_region(rid, 1)
    g.transfer_region(a, 1)
    assert g.player.capital == b
    assert not any(g.regions[b].lines.values())


def test_v1214_naval_battle_marks_combat():
    g = new_game(player_start="S002", n_enemies=1)
    sid = next(iter(g.world.seas))
    D.declare_war(g, 0, 1)
    x = g.new_army(0, sid, {"dd": 2})
    y = g.new_army(1, sid, {"dd": 2})
    g._naval_battle(sid, 0, [x], 1, [y])
    assert x.last_combat == g.turn and y.last_combat == g.turn


def _liberation_setup():
    """0(원 주인)·2(0의 동맹)·1(적)·3(제3국). 0의 지역 x 를 1이 전쟁으로 빼앗은 상태."""
    g = new_game(player_start="S002", n_enemies=3)
    _neutral_ai(g, 1, 2, 3)
    x = sorted(g.world.land_adj["S002"])[0]
    _own(g, 0, [x])
    g.dip.alliance[D.pair(0, 2)] = g.turn
    for a, b in ((0, 1), (2, 1), (3, 1), (2, 3), (0, 3)):
        g.dip.wars.pop(D.pair(a, b), None)
        D.declare_war(g, a, b) if not D.at_war(g, a, b) else None
    rr = g.regions[x]
    rr.happy = 40.0
    _clear(g, x)
    g.new_army(1, x, {"inf": 1})
    g.complete_occupation(1, x)
    assert rr.owner == 1 and rr.war_from == 0
    return g, x, rr


def test_ally_retaking_lost_region_returns_it_to_original_owner():
    """v1.3.0: 동맹·연합국이 전쟁으로 빼앗긴 땅을 되찾으면 원 주인에게 돌아간다(원 주인이 직접 되찾은 것과 같이
    저항·회복 기간 안이면 저항 없이 빼앗기기 전 행복도로)."""
    g, x, rr = _liberation_setup()
    assert g.liberation_owner(2, x) == 0 and g.liberation_owner(3, x) is None
    _clear(g, x)
    a2 = g.new_army(2, x, {"inf": 1})
    g.complete_occupation(2, x)
    assert rr.owner == 0 and rr.war_from == 1 and not g.resisting(rr)     # 이제 직전 주인은 1(v1.3.0)
    assert rr.happy == pytest.approx(40.0)
    assert any("원 주인" in e["text"] for e in g.events)
    assert a2.id in g.armies and a2.loc == x                     # 되찾은 부대는 동맹 땅에 그대로


def test_liberation_chain_and_non_ally_and_dead_owner():
    """v1.3.0: 반환은 직전 주인이 그 동맹국일 때만 — 1 → 3 으로 넘어간 땅은 0의 동맹이 되찾아도 자기 땅."""
    g, x, rr = _liberation_setup()
    # 동맹이 아닌 제3국이 빼앗으면 자기 땅(직전 주인 기록은 1로 바뀜)
    _clear(g, x)
    g.new_army(3, x, {"inf": 1})
    g.complete_occupation(3, x)
    assert rr.owner == 3 and rr.war_from == 1 and rr.war_turn == g.turn
    # 그 뒤 0의 동맹 2가 되찾으면: 직전 주인(3)은 2의 동맹이 아니므로 2가 갖는다
    assert g.liberation_owner(2, x) is None
    _clear(g, x)
    g.new_army(2, x, {"inf": 1})
    g.complete_occupation(2, x)
    assert rr.owner == 2 and rr.war_from == 3
    # 원 주인이 직접 되찾으면 직전 주인은 1(1의 동맹이 24턴 안에 되찾으면 1에게)
    g2, x2, rr2 = _liberation_setup()
    _clear(g2, x2)
    g2.new_army(0, x2, {"inf": 1})
    g2.complete_occupation(0, x2)
    assert rr2.owner == 0 and rr2.war_from == 1
    # 원 주인이 멸망했으면 동맹이 차지한다
    g3, x3, rr3 = _liberation_setup()
    g3.factions[0].alive = False
    assert g3.liberation_owner(2, x3) is None
    # 거래·할양 등 전쟁이 아닌 이전은 기록을 지운다
    g4, x4, rr4 = _liberation_setup()
    g4.transfer_region(x4, 3, reason="거래")
    assert rr4.war_from is None


def test_liberation_only_within_24_turns():
    """v1.3.0: 지금 주인이 빼앗은 지 24턴 안에만 반환(25턴째부터는 되찾은 나라가 갖는다)."""
    g, x, rr = _liberation_setup()
    t0 = rr.war_turn
    assert C.LIBERATION_TURNS == 24
    g.turn = t0 + 24
    assert g.liberation_left(x) == 1 and g.liberation_owner(2, x) == 0
    g.turn = t0 + 25
    assert g.liberation_left(x) == 0 and g.liberation_owner(2, x) is None
    _clear(g, x)
    g.new_army(2, x, {"inf": 1})
    g.complete_occupation(2, x)
    assert rr.owner == 2 and rr.war_from == 1
    # 예전 세이브(턴 기록 없음)의 기록은 반환하지 않는다
    g2, x2, rr2 = _liberation_setup()
    rr2.war_turn = None
    assert g2.liberation_owner(2, x2) is None


def test_coalition_member_also_liberates():
    g, x, rr = _liberation_setup()
    g.dip.alliance.pop(D.pair(0, 2), None)
    assert g.liberation_owner(2, x) is None
    g.dip.coalitions[99] = {"members": {0, 2}, "name": "시험 연합"}
    assert D.same_coalition(g, 0, 2) and g.liberation_owner(2, x) == 0


def test_priority_mode_stays_until_turned_off():
    """v1.3.0: 지출 우선순위 정렬 버튼은 해제할 때까지 그 규칙을 유지한다(새 작업도 규칙대로)."""
    g = new_game(player_start="S002", n_enemies=1)
    near = sorted(g.world.land_adj["S002"])[:4]
    _own(g, 0, near)
    for r in near:
        g.regions[r].resist = None
    f = g.factions[0]
    f.money = 1e7
    f.res["oil"] = 5
    assert g.start_project(0, near[0], "build", "bank")[0]
    assert g.start_project(0, near[1], "unit", "inf")[0]
    assert g.set_priority_mode(0, "build") == "build"
    assert g.projects_by_priority(0)[0].project.kind == "build"
    assert g.set_priority_mode(0, "unit") == "unit"
    assert g.projects_by_priority(0)[0].project.kind == "unit"
    # 나중에 착수한 건설·생산도 규칙대로 들어간다: 유닛은 모두 건설보다 앞
    _room(g, [near[2]])
    assert g.start_project(0, near[2], "build", "farm")[0]
    assert g.start_project(0, near[3], "unit", "inf")[0]
    kinds = [r.project.kind for r in g.projects_by_priority(0)]
    assert kinds == sorted(kinds, key=lambda k: k != "unit")
    # 자금도 그 순서로 낸다: 돈이 모자라면 유닛부터 진행
    f.money = sum(r.project.per_turn for r in g.regions_of(0) if r.project and r.project.kind == "unit") + 1
    g._fund_projects()
    assert all(r.project.funded == (r.project.kind == "unit") for r in g.regions_of(0) if r.project)
    # 같은 버튼을 다시 누르면 해제, 직접 옮겨도 해제
    assert g.set_priority_mode(0, "unit") is None and f.prio_mode is None
    g.set_priority_mode(0, "short")
    ids = [r.id for r in g.projects_by_priority(0)]
    g.set_priority_order(0, ids[::-1], manual=True)
    assert f.prio_mode is None and [r.id for r in g.projects_by_priority(0)] == ids[::-1]


def test_fog_lifted_after_game_over():
    """v1.3.0: 게임이 끝나면(승리 뒤 [지도 계속 보기]) 전장의 안개를 걷는다 — 모든 지역·국명이 보이고,
    탐색·조우 기록 자체는 바뀌지 않는다."""
    g = new_game(meet=False, player_start="S002", n_enemies=3, fog=2)
    far = next(r for r in g.world.order if not g.is_explored(0, r))
    other = next(f.id for f in g.factions if f.id != 0 and not g.has_met(0, f.id))
    assert not g.is_visible(0, far) and g.seen_name(other) == g.UNKNOWN_NAME
    explored0, met0 = set(g.player.explored), set(g.player.met)
    g._win((0,), "conquest")
    assert g.game_over and g.fog_lifted()
    assert g.is_visible(0, far) and g.is_explored(0, far) and g.has_met(0, other)
    assert g.seen_name(other) == g.fname(other)
    g._update_fog()
    assert g.player.explored == explored0 and g.player.met == met0


def test_annex_of_non_adjacent_target_is_cancelled():
    """v1.3.4: 맞닿지 않은 지역을 편입하던 작업(예전 세이브의 대안 → 송림 등)은 다음 편입 진행 때 취소·50% 환급."""
    g = new_game(player_start="S002", n_enemies=1)
    tgt = next(r for r in g.world.order if g.regions[r].owner == NEUTRAL and r not in g.world.land_adj["S002"])
    rr = g.regions["S002"]
    rr.project = None
    from korciv.state import Project
    p = Project(kind="annex", key=tgt, level=0, turns=4, per_turn=100.0, name=f"편입: {g.info(tgt).name}")
    p.paid, p.funded = 200.0, True
    rr.project = p
    money = g.player.money
    g._advance_annexes()
    assert rr.project is None or rr.project.key != tgt
    assert g.player.money == pytest.approx(money + 200.0 * C.PROJECT_REFUND)
    assert any("맞닿지 않아" in e["text"] for e in g.events)
