"""지도자 개편: 실제 비용·경계·역사·저항·생산·저장 검증."""
import math
import pickle

import pytest

from korciv import config as C, diplomacy as D, rules as R
from korciv.game import Game
from korciv.leaders import LEADERS, Mods
from korciv.state import Settings, Project


def game(key="cus", enemies=1):
    g = Game(Settings(seed=61, player_start="S002", ai_starts=["N001"], n_enemies=enemies,
                      player_leader=key, ai_leaders=["cus"] * enemies, victories=("time",)))
    g.player.money = g.player.admin = g.player.sci_points = 1e7
    g.player.res["food"] = 1e7
    for f in g.factions:
        f.is_ai = False
    return g


def leader(g, key):
    g.player.leader = key
    g._mods.clear()
    g._morale.clear()


def own(g, rid, fid=0):
    g.transfer_region(rid, fid, reason="편입")
    r = g.regions[rid]
    r.resist = None
    r.pop, r.happy = 1, 20
    r.b["housing"] = 5
    for a in list(g.armies_at(rid)):
        if a.owner != fid:
            g.remove_army(a)
    return r


@pytest.mark.parametrize("key", [l["key"] for l in LEADERS])
def test_every_leader_turn_and_save(key):
    g = game(key)
    g.end_turn()
    loaded = pickle.loads(pickle.dumps(g))
    assert loaded.player.leader == key
    assert loaded.player.original_regions
    assert all(math.isfinite(f.money) for f in loaded.factions)


def test_fleet_disband_preserves_transport_capacity():
    g = game()
    sea = next(iter(g.world.seas))
    fleet = g.new_army(0, sea, {"dd": 1, "lst": 1, "inf": 1})
    assert not g.disband(fleet.id, {"lst": 1})[0]
    assert fleet.units == {"dd": 1, "lst": 1, "inf": 1}
    assert g.disband(fleet.id, {"inf": 1, "lst": 1})[0]
    assert fleet.units == {"dd": 1}


def test_sinking_last_transport_removes_cargo_and_stale_damage():
    g = game()
    sea = next(iter(g.world.seas))
    fleet = g.new_army(0, sea, {"lst": 1, "inf": 2})
    fleet.dmg["inf"] = 3
    g.apply_damage([fleet], 1e9, unit_filter=("lst",))
    assert fleet.id not in g.armies
    fleet = g.new_army(0, sea, {"dd": 1, "inf": 1})
    fleet.dmg["inf"] = 4
    g._validate_capacity(fleet)
    assert fleet.units == {"dd": 1} and "inf" not in fleet.dmg


def test_general_escort_follows_moves_merges_and_disband():
    g = game()
    cap = g.player.capital
    target = next(r for r in g.world.land_adj[cap] if g.regions[r].owner == -1)
    for a in list(g.armies_at(target)):
        g.remove_army(a)
    a = g.new_army(0, target, {"inf": 2})
    gp = dict(id=1, owner=0, kind="general", name="을지문덕", loc=target, escort=a.id)
    g.great_people.append(gp)
    b = g.new_army(0, target, {"inf": 1})
    assert g.merge_armies(b.id, a.id)[0]
    assert gp["escort"] == b.id
    g._exec_move(b, [cap])
    assert gp["loc"] == cap
    g._exec_move(b, [target])
    assert gp["loc"] == target
    assert g.disband(b.id, dict(b.units))[0]
    assert gp not in g.great_people


def test_dangun_scenery_crowding_and_oil():
    g = game("dan")
    rid = next(r for r in g.world.order if g.info(r).scenic)
    r = own(g, rid)
    assert g.scenic_bonus(r) >= 10
    r.pop = g.crowd_thresholds(rid)[1] * 2             # 과밀 −4 문턱의 두 배여도
    assert g.crowd_penalty(r) == 0
    assert g.unit_oil(0, "inf") == 0
    for key in ("tank", "lst", "dd", "cv", "ftr", "bmb"):
        assert g.unit_oil(0, key) == g.unit_spec(0, key)["oil"] + 1


def test_ranges_timing_and_academy_radius():
    g = game("jum")
    cap = g.player.capital
    target = next(iter(g.land_within(cap, 3) - g.land_within(cap, 2)))
    army = g.new_army(0, cap, {"art": 1})
    assert g._bombard_units(army, target).get("art") == 1
    assert g.build_time(0, "port", 3, cap) == 4
    assert g.unit_turns(0, "dd") == 4
    leader(g, "yis")
    assert g.naval_bomb_range(0) == C.NAVAL_BOMB_RANGE + 1
    g.player.naval_off_until = g.turn + 4
    assert g.naval_bomb_range(0) == C.NAVAL_BOMB_RANGE
    g.turn += 4
    assert g.naval_bomb_range(0) == C.NAVAL_BOMB_RANGE + 1
    leader(g, "jin")
    site = next(iter(g.land_within(cap, 2) - g.land_within(cap, 1)))
    own(g, site)
    g.regions[cap].b["academy"] = 1
    assert g.unit_cost(0, site, "inf") == 250 * C.MONEY_SCALE * .9


def test_river_construction_and_joint_annex_costs():
    g = game("onz")
    river = next(iter(g.world.river_regions))
    assert g.build_time(0, "bank", 8, river, 4) == 6
    leader(g, "egg")
    target = next(r.id for r in g.regions.values() if r.owner == -1)
    base = g.annex_cost(0, target)
    assert g.annex_cost(0, target, 2) == pytest.approx(base * .6)
    assert g.annex_cost(0, target, 5) == 0
    before = g.player.war_weary
    D._start_war(g, 0, 1, aggressor=0)
    assert g.player.war_weary - before == C.WAR_WEARY_START["aggressor"] + 5


def test_mountain_attack_and_boundary_defense():
    g = game()
    (source, target), _ = next((pair, t) for pair, t in g.world.terrain.items() if t["kind"] == "돌파")
    own(g, source)
    own(g, target, 1)
    leader(g, "dae")
    assert g.leader_attack_mult(0, source, target, {"inf": 1}) == 1.25
    leader(g, "kgc")
    dd, ad = g._leader_battle_mods(1, 0, [], [], source, target, 10, 10)
    assert (dd, ad) == (10, 15)


def test_wanggeon_resistance_and_gungye_weariness():
    g = game("wan")
    target = next(iter(g.world.land_adj[g.player.capital]))
    own(g, target, 1)
    g.complete_occupation(0, target)
    r = g.regions[target]
    assert r.resist["resist"] == 2 and r.resist["recover"] == C.RESIST_RECOVER_TURNS
    assert g.base_happy(r) == -50
    r.resist = None
    r.happy = 0
    leader(g, "gun")
    g.player.war_weary = 30
    assert g.eff_happy(r) == pytest.approx(g.growth_happy(r))
    assert g.rebel_happy(r) < g.eff_happy(r)


def test_relocation_and_resource_negotiation_limits():
    from korciv import negotiation as N
    g = game()
    site = own(g, sorted(g.world.land_adj[g.player.capital])[0])
    base = next(o for o in g.options(0, site.id) if o["kind"] == "capital")
    leader(g, "tae")
    opt = next(o for o in g.options(0, site.id) if o["kind"] == "capital")
    assert opt["cost"] == base["cost"] / 2 and opt["turns"] == 2
    leader(g, "kim")
    assert not D.resource_trade_allowed(g, 0, 1)
    assert N.start(g, 1, 0, "food", 1, True)["status"] == "refused"
    for key in ("factory", "extract", "power"):
        assert g.build_time(0, key, 8, site.id, 4) == 6


def test_capture_healing_population_and_multiwar_defense():
    g = game("ggt", enemies=2)
    target = sorted(g.world.land_adj[g.player.capital])[0]
    r = own(g, target, 1)
    r.pop = 100
    a = g.new_army(0, target, {"inf": 2})
    a.dmg["inf"] = 8
    g.complete_occupation(0, target)
    assert r.pop == 90 and a.dmg["inf"] == 4
    leader(g, "gcg")
    D._start_war(g, 0, 1, aggressor=0)
    D._start_war(g, 0, 2, aggressor=0)
    assert g.unit_spec(0, "inf")["df"] == 8


def test_revenge_history_is_persistent_and_neutral_occupation_only():
    g = game("mur")
    D._start_war(g, 1, 0, aggressor=1)
    assert 1 in g.player.attacked_by
    D.make_peace(g, 0, 1)
    D._start_war(g, 0, 1, aggressor=0)
    assert g.leader_attack_mult(0, g.player.capital, g.factions[1].capital, {"inf": 1}) == 1.15
    target = next(r.id for r in g.regions.values() if r.owner == -1)
    assert g.military_occupation_turns(0, target) == g.neutral_turns(0, target) + 2
    assert 1 in pickle.loads(pickle.dumps(g)).player.attacked_by


def test_gongmin_suppression_has_no_losses_and_twelve_turn_boost(monkeypatch):
    g = game("gon")
    r = g.regions[g.player.capital]
    a = g.new_army(0, r.id, {"inf": 20})
    r.happy = -55
    monkeypatch.setattr(g.rng, "random", lambda: 0)
    g.resolve_rebellion(0, r.id, "suppress")
    assert a.units["inf"] == 20
    assert r.suppress_output_until == g.turn + 12
    assert g.leader_output_mult(r.id) >= 1.25
    assert g.build_time(0, "bank", 10, r.id, 5) == 12


def test_scientist_cost_royal_tithe_and_policy_scaling():
    g = game("sej")
    r = g.regions[g.player.capital]
    r.b["edu"] = 4
    assert g.great_person_cost(0, "scientist") == 300
    site = next(i for i in g.world.order if g.info(i).specialties)
    r = own(g, site)
    r.b["specialty"] = 16
    raw = sum(rr.b["specialty"] * len(g.info(rr.id).specialties) for rr in g.regions_of(0))
    made = g.specialty_made(g.player)
    assert sum(made.values()) == raw - raw // 8
    assert sum(g.player.last["specialty_tithe_items"].values()) == raw // 8
    assert Mods("hae", "absolute", 5).mult("output_money") == pytest.approx(1.07)


def test_focus_release_tech_cost_and_production_counter():
    g = game("pak")
    r = g.regions[g.player.capital]
    g.set_focus(0, r.id, True)
    g.set_focus(0, r.id, False)
    assert r.focus_unrest_until == g.turn + 2
    leader(g, "ahn")
    assert g.focus_multiplier(0) == 2
    assert g.tech_cost(0, "inf") == 960
    assert g.tech_cost(0, "farm") == 1000
    leader(g, "yan")
    assert [g.leader_units_completed(0, r.id, "inf") for _ in range(3)] == [1, 1, 2]
    assert g.building_cost_mult(0, "bank") == 1.1


def test_succession_freeze_defers_queued_start_without_spending_oil():
    g = game("egg")
    r = g.regions[g.player.capital]
    p = Project(kind="unit", key="tank", turns=3, started=False)
    g.player.res["oil"] = 10
    g.turn = 48
    assert not g._activate_project(r.id, p)
    assert not p.started and g.player.res["oil"] == 10
    g.turn = 49
    assert g._activate_project(r.id, p)
    assert p.started and g.player.res["oil"] == 9
    g.turn = 96
    assert g._activate_project(r.id, p)  # 이미 진행 중인 생산은 계속한다.


def test_tank_only_surprise_uses_reworked_sabotage(monkeypatch):
    g = game("kwb")
    cap = g.player.capital
    target = next(r for r in g.world.land_adj[cap] if g.regions[r].owner == -1)
    for army in list(g.armies_at(target)):
        g.remove_army(army)
    g.new_army(-1, target, {"inf": 1})
    a = g.new_army(0, cap, {"tank": 20})
    called = []
    monkeypatch.setattr(g.rng, "random", lambda: 0)
    monkeypatch.setattr(g, "_sabotage", lambda rr, fid: called.append((rr.id, fid)) or "")
    g._ground_battle(0, [a], target, "surprise", [a])
    assert called == [(target, 0)]


def test_free_coastal_ports_and_chancellor_ban():
    g = game("jan")
    coast = [rid for rid in g.world.order if g.info(rid).coastal and g.regions[rid].owner == -1][:5]
    for rid in coast:
        b = g.regions[rid].b
        if b.card(("coast", 0)):
            b.remove(("coast", 0))
    # 건물 슬롯(v1.3.9): 무료 항구는 기타 슬롯에 칸을 붙여 꽂는다 — 해안 슬롯이 차 있어도 받고, 해안 슬롯은 그대로
    full = coast[0]
    g.regions[full].b.place("fishery", 1, ("coast", 0))
    has_port = coast.pop()                                  # 이미 항구가 있는 지역은 건너뛴다(횟수도 안 씀)
    g.regions[has_port].b.place("port", 1, ("coast", 0))
    own(g, has_port)
    assert not g.player.coastal_rewards
    for rid in coast:
        own(g, rid)
    assert len(g.player.coastal_rewards) == 3
    assert [g.regions[rid].b["port"] for rid in coast] == [1, 1, 1, 0]
    b = g.regions[full].b
    assert b.card(("coast", 0)) == {"key": "fishery", "level": 1}
    assert b.slots["etc"][-1] == {"key": "port", "level": 1, "free": True} and b.free_cards() == 1
    b["port"] = 0                                           # 폭격으로 부서지면 붙인 칸째 사라진다
    assert b.free_cards() == 0 and all(c is None or c["key"] != "port" for c in b.slots["etc"])
    leader(g, "jun")
    g.regions[g.player.capital].b["admin"] = 4
    assert not g.can_recruit_great_person(0, "chancellor")[0]


def test_tax_cap_rich_enemy_loot_and_original_land():
    g = game("gil")
    g.set_tax(0, .5)
    assert g.player.tax == .15
    g.regions[g.player.capital].output = 100
    target = g.factions[1].capital
    g.regions[target].output = 10000
    assert g.leader_attack_mult(0, g.player.capital, target, {"inf": 1}) == 1.2
    g.factions[1].money = 1000
    before = g.player.money
    g.leader_battle_win(0, 1)
    assert g.player.money == before + 50 and g.factions[1].money == 950
    leader(g, "kgu")
    g.player.original_regions.add(target)
    g.player.lost_regions.add(target)
    assert g.leader_attack_mult(0, g.player.capital, target, {"inf": 1}) == 1.35


@pytest.mark.parametrize("battle", ("encounter", "naval"))
def test_rich_enemy_loot_in_encounters_and_naval_battles(monkeypatch, battle):
    g = game("gil")
    cap, enemy = g.player.capital, g.factions[1].capital
    g.regions[cap].output, g.regions[enemy].output = 100, 10000
    g.factions[1].money = 1000
    before = g.player.money
    D._start_war(g, 0, 1, aggressor=0)
    monkeypatch.setattr(R, "battle_damage", lambda *args: (1000, 0))
    if battle == "encounter":
        a = g.new_army(0, cap, {"inf": 1})
        b = g.new_army(1, enemy, {"inf": 1})
        a.order, b.order = {"path": [enemy]}, {"path": [cap]}
        g._encounter(a, b)
    else:
        sea = next(iter(g.world.seas))
        a = g.new_army(0, sea, {"dd": 1})
        b = g.new_army(1, sea, {"dd": 1})
        g._naval_battle(sea, 0, [a], 1, [b])
    assert g.player.money == before + 50 and g.factions[1].money == 950


def test_sabotage_levels_pause_and_bomber_probability(monkeypatch):
    g = game("kwb")
    r = g.regions[g.factions[1].capital]
    r.b = dict.fromkeys(r.b, 0)
    r.b["factory"] = 3
    r.econ.add("ifc")
    monkeypatch.setattr(g.rng, "random", lambda: 0)
    g._sabotage(r, 0)
    assert r.b["factory"] == 1 and r.facility_off_until == g.turn + 4
    assert not g.econ_buildings(1, "ifc")
    assert g.bomb_building_probability(0, False, True) == R.bomb_building_chance(False, True) + .2
    g.turn += 4
    assert r.id in g.econ_buildings(1, "ifc")


def test_naval_and_guerrilla_percent_damage_and_stalin_gate():
    g = game("kan")
    fleet = g.new_army(0, next(iter(g.world.seas)), {"lst": 1})
    g.leader_attrition()
    assert fleet.dmg["lst"] == 2
    leader(g, "ito")
    r = g.regions[g.player.capital]
    r.resist = {"turn": g.turn, "from": 1, "resist": 4, "recover": 20}
    a = g.new_army(0, r.id, {"tank": 1})
    g.leader_attrition()
    assert a.dmg["tank"] == 3.5
    assert g.leader_tax_revenue(0) > 0
    leader(g, "sta")
    r.resist = None
    assert not g.building_allowed(0, r.id, "academy", 1)[0]
    assert g.leader_attack_mult(0, r.id, g.factions[1].capital, {"inf": 1, "tank": 1}) == 1.1


def test_mongol_attack_allows_exactly_one_extra_move():
    g = game("kan")
    cap = g.player.capital
    target = next(r for r in sorted(g.world.land_adj[cap]) if g.regions[r].owner == -1)
    for army in list(g.armies_at(target)):
        g.remove_army(army)
    a = g.new_army(0, cap, {"tank": 2})
    g._ground_battle(0, [a], target, "assault", [a])
    assert a.loc == target and not g.army_acted(a.id)
    assert g.act_now(a.id, cap)[0]
    assert a.loc == cap and g.army_acted(a.id)
    assert not g.act_now(a.id, target)[0]


def test_coalition_attack_war_weariness_and_tribute():
    g = game("muy", enemies=2)
    D._start_war(g, 0, 1, aggressor=0)
    assert g.player.war_weary == C.WAR_WEARY_START["aggressor"] * 1.25
    base = D.war_weary_rate(g, 0)
    assert base == C.WAR_WEARY_TURN["aggressor"] * 1.25
    old = g.player.war_weary
    g._phase_happiness()
    assert g.player.war_weary == old + base
    g.dip.coalitions[1] = {"members": {0, 2}}
    g.dip.wars[D.pair(0, 1)]["coalition_declarers"] = {0}
    assert g.leader_attack_mult(0, g.player.capital, g.factions[1].capital, {"inf": 1}) == 1.15
    leader(g, "yyl")
    for r in g.regions_of(0):
        r.b["specialty"] = 0
    D._dip_attr(g, "declared")[D.pair(0, 2)] = g.turn
    assert g.specialty_made(g.player)[C.TRIBUTE_SPECIALTY] == 2


def test_metro_population_tax_and_city_market():
    from korciv import metro as M
    g = game("sur")
    cap = g.player.capital
    sel = [cap] + sorted(g.world.land_adj[cap])[:3]
    for rid in sel:
        r = own(g, rid)
        r.pop = 26
        r.b.update(admin=4, factory=5, bank=5, housing=5)
    assert not M.check(g, 0, cap, sel)[0]
    for rid in sel:
        g.regions[rid].pop = 37.5
    assert g.create_metro(0, cap, sel)[0]
    for rid in sel:
        g.regions[rid].output = 100
    leader(g, "cus")
    baseline = g.leader_tax_revenue(0)
    leader(g, "sun")
    assert g.leader_tax_revenue(0) == pytest.approx(baseline * 1.1)
    leader(g, "jjo")
    assert all(g.leader_bank_mult(0, rid) == 1.25 for rid in sel)


def test_border_group_discount_tax_band_and_peace_minimum():
    g = game()
    cap = g.player.capital
    enemy = own(g, sorted(g.world.land_adj[cap])[0], 1)
    base = g.border_line_plan(0, 1, 3)
    leader(g, "yon")
    plan = g.border_line_plan(0, 1, 3)
    assert plan["total"] == pytest.approx(base["total"] * .75)
    assert plan["turns"] == math.ceil(base["turns_sum"] / base["slots"] * .75)
    leader(g, "tai")
    relief18 = g.tax_happy(0, 18) - R.tax_happiness(18)
    relief25 = g.tax_happy(0, 25) - R.tax_happiness(25)
    assert relief18 == pytest.approx(relief25) and relief18 > 0
    enemy.lines[cap] = 2
    assert g.leader_bomb_mult(0, cap, enemy.id, {"bmb": 1}) == .8
    leader(g, "cho")
    D._start_war(g, 0, 1, aggressor=0)
    assert "20턴" in D.treaty_check(g, 1, 0, "peace")[1]


@pytest.mark.parametrize("mode", C.GAME_MODES)
def test_initial_population_money_and_scientist_site(mode):
    g = Game(Settings(seed=61, mode=mode, player_start="S002", n_enemies=1, player_leader="onz"))
    assert g.regions["S002"].pop == pytest.approx((g.info("S002").pop0 if mode == "standard" else 1) * .85)
    g = Game(Settings(seed=61, mode=mode, player_start="S002", n_enemies=1, player_leader="kgu"))
    assert g.player.money == C.START_MONEY * C.MONEY_SCALE * .9
    leader(g, "sej")
    cap = g.player.capital
    r = own(g, sorted(g.world.land_adj[cap])[0])
    r.b["edu"] = 4
    g.regions[cap].b["edu"] = 0
    g.player.sci_points = 1000
    assert not g.can_recruit_great_person(0, "scientist", cap)[0]
    assert g.recruit_great_person(0, "scientist", r.id)[0]
