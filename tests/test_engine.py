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


def test_kimdj_friendship_no_backlash():
    g = new_game(player_start="S002", n_enemies=3, player_leader="kdj")
    g.dip.op[(3, 1)] = -60
    assert all(e[2] > 0 for e in D.friendship_effects(g, 0, 1))


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
    # 2단계: 산맥과 맞닿은 지역에서만, 비용 ×1.2
    mtn = next(r for r in g.world.order if r in g.world.mountain_regions and g.regions[r].owner == NEUTRAL)
    flat = next(r for r in g.world.order if r not in g.world.mountain_regions and g.regions[r].owner == NEUTRAL
                and g.world.land_adj[r])
    _own(g, 0, [mtn, flat])
    assert [o["key"] for o in sci(mtn)] == ["observatory"] and not sci(flat)
    assert sci(mtn)[0]["per_turn"] == pytest.approx(C.SCIENCE_COST_PER_TURN * 1.2)
    # 4·5단계는 공장 5단계, 6단계는 석유 지역
    f.science = ["lab", "observatory", "pad"]
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
    assert g.science_turns(0) == 10                                                # 첨성대
    g = new_game(player_start="S002", n_enemies=1, player_leader="gon")
    assert g.science_step_cost(0, "lab") == pytest.approx(
        C.SCIENCE_COST_PER_TURN * C.SCIENCE_TURNS * 1.25)                          # 영전 공사


def test_production_focus_bonus():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    base = g.calc_output("S002", full=True)
    g.set_focus(0, "S002", True)
    assert g.calc_output("S002", full=True) == pytest.approx(base + 30 * r.pop * C.FOCUS_POP_BONUS)
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


def test_island_annex_needs_landing_ship_in_island_sea():
    g = new_game(player_start="S002", n_enemies=1)
    n = g.world.name_to_id
    busan, jeju_s = n["부산 중구"], n["제주 서귀포시"]
    _own(g, 0, [busan])
    g.regions[busan].b["port"] = 1
    # 항구가 있어도 같은 해역(남동해) 해로만으로는 제주·울릉을 편입할 수 없다
    assert jeju_s not in {t["target"] for t in g.annex_targets(0, busan)}
    fleet = g.new_army(0, "SEA4", {"lst": 1})
    assert jeju_s not in {t["target"] for t in g.annex_targets(0, busan)}
    fleet.loc = "SEA8"                          # 제주도 연안에 상륙함
    assert jeju_s in {t["target"] for t in g.annex_targets(0, busan)}
    assert n["경북 울릉군"] not in {t["target"] for t in g.annex_targets(0, busan)}


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
    g = new_game(n_enemies=2, ai_leaders=["sej", "jjo"])   # 우호도 효과가 없는 지도자
    g.factions[1].gov, g.factions[2].gov = "absolute", "socialist"
    g.dip.op[(1, 2)] = 0.0
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
    assert g.player.war_weary == pytest.approx(15.75)      # 선포 +15, 전쟁 중 턴당 +0.75
    assert g.factions[1].war_weary == pytest.approx(10.5)  # 당한 쪽 +10, 턴당 +0.5
    assert g.eff_happy(cap) == pytest.approx(-15.75)       # 실질 행복도 = 행복도 − 전쟁 피로도
    assert g.avg_happiness(0) == pytest.approx(-15.75) and g.avg_happiness(0, effective=False) == pytest.approx(0)
    for _ in range(300):
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
    assert D.war_weary_rate(g, 0) == pytest.approx(0.75)
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
    assert len(keys) == len(set(keys)) == len(LEADERS) - 1 == 39
    assert LEADER_BY_KEY["jum"]["name"] == "동명성왕" and LEADER_BY_KEY["sej"]["name"] == "세종대왕"
    for l in LEADERS:
        assert len(l["fx"]) >= (0 if l["key"] == "cus" else 2)
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
    assert costs[-1] == pytest.approx(costs[0] * 1.2 ** 5)    # 6단계 ≈ 2.5배


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
    assert g.regions["S002"].resist["resist"] == 6


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
    f.res.update(coal=3, oil=C.AUTO_OIL_RESERVE + 1)
    plan = g.energy_plan(0)
    p = plan["plants"]["S002"]
    assert p == {"coal": 2, "oil": 0, "elec_out": 4}           # 석탄부터 발전소에(석유는 아낀다)
    fu = plan["factories"]["S002"]
    assert fu["units"] == 3                                    # 공장 3단계 = 연료 3개
    # 발전소 용량이 모자라면 석탄 칸을 석유로 바꿔 전기를 더 만든다
    r.b["power"] = 1
    plan2 = g.energy_plan(0)
    assert plan2["plants"]["S002"]["oil"] == 1 and plan2["factories"]["S002"]["units"] == 3
    assert plan2["after"]["oil"] == C.AUTO_OIL_RESERVE         # 군 생산용 석유는 남긴다
    r.b["power"] = 2
    plan = g.energy_plan(0)
    after = dict(plan["after"])
    g._phase_resources(f)
    assert {k: f.res[k] for k in C.ENERGY} == pytest.approx(after)    # 미리보기 = 실제 처리
    assert r.fuel_used == 3
    assert r.output == pytest.approx(g.calc_output("S002", full=True))


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
    assert R.econ_share(8) == pytest.approx(0.5) and R.econ_share(6) == pytest.approx(0.6)
    g = new_game(player_start="S002", n_enemies=7)
    assert g.econ_share_needed() == pytest.approx(0.5)
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


def test_dangun_war_weary_recovery():
    for lk, rec in (("cus", 1.0), ("dan", 1.5)):
        g = new_game(player_start="S002", n_enemies=1, player_leader=lk)
        g.player.war_weary = 10.0
        g._phase_happiness()
        assert g.player.war_weary == pytest.approx(10.0 - rec)
