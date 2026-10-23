"""새 기믹을 함께 판단하는 AI의 예산·카드 선택·연구·위인·상황별 선호 검증."""
import math
import pickle

import pytest

from korciv import ai as AI, ai_economy as E, ai_progression as AP, diplomacy as D, slots as S
from korciv.ai_personality import PROFILES, preference
from korciv.game import Game
from korciv.leaders import LEADERS
from korciv.progression import TECHS
from korciv.state import Settings, Project


@pytest.fixture
def game(monkeypatch):
    monkeypatch.setattr(S, 'GROW_WHEN_FULL', False)
    g = Game(Settings(seed=410, mode='frontier', player_start='S002', ai_starts=['N001'],
                      n_enemies=1, player_leader='cus', ai_leaders=['cus'], victories=('time',), max_turns=500))
    g.set_player_government('presidential')
    g.player.money = 100000
    g.player.res['food'] = 10000
    g.player.ai['weights'] = dict(economy=1, expansion=1, military=1, defense=1)
    for f in g.factions:
        f.is_ai = False
    r = g.regions[g.player.capital]
    r.b.clear_cards()
    r.b.slots['base'] = [None] * 5
    r.pop, r.happy = 5, 25
    r.b['admin'] = 3
    return g


def ctx(g):
    return E.snapshot(g, g.player)


def admin_burden(g, population):
    """집무실은 수도 인구를 담당하므로 행정 적자는 추가 지역에서 만든다."""
    rid = next(n for n in g.world.land_adj[g.player.capital] if g.regions[n].owner == -1)
    g.transfer_region(rid, 0, reason='편입')
    r = g.regions[rid]
    r.b.clear_cards()
    r.pop = population
    r.resist = None


@pytest.mark.parametrize('key', [x['key'] for x in LEADERS])
def test_every_leader_has_current_finite_preferences(game, key):
    g = game
    assert set(PROFILES) == {x['key'] for x in LEADERS}
    g.player.leader = key
    g._mods.clear()
    for action in ('admin', 'edu', 'science', 'inf', 'tank', 'art', 'naval', 'ally', 'war', 'annex', 'focus'):
        value = preference(g, 0, action, rid=g.player.capital)
        assert math.isfinite(value) and .65 <= value <= 1.35
    g.player.is_ai = True
    AI.plan_turn(g, 0)
    g.end_turn()
    assert math.isfinite(g.player.money) and g.player.sci_points >= 0 and g.player.admin >= 0


def test_administration_reserve_prevents_policy_bankruptcy(game):
    g = game
    r = g.regions[g.player.capital]
    r.pop, g.player.admin, g.player.policy_level = 150, 200, 0
    admin_burden(g, 150)
    AP.progression_orders(g, g.player, {})
    assert g.player.policy_level == 0 and g.player.admin == 200
    assert ctx(g)['admin_keep'] > 200


def test_policy_that_solves_admin_deficit_is_evaluated_after_unlock(game):
    g = game
    g.player.gov = 'absolute'
    g._mods.clear()
    r = g.regions[g.player.capital]
    r.pop = 35
    admin_burden(g, 35)
    g.player.admin = 110
    before = ctx(g)['admin_keep']
    assert AP.policy_reserve(g, g.player, ctx(g)) < before
    AP.progression_orders(g, g.player, {})
    assert g.player.policy_level == 1 and g.player.admin >= 0


def test_capital_growth_includes_matching_office_growth(game):
    g = game
    g.regions[g.player.capital].pop = 50
    development = ctx(g)
    assert development['growth'] > 0
    assert development['admin_growth'] == pytest.approx(0)
    g.player.gov = None
    g._mods.clear()
    development = ctx(g)
    assert development['admin_growth'] == development['growth']


def test_science_reserve_covers_actual_remaining_shortfall(game):
    g = game
    r = g.regions[g.player.capital]
    r.project = Project('science', 'lab', turns=15)
    assert AP.science_reserve(g, 0) == 3000
    r.b['edu'] = 4
    r.pop = 100
    assert AP.science_reserve(g, 0) == 1000


def test_shared_science_production_is_not_spent_twice(game, monkeypatch):
    g = game
    r = g.regions[g.player.capital]
    other = next(n for n in g.world.land_adj[r.id] if g.regions[n].owner == -1)
    g.transfer_region(other, 0, reason='편입')
    r.project = Project('science', 'lab', turns=15)
    g.regions[other].project = Project('science', 'observatory', turns=15)
    monkeypatch.setattr(g, 'science_production', lambda fid: 250)
    due = g.science_per_turn_cost(0) + g.science_per_turn_cost(1)
    assert AP.science_reserve(g, 0) == max(5 * due, (due - 250) * 15)


def test_queued_admin_waits_for_preceding_project_in_forecast(game):
    g = game
    r = g.regions[g.player.capital]
    r.pop = 50
    base = ctx(g)['admin_gap']
    r.project = Project('build', 'bank', level=1, turns=10)
    r.queue = [Project('build', 'admin', level=4, turns=2)]
    assert ctx(g)['admin_gap'] == base


def test_unaffordable_top_research_does_not_block_army_modernization(game):
    g = game
    g.player.ai['victory_goal'] = 'science'
    g.player.admin = 0
    g.player.sci_points = 1000
    g.new_army(0, g.player.capital, {'inf': 8})
    AP.progression_orders(g, g.player, {}, crisis=True)
    assert 'inf' in g.player.techs and 'aerospace' not in g.player.techs
    assert 0 <= g.player.sci_points < 1000


def test_marginal_factory_does_not_assume_free_fuel(game):
    g = game
    r = g.regions[g.player.capital]
    r.fuel_used = 0
    fuel = dict(spare=-3, supply=0, raw_left=0, plant_room=0)
    o = next(o for o in g.options(0, r.id) if o['key'] == 'factory' and o['kind'] == 'build')
    assert E.marginal(g, g.player, r.id, o, ctx(g), fuel)[0] == 0
    r.b['factory'] = 2
    r.fuel_used = 1
    o = next(o for o in g.options(0, r.id) if o['key'] == 'factory' and o['level'] == 3)
    assert E.marginal(g, g.player, r.id, o, ctx(g), fuel)[0] > 0


def test_multiple_cards_retain_their_own_slot_and_level(game, monkeypatch):
    g = game
    r = g.regions[g.player.capital]
    r.b['bank'] = 3
    opts = [o for o in g.options(0, r.id) if o['key'] == 'bank' and o['ok']]
    new = next(o for o in opts if o['level'] == 1)
    g.player.techs.add('bank')
    upgrade = next(o for o in g.options(0, r.id) if o['key'] == 'bank' and o['level'] == 4)
    assert new['slot'] != upgrade['slot']
    monkeypatch.setattr(E, 'build_candidates', lambda *args, **kwargs:
                        [(100, r.id, 'build', 'bank', None, new['per_turn'], new['slot'], None)])
    AI._slots(g, g.player, {}, military=False)
    assert r.project is not None and r.project.slot == new['slot'] and r.project.level == 1


def test_last_slot_is_preserved_for_necessary_admin(game):
    g = game
    r = g.regions[g.player.capital]
    r.b.clear_cards()
    r.b.slots['base'] = [dict(key='bank', level=1), None]
    r.b.resync()
    r.pop, g.player.admin = 50, 0
    options = g.options(0, r.id)
    a = next(o for o in options if o['key'] == 'admin' and o['ok'])
    bank = next(o for o in options if o['key'] == 'bank' and o['level'] == 1)
    assert E.slot_factor(g, g.player, r.id, a, ctx(g)) > E.slot_factor(g, g.player, r.id, bank, ctx(g))


def test_planned_admin_reduces_pressure_and_redevelopment_preserves_food(game):
    g = game
    r = g.regions[g.player.capital]
    before = ctx(g)['admin_gap']
    r.project = Project('build', 'admin', level=4, turns=2)
    assert ctx(g)['admin_gap'] <= before
    r.project = None
    r.b.clear_cards()
    r.b.slots['base'] = [dict(key='farm', level=1), dict(key='bank', level=1)]
    r.b.resync()
    r.pop, g.player.admin, g.player.lawless = 50, 0, True
    r.output = 1000
    assert E.redevelop(g, g.player, {}, ctx(g))
    assert r.b['farm'] == 1 and r.b['bank'] == 0 and r.project.key == 'admin'


def test_research_target_does_not_demolish_only_productive_market(game):
    g = game
    r = g.regions[g.player.capital]
    r.b.slots['base'] = [dict(key='bank', level=2), dict(key='admin', level=3)]
    r.b.resync()
    c = ctx(g)
    c.update(science=1, admin_gap=0, admin_cover=999, net=1000)
    g.turn = 20
    assert not E.redevelop(g, g.player, {}, c)
    assert r.b['bank'] == 2


def test_simultaneous_projects_share_one_cash_budget(game):
    g = game
    c = ctx(g)
    c.update(income=100, upkeep=0, food_short=0, money_keep=100)
    g.player.money = 200
    option = dict(turns=4, per_turn=100)
    assert E.can_finance(g, g.player, c, option)
    c['new_commitments'] = 100
    assert not E.can_finance(g, g.player, c, option)


def test_existing_food_stock_is_not_charged_again_as_cash(game):
    g = game
    c = ctx(g)
    c.update(income=100, upkeep=0, food_short=100, money_keep=100)
    g.player.money = 200
    g.player.res['food'] = 1000
    assert E.can_finance(g, g.player, c, dict(turns=4, per_turn=100))
    g.player.res['food'] = 0
    assert not E.can_finance(g, g.player, c, dict(turns=4, per_turn=100))


def test_scientist_and_artist_are_not_consumed_without_benefit(game):
    g = game
    r = g.regions[g.player.capital]
    r.b['edu'] = 4
    g.player.admin = g.player.sci_points = 10000
    assert g.recruit_great_person(0, 'scientist')[0]
    r.b['specialty'] = 3
    # 예술가 입지 조건은 특산물 지역이므로 실제 입지를 맞춘다.
    specialty = next(x for x in g.world.order if g.info(x).specialties and g.regions[x].owner == -1)
    g.transfer_region(specialty, 0, reason='편입')
    g.regions[specialty].b['specialty'] = 3
    g.regions[specialty].b['admin'] = 3
    g.regions[specialty].happy = 25
    assert g.recruit_great_person(0, 'artist')[0]
    ids = {p['id'] for p in g.great_people}
    AP.great_people_orders(g, g.player, {})
    assert ids <= {p['id'] for p in g.great_people}


def test_chancellor_kept_while_covering_administration(game):
    g = game
    r = g.regions[g.player.capital]
    r.b['admin'] = 4
    g.player.admin = 10000
    assert g.recruit_great_person(0, 'chancellor')[0]
    r.pop = 100
    r.project = Project('econ', 'exchange', turns=15, per_turn=10000)
    admin_burden(g, 100)
    AP.great_people_orders(g, g.player, {})
    assert any(p['kind'] == 'chancellor' for p in g.great_people)
    assert r.project.turns == 15


def test_situational_leader_preferences(game):
    g = game
    target = next(n for n in g.world.land_adj[g.player.capital] if g.regions[n].owner == -1)
    g.player.leader = 'yis'
    on = preference(g, 0, 'naval')
    g.player.naval_off_until = g.turn + 4
    assert preference(g, 0, 'naval') < on
    g.player.leader = 'kgu'
    normal = preference(g, 0, 'assault', target=target)
    g.player.lost_regions.add(target)
    assert preference(g, 0, 'assault', target=target) > normal


def test_growth_focus_respects_admin_and_food(game):
    g = game
    r = g.regions[g.player.capital]
    r.pop, g.player.admin = 150, 0
    admin_burden(g, 150)
    AP.focus_orders(g, g.player, {})
    assert not r.pop_focus and r.focus
    assert g.player.ai['development']['admin_gap'] > 0
    loaded = pickle.loads(pickle.dumps(g))
    assert loaded.player.ai['development'] == g.player.ai['development']


def test_snapshot_does_not_read_hidden_enemy_armies(game):
    g = game
    before = {k: v for k, v in ctx(g).items() if isinstance(v, (int, float))}
    g.new_army(1, g.factions[1].capital, {'tank': 1000})
    after = {k: v for k, v in ctx(g).items() if isinstance(v, (int, float))}
    assert before == after


def test_no_long_construction_immediately_before_time_limit(game):
    g = game
    g.turn = g.settings.max_turns - 1
    r = g.regions[g.player.capital]
    candidates = E.build_candidates(g, g.player, r, g.options(0, r.id), {}, ctx(g), AI.fuel_balance(g, 0))
    assert not candidates


def test_growth_capacity_uses_near_term_forecast_not_entire_investment_horizon(game):
    g = game
    r = g.regions[g.player.capital]
    r.pop, r.happy = 1, 50
    AP.focus_orders(g, g.player, {})
    assert r.pop_focus and not r.focus


def test_science_project_waits_for_knowledge_funding(game):
    g = game
    g.player.is_ai = True
    g.player.money = 1e9
    g.player.sci_points = 0
    g.player.techs.add('aerospace')
    g.player.ai.update(victory_goal='science', phase=2, p2=dict(path='science', posture='normal', mil_ok=True))
    AI._slots(g, g.player, {}, military=False)
    assert not any(r.project and r.project.kind == 'science' for r in g.regions_of(0))
