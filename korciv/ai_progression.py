"""행정 비축·연구·위인·성장 집중을 같은 국가 전망과 기회비용으로 판단한다."""
from __future__ import annotations

import math

from . import ai_economy as E, config as C, diplomacy as D, metro as M
from .ai_personality import preference
from .leaders import POLICY_COSTS, Mods
from .progression import TECHS, MODERN_UNITS


def education_centers(g, fid):
    regs = g.regions_of(fid)
    if not regs:
        return set()
    # 과학 수요가 늘수록 안전한 인구 거점으로 넓힌다. 기존 대학과 수도는 계속 유지한다.
    peak = max(r.pop for r in regs)
    f = g.factions[fid]
    ratio = .25 if f.ai.get('victory_goal') == 'science' else .5
    return {r.id for r in regs if r.b['edu'] or r.pop >= peak * ratio} | {f.capital}


def science_reserve(g, fid):
    return E.science_reserve(g, g.factions[fid])


def infrastructure_candidates(g, f, r, opts, threat, edu_centers):
    from .ai import fuel_balance
    ctx = E.snapshot(g, f, threat)
    return [c for c in E.build_candidates(g, f, r, opts, threat, ctx, fuel_balance(g, f.id))
            if c[3] in ('admin', 'edu')]


def tech_scores(g, f, ctx=None):
    ctx = ctx or E.snapshot(g, f)
    regs, enemies = ctx['regs'], ctx['enemies']
    units = {key: sum(a.units.get(key, 0) for a in g.armies.values() if a.owner == f.id) for key in C.BUILD_UNITS}
    goal = f.ai.get('victory_goal', f.ai.get('goal'))
    scores = {}
    for key, spec in TECHS.items():
        if key in f.techs:
            continue
        benefit = 0.0
        if spec['kind'] == 'unit':
            now = g.unit_spec(f.id, key)
            after = MODERN_UNITS[key]
            combat_gain = sum(max(0, after.get(k, now.get(k, 0)) - now.get(k, 0))
                              for k in ('atk', 'df', 'hp', 'bomb', 'intercept'))
            benefit = combat_gain * units.get(key, 0) / 12
            if enemies:
                benefit *= 1.8 + min(1, ctx['pressure'])
                if key == 'inf':
                    benefit += 3
                if key == 'ftr' and any(r.b['airport'] for r in regs):
                    benefit += 2
            elif goal != 'conquest':
                benefit *= .35
            if key == 'cv':
                benefit = 5 if units.get('bmb') and any(r.b['port'] and r.b['airport'] for r in regs) and enemies else 0
            action = key if key in ('inf', 'art', 'tank') else 'naval' if key in ('lst', 'dd', 'cv') else 'air'
            benefit *= preference(g, f.id, action) * preference(g, f.id, 'tech_military')
        elif spec['kind'] == 'building':
            building = key
            eligible = [r for r in regs if key != 'extract' or M.extract_res(g, r.id)]
            high = sum(sum(lv >= 3 for lv in r.b.levels(building)) for r in eligible)
            benefit = high * (4 if building in ('bank', 'factory') else 2)
            if key in ('farm', 'fishery') and ctx['food_short'] > 0:
                benefit *= 2
            if key == 'power' and any(g.info(r.id).nuclear and not r.b['nuclear'] for r in regs):
                benefit += 2
            if goal == 'science' and (key in ('factory', 'bank') or
                                     key == 'extract' and any('oil' in M.extract_res(g, r.id) for r in eligible)):
                benefit += 3 if high else 1
            if key == 'bank' and not enemies:
                benefit += .5
            benefit *= preference(g, f.id, building)
        elif 'science' in g.settings.victories and goal == 'science':
            # 해금해도 실제 공사를 착수할 생산/재정이 없으면 과학력을 묶어 두지 않는다.
            can_start = ctx['science'] >= g.science_per_turn_cost(0) * .5 or f.sci_points >= 4500
            benefit = 12 if can_start and ctx['net'] > 0 else .1
            benefit *= preference(g, f.id, 'science')
        scores[key] = benefit * 1000 / max(1, g.tech_cost(f.id, key))
    return scores


def tech_order(g, f):
    scores = tech_scores(g, f)
    return sorted(scores, key=lambda key: (-scores[key], key))


def _recruit(g, f, kind, rid, reserve=0):
    if kind == 'scientist' and f.leader == 'sej':
        sites = [r for r in g.regions_of(f.id) if r.b['edu'] >= 4]
        if not sites:
            return False
        rid = max(sites, key=lambda r: (g.science_output(r.id), r.id)).id
    currency = f.sci_points if kind == 'scientist' else f.admin
    if currency < g.great_person_cost(f.id, kind) + reserve:
        return False
    return g.recruit_great_person(f.id, kind, rid)[0]


def policy_reserve(g, f, ctx):
    """행정 산출을 늘리는 정책은 해금한 뒤의 적자와 성장 여유로 비축을 다시 계산한다."""
    if f.policy_level >= 5:
        return ctx['admin_keep']
    after = Mods(f.leader, f.gov, f.policy_level + 1)
    future = 0.0
    for r in ctx['regs']:
        future += g.office_output(r.id)
        if r.occ or g.resisting(r) or r.flooded:
            continue
        k = r.b.mult_of('base')                 # 광역 슬롯 시청: 구성 지역 수만큼(v1.3.16)
        base = C.ADMIN_OUTPUT[min(5, r.b['admin'])] * k
        metro = M.of(g, r.id)
        if metro and r.b['admin'] == 5:
            base = (50 * k + (100 if f.capital in metro['members'] else 0) if M.is_merged_center(g, r.id)
                    else 50 + (100 / len(metro['members']) if f.capital in metro['members'] else 0))
        future += (base * after.mult('admin_building_output') + after.add('admin_each')
                   + (after.add('capital_admin') if r.id == f.capital else 0)
                   + g.great_person_bonus(r.id, 'admin_add')) * after.mult('admin_output')
    if future <= ctx['admin_prod']:
        return ctx['admin_keep']
    return E.administration_forecast(g, f, ctx['regs'], future, ctx['admin_cons'])['admin_keep']


def progression_orders(g, f, threat, crisis=False):
    ctx = E.snapshot(g, f, threat)
    regs = ctx['regs']
    if not regs:
        return
    if E.develop_resources(g, f, threat, ctx):
        ctx = E.snapshot(g, f, threat)
    E.remember(f, ctx)
    E.redevelop(g, f, threat, ctx)
    people = [p for p in g.great_people if p['owner'] == f.id]
    kinds = {p['kind'] for p in people}
    worst = min(regs, key=lambda r: (g.rebel_happy(r), r.id))
    keep = ctx['admin_keep']
    # 행정 파산 때문에 생긴 민심 위기는 +30 행정/턴의 재상과 행정 시설부터 복구한다.
    if ctx['admin_gap'] >= 15 / preference(g, f.id, 'chancellor') and 'chancellor' not in kinds:
        if _recruit(g, f, 'chancellor', f.capital, min(keep, max(0, ctx['admin_cons'] - ctx['admin_prod']) * 2)):
            kinds.add('chancellor')
            ctx = E.snapshot(g, f, threat)
            keep = ctx['admin_keep']
    if g.rebel_happy(worst) <= -40 / preference(g, f.id, 'artist') and 'artist' not in kinds and not f.lawless:
        if _recruit(g, f, 'artist', worst.id, keep):
            kinds.add('artist')
    general = E.general_plan(g, f, ctx)
    if general['value'] > 0 and general['site'] is not None and 'general' not in kinds:
        _recruit(g, f, 'general', general['site'], keep)
    for _ in range(5):
        if f.policy_level >= 5:
            break
        cost = POLICY_COSTS[f.policy_level]
        required = policy_reserve(g, f, ctx)
        immediate = min(required, max(0, ctx['admin_cons'] - ctx['admin_prod']) * 4)
        required = max(immediate, required / preference(g, f.id, 'policy'))
        if f.admin < cost + required or not g.unlock_policy(f.id)[0]:
            break
        ctx = E.snapshot(g, f, threat)
        keep = ctx['admin_keep']
    ctx = E.snapshot(g, f, threat)
    scores = tech_scores(g, f, ctx)
    reserve = E.science_reserve(g, f, ctx)
    f.ai['research_plan'] = [[k, round(scores[k], 3)] for k in sorted(scores, key=scores.get, reverse=True)[:6]]
    # 과학자 30%의 지속 산출과 기술의 즉시 이득을 비교한다. 연구비 50% 할인도 실제 구매 비용으로 계산.
    campus = max(regs, key=lambda r: (g.science_output(r.id), r.id))
    scientist_value = .3 * g.science_output(campus.id) * ctx['horizon'] * preference(g, f.id, 'scientist')
    if ('scientist' not in kinds and scientist_value >= g.great_person_cost(f.id, 'scientist') * 1.1
            and (not crisis or not ctx['enemies'])):
        if _recruit(g, f, 'scientist', campus.id, reserve):
            kinds.add('scientist')
    for key in sorted(scores, key=lambda k: (-scores[k], k)):
        if scores[key] < .3 or f.sci_points < g.tech_cost(f.id, key) + reserve:
            continue  # 비싼 연구 하나 때문에 더 싸고 필요한 연구까지 멈추지 않는다.
        g.unlock_tech(f.id, key)
    if 'chancellor' not in kinds and ctx['horizon'] >= 20 and ctx['income'] > 300 / preference(g, f.id, 'chancellor'):
        valuable = max(regs, key=lambda r: (g.calc_output(r.id), r.id))
        _recruit(g, f, 'chancellor', valuable.id, keep)
    great_people_orders(g, f, threat)


def great_people_orders(g, f, threat):
    ctx = E.snapshot(g, f, threat)
    regs = ctx['regs']
    if not regs:
        return
    generals = set()
    for person in list(g.great_people):
        if person['owner'] != f.id:
            continue
        kind = person['kind']
        target, use = None, False
        if kind in ('scientist', 'chancellor'):
            project_kind = 'science' if kind == 'scientist' else 'econ'
            passive = (max(g.science_output(r.id) for r in regs) * .3 if kind == 'scientist'
                       else 30 + max(g.calc_output(r.id) for r in regs) * .15)
            sites = [r for r in regs if r.project and r.project.kind == project_kind
                     and not r.project.stalled and not g.facility_paused(r.id)]
            if sites:
                site = max(sites, key=lambda r: (r.project.remaining, r.id))
                saved = site.project.remaining - max(3 if kind == 'scientist' else 1, math.ceil(site.project.remaining / 2))
                urgent = f.ai.get('phase', 1) >= 3 or f.ai.get('victory_goal') == ('science' if kind == 'scientist' else 'economic')
                money_saved = saved * site.project.per_turn
                passive_value = passive * min(24, ctx['horizon'])
                # 재상이 행정 적자를 메우고 있으면 경제 단계 단축에 소모하지 않는다.
                stable = kind != 'chancellor' or ctx['admin_prod'] - ctx['admin_cons'] >= 30
                if saved > 0 and stable and (urgent and saved >= 3 or money_saved > passive_value * 1.5):
                    target, use = site.id, True
            if target is None:
                target = max(regs, key=lambda r: ((g.science_output(r.id) / g.great_person_bonus(r.id, 'science_mult', f.id) if kind == 'scientist'
                              else g.calc_output(r.id) / g.great_person_bonus(r.id, 'output_mult', f.id)), -threat.get(r.id, 0), r.id)).id
        elif kind == 'artist':
            rr = min(regs, key=lambda r: (g.rebel_happy(r), r.id))
            target = M.center_of(g, rr.id)
            use = g.rebel_happy(rr) <= -30 or f.war_weary >= 25 or sum(g.eff_happy(r) < 0 for r in regs) >= max(2, len(regs) // 3)
        elif kind == 'general':
            escort = g.armies.get(person.get('escort'))
            if escort is not None and escort.owner == f.id and (escort.order or person['loc'] not in g.regions
                                                               or g.regions[person['loc']].owner != f.id):
                # 진군 중인 장군을 매 턴 수도로 되돌리지 않는다.
                generals.add(person['loc'])
                continue
            choices = [r for r in regs if r.id not in generals and g.armies_at(r.id, f.id)]
            if choices:
                target = max(choices, key=lambda r: (sum(a.count(('land',)) for a in g.armies_at(r.id, f.id))
                             * (1 + threat.get(r.id, 0)), r.id)).id
                generals.add(target)
        if target is None:
            continue
        if person['loc'] != target:
            g.move_great_person(person['id'], target)
        if use and person['loc'] == target:
            g.activate_great_person(person['id'])


def focus_orders(g, f, threat):
    ctx = E.snapshot(g, f, threat)
    E.remember(f, ctx)
    # 행정·식량으로 유지할 수 있는 성장만 선택한다. 모든 빈 지역의 P/G를 한꺼번에 같은 방향으로 돌리지 않는다.
    admin_room = max(0, ctx['admin_prod'] - ctx['admin_cons']) + max(0, f.admin - ctx['admin_keep']) / 12
    food_room = max(0, ctx['food_prod'] - ctx['food_cons']) + f.res.get('food', 0) / 16
    for r in sorted(ctx['regs'], key=lambda r: (-g.density_growth(r.id), -r.pop, r.id)):
        if r.project or r.occ or g.resisting(r) or r.flooded:
            continue
        horizon = max(4, ctx['horizon'])
        bonus = C.POP_FOCUS_GROWTH * g.growth_scale(r.id) * g.focus_multiplier(f.id)
        people = r.pop * bonus * horizon
        near_people = r.pop * bonus * min(8, horizon)
        near_admin = max(0, near_people - (g.office_output(r.id, r.pop + near_people) - g.office_output(r.id)))
        income_gain = 30 * people * f.tax * horizon / 2
        focus_income = 30 * r.pop * C.FOCUS_POP_BONUS * g.focus_multiplier(f.id) * f.tax * horizon * preference(g, f.id, 'focus')
        grow = (g.growth_happy(r) >= C.POP_FOCUS_MIN_H + 3 and threat.get(r.id, 0) < .8
                and not f.lawless and near_admin <= admin_room and near_people <= food_room
                and r.pop < g.crowd_thresholds(r.id)[0]
                and income_gain * preference(g, f.id, 'growth') > focus_income * .8)
        # 박정희의 집중 해제 불행을 이익이 작을 때 반복 유발하지 않는다.
        if grow and r.focus and g.mods(f.id).value('focus_release_happy'):
            grow = income_gain > focus_income * 1.5
        if grow:
            admin_room -= near_admin
            food_room -= near_people
        if r.focus and grow:
            g.release_focus(r)
        r.pop_focus, r.focus = grow, not grow
    # 잉여를 무조건 판매하지 않고, 성장 투자에 쓸 배급을 재정 여유와 함께 선택한다.
    if ctx['food_prod'] > ctx['food_cons'] * 1.2 and ctx['admin_gap'] <= 0 and ctx['net'] > 0:
        f.food_mode = 'ration'
    else:
        f.food_mode = 'store'
