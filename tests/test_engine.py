import math
import pickle

import pytest

from korciv import config as C
from korciv import diplomacy as D
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
    g._phase_projects(("build",))
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
    assert g.regions[g.player.capital].h_delta <= -10
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
