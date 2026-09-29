import math
import pickle

import pytest

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
    assert len(g.factions) <= 24
