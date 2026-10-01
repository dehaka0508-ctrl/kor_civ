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
    assert sum(1 for a in g.armies.values() if a.owner == NEUTRAL) == 424 - 4
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


def test_market_price_rises():
    g = new_game()
    p0 = g.buy_price(0, "oil")
    g.market_buy(0, "oil", 1)
    assert g.buy_price(0, "oil") == pytest.approx(p0 * 1.1)
    assert g.buy_price(0, "food") == g.buy_price(0, "food")


def test_tax_lock_jeongjo():
    g = new_game(player_leader="jeongjo")
    assert g.set_tax(0, 0.15)[0]
    ok, _ = g.set_tax(0, 0.12)
    assert not ok


def test_war_and_peace():
    g = new_game(n_enemies=2)
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
    r.landmark = True
    pop, b = r.pop, dict(r.b)
    g.start_project(0, rid, "build", "farm")
    msg = _fail_suppression(g, 0, rid)
    nf = g.factions[-1]
    assert "분리독립" in msg
    assert r.owner == nf.id and nf.capital == rid and nf.rebel_of == 0
    assert r.pop == pop and r.b == b and r.landmark
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
    assert low.h_delta == 2 * C.SPECIALTY_HAPPY
    # 수동: 가장 행복한 지역에 '가' 고정, 낮은 지역은 '나' 제외
    high = max(regs, key=lambda r: r.happy)
    g.set_specialty(0, high.id, "가", "pin")
    g.set_specialty(0, low.id, "나", "block")
    f.specialty = {"가": 1, "나": 1}
    for r in regs:
        r.h_delta = 0
    g._distribute_specialties(f, regs)
    assert "가" in high.supplied and "나" not in low.supplied
    assert low.h_delta == -2 * C.SPECIALTY_HAPPY  # 두 종류 모두 중단


def test_landmark_naming():
    g = new_game(player_start="S002", n_enemies=1)
    n = g.world.name_to_id
    assert g.default_landmark_name(n["경북 안동시"]) == "안동 타워"
    assert g.default_landmark_name(n["부산 북구"]) == "북구 타워"
    assert g.default_landmark_name(n["서울 중구"]) == "중구 타워"
    assert g.default_landmark_name(n["세종시"]) == "세종 타워"
    ok, msg = g.start_project(0, "S002", "landmark", "landmark", name="테헤란 타워")
    assert ok and "테헤란 타워" in msg
    p = g.regions["S002"].project
    g.regions["S002"].project = None
    g._complete_project(g.player, g.regions["S002"], p)
    assert g.regions["S002"].landmark and g.regions["S002"].landmark_name == "테헤란 타워"
    g.regions["S002"].landmark = False
    ok, _ = g.start_project(0, "S002", "landmark", "landmark")
    assert g.regions["S002"].project.name == "강남 타워"


def test_production_focus_bonus():
    g = new_game(player_start="S002", n_enemies=1)
    r = g.regions["S002"]
    base = g.calc_output("S002", phi=1.0)
    g.set_focus(0, "S002", True)
    assert g.calc_output("S002", phi=1.0) == pytest.approx(base + 30 * r.pop * C.FOCUS_POP_BONUS)
    g.start_project(0, "S002", "build", "farm")          # 건설 중에는 효과 없음
    assert g.calc_output("S002", phi=1.0) == pytest.approx(base)
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
    g = new_game(n_enemies=2, ai_leaders=["sejong", "jeongjo"])   # 우호도 효과가 없는 지도자
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
    ai_f.aggression, ai_f.gov = aggr, gov
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
        r.happy = -10.0
    AI._consider_war(g, f)
    assert not D.at_war(g, 0, 1)      # 하지만 민심(실질 행복도 −10)이 전쟁 피로를 견디지 못할 전망이면 참는다
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
    assert len(keys) == len(set(keys)) == len(LEADERS) - 1 == 38
    assert LEADER_BY_KEY["jumong"]["name"] == "동명성왕" and LEADER_BY_KEY["sejong"]["name"] == "세종대왕"
    for l in LEADERS:
        assert len(l["fx"]) >= (0 if l["key"] == "custom" else 2)
    # 새 지도자로 게임을 시작해도 효과가 적용된다
    g = new_game(player_start="S002", n_enemies=5, player_leader="yisunsin",
                 ai_leaders=["yangdi", "kublai", "hideyoshi", "hongtaiji", "terauchi"])
    assert g.mods(0).mult("def_coast") == pytest.approx(1.2)
    assert {f.leader for f in g.factions} == {"yisunsin", "yangdi", "kublai", "hideyoshi", "hongtaiji", "terauchi"}


def test_landmark_cost_grows():
    g = new_game(player_start="S002", n_enemies=1)
    opt = next(o for o in g.options(0, "S002") if o["kind"] == "landmark")
    base = opt["per_turn"]
    assert base == pytest.approx(C.LANDMARK_COST_PER_TURN)
    others = [r for r in g.world.order if g.regions[r].owner == NEUTRAL][:7]
    _own(g, 0, others)
    for rid in others:
        g.regions[rid].landmark = True
    opt = next(o for o in g.options(0, "S002") if o["kind"] == "landmark")
    assert opt["per_turn"] == pytest.approx(base * 1.2 ** 7)   # 8번째 랜드마크 ≈ 3.6배


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
    base = g.calc_output("S002", phi=1.0)
    r.happy = -100
    assert g.calc_output("S002", phi=1.0) == pytest.approx(base * 0.7)


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
