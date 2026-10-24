"""통합 채굴 기술·정치체제 판단·도시 재개발·승리 공사 예산 회귀."""
import math
import pickle
import random

import pytest

from korciv import ai as AI, ai_economy as E, ai_endgame as EG, ai_progression as AP, config as C, slots as S
from korciv.game import Game
from korciv.leaders import LEADERS, LEADER_BY_KEY, POLICIES, ai_government_scores, ai_pick_government, banned_govs
from korciv.progression import TECHS
from korciv.state import Project, Settings


@pytest.fixture
def game(monkeypatch):
    monkeypatch.setattr(S, 'GROW_WHEN_FULL', False)
    g = Game(Settings(seed=2110, mode='frontier', player_start='S002', ai_starts=['N001'], n_enemies=1,
                      player_leader='cus', ai_leaders=['cus'], max_turns=500))
    g.set_player_government('presidential')
    for f in g.factions:
        f.is_ai = False
    f = g.player
    f.money, f.admin, f.sci_points = 1e8, 20000, 1e6
    f.res['food'] = 1e6
    f.ai.update(phase=2, victory_goal='science', weights=dict(economy=1, expansion=1, military=1, defense=1))
    r = g.regions[f.capital]
    r.b.clear_cards()
    r.b.slots['base'] = [None] * 5
    r.pop, r.happy = 1, 25
    return g


def own(g, population=40, resource=None):
    rid = next(rid for rid in g.world.order if g.regions[rid].owner == -1 and
               (resource is None or getattr(g.info(rid), 'is_' + resource)))
    g.transfer_region(rid, 0, reason='편입')
    r = g.regions[rid]
    r.b.clear_cards()
    r.pop, r.happy, r.resist = population, 25, None
    return r


def test_one_resource_research_unlocks_oil_and_coal_at_exact_cost(game):
    g, f = game, game.player
    assert TECHS['extract']['name'] == '자원 채굴 고도화'
    assert not {'coal', 'oil'} & TECHS.keys()
    sites = [own(g, resource=resource) for resource in ('oil', 'coal')]
    for r in sites:
        r.b['extract'] = 3
        assert not g.building_allowed(0, r.id, 'extract', 4)[0]
    f.sci_points = 1500
    assert g.unlock_tech(0, 'extract')[0] and f.sci_points == 0
    for r in sites:
        assert g.building_allowed(0, r.id, 'extract', 5)[0]
        assert g.start_project(0, r.id, 'build', 'extract', slot=r.b.primary('extract'))[0]
    assert not g.unlock_tech(0, 'extract')[0]


@pytest.mark.parametrize('legacy', [set(), {'oil'}, {'coal'}, {'oil', 'coal'}, {'extract', 'oil'}])
def test_legacy_resource_technology_migrates_without_currency_or_rng_changes(game, legacy):
    g, f = game, game.player
    f.techs = {'inf', *legacy}
    stock, state = (f.money, f.admin, f.sci_points), g.rng.getstate()
    loaded = pickle.loads(pickle.dumps(g))
    expected = {'inf'} | ({'extract'} if legacy else set())
    assert loaded.player.techs == expected
    assert (loaded.player.money, loaded.player.admin, loaded.player.sci_points) == stock
    assert loaded.rng.getstate() == state
    assert all(a.techs is loaded.player.techs for a in loaded.armies.values() if a.owner == 0)
    assert pickle.loads(pickle.dumps(loaded)).player.techs == expected


def test_naval_costs_and_leader_research_penalty(game):
    g, f = game, game.player
    assert g.tech_cost(0, 'dd') == 1400 and g.tech_cost(0, 'cv') == 2000
    f.sci_points = 3400
    assert g.unlock_tech(0, 'dd')[0] and g.unlock_tech(0, 'cv')[0]
    assert f.sci_points == 0
    f.leader = 'ahn'
    g._mods.clear()
    assert g.tech_cost(0, 'dd') == 1680 and g.tech_cost(0, 'cv') == 2400
    assert g.tech_cost(0, 'extract') == 1500


def test_ai_resource_research_combines_both_deposits(game):
    g, f = game, game.player
    for resource in ('oil', 'coal'):
        own(g, resource=resource).b['extract'] = 3
    scores = AP.tech_scores(g, f)
    assert scores['extract'] > 0 and not {'oil', 'coal'} & scores.keys()


def test_science_eta_prices_unified_extraction_once(game, monkeypatch):
    g, f = game, game.player
    oil = own(g, resource='oil')
    oil.b['extract'] = 3
    f.science = list(C.SCIENCE_STEPS[:6])
    f.techs.add('aerospace')
    f.sci_points = 0
    g.new_army(0, f.capital, {key: 1 for key in C.SCIENCE_UNITS if key != 'propellant'})
    monkeypatch.setattr(g, 'science_production', lambda fid: 100)
    required = g.science_per_turn_cost(C.SCIENCE['propellant']['tier']) * g.science_turns(0, 'propellant') + 1500
    assert EG.eta_science(g, 0) == pytest.approx(required / 100)


@pytest.mark.parametrize('leader', LEADERS, ids=lambda leader: leader['key'])
def test_every_leader_gets_finite_legal_government_scores(leader):
    key, aggression = leader['key'], leader['aggr']
    scores = ai_government_scores(aggression, 2, 2, leader_key=key, resources=1, coastal=True, neighbors=3)
    assert set(scores) == set(POLICIES) and all(math.isfinite(x) for x in scores.values())
    choice = ai_pick_government(random.Random(21), aggression, 2, 2, leader_key=key, resources=1, coastal=True, neighbors=3)
    assert choice in POLICIES and choice not in banned_govs(key)


def test_government_environment_spread_compressed_and_aggression_matters():
    empty = ai_government_scores(5, 0, 0)
    developed = ai_government_scores(5, 3, 2, resources=1, coastal=True, neighbors=2)
    raw = dict(absolute=.2, constitutional=.44, presidential=.75, parliamentary=1.15,
               socialist=1.5, fascist=.49)
    assert {key: developed[key] - empty[key] for key in raw} == pytest.approx({key: .8 * x for key, x in raw.items()})
    assert ai_pick_government(random.Random(1), 1, 0, 0) == 'parliamentary'
    assert ai_pick_government(random.Random(1), 10, 0, 0) == 'fascist'
    assert ai_pick_government(random.Random(1), 5, 0, 0, banned=('presidential',)) != 'presidential'


def test_government_uses_effect_sign_and_unusable_policy_benefits(monkeypatch):
    monkeypatch.setitem(LEADER_BY_KEY, 'probe', dict(fx={'output_bank': .5}))
    positive = ai_government_scores(5, 0, 0, leader_key='probe')['parliamentary']
    monkeypatch.setitem(LEADER_BY_KEY, 'probe', dict(fx={'output_bank': -.5}))
    negative = ai_government_scores(5, 0, 0, leader_key='probe')['parliamentary']
    assert positive > negative
    monkeypatch.setitem(LEADER_BY_KEY, 'probe', dict(fx={'no_resource_trade': True}))
    blocked = ai_government_scores(5, 0, 0, leader_key='probe')['parliamentary']
    assert blocked < ai_government_scores(5, 0, 0)['parliamentary']
    monkeypatch.setitem(LEADER_BY_KEY, 'probe', dict(fx={'gov_buff_scale': .7}))
    assert ai_government_scores(5, 0, 0, leader_key='probe')['parliamentary'] < ai_government_scores(5, 0, 0)['parliamentary']


@pytest.mark.parametrize('need', ['admin', 'edu', 'bank'])
def test_full_city_replaces_only_lowest_farm_with_missing_building(game, need):
    g, f = game, game.player
    r = own(g, population=80 if need == 'admin' else 40)
    cards = [dict(key='farm', level=4), dict(key='farm', level=1)]
    if need != 'admin':
        cards.append(dict(key='admin', level=4))
    if need == 'bank':
        cards.append(dict(key='edu', level=3))
    else:
        cards.append(dict(key='bank', level=3))
    r.b.slots['base'] = cards
    r.b.resync()
    assert E.redevelop(g, f, {}, E.snapshot(g, f))
    assert r.project.key == need and r.project.slot == ('base', 1)
    assert r.b.card(('base', 0)) == dict(key='farm', level=4)
    assert r.b.count('farm') == 1


def test_city_threshold_and_famine_and_failed_start_protection(game, monkeypatch):
    g, f = game, game.player
    r = own(g, population=39.9)
    r.b.slots['base'] = [dict(key='admin', level=4), dict(key='farm', level=1)]
    r.b.resync()
    assert not E.redevelop(g, f, {}, E.snapshot(g, f))
    r.pop = 40
    f.money = f.res['food'] = 0
    assert not E.redevelop(g, f, {}, E.snapshot(g, f))
    f.money, f.res['food'] = 1e8, 1e6
    monkeypatch.setattr(g, 'start_project', lambda *args, **kwargs: (False, '검사 거절'))
    assert not E.redevelop(g, f, {}, E.snapshot(g, f))
    assert r.b['farm'] == 1 and r.b['admin'] == 4 and r.project is None


def test_redevelopment_does_not_create_famine_when_food_purchase_is_disabled(game):
    g, f = game, game.player
    r = own(g)
    r.b.slots['base'] = [dict(key='farm', level=1), dict(key='admin', level=4)]
    r.b.resync()
    f.res['food'], f.auto_food = 0, False
    assert not E.redevelop(g, f, {}, E.snapshot(g, f))
    assert r.b['farm'] == 1


def test_ai_slots_does_not_start_science_while_economic_project_is_underfunded(game):
    g, f = game, game.player
    f.is_ai = True
    r = own(g, population=2)
    r.project = Project('econ', 'exchange', turns=15, per_turn=80000)
    f.techs.add('aerospace')
    f.money, f.sci_points = 1e6, 10000
    AI._slots(g, f, {}, military=False)
    projects = [p for p in g.unique_projects(g.regions_of(0)) if p.kind in ('science', 'econ')]
    assert len(projects) == 1 and projects[0] is r.project


@pytest.mark.parametrize('active_kind', ['science', 'econ'])
@pytest.mark.parametrize('new_kind', ['science', 'econ'])
def test_victory_concurrency_requires_cash_and_shared_science_reserves(game, active_kind, new_kind):
    g, f = game, game.player
    f.is_ai = True
    r = own(g, population=2)
    active_key = 'lab' if active_kind == 'science' else 'exchange'
    r.project = Project(active_kind, active_key, turns=15, per_turn=80000)
    new_key = 'lab' if new_kind == 'science' else 'exchange'
    cap = g.regions[f.capital]
    f.techs.add('aerospace')
    if new_kind == 'science' and active_kind == 'science':
        # 실제로 허용되는 다른 과학 단계로 만든다.
        f.science = ['lab']
        cap.b['bank'] = 5
        new_key = 'budget'
        f.science.append('observatory')
    elif new_kind == 'econ':
        # 입지 규칙은 별도 엔진 시험에서 검증하며 여기서는 예산 경계를 분리한다.
        g.options = lambda fid, rid: [dict(kind='econ', key='exchange', ok=True, cost=1200000, turns=15)]
    f.money, f.sci_points = 1e6, 10000
    assert not E.victory_project_allowed(g, f, cap.id, new_kind, new_key)
    f.money, f.sci_points = 1e9, 100000
    assert E.victory_project_allowed(g, f, cap.id, new_kind, new_key)
    if active_kind == 'science' or new_kind == 'science':
        f.sci_points = 0
        assert not E.victory_project_allowed(g, f, cap.id, new_kind, new_key)


def test_victory_gate_counts_queue_and_allows_first_project(game):
    g, f = game, game.player
    f.is_ai = True
    cap = g.regions[f.capital]
    f.money = 100000
    f.techs.add('aerospace')
    assert E.victory_project_allowed(g, f, cap.id, 'science', 'lab')
    r = own(g, population=2)
    r.queue = [Project('econ', 'exchange', turns=15, per_turn=80000)]
    assert not E.victory_project_allowed(g, f, cap.id, 'science', 'lab')
