"""행정·정책·연구·위인의 자원 보존, 해금 경계, 점령 및 저장 회귀."""
import pickle
from dataclasses import replace

import pytest

from korciv import config as C, diplomacy as D, metro as M, rules as R
from korciv.game import Game
from korciv.leaders import Mods, POLICIES, POLICY_COSTS, ai_pick_government
from korciv.progression import TECHS, GP_POOLS
from korciv.state import Settings, Project


def game(mode="standard", gov=None):
    g = Game(Settings(seed=41, mode=mode, player_start="S002", ai_starts=["N001"],
                      n_enemies=1, player_leader="cus", ai_leaders=["cus"]))
    if gov is not None:
        assert g.set_player_government(gov)[0]
    g.factions[1].is_ai = False
    g.player.money = 1e9
    g.player.admin = g.player.sci_points = 1e6
    g.player.res["food"] = 1e6
    return g


def own(g, rid):
    g.transfer_region(rid, 0, reason="편입")
    g.regions[rid].resist = None
    for a in list(g.armies_at(rid)):
        if a.owner != 0:
            g.remove_army(a)
    return g.regions[rid]


def policy(g, gov, n):
    g.player.admin = max(g.player.admin, 10000)
    g.player.gov = gov
    g.player.policy_level = 0
    g._mods.clear()
    for _ in range(n):
        assert g.unlock_policy(0)[0]


def empty(r):
    r.b = dict.fromkeys(r.b, 0)
    r.project = None
    r.queue = []
    r.happy = 0


@pytest.mark.parametrize("mode", C.GAME_MODES)
def test_initial_admin_edu_layout(mode):
    g = Game(Settings(mode=mode, seed=41, player_start="S002", n_enemies=1))
    expected = 2 if mode == "standard" else 0
    assert g.regions["S002"].b["admin"] == expected
    assert g.player.admin == (g.regions["S002"].pop * 10 if mode == "standard" else 10)
    assert {r.id for r in g.regions.values() if r.b["edu"]} == (set(C.INITIAL_EDU) if mode == "standard" else set())
    if mode != "standard":
        capitals = {f.capital for f in g.factions}
        assert not any(r.b["admin"] for r in g.regions.values() if r.id not in capitals)


@pytest.mark.parametrize("gov", POLICIES)
def test_policy_sequential_cost_and_completion(gov):
    g = game(gov=gov)
    start = g.player.admin
    assert not any(Mods("cus", gov).fx)
    for level, cost in enumerate(POLICY_COSTS, 1):
        assert g.unlock_policy(0)[0]
        assert g.player.policy_level == level
        assert g.player.admin == start - sum(POLICY_COSTS[:level])
    assert not g.unlock_policy(0)[0]
    assert g.player.admin == start - sum(POLICY_COSTS)


def test_admin_deficit_grace_and_recovery_resistance():
    g = game()
    r = g.regions[g.player.capital]
    r.b["admin"], r.pop, g.player.admin = 0, 10, 0
    for turn in range(1, 5):
        g._phase_knowledge(g.player)
        assert g.player.lawless == (turn == 4)
    assert r.h_delta == -5
    r.b["admin"] = 3
    g._phase_knowledge(g.player)
    assert not g.player.lawless and g.player.admin == 20
    r.resist = {"turn": g.turn, "from": 1, "resist": 4, "recover": 20}
    assert g.admin_output(r.id) == 0
    assert g.admin_consumption(r.id) == 5
    r.resist = None
    policy(g, "constitutional", 1)
    r.b["admin"], g.player.admin = 0, 0
    own(g, sorted(g.world.land_adj[r.id])[0]).pop = 50  # 집무실보다 소비가 커야 적자
    for _ in range(5):
        g._phase_knowledge(g.player)
    assert not g.player.lawless
    g._phase_knowledge(g.player)
    assert g.player.lawless


def test_admin_edu_costs_and_adjacent_reservations():
    g = game()
    rid = g.player.capital
    a = g.regions[rid]
    b = own(g, sorted(g.world.land_adj[rid])[0])
    empty(a)
    empty(b)
    a.pop = b.pop = 1
    for k, base in (("admin", 800), ("edu", 1000)):
        o = next(o for o in g.options(0, rid) if o["kind"] == "build" and o["key"] == k)
        assert o["cost"] == base * C.BUILD_COST_MULT
        assert o["turns"] == 2
    a.b["admin"] = b.b["admin"] = 3
    assert g.start_project(0, rid, "build", "admin")[0]
    assert not g.start_project(0, b.id, "build", "admin")[0]
    g.cancel_project(0, rid)
    assert g.start_project(0, b.id, "build", "admin")[0]
    assert not g.building_allowed(0, b.id, "edu", 5)[0]


@pytest.mark.parametrize("key", list(TECHS)[:8])
def test_modernization_applies_existing_armies_and_damage(key):
    g = game()
    a = g.new_army(0, g.player.capital, {key: 2})
    old = a.spec(key)
    a.dmg[key] = old["hp"] / 2
    assert g.unlock_tech(0, key)[0]
    spec = g.unit_spec(0, key)
    assert a.hp_max(key) == 2 * spec["hp"]
    assert a.dmg[key] == spec["hp"] / 2
    assert not g.unlock_tech(0, key)[0]
    assert g.factions[1].techs == set()


def test_technology_construction_gates_and_atomic_science_funding():
    g = game()
    r = g.regions[g.player.capital]
    empty(r)
    r.pop = 1
    r.b["bank"] = 3
    slot = r.b.primary("bank")                      # 그 시장 카드를 4단계로(빈 칸 신축은 기술 없이 된다)
    assert not g.start_project(0, r.id, "build", "bank", slot=slot)[0]
    assert g.unlock_tech(0, "bank")[0]
    assert g.start_project(0, r.id, "build", "bank", slot=slot)[0]
    g.cancel_project(0, r.id)
    assert not g.science_site_ok(0, r.id, "lab")
    assert g.unlock_tech(0, "aerospace")[0]
    assert g.start_project(0, r.id, "science", "lab")[0]
    p = r.project
    before = g.player.money
    g.player.sci_points = 199
    g._fund_projects()
    assert not p.funded and p.paid == 0 and g.player.money == before
    g.player.sci_points = 200
    g._fund_projects()
    assert p.funded and p.paid == p.per_turn and g.player.sci_points == 0
    g._phase_projects(("science",))
    assert p.progress == 1


def test_gp_pool_costs_actions_and_no_duplication_after_save():
    g = game()
    r = g.regions[g.player.capital]
    r.b.update(admin=4, edu=4, specialty=3, academy=1)
    assert [len(GP_POOLS[k]) for k in ("scientist", "chancellor", "general", "artist")] == [22, 24, 25, 33]
    for count, cost in enumerate((600, 1000, 1500, 2200, 3000)):
        assert g.great_person_cost(0, "scientist") == cost
        assert g.recruit_great_person(0, "scientist")[0]
    assert len(g.spawned_great_people) == 5
    assert g.science_output(r.id) == pytest.approx(6 * r.pop * (1 + .3 * 5))
    g = pickle.loads(pickle.dumps(g))
    assert len({p["name"] for p in g.great_people}) == 5
    scientist = g.great_people[0]
    r = g.regions[g.player.capital]
    r.project = Project("build", "edu", level=5, turns=10)
    assert g.activate_great_person(scientist["id"])[0]
    assert r.project.remaining == 5
    assert g.recruit_great_person(0, "chancellor")[0]
    p = g.great_people[-1]
    assert g.admin_output(r.id) == 80
    r.project = Project("build", "admin", level=5, turns=10, progress=2, paid=40)
    assert g.activate_great_person(p["id"])[0]
    assert r.project.remaining == 4 and r.project.paid == 40
    assert g.recruit_great_person(0, "artist")[0]
    g.player.war_weary = 20
    r.happy = 0
    assert g.activate_great_person(g.great_people[-1]["id"])[0]
    assert r.happy == 33 and g.player.war_weary == 10


def test_special_metro_admin_edu_and_noncenter_capital():
    g = game()
    cap = g.player.capital
    neighbors = sorted(g.world.land_adj[cap])[:3]
    for rid in neighbors:
        own(g, rid)
    sel = [cap] + neighbors
    for rid in sel:
        r = g.regions[rid]
        r.pop, r.happy = 26, 10
        r.b.update(admin=3, edu=4, farm=0, fishery=0, factory=5, bank=5, housing=5)
    # 식량 수지가 적자여도 행정 수지가 흑자면 지정할 수 있다.
    assert g.create_metro(0, neighbors[0], sel)[0]
    m = M.of(g, cap)
    assert m["special"] and g.admin_balance(0)[0] == 120
    for rid in sel:
        g.regions[rid].b["admin"] = g.regions[rid].b["edu"] = 5        # 광역 슬롯: 중심의 광역 카드만 바뀐다
    assert g.admin_balance(0)[0] == 50 * 4 + 100
    assert g.science_production(0) == 6 * 104 + 500
    policy(g, "constitutional", 5)
    assert M.def_mult(g, cap) == 1


def test_capital_capture_resistance_downgrade_retake_refunds():
    g = game()
    cap = g.player.capital
    temp = own(g, sorted(g.world.land_adj[cap])[0])
    original = g.regions[cap]
    original.b.update(admin=5, edu=5)
    g.dip.wars[D.pair(0, 1)] = {"start": g.turn, "declarer": 1, "score": {}}
    g.complete_occupation(1, cap)
    assert g.player.capital == temp.id
    assert original.b["admin"] == 5 and g.admin_output(cap) == 0
    assert g.player.lost_capital["rid"] == cap
    g.turn += original.resist["resist"]
    g._settle_government_buildings()
    assert original.b["admin"] == original.b["edu"] == 4
    temp.b.update(admin=4, edu=5)
    temp.project = Project("build", "admin", level=5, turns=10, paid=123, site=temp.id)
    temp.queue = [Project("build", "edu", level=5, turns=10, paid=45, site=temp.id)]
    before = g.player.money
    g.complete_occupation(0, cap)
    assert g.player.capital == cap
    assert original.b["admin"] == original.b["edu"] == 5
    assert temp.b["edu"] == 4 and temp.project is None and not temp.queue
    assert g.player.money == before + 168


def test_occupied_prefecture_grace_and_expiry():
    g = game()
    cap = g.player.capital
    adjacent = own(g, sorted(g.world.land_adj[cap])[0])
    g.regions[cap].b["admin"] = 4
    adjacent.b["admin"] = 4
    adjacent.occupied_admin = {"fid": 1, "turn": g.turn}
    g.turn += 35
    g._settle_government_buildings()
    assert adjacent.b["admin"] == 4
    g.turn += 1
    g._settle_government_buildings()
    assert adjacent.b["admin"] == 3


def test_policy_cost_output_combat_and_repair_hooks():
    g = game()
    r = g.regions[g.player.capital]
    r.b.update(admin=3, edu=3, bank=3, factory=3)
    base = g.calc_output(r.id, full=True)
    policy(g, "presidential", 5)
    assert g.calc_output(r.id, full=True) > base
    assert g.building_cost_mult(0, "bank", 1) == .85
    r.flooded = True
    assert g.start_project(0, r.id, "repair", "flood")[0]
    assert not r.flooded and r.project is None
    policy(g, "fascist", 5)
    before = r.h_delta
    assert g.start_project(0, r.id, "unit", "inf")[0]
    assert r.h_delta == before
    g.cancel_project(0, r.id)
    assert r.h_delta == before
    assert g.mods(0).value("rebel_threshold") == -70
    policy(g, "socialist", 5)
    assert g.power_elec(0, "coal", 3) == pytest.approx(2.4 * 1.2)
    r.mil_hist = (1 << 7) - 1
    g._phase_conscription({r.id})
    assert r.conscript == 0


def test_general_battle_bonus_and_death():
    g = game()
    rid = g.player.capital
    r = g.regions[rid]
    r.b["academy"] = 1
    assert g.recruit_great_person(0, "general")[0]
    assert g.great_person_bonus(rid, "attack_mult") == 1.2
    assert g.recruit_great_person(0, "general")[0]
    assert g.great_person_bonus(rid, "attack_mult") == 1.2
    troops = g.armies_at(rid, 0)
    g.apply_damage(troops, 1e9)
    assert not g.great_people


def test_civilian_passives_stack_but_general_is_capped():
    g = game()
    rid = g.player.capital
    g.regions[rid].b.update(admin=4, edu=4, academy=1)
    for kind in ("scientist", "chancellor", "general"):
        assert g.recruit_great_person(0, kind)[0]
        assert g.recruit_great_person(0, kind)[0]
    assert g.great_person_bonus(rid, "science_mult") == 1.6
    assert g.great_person_bonus(rid, "admin_add") == 60
    assert g.great_person_bonus(rid, "output_mult") == 1.3
    assert g.great_person_bonus(rid, "attack_mult") == 1.2
    assert g.great_person_bonus(rid, "defense_mult") == 1.25


def test_save_migration_and_invalid_ids():
    g = game()
    state = g.__getstate__()
    for name in ("great_people", "spawned_great_people", "great_people_bought", "next_great_person_id"):
        state.pop(name)
    for f in state["factions"]:
        for name in ("admin", "sci_points", "techs", "policy_level"):
            f.__dict__.pop(name, None)
    for r in state["regions"].values():
        r.b.pop("admin", None)
        r.b.pop("edu", None)
    loaded = Game.__new__(Game)
    loaded.__setstate__(state)
    assert loaded.great_people == []
    assert all("admin" in r.b and "edu" in r.b for r in loaded.regions.values())
    assert not loaded.unlock_policy(-1)[0]
    assert not loaded.unlock_tech(999, "inf")[0]
    assert not loaded.recruit_great_person(0, "unknown")[0]
    assert not loaded.move_great_person(99, "S002")[0]


def test_ai_uses_economic_environment_instead_of_aggression():
    import random
    from korciv.ai_progression import education_centers, science_reserve, tech_order
    assert ai_pick_government(random.Random(1), 1, 4, 1, leader_key="cus") == ai_pick_government(random.Random(1), 10, 4, 1, leader_key="cus")
    g = game()
    assert g.player.capital in education_centers(g, 0)
    r = g.regions[g.player.capital]
    r.project = Project("science", "lab", turns=15)
    assert science_reserve(g, 0) == 3000  # 산출이 없으므로 완공까지 납부할 과학력을 보전한다.
    g.player.ai["victory_goal"] = "science"
    order = tech_order(g, g.player)
    assert set(order) <= set(TECHS) and len(order) == len(set(order))


def test_legacy_damage_ratio_and_military_power_upgrade():
    g = game()
    a = g.new_army(0, g.player.capital, {"tank": 2, "ftr": 2})
    a.dmg = {"tank": 25, "ftr": 15}  # 이전 버전 체력의 절반 피해
    state = g.__getstate__()
    state.pop("great_people")
    loaded = Game.__new__(Game)
    loaded.__setstate__(state)
    army = loaded.armies[a.id]
    assert army.dmg == {"tank": 17.5, "ftr": 12.5}
    before = loaded.mil_power(0)
    assert loaded.unlock_tech(0, "tank")[0]
    assert loaded.mil_power(0) > before
    assert army.dmg["tank"] == 27.5
    restored = pickle.loads(pickle.dumps(loaded))
    assert restored.armies[a.id].dmg == army.dmg  # 변환은 한 번만


def test_capital_level_five_not_blocked_by_occupied_neighbor():
    g = game()
    cap = g.player.capital
    neighbor = own(g, sorted(g.world.land_adj[cap])[0])
    neighbor.b["admin"] = 4
    g.regions[cap].b["admin"] = 4
    assert g.building_allowed(0, cap, "admin", 5)[0]


def test_general_escorts_army_into_timed_neutral_occupation():
    g = game()
    cap = g.player.capital
    target = next(r for r in sorted(g.world.land_adj[cap]) if g.regions[r].owner == -1)
    for army in list(g.armies_at(target)):
        g.remove_army(army)
    g.regions[cap].b["academy"] = 1
    assert g.recruit_great_person(0, "general")[0]
    troops = g.armies_at(cap, 0)
    g._ground_battle(0, troops, target, "assault", troops)
    assert g.regions[target].owner == -1 and 0 in g.regions[target].occs
    assert g.great_people[0]["loc"] == target
    assert g.great_person_bonus(target, "attack_mult", 0) == 1.2
    g.apply_damage(g.armies_at(target, 0), 1e9)
    assert not g.great_people


def test_fascist_timed_occupation_discount_preserves_annex_time():
    g = game()
    rid = next(r.id for r in g.regions.values() if r.owner == -1 and g.region_value(r.id)[0] >= 5)
    base = g.neutral_turns(0, rid)
    policy(g, "fascist", 5)
    assert g.neutral_turns(0, rid) == base
    assert g.military_occupation_turns(0, rid) == R.value_turns(g.region_value(rid)[0], .75)
    assert g.military_occupation_turns(0, g.factions[1].capital) == 0


def test_special_metro_capture_keeps_all_complex_records():
    g = game()
    cap = g.player.capital
    sel = [cap] + sorted(g.world.land_adj[cap])[:3]
    for rid in sel:
        r = own(g, rid) if rid != cap else g.regions[rid]
        r.pop, r.happy = 26, 10
        r.b.update(admin=3, edu=4, factory=5, bank=5, housing=5)
    temp = own(g, "S109")
    temp.pop = 1
    temp.b["admin"] = 3
    assert g.create_metro(0, cap, sel)[0]
    for rid in sel:
        g.regions[rid].b.update(admin=5, edu=5)
    g.complete_occupation(1, cap)
    # 광역 슬롯(v1.3.16): 정부청사·국립연구원은 중심의 광역 카드 하나 — 그 기록도 중심에
    assert g.regions[cap].lost_gov_complex and g.regions[cap].lost_gov_complex["admin5"]
    assert g.player.capital == temp.id
    g.complete_occupation(0, cap)
    assert g.player.capital == cap
    assert all(g.blevel(r, "admin") == g.blevel(r, "edu") == 5 for r in sel)
