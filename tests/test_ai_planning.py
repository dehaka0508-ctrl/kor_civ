"""승리 경로·자원 슬롯·전쟁 준비·행정 선행 투자의 회귀 검증."""
import math

import pytest

from korciv import ai as AI, ai_economy as E, ai_endgame as EG, ai_progression as AP
from korciv import ai_strategy as ST, config as C, metro as M, slots as S
from korciv.game import Game
from korciv.state import Project, Settings


@pytest.fixture
def game(monkeypatch):
    monkeypatch.setattr(S, 'GROW_WHEN_FULL', False)
    g = Game(Settings(seed=1914, mode='frontier', player_start='S002', ai_starts=['N001'],
                      n_enemies=1, player_leader='cus', ai_leaders=['cus'], max_turns=500,
                      victories=('science', 'economic', 'conquest', 'diplomatic', 'time')))
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
    r.pop, r.happy = 20, 25
    return g


def own(g, *, resource=None, population=10):
    rid = next(rid for rid in g.world.order if g.regions[rid].owner == -1 and
               (resource is None or getattr(g.info(rid), 'is_' + resource)))
    g.transfer_region(rid, 0, reason='편입')
    r = g.regions[rid]
    r.b.clear_cards()
    r.pop, r.happy, r.resist = population, 25, None
    return r


def test_gdp_first_keeps_science_and_leader_progress(game):
    g, f = game, game.player
    g.rankings = {g.turn: [dict(fid=0, gdp=10000, science=0, econ=0), dict(fid=1, gdp=1, science=0, econ=0)]}
    before = ST.path_scores(g, f, {})['scores']['science']
    assert before > 0
    f.leader = 'sen'
    f.science = list(C.SCIENCE_STEPS[:4])
    g._mods.clear()
    assert ST.path_scores(g, f, {})['scores']['science'] > before


@pytest.mark.parametrize('winner', ['science', 'economic', 'conquest', 'diplomatic', 'time'])
def test_fastest_path_overrides_personality_and_dwell(game, monkeypatch, winner):
    g, f = game, game.player
    f.ai['p2'] = dict(path='economic' if winner != 'economic' else 'science', path_turn=g.turn)
    scores = {k: .5 for k in ST.PATHS}
    scores['conquest'] = 10
    monkeypatch.setattr(ST, 'path_scores', lambda *args: dict(scores=dict(scores), why={k: k for k in ST.PATHS + ('time',)}))
    monkeypatch.setattr(EG, 'victory_estimates', lambda *args: {k: 8 if k == winner else 150 for k in scores.keys() | {'time'}})
    assert ST.choose_path(g, f, {}) == winner


def test_final_phase_can_change_to_faster_victory(game, monkeypatch):
    g, f = game, game.player
    f.ai.update(phase=3, p3=dict(kind='economic'), p2=dict(path='economic', path_turn=0, last_eval=-99))
    f.science = list(C.SCIENCE_STEPS[:3])
    monkeypatch.setattr(EG, 'victory_estimates', lambda *args: dict(science=12, economic=100, conquest=999, diplomatic=999))
    ST.update(g, f)
    assert f.ai['p2']['path'] == 'economic'
    g.turn += C.AI_P2_EVAL_TURNS
    ST.update(g, f)
    assert f.ai['p2']['path'] == f.ai['p3']['kind'] == 'science'
    assert f.ai['phase'] == 3


@pytest.mark.parametrize('current, alternative', [(100, 80), (30, 21), (100, 99)])
def test_final_phase_keeps_goal_for_small_or_short_lived_advantage(game, monkeypatch, current, alternative):
    g, f = game, game.player
    f.ai.update(phase=3, p3=dict(kind='economic'), p2=dict(path='economic'))
    monkeypatch.setattr(ST, 'path_scores', lambda *args: dict(scores=dict(science=100, economic=.1,
                        conquest=0, diplomatic=0), why={k: k for k in ST.PATHS}))
    monkeypatch.setattr(EG, 'victory_estimates', lambda *args: dict(science=alternative, economic=current))
    for _ in range(3):
        assert ST.choose_path(g, f, {}) == 'economic'
        g.turn += C.AI_P2_EVAL_TURNS


def test_final_phase_requires_two_separate_consistent_forecasts(game, monkeypatch):
    g, f = game, game.player
    f.ai.update(phase=3, p3=dict(kind='economic'), p2=dict(path='economic'))
    estimates = dict(science=20, economic=100, conquest=999)
    monkeypatch.setattr(EG, 'victory_estimates', lambda *args: estimates)
    assert ST.choose_path(g, f, {}) == 'economic'
    assert ST.choose_path(g, f, {}) == 'economic'  # 같은 턴 재호출은 재확인이 아니다.
    g.turn += C.AI_P2_EVAL_TURNS
    estimates['science'] = 95
    assert ST.choose_path(g, f, {}) == 'economic'
    assert 'switch_candidate' not in f.ai['p2']
    g.turn += C.AI_P2_EVAL_TURNS
    estimates['science'] = 20
    assert ST.choose_path(g, f, {}) == 'economic'
    g.turn += C.AI_P2_EVAL_TURNS
    assert ST.choose_path(g, f, {}) == 'science'


def test_science_eta_counts_current_project_progress_and_leader_turns(game):
    g, f = game, game.player
    f.science = list(C.SCIENCE_STEPS[:6])
    oil = own(g, resource='oil')
    oil.b['extract'] = 5
    f.techs.update(('aerospace', 'extract'))
    for st in C.SCIENCE_UNITS:
        if st != 'propellant':
            g.new_army(0, f.capital, {st: 1})
    before = EG.eta_science(g, 0)
    f.leader = 'sen'
    g._mods.clear()
    assert EG.eta_science(g, 0) < before
    oil.project = Project('science', 'propellant', turns=12, progress=10, per_turn=1000)
    assert EG.eta_science(g, 0) == 6
    g.transfer_region(oil.id, 1, reason='편입')
    assert EG.eta_science(g, 0) == EG.ETA_NONE


@pytest.mark.parametrize('resource', ['oil', 'coal'])
def test_last_resource_slot_reserved_until_extraction_is_queued(game, resource):
    g, f = game, game.player
    r = own(g, resource=resource)
    r.b.slots['base'] = [dict(key='bank', level=2), None]
    r.b.resync()
    ctx = E.snapshot(g, f)
    options = g.options(0, r.id)
    candidates = E.build_candidates(g, f, r, options, {}, ctx, AI.fuel_balance(g, 0))
    new = [c for c in candidates if c[6] == ('base', 1)]
    assert new and {c[3] for c in new} == {'extract'}
    assert any(c[3] == 'bank' and c[6] == ('base', 0) for c in candidates)
    r.queue = [Project('build', 'extract', turns=2, level=1, slot=('base', 1), site=r.id)]
    assert not E.resource_missing(g, r.id)


def test_resource_is_built_and_old_full_level_five_slots_can_recover(game):
    g, f = game, game.player
    r = own(g, resource='oil')
    r.b.slots['base'] = [dict(key='factory', level=5)] + [dict(key='bank', level=5) for _ in range(4)]
    r.b.resync()
    assert E.develop_resources(g, f, {}, E.snapshot(g, f))
    assert r.project.key == 'extract' and r.project.slot[0] == 'base'
    assert r.b['factory'] == 5 and r.b.count('bank') == 3
    assert not E.resource_missing(g, r.id)
    assert not E.develop_resources(g, f, {}, E.snapshot(g, f))


def test_other_goal_candidates_cannot_bypass_resource_reservation(game, monkeypatch):
    g, f = game, game.player
    r = own(g, resource='oil')
    r.b.slots['base'] = [dict(key='bank', level=3), None]
    r.b.resync()
    f.is_ai = True
    f.ai['victory_goal'] = 'conquest'
    monkeypatch.setattr(E, 'build_candidates', lambda *args, **kwargs:
                        [(10000, r.id, 'build', 'bank', None, 300, ('base', 1), None)])
    AI._slots(g, f, {}, military=False)
    assert r.project is None and r.b.empty('base')


@pytest.mark.parametrize('building', ['bank', 'factory'])
def test_failed_resource_start_restores_existing_card(game, monkeypatch, building):
    g, f = game, game.player
    r = own(g, resource='coal')
    r.b.slots['base'] = [dict(key=building, level=3)] * 2
    r.b.resync()
    r.energy = dict(coal=2, elec=1)
    monkeypatch.setattr(g, 'start_project', lambda *args, **kwargs: (False, '검증 거절'))
    assert not E.develop_resources(g, f, {}, E.snapshot(g, f))
    assert r.b.count(building) == 2 and not r.b.empty('base')
    assert r.energy == dict(coal=2, elec=1)


def test_resource_reservation_does_not_consume_unaffordable_cash(game):
    g, f = game, game.player
    r = own(g, resource='oil', population=1000)
    f.money = 0
    assert not E.develop_resources(g, f, {}, E.snapshot(g, f))
    assert r.project is None and E.resource_missing(g, r.id)


def test_preparing_war_values_first_academy_and_recruits_general(game):
    g, f = game, game.player
    f.ai['victory_goal'] = 'conquest'
    g.new_army(0, f.capital, {'inf': 80})
    r = g.regions[f.capital]
    ctx = E.snapshot(g, f)
    assert E.general_plan(g, f, ctx)['value'] > 0
    candidates = E.build_candidates(g, f, r, g.options(0, r.id), {}, ctx, AI.fuel_balance(g, 0))
    war = next(c[0] for c in candidates if c[3] == 'academy')
    f.ai['victory_goal'] = 'science'
    peaceful = E.build_candidates(g, f, r, g.options(0, r.id), {}, ctx, AI.fuel_balance(g, 0))
    assert war > next(c[0] for c in peaceful if c[3] == 'academy')
    f.ai['victory_goal'] = 'conquest'
    r.b['academy'] = 1
    AP.progression_orders(g, f, {})
    assert any(p['owner'] == 0 and p['kind'] == 'general' for p in g.great_people)


def test_general_keeps_administration_reserve_and_academy_ban(game):
    g, f = game, game.player
    f.ai['victory_goal'] = 'conquest'
    f.admin = 600
    own(g, population=1000)
    g.new_army(0, f.capital, {'inf': 80})
    g.regions[f.capital].b['academy'] = 1
    AP.progression_orders(g, f, {})
    assert not any(p['kind'] == 'general' for p in g.great_people)
    f.leader = 'sta'
    g._mods.clear()
    r = own(g)
    assert not any(c[3] == 'academy' for c in E.build_candidates(g, f, r, g.options(0, r.id), {},
                                                               E.snapshot(g, f), AI.fuel_balance(g, 0)))


def test_growth_forecast_matches_focus_and_ration_before_administration_runs_out(game):
    g, f = game, game.player
    g.regions[f.capital].pop = 30
    r = own(g, population=29.8)
    r.b['admin'] = 3
    r.happy = 50
    r.pop_focus = True
    f.ration_bonus = .01
    f.admin = 1
    before = r.pop
    rate = E.population_rate(g, f, r)
    g._phase_population()
    assert r.pop == pytest.approx(before * (1 + rate))
    ctx = E.snapshot(g, f)
    assert ctx['admin_prod'] >= ctx['admin_cons'] and ctx['admin_gap'] > 0
    assert ctx['admin_cover'] <= 12
    candidates = E.build_candidates(g, f, r, g.options(0, r.id), {}, ctx, AI.fuel_balance(g, 0))
    assert any(c[3] == 'admin' and c[0] > 1 for c in candidates)


def test_forecast_counts_joint_annex_once_and_queued_admin_only_after_completion(game):
    g, f = game, game.player
    source = own(g, population=1)
    target = next(rid for rid in g.world.land_adj[source.id] if g.regions[rid].owner == -1)
    g.regions[target].pop = 100
    cap = g.regions[f.capital]
    cap.project = Project('annex', target, turns=4)
    one = E.snapshot(g, f)['expansion_admin']
    source.project = Project('annex', target, turns=4)
    two = E.snapshot(g, f)['expansion_admin']
    assert one > 0 and two == pytest.approx(one, rel=.05)
    source.project = None
    source.queue = [Project('build', 'admin', level=3, turns=6)]
    after = E.snapshot(g, f)['admin_gap']
    source.project = Project('build', 'bank', level=1, turns=15)
    assert E.snapshot(g, f)['admin_gap'] > after


def test_ending_resistance_forecasts_full_population_demand(game):
    g, f = game, game.player
    r = own(g, population=80)
    r.resist = dict(turn=g.turn, resist=2, recover=20, **{'from': 1})
    assert g.admin_consumption(r.id) == 40
    ctx = E.snapshot(g, f)
    assert ctx['admin_gap'] > 70
    r.b['admin'] = 3
    assert E.snapshot(g, f)['admin_gap'] < ctx['admin_gap']


def test_growth_forecast_starts_admin_before_lawlessness(game):
    g, f = game, game.player
    g.regions[f.capital].pop = 30
    r = own(g, population=29.8)
    r.b['admin'] = 3
    r.pop_focus, r.happy = True, 50
    f.ration_bonus, f.admin = .01, 1
    f.is_ai = True
    assert not f.lawless
    AI._slots(g, f, {}, military=False)
    assert any(rr.project and rr.project.kind == 'build' and rr.project.key == 'admin' for rr in g.regions_of(0))


def test_merged_resource_region_reserves_center_slot(game):
    g, f = game, game.player
    oil = own(g, resource='oil')
    center = own(g)
    # 이미 합쳐진 광역 슬롯의 최소 상태. 자원은 다른 구성 지역에 있다.
    mid = 999
    g.metros[mid] = dict(center=center.id, members=[center.id, oil.id], slot_merge=True,
                         pre_slots={center.id: {'base': [None] * 3}, oil.id: {'base': [None] * 3}})
    center.metro = oil.metro = mid
    center.b.slots['base'] = [dict(key='bank', level=1)] * 5 + [None]
    center.b.resync()
    assert E.resource_missing(g, center.id)
    ctx = E.snapshot(g, f)
    option = dict(slot=('base', 5), level=1, key='bank', site=center.id)
    assert E.slot_factor(g, f, center.id, option, ctx) == 0


def test_lawless_and_famine_apply_three_with_partial_famine_scaling(game):
    g, f = game, game.player
    r = own(g, population=1000)
    f.admin = 0
    f.admin_deficit_turns = C.LAWLESS_TURNS
    r.h_delta = 0
    g._phase_knowledge(f)
    assert f.lawless and r.h_delta == -3
    for rr in g.regions_of(0):
        rr.h_delta = 0
    f.auto_food = False
    f.res['food'] = sum(rr.pop for rr in g.regions_of(0)) * C.FOOD_PER_POP / 2
    g._phase_resources(f)
    assert r.famine == pytest.approx(.5)
    assert r.h_delta == pytest.approx(-1.5)


def test_disabled_victories_never_selected(game):
    g, f = game, game.player
    g.settings.victories = ('science',)
    assert ST.choose_path(g, f, {}) == 'science'
    assert all(math.isfinite(v) for v in EG.victory_estimates(g, 0).values())
