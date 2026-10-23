"""면적(밀도·슬롯 칸 수)·예약·모드·재해의 엔진 경계 및 저장 복원 회귀 테스트."""
import math
import pickle
from dataclasses import replace

import pytest
from korciv import config as C, rules as R, metro as M, slots as S
from korciv.game import Game, initial_buildings
from korciv.state import Settings, NEUTRAL
from korciv.data import load_world


def game(mode='frontier', **kw):
    g = Game(Settings(mode=mode, n_enemies=1, player_start='S002', seed=33, **kw))
    g.player.money = 10**8
    return g


def complete(g, rid='S002'):
    r = g.regions[rid]
    r.project.progress = r.project.turns - 1
    g._fund_projects()
    g._phase_projects(('build', 'unit', 'repair', 'science', 'capital'))


def test_density_curve_and_happiness():
    assert R.density_growth_max(5) == pytest.approx(.1)
    assert R.density_growth_max(1) == pytest.approx(.1)
    assert R.density_growth_max(400) == pytest.approx(.0025)
    assert R.density_growth_max(20000) == pytest.approx(.000125)
    rates = [R.density_growth_max(d) for d in (5, 20, 100, 400, 1000, 20000)]
    assert rates == sorted(rates, reverse=True)
    assert R.pop_growth_rate(50, .1) == pytest.approx(.1)
    assert R.pop_growth_rate(5, .1) == pytest.approx(.01)


def test_geometry_and_all_standard_starting_areas():
    g = game('standard')
    for rid in g.world.order:
        i = g.info(rid)
        assert i.area_km2 == max(3, round(g.world.geometry[rid]['area'] * 9321.3, 1))
        # 건물 슬롯(v1.3.8): 면적에 따른 기본 슬롯 2~6칸, 시작 카드는 칸 수를 넘지 않는다
        b = g.regions[rid].b
        assert {t: len(v) for t, v in b.slots.items()} == S.slot_lengths(g.world, rid, 'standard', b.free_cards()), i.name
        assert len(b.slots['base']) == S.base_slot_count(i.area_km2)
        assert b.used() <= b.total()
    hongcheon = g.world.name_to_id['강원 홍천군']
    assert g.info(hongcheon).area_km2 == pytest.approx(1731, rel=.02)


@pytest.mark.parametrize('mode', ['frontier', 'chaos'])
def test_blank_starts(mode):
    g = game(mode)
    for rid, r in g.regions.items():
        assert r.pop == 1.0
        assert all(not v for k, v in r.b.items() if k != 'port')
        assert r.b['admin'] == 0
        assert not r.lines
        if r.owner == NEUTRAL:
            assert sum(a.units.get('inf', 0) for a in g.armies_at(rid)) == 1
    assert all(g.self_power(rid) == 0 for rid in g.world.order)


def test_chaos_seed_ranges_independent_world_and_save():
    base = load_world()
    g, same = game('chaos'), game('chaos')
    for key, lo, hi in [('oil', 5, 10), ('coal_field', 20, 30), ('nuclear', 4, 10), ('hydro', 8, 12)]:
        chosen = [rid for rid in g.world.order if getattr(g.info(rid), key)]
        assert lo <= len(chosen) <= hi
        assert chosen == [rid for rid in same.world.order if getattr(same.info(rid), key)]
        assert len({g.info(rid).do8 for rid in chosen}) >= min(8, len(chosen))
        if key == 'nuclear':
            assert all(g.info(rid).coastal for rid in chosen)
    assert base is load_world() and g.world is not base
    restored = pickle.loads(pickle.dumps(g))
    assert restored.world.regions == g.world.regions
    assert restored.rng.getstate() == g.rng.getstate()
    for rid in g.world.order:
        value, parts = g.region_value(rid)
        assert value == max(1, min(10, math.floor(sum(parts.values()))))


def test_queue_levels_paid_swap_cancel_and_national_list():
    g = game()
    r = g.regions['S002']
    assert g.start_project(0, r.id, 'build', 'bank')[0]
    p = r.project
    g._fund_projects()
    p.progress = 1
    assert g.start_project(0, r.id, 'build', 'bank')[0]
    assert r.queue[0].level == 2 and r.queue[0].slot == p.slot          # 같은 칸의 다음 단계
    assert g.start_project(0, r.id, 'build', 'fishery')[0]              # 하천 슬롯 어장
    h = r.queue[1]
    paid = p.paid
    assert g.move_queued_project(0, r.id, 2, 0)[0]
    assert r.project is h and r.queue[0] is p and p.paid == paid and p.progress == 1
    assert [x.project for x in g.projects_by_priority(0)] == [h]
    assert g.cancel_project(0, r.id)[0]
    assert r.project is p and p.progress == 1 and p.paid == paid
    complete(g)
    assert r.b['bank'] == 1 and r.project.level == 2
    assert r.project.paid == 0
    restored = pickle.loads(pickle.dumps(g))
    assert restored.regions[r.id].project.level == 2


def test_chain_and_repeat_finish_before_next_queue():
    g = game()
    r = g.regions['S002']
    g.player.techs.add('farm')                          # 4단계 이상 증축 기술
    assert g.start_project_max(0, r.id, 'build', 'farm')[0]
    assert g.start_units(0, r.id, 'inf', 2)[0]
    queued = r.queue[0]
    assert queued.repeat == 1 and r.project.chain
    slot = r.project.slot
    for lv in range(1, 6):
        complete(g)
        assert r.b['farm'] == lv and r.b.card(slot)['level'] == lv      # 같은 칸에서 이어서
    assert r.project is queued
    assert g.start_project(0, r.id, 'build', 'fishery')[0]
    complete(g)
    assert r.project.kind == 'unit' and not r.project.repeat
    complete(g)
    assert r.project.key == 'fishery'


def test_slot_reservations_and_no_population_cap(monkeypatch):
    """빈 칸은 대기열의 신축이 예약하고(다른 신축이 못 들어간다), 인구는 면적 상한 없이 밀도 성장률로만 자란다."""
    monkeypatch.setattr(S, 'GROW_WHEN_FULL', False)
    g = game()
    rid = 'S002'
    r = g.regions[rid]
    free = r.b.empty('base')
    assert free
    for i in free:
        assert g.start_project(0, rid, 'build', 'farm', slot=('base', i))[0]
    opts = [o for o in g.options(0, rid) if o.get('slot') and o['slot'][0] == 'base']
    assert not [o for o in opts if o['level'] == 1]                       # 빈 기본 슬롯이 남지 않음
    assert {o['slot'] for o in opts if o['key'] == 'farm'} == {('base', i) for i in free}   # 예약한 칸은 다음 단계
    assert not g.start_project(0, rid, 'build', 'bank')[0]
    while r.project:
        g.cancel_project(0, rid)
    r.pop, r.happy = 80, 50                                                # 아주 높은 밀도
    p0 = r.pop
    g._phase_population()
    assert r.pop > p0


def test_power_site_construction_and_flood_repair():
    g = game()
    rid = next(r for r in g.world.order if g.info(r).hydro)
    r = g.regions[rid]
    r.owner = 0
    assert not g.self_power(rid)
    assert g.start_project(0, rid, 'build', 'hydro')[0]
    assert r.project.turns == g.build_time(0, 'power', R.prod_building_turns(2))
    complete(g, rid)
    assert g.self_power(rid) == g.info(rid).hydro
    g.set_flooded(rid)
    assert g.calc_output(rid, full=True) == g.food_prod(0, r) == g.self_power(rid) == 0
    assert g.start_project(0, rid, 'repair', 'flood')[0]
    complete(g, rid)
    assert not r.flooded and g.self_power(rid) > 0


def test_forecast_activation_season_weather_production_and_terrain():
    g = game()
    rid = next(r for r in g.world.order if not g.info(r).coastal and not g.river_farm(r))
    g.regions[rid].b['farm'] = 1
    g.turn = 9
    e = g.forecast_disaster('drought', duration=2)
    assert not g.weather and e['turn'] == 10
    g.turn += 1
    g.begin_disaster_turn()
    assert g.weather_at(rid, 'drought') and g.weather_farm_mult(rid) == .7
    assert g.regions[rid].last_agri_damage == g.turn
    g.turn += 2
    g.begin_disaster_turn()
    assert not g.weather_at(rid, 'drought')
    river = next(r for r in g.world.river_regions if not g.info(r).coastal)
    g.start_disaster({'kind': 'cold', 'duration': 2})
    assert g.weather_farm_mult(river) == .5 and g.weather_fish_mult(river) == 0
    assert g.weather_happy(river) == -3
    terrain = {'kind': '도하', 'mult': .9}
    g.start_disaster({'kind': 'rain', 'duration': 2})
    assert g.terrain_multiplier(river, rid, terrain) == .7
    g.start_disaster({'kind': 'heat', 'duration': 2})
    assert g.terrain_multiplier(river, rid, terrain) == .95
    assert g.weather_fish_mult(river) == .7


def test_fire_scar_recovers_exactly_and_cycle_immunity(monkeypatch):
    g = game()
    rid = 'S002'
    g.regions[rid].b = dict.fromkeys(g.regions[rid].b, 0)
    g.regions[rid].lines = {}
    g.regions[rid].b['farm'] = 2
    monkeypatch.setattr(C, 'FIRE_OUT_CHANCE', 1)
    monkeypatch.setattr(C, 'FIRE_SPREAD_CHANCE', 0)
    g.ignite(rid)
    g.disaster_damage()
    r = g.regions[rid]
    assert r.fire_scar == 3 and r.fire_recovery == 1 and rid not in g.fires
    assert r.b['farm'] == 1
    g.ignite(rid)
    assert rid not in g.fires
    g.disaster_damage()
    assert r.fire_scar == 0 and r.fire_recovery == 0


def test_typhoon_danger_and_harbor_safety():
    g = game()
    e = g.forecast_disaster('typhoon', duration=2)
    assert len(e['path']) == 4 and e['danger']
    e['danger'] = {'SEA4', 'S002'}
    g.start_disaster(e)
    sea = g.new_army(0, 'SEA4', {'dd': 1})
    port = g.new_army(0, 'S002', {'dd': 1})
    g.disaster_damage()
    assert sea.hp_left('dd') == pytest.approx(35)
    assert port.hp_left('dd') == 50
    assert g.weather_fish_mult('S002') == 0


@pytest.mark.parametrize('magnitude,tiers', [(5,(5,)),(6,(6,5)),(7,(7,6,5)),(8,(8,7,5)),(9,(9,8,6,5))])
def test_quake_propagation(magnitude, tiers, monkeypatch):
    g = game()
    seen = {}
    monkeypatch.setattr(g, 'apply_quake_tier', lambda rid,tier: seen.setdefault(rid,tier))
    g.earthquake('S002', magnitude)
    dist = M.distances(g, 'S002', len(tiers)-1)
    assert seen == {rid: tiers[d] for rid,d in dist.items()}


def test_nuclear_quake_outage_and_permanent_loss():
    g = game('standard')
    rid = next(r for r in g.world.order if g.info(r).nuclear)
    r = g.regions[rid]
    r.owner = 0
    g.apply_quake_tier(rid, 8)
    assert g.self_power(rid) == 0
    g.turn += 4
    assert g.self_power(rid) == g.info(rid).nuclear
    g.apply_quake_tier(rid, 9)
    assert r.nuclear_destroyed and r.b['nuclear'] == 0
    o = next(o for o in g.options(0,rid) if o['key'] == 'nuclear')
    assert not o['ok']


def test_harvest_requires_complete_40_turn_record_and_stops_on_damage():
    g = game()
    rid = 'S002'
    g.turn = 33
    assert not g.harvest_active(rid)
    g.turn = 81
    assert g.harvest_active(rid) and g.weather_farm_mult(rid) == 1.3
    g.regions[rid].last_agri_damage = 41
    assert not g.harvest_active(rid)
    g.regions[rid].last_agri_damage = 40
    assert g.harvest_active(rid)
    g.agri_damage(rid)
    assert not g.harvest_active(rid)


def test_metro_queue_shared_and_single_building_reservation():
    from test_metro import _setup
    g, sel = _setup()
    assert g.create_metro(0, 'S002', sel)[0]
    assert g.start_project(0, sel[1], 'build', 'bank', pool='bank')[0]
    assert g.start_project(0, sel[2], 'build', 'farm', pool='farm')[0]
    center = g.queue_region(sel[2])
    assert len(center.queue) == 1 and not g.regions[sel[1]].queue
    p = center.project
    g._fund_projects()
    paid = p.paid
    assert g.move_queued_project(0, sel[3], 1, 0)[0]
    assert all(g.regions[rid].project is center.project for rid in sel)
    assert center.queue[0] is p and p.paid == paid
    # 사관학교 예약 중 options를 다시 열어도 1단계 상한을 올바르게 처리한다.
    assert g.start_project(0, sel[2], 'build', 'academy')[0]
    assert not any(o['key'] == 'academy' for o in g.options(0, sel[2]))
    restored = pickle.loads(pickle.dumps(g))
    cr = restored.queue_region('S002')
    assert len(cr.queue) == 2
    assert all(restored.regions[rid].project is cr.project for rid in sel)


def test_reorder_defers_unit_fuel_until_activation_and_charges_once():
    g = game()
    g.player.res['oil'] = 3
    assert g.start_project(0, 'S002', 'build', 'bank')[0]
    assert g.start_project(0, 'S002', 'unit', 'tank')[0]
    assert g.player.res['oil'] == 3
    assert g.move_queued_project(0, 'S002', 1, 0)[0]
    assert g.player.res['oil'] == 2
    assert g.move_queued_project(0, 'S002', 0, 1)[0]
    assert g.move_queued_project(0, 'S002', 1, 0)[0]
    assert g.player.res['oil'] == 2


def test_old_save_migration_populates_queue_and_power():
    """v1.3.7까지의 세이브(건물 단계 사전·주거 지구)를 불러오면 슬롯 카드로 옮기고 주거 지구는 없앤다."""
    g = game('standard')
    for r in g.regions.values():
        del r.queue
        old = {k: v for k, v in dict(r.b).items() if k not in ('hydro', 'nuclear')}
        old['housing'] = 2
        old['farm'], old['bank'], old['factory'] = 3, 2, 1
        r.__dict__['b'] = old
    state = g.__getstate__()
    state.pop('world_overrides')
    for key in ('weather', 'forecasts', 'fires', 'fire_burned'):
        state.pop(key)
    restored = Game.__new__(Game)
    restored.__setstate__(state)
    assert restored.weather is None
    for r in restored.regions.values():
        assert hasattr(r, 'queue') and isinstance(r.b, S.Buildings) and 'housing' not in r.b
        assert {t: len(v) for t, v in r.b.slots.items()} == S.slot_lengths(restored.world, r.id, 'standard', r.b.free_cards())
        assert r.b.used() <= r.b.total()
    assert sum(restored.self_power(rid) for rid in restored.world.order) > 0
    big = next(r for r in restored.regions.values() if len(r.b.slots['base']) >= 6 and not r.b['admin'])
    assert big.b['farm'] == 3 and big.b['bank'] == 2 and big.b['factory'] == 1


def test_chaos_overlapping_resources_both_produced():
    import copy
    g = game('chaos')
    rid = 'S002'
    g.world = copy.copy(g.world)
    g.world.regions = dict(g.world.regions)
    g.world.regions[rid] = replace(g.info(rid), oil=2, coal_field='①')
    g.regions[rid].b['extract'] = 3
    mined = g.energy_mined(0)
    assert mined['oil'] == 5 and mined['coal'] == 3


def test_joint_annex_reservations_with_different_durations_stay_within_gauge():
    from korciv.state import Project
    g = game()
    rid = 'S002'
    target = next(iter(g.world.land_adj[rid]))
    other = next(r for r in g.world.land_adj[target] if r != rid)
    g.regions[other].owner = 0
    for source, turns in [(rid,13),(other,16)]:
        g.regions[source].project = Project(kind='annex',key=target,turns=turns,progress=12.5,
                                            per_turn=1,funded=True)
    g._advance_annexes()
    assert all(r.project.progress <= r.project.turns for r in (g.regions[rid],g.regions[other]))


def test_repeat_waits_for_fuel_before_promoting_queue():
    g = game()
    r = g.regions['S002']
    g.player.res['oil'] = 1
    assert g.start_units(0,r.id,'tank',2)[0]
    assert g.start_project(0,r.id,'build','farm')[0]
    complete(g)
    assert r.project.kind == 'unit' and r.project.stalled and not r.project.started
    assert r.queue[0].key == 'farm'
    g.player.res['oil'] = 1
    complete(g)
    assert r.project.key == 'farm'


def test_future_unit_can_be_reserved_without_fuel():
    g = game()
    assert g.start_project(0,'S002','build','farm')[0]
    g.player.res.update(oil=0,coal=0)
    assert g.start_project(0,'S002','unit','tank')[0]
    complete(g)
    r = g.regions['S002']
    assert r.project.key == 'tank' and not r.project.started and r.project.stalled


def test_metro_rebuild_after_uneven_disaster_damage():
    from test_metro import _setup
    g, sel = _setup()
    assert g.create_metro(0,'S002',sel)[0]
    for rid in sel:
        g.regions[rid].b['bank'] = 3
    g.regions[sel[1]].b['bank'] = 1                      # 재해로 한 곳만 크게 깎임(카드는 남음)
    mean = M.pool_level(g,M.of(g,'S002'),'bank')
    assert mean == 2
    assert g.start_project(0,'S002','build','bank',pool='bank')[0]
    assert g.regions['S002'].project.level == mean + 1
    complete(g)
    assert all(g.regions[rid].b['bank'] == mean+1 for rid in sel)
