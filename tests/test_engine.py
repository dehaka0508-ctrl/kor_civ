import math
import pickle

import pytest

from korciv import config as C
from korciv import diplomacy as D
from korciv import rules as R
from korciv.game import Game
from korciv.state import NEUTRAL, Settings


def new_game(**kw):
    kw.setdefault("seed", 5)
    g = Game(Settings(**kw))
    g.set_player_government("philosopher")
    return g


def test_setup():
    g = new_game(n_enemies=3, player_start="S002")
    assert len(g.factions) == 4
    assert g.player.capital == "S002"
    assert g.regions["S002"].owner == 0
    assert g.player.money == 3000
    assert g.player.res["food"] == pytest.approx(55.2 * 5)
    assert sum(1 for a in g.armies.values() if a.owner == NEUTRAL) == 426 - 4
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
    g = new_game(n_enemies=2)
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
    msg = g.resolve_rebellion(0, "S002", "tax")
    assert "세율" in msg and r.happy == pytest.approx(-60)
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


def test_rebel_region_becomes_capital_and_inherits_state():
    g = new_game(player_start="S002", n_enemies=1)
    near = sorted(g.world.land_adj["S002"])[:3]
    _own(g, 0, near)
    rid = near[0]
    r = g.regions[rid]
    r.b["bank"] = 3
    r.sci.add("lab")
    pop, b = r.pop, dict(r.b)
    g.start_project(0, rid, "build", "farm")
    msg = _fail_suppression(g, 0, rid)
    nf = g.factions[-1]
    assert "분리독립" in msg
    assert r.owner == nf.id and nf.capital == rid and nf.rebel_of == 0
    assert r.pop == pop and r.b == b and "lab" in r.sci
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
    assert [o["key"] for o in sci(oil)] == ["propellant"]
    # 유닛을 잃으면 그 단계를 다시 만들 수 있다(다음 단계와 함께)
    assert g.science_available(0) == ["propellant", "booster", "module"]
    f.science.append("propellant")
    assert g.science_available(0) == ["booster", "module", "propellant"]
    # 발사: 세 유닛을 발사대 지역에 모으고 턴을 마치면 승리
    pad = next(r for r in g.world.order if g.world.regions[r].coastal and g.regions[r].owner == NEUTRAL)
    _own(g, 0, [pad])
    g.regions[pad].sci.add("pad")
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
    sea = "SEA3"
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
    g.new_army(0, "SEA8", {"lst": 1})                  # 상륙함이 있어도 해로 편입은 없다
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
    g = new_game(n_enemies=3)
    before = {c: D.opinion(g, c, 0) for c in (2, 3)}
    D.declare_war(g, 0, 1)
    for c in (2, 3):
        assert D.opinion(g, c, 0) == pytest.approx(before[c] - 10)
    D.make_peace(g, 0, 1)
    g.turn += 30                                   # 직전 전쟁이 끝난 지 1년이 안 됐다
    before = D.opinion(g, 3, 0)
    D.declare_war(g, 0, 2)
    assert D.opinion(g, 3, 0) == pytest.approx(before - 15)
    assert D.warmonger_penalty(g, 0) == -20        # 또 선포하면 −20
    D.make_peace(g, 0, 2)
    g.turn += C.WARMONGER_WINDOW + 1
    assert D.warmonger_penalty(g, 0) == -10        # 1년이 지나면 처음처럼


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
    g = Game(Settings(seed=5, player_start="S002", n_enemies=1, player_leader="gil"))
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
    assert g.combat_strength(0, [a], t1)[0] == pytest.approx(s1 * 1.10)


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
    assert costs[0] == pytest.approx(100_000 * C.SCIENCE_TURNS)


def test_no_peace_victory():
    assert "peace" not in C.VICTORY_TYPES and "peace" not in Settings().victories


def test_bombard_breaks_buildings():
    g = new_game(player_start="S002", n_enemies=1)
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 1, [tgt])
    D.declare_war(g, 0, 1)
    rr = g.regions[tgt]
    rr.b.update(farm=0, fishery=0, factory=2, bank=0, specialty=0, shelter=0, aa=0, port=1)
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
    assert g.regions[tgt].lines["S002"] == 1


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


def test_annex_allowed_while_other_occupies_and_tie_goes_to_bigger_neighbor():
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
    assert g.regions[tgt].owner == 1                    # 맞닿은 지역 인구가 많은 쪽


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
    # 평시: 점령을 계속한다
    AI._army_orders(g, f, AI.threat_map(g, 1))
    assert army.order is None
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
    assert A1 == pytest.approx(A0 + 2 * C.FTR_SUPPORT_ATK * g.morale(0))
    D0, _, _ = g.defense_strength(0, tgt, "S002", "assault")
    far = next(n for n in sorted(g.world.land_adj[tgt]) if n != "S002")
    _own(g, 1, [far])
    g.regions[far].b["airport"] = 1
    g.new_army(1, far, {"ftr": 3})
    D1, _, _ = g.defense_strength(0, tgt, "S002", "assault")
    assert D1 > D0
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


def test_destroyer_bombard_hits_port_first():
    g, tgt = _war_pair()
    rr = g.regions[tgt]
    rr.b["port"] = 1
    rr.b["factory"] = 3
    sea = g.world.regions[tgt].seas[0] if g.world.regions[tgt].seas else None
    if sea is None:
        return
    fl = g.new_army(0, sea, {"dd": 1})
    g.rng.random = lambda: 0.1
    g._bombard(fl, tgt, {"dd": 1})
    assert rr.b["port"] == 0 and rr.b["factory"] == 3


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
            g.player.specialty = {}
            g._phase_resources(g.player)
            made = sum(len(g.world.regions[x].specialties) * lv for x in spec)
            have = sum(g.player.specialty.values()) + sum(len(x.supplied) for x in g.regions_of(0))
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
    assert (a, p, C.DECL_FRIEND_BONUS, True) in eff and (c, p, C.DECL_FRIEND_ENEMY, False) in eff
    before_c = D.opinion(g, c, p)
    assert D.declare_friendship(g, p, a)[0]
    assert D.opinion(g, a, p) == pytest.approx(-20 + 15)
    assert D.opinion(g, c, p) == pytest.approx(before_c - 5)
    assert not D.friendship_check(g, p, a)[0]    # 쿨타임
    g.turn += C.DECL_FRIEND_TURNS
    assert D.opinion(g, a, p) == pytest.approx(-20)     # 기한부 +15 만료
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
    # 한 턴 아무것도 하지 않으면 10% 회복
    g.end_turn()
    assert a.hp_left("inf") == pytest.approx(16 + 0.1 * 3 * hp)
    # 명령을 받은 턴은 회복하지 않는다
    tgt = sorted(g.world.land_adj["S002"])[0]
    _own(g, 0, [tgt])
    for x in g.armies_at(tgt):
        g.remove_army(x)
    left = a.hp_left("inf")
    g.order_army(a.id, tgt)
    g.end_turn()
    assert a.hp_left("inf") == pytest.approx(left)


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
    expect = p0 * (C.POP_FOCUS_GROWTH + R.pop_growth_rate(g.growth_happy(r)))
    g._phase_population()
    assert r.pop - p0 == pytest.approx(expect)
    g.player.war_weary = 80                        # 이주는 전쟁 피로 포함 실질 행복도(−60)로 판정
    p1 = r.pop
    g._phase_population()
    assert r.pop == pytest.approx(p1 * (1 + C.POP_FOCUS_GROWTH + R.pop_growth_rate(g.growth_happy(r)))
                                  * (1 + C.MIGRATION_POP))
    g.set_focus(0, "S002", True)
    assert r.focus and not r.pop_focus             # 집중은 하나만


def test_crowd_penalty_tiers():
    g = new_game(player_start="S002", n_enemies=1)
    small = next(rid for rid in g.world.order if g.info(rid).pop0 <= 10)
    big = next(rid for rid in g.world.order if g.info(rid).pop0 > 60)
    _own(g, 0, [small, big])
    rs, rb = g.regions[small], g.regions[big]
    p0 = g.info(small).pop0
    rs.pop = p0 * 1.99
    assert g.crowd_penalty(rs) == 0
    rs.pop = p0 * 2.0
    assert g.crowd_penalty(rs) == -2
    rs.pop = p0 * 2.5
    assert g.crowd_penalty(rs) == -4
    q0 = g.info(big).pop0
    rb.pop = q0 * 1.4
    assert g.crowd_penalty(rb) == -2
    rb.pop = q0 * 1.5
    assert g.crowd_penalty(rb) == -4
    h = g.eff_happy(rb)
    rb.pop = q0
    assert g.eff_happy(rb) == pytest.approx(h + 4)


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
    f.auto_energy = True                                       # AI 방식: 매 턴 자동, 군 생산용 석유는 남긴다
    f.res.update(coal=3, oil=C.AUTO_OIL_RESERVE + 1)
    plan = g.energy_plan(0)
    assert plan["plants"]["S002"] == {"coal": 1, "oil": 1, "elec_out": 6}   # 발전소에 석유 먼저, 그다음 석탄
    fu = plan["factories"]["S002"]
    assert fu["units"] == 3 and fu["elec"] == 3                # 공장은 전기부터
    assert plan["after"]["oil"] == C.AUTO_OIL_RESERVE
    after = dict(plan["after"])
    g._phase_resources(f)
    assert {k: f.res[k] for k in C.ENERGY} == pytest.approx(after)    # 미리보기 = 실제 처리
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
    f.res.update(coal=50, oil=50, elec=50)                     # 재고는 배정에 쓰지 않는다
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
    assert plan["plants"]["S002"] == {"coal": 2, "oil": 0, "elec_out": 4}
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
    assert cv.air_used() == 4 and cv.air_cap() == 4


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
    assert C.SCIENCE_COST_PER_TURN == 100_000


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
    assert science_progress_text(g, 0) == "2/8 · 예산 편성 진행(은행 5단계 지역)"
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
    assert (C.MARKET_BUY["elec"], C.MARKET_SELL["elec"], C.MARKET_SELL["food"]) == (20, 10, 3)
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
    assert not ok and "수송 칸" in msg
    cv = g.new_army(0, port, {"cv": 1})
    air = g.new_army(0, port, {"ftr": 2, "bmb": 1})
    assert g.boarding_target(air.id) is cv
    assert g.board(air.id)[0] and cv.units == {"cv": 1, "ftr": 2, "bmb": 1}


def test_production_level_names():
    g = new_game(player_start="S002", n_enemies=1)
    assert g.build_label("S002", "factory", 5) == "공업 단지 건설"
    assert g.build_label("S002", "farm", 3) == "농장 건설"
    assert g.build_label("S002", "fishery", 1) == "낚시터 건설"
    assert g.build_label("S002", "bank", 4) == "은행 본사 건설"
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
    g = new_game(n_enemies=2)
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
    # 자원 선물은 주는 쪽의 시장 판매가로 환산
    offer = D.empty_offer()
    offer["give"]["food"] = 100
    assert D.gift_value(g, offer["give"], 0) == pytest.approx(100 * g.sell_price(0, "food"))
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
    assert g.food_prod(0, r) == pytest.approx(R.food_output(3 * 1.15, r.b["fishery"], g.fish_mult(0, cap)))
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
    before = g.player.specialty.get(C.TRIBUTE_SPECIALTY, 0)
    g._phase_resources(g.player)
    got = g.player.specialty.get(C.TRIBUTE_SPECIALTY, 0) + sum(
        1 for r in g.regions_of(0) if C.TRIBUTE_SPECIALTY in r.supplied) - before
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


# ---------------------------------------------------------------- v1.20.0 패치
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
    g.turn = 12
    assert g.calc_output("S002", full=True) == pytest.approx(y * 0.8)
    g.turn = 13
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
    g = new_game(player_start="S002", n_enemies=1)
    fid = 1
    f = g.factions[fid]
    _neutral_ai(g, fid)
    f.ai.update(phase=1, free=1.0, weights={"military": 0.5, "economy": 1, "expansion": 1, "defense": 1})
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
    g = Game(Settings(n_enemies=n, seed=7, all_ai=True))
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
    """경제 점수는 '돈'(반기 랭킹 GDP 순위)을 따른다: 1위 ×1.2 → 꼴찌 ×0.4, 1~2위가 다음 단계를 감당하면 ×1.25."""
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
    assert first > 3 * last                          # 순위 배수 1.2/0.4 = 3배에 계단 가점까지
    f.last["tax"] = 10 ** 7                         # 다음 단계를 순수입으로 감당할 수 있다
    assert ST.path_scores(g, f, {})["scores"]["economic"] == pytest.approx(first * C.AI_P2_ECON_RICH, rel=0.01)
    assert "감당 가능" in ST.path_scores(g, f, {})["why"]["economic"]


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
    g = Game(Settings(n_enemies=3, seed=7, all_ai=True))
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
