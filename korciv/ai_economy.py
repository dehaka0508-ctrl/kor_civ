"""성장·행정·연구·작업 슬롯의 공통 한계효용과 자원 예산. 상대의 숨은 병력/재고는 읽지 않는다."""
from __future__ import annotations

import math

from . import config as C, diplomacy as D, metro as M, rules as R
from .ai_personality import preference
from .leaders import POLICY_COSTS
from .state import NEUTRAL


def population_rate(g, f, r):
    """실제 성장 요인을 사용하되 기근·이주 감소를 행정 여유로 잡지 않는다."""
    rate = R.pop_growth_rate(g.growth_happy(r), g.density_growth(r.id)) * f.pop_mult
    if g.pop_focus_active(r):
        rate += C.POP_FOCUS_GROWTH * g.growth_scale(r.id) * g.focus_multiplier(f.id)
    rate += getattr(f, 'ration_bonus', 0) * g.growth_scale(r.id) * g.mods(f.id).mult('ration_growth')
    return max(0, rate * g.mods(f.id).mult('growth'))


def admin_base(g, f, r, level):
    n = r.b.mult_of('base')
    metro = M.of(g, r.id)
    if metro and level == 5:
        return 50 * n + (100 if f.capital in metro['members'] else 0)
    return C.ADMIN_OUTPUT[min(5, level)] * n


def administration_forecast(g, f, regs, prod, cons, window=12):
    """건설 선행 시간 동안 인구·편입/점령·예약 행정 산출과 비축 소진을 예측한다."""
    if 'time' in g.settings.victories:
        window = min(window, max(1, g.settings.max_turns - g.turn))
    rates = {r.id: population_rate(g, f, r) for r in regs}
    pops = {r.id: r.pop for r in regs}
    ends = {r.id: max(0, r.resist['turn'] + r.resist['resist'] - g.turn) if g.resisting(r) else 0 for r in regs}
    growth = sum(pops[r.id] * rates[r.id] for r in regs)
    incoming, completions = {}, []
    mult = g.mods(f.id).mult('admin_building_output') * g.mods(f.id).mult('admin_output')
    for r in regs:
        if M.is_extra(g, r.id):
            continue
        elapsed, level = 0, r.b['admin']
        for p in g.local_projects(r.id):
            elapsed += p.remaining
            if p.kind == 'build' and p.key == 'admin':
                completions.append((elapsed, (admin_base(g, f, r, p.level) - admin_base(g, f, r, level)) * mult))
                level = p.level
            if p.kind == 'annex' and p.key in g.regions and g.regions[p.key].owner != f.id:
                left = max(1, math.ceil(g.project_left(r.id))) if p is r.project else elapsed
                incoming[p.key] = (min(left, incoming.get(p.key, (999,))[0]), 1.0)
    # 같은 대상의 공동 편입은 한 번만. 점령 직후에는 저항기의 반액 소비를 적용한다.
    for r in g.regions.values():
        occ = r.occs.get(f.id)
        if r.owner != f.id and occ:
            left = max(1, occ['need'] - occ['progress'])
            if left < incoming.get(r.id, (999,))[0]:
                incoming[r.id] = (left, .5)
    incoming = {rid: data for rid, data in incoming.items() if data[0] <= window}
    capital_members = M.members(g, f.capital) if f.capital in g.regions else []
    office = g.office_output(f.capital) if f.capital in g.regions else 0
    stock, minimum, cover = 0.0, 0.0, 999.0
    final_gap = expansion = office_gain = 0.0
    for t in range(1, window + 1):
        pops = {rid: pop * (1 + rates[rid]) for rid, pop in pops.items()}
        future_cons = sum(pops[r.id] * (.5 if ends[r.id] > t else 1) for r in regs)
        office_gain = (max(30, sum(pops.get(rid, 0) for rid in capital_members)) - office) if office else 0
        future_prod = prod + office_gain + sum(delta for done, delta in completions if done <= t)
        for r in regs:
            if 0 < ends[r.id] <= t and not r.flooded and not r.occ and not M.is_extra(g, r.id):
                m = g.mods(f.id)
                future_prod += (admin_base(g, f, r, r.b['admin']) * m.mult('admin_building_output')
                                + m.add('admin_each') + g.great_person_bonus(r.id, 'admin_add')) * m.mult('admin_output')
        expansion = 0.0
        for rid, (done, factor) in incoming.items():
            if done > t:
                continue
            rr = g.regions[rid]
            burden = rr.pop * (1 + population_rate(g, f, rr)) ** max(0, t - done) * factor
            supply = admin_base(g, f, rr, rr.b['admin']) * mult if factor == 1 else 0
            expansion += max(0, burden - supply)
        future_cons += expansion
        stock += future_prod - future_cons
        minimum = min(minimum, stock)
        if cover == 999 and f.admin + stock <= 0 and future_cons > future_prod:
            cover = float(t)
        final_gap = max(0, future_cons + max(0, future_cons - office - office_gain) * .08 - future_prod)
    deficit = max(0, cons - prod)
    current_cover = f.admin / deficit if deficit else 999.0
    return dict(growth=growth, admin_growth=max(0, growth - office_gain / max(1, window)), admin_gap=final_gap,
                admin_keep=max(-minimum, deficit * 6) + final_gap * 2,
                admin_cover=min(current_cover, cover), expansion_admin=expansion, admin_window=window,
                admin_margin=future_prod - future_cons)


def snapshot(g, f, threat=None):
    regs = g.regions_of(f.id)
    threat = threat or {}
    projects = list(g.unique_projects(regs))
    prod, cons = g.admin_balance(f.id)
    science = g.science_production(f.id)
    food_prod = sum(g.food_prod(f.id, r) for r in regs if not r.occ and not g.resisting(r))
    food_cons = sum(r.pop for r in regs) * C.FOOD_PER_POP
    forecast = administration_forecast(g, f, regs, prod, cons)
    enemies = D.enemies(g, f.id)
    # 공개 외교 신호와 기존 시야 기반 정세만 사용한다.
    scan = (f.ai.get('p2') or {}).get('scan', {})
    pressure = max(max(threat.values(), default=0), max((v['T'] for v in scan.values()), default=0))
    horizon = min(64, max(12, 52 - 8 * len(enemies) - 10 * min(2, pressure)))
    if 'time' in g.settings.victories:
        horizon = min(horizon, max(1, g.settings.max_turns - g.turn))
    income = g.leader_tax_revenue(f.id)
    upkeep = g.upkeep(f.id)
    committed = sum(p.per_turn for p in projects)
    food_short = max(0, food_cons - food_prod)
    food_bill = max(0, food_short - f.res.get('food', 0) / 6) * C.MARKET_BUY['food']
    food_keep = max(0, food_short * 4 - f.res.get('food', 0)) * C.MARKET_BUY['food']
    money_keep = 200 + upkeep * (5 if enemies or pressure > .7 else 3) + food_keep
    active_science = sum(g.science_per_turn_cost(C.SCIENCE[p.key]['tier']) for p in projects if p.kind == 'science')
    return dict(regs=regs, projects=projects, threat=threat, pressure=pressure, enemies=enemies,
                horizon=horizon, **forecast, admin_prod=prod, admin_cons=cons, science=science, science_due=active_science,
                food_prod=food_prod, food_cons=food_cons, food_short=food_short, food_bill=food_bill, income=income,
                upkeep=upkeep, committed=committed, money_keep=money_keep,
                net=income - upkeep - committed - food_bill)


def remember(f, ctx):
    f.ai['development'] = {k: round(v, 3) for k, v in ctx.items() if isinstance(v, (int, float))}


def science_reserve(g, f, ctx=None):
    ctx = ctx or snapshot(g, f)
    # 기존 5턴 납부액은 항상 보호하고, 산출이 납부액보다 작으면 완공까지 부족분도 보호한다.
    due = ctx['science_due']
    projects = [p for p in ctx['projects'] if p.kind == 'science']
    shortfall = max((sum(g.science_per_turn_cost(C.SCIENCE[p.key]['tier']) * min(t, p.remaining)
                         for p in projects) - ctx['science'] * t for t in {p.remaining for p in projects}), default=0)
    return max(5 * due, shortfall)


def resource_missing(g, rid):
    """예약까지 반영한 채굴 카드 부재. 광역시는 한 카드가 구성 지역의 두 자원을 함께 개발한다."""
    rid = M.center_of(g, rid)
    return bool(M.extract_res(g, rid)) and not any(
        c and c['key'] == 'extract' for c in g.projected_slots(rid).get('base', ()))


def develop_resources(g, f, threat, ctx):
    """자원 개발을 선행 투자로 확정한다. 기존 꽉 찬 유전/탄전은 저손실 생산 카드부터 교체한다."""
    if g.order_frozen(f.id):
        return False
    changed = False
    for r in ctx['regs']:
        if M.is_extra(g, r.id) or r.project or r.queue or r.occ or g.resisting(r) or r.flooded:
            continue
        if not resource_missing(g, r.id) or threat.get(r.id, 0) >= 1:
            continue
        choices = [o for o in g.options(f.id, r.id) if o['kind'] == 'build' and o['key'] == 'extract' and o['ok']]
        removed = None
        if not choices and not r.b.empty('base'):
            # 채굴 가능한 1단계는 기술 없이 허용된다. 허가·예산 확인 후에만 철거한다.
            cost, turns = g.card_cost(f.id, r.id, 'extract', 1)
            cost *= r.b.mult_of('base')
            if not g.building_allowed(f.id, r.id, 'extract', 1)[0] or not can_finance(
                    g, f, ctx, dict(turns=turns, per_turn=cost / turns)):
                continue
            swaps = []
            for t, idx, card in r.b.cards():
                key, lv = card['key'], card['level']
                if t != 'base' or key not in ('bank', 'farm', 'factory'):
                    continue
                # 승리 시설이 의존하는 유일한 고급 은행/공장은 보존한다.
                if key in ('bank', 'factory') and lv >= 5 and r.b.count(key) == 1:
                    if r.econ or r.sci or f.ai.get('victory_goal') in ('science', 'economic'):
                        if not any(x.id != r.id and g.blevel(x.id, key) >= 5 for x in ctx['regs']):
                            continue
                n = r.b.mult_of(t)
                if key == 'farm' and ctx['food_prod'] - C.FARM_FOOD * lv * n < ctx['food_cons'] * 1.1:
                    continue
                loss = (C.BANK_OUTPUT * R.g(lv) if key == 'bank' else C.FARM_OUTPUT * lv if key == 'farm'
                        else R.factory_output(lv, min(lv, r.fuel_used))) * n
                swaps.append((loss, t, idx, dict(card)))
            if not swaps:
                continue
            _, t, idx, card = min(swaps, key=lambda x: x[:3])
            energy = dict(r.energy)
            if not g.demolish_card(f.id, r.id, (t, idx))[0]:
                continue
            removed = ((t, idx), card, energy)
            choices = [o for o in g.options(f.id, r.id) if o['kind'] == 'build' and o['key'] == 'extract' and o['ok']]
        option = next((o for o in choices if can_finance(g, f, ctx, o)), None)
        ok = bool(option) and g.start_project(f.id, r.id, 'build', 'extract', slot=option['slot'])[0]
        if ok:
            changed = True
            ctx = snapshot(g, f, threat)  # 다른 자원 지역 공사와 예산을 공유한다.
            if removed:
                f.ai['last_redevelopment'] = [g.turn, r.id, 'extract', True]
        elif removed:
            slot, card, energy = removed
            r.b.place(card['key'], card['level'], slot)  # 예상 밖 착수 거절 시 원래 카드 복원
            r.energy = energy
    return changed


def general_plan(g, f, ctx):
    """전투 예정 병력의 장군 공격 +20%/방어 +25%를 병력 대체 비용과 비교한다."""
    from .progression import GP_POOLS
    armies = [a for a in g.armies.values() if a.owner == f.id and a.count(('land',))]
    preparing = bool(ctx['enemies'] or ctx['pressure'] >= .7 or
                     f.ai.get('victory_goal') == 'conquest' and f.ai.get('phase', 1) >= 2)
    if not armies or not preparing or all(n in g.spawned_great_people for n in GP_POOLS['general']):
        return dict(value=0, site=None)
    sites = [(sum(sum(g.unit_cost(f.id, r.id, k) * a.units.get(k, 0) for k in ('inf', 'art', 'tank'))
                  for a in g.armies_at(r.id, f.id)), r.id) for r in ctx['regs'] if not M.is_extra(g, r.id)]
    force, site = max(sites, default=(0, None))
    battles = min(3, ctx['horizon'] / 12) * (1 if ctx['enemies'] else .6)
    gain = .25 if ctx['pressure'] >= 1 else .20
    value = force * gain * battles * preference(g, f.id, 'general')
    # 장군은 행정력을 소모한다. 민생 비축을 쓸 수 없으면 해금 가치도 낮춘다.
    cost = g.great_person_cost(f.id, 'general')
    available = max(0, f.admin - ctx['admin_keep']) + max(0, ctx['admin_prod'] - ctx['admin_cons']) * 8
    value = max(0, value - cost * (3 if ctx['admin_gap'] <= 0 else 8)) * min(1, available / max(1, cost))
    return dict(value=value, site=site)


def slot_factor(g, f, rid, o, ctx):
    slot = o.get('slot')
    if not slot or o['level'] > 1:
        return 1.0
    rid = o.get('site') or M.center_of(g, rid)
    proj = g.projected_slots(rid)
    free = sum(c is None for c in proj.get(slot[0], ()))
    r, key = g.regions[rid], o['key']
    if slot[0] == 'base' and free <= 1:
        if key != 'extract' and resource_missing(g, rid):
            return 0.0
        if key == 'admin' and ctx['admin_gap'] > 0:
            return 1.25
        if key == 'edu' and r.id == f.capital and not any(x.b['edu'] for x in ctx['regs']):
            return 1.0
        if not r.b['admin'] and ctx['admin_gap'] > 0:
            return .18
        if not r.b['edu'] and r.pop >= max((x.pop for x in ctx['regs']), default=0) * .7:
            return .45
        return .72
    # 항구·발전소·어장이 경합한다. 이미 다른 항구가 있거나 무료 항구를 받는 지도자는 어장을 덜 억제한다.
    if slot[0] == 'coast' and free <= 1 and key == 'fishery':
        naval_need = bool(ctx['enemies']) or f.ai.get('victory_goal') == 'conquest'
        if naval_need and not any(x.b['port'] for x in ctx['regs']):
            return .45
    return 1.0


def _output_mult(g, f, r):
    m = g.mods(f.id)
    mult = m.mult('output_prod') * m.mult('output_money') * R.unhappy_output_mult(g.eff_happy(r))
    mult *= g.great_person_bonus(r.id, 'output_mult') * g.leader_output_mult(r.id)
    if r.id == f.capital:
        mult *= m.mult('capital_money') * (1 + C.CAPITAL_OUTPUT_BONUS * m.value('capital_bonus_mult', 1))
    if r.id not in g.near_capital(f.id):
        mult *= 1 - m.value('far_output', 0)
    return mult


def marginal(g, f, rid, o, ctx, fuel):
    """완공 후 매 턴 늘어나는 (금전 산출, 식량, 행정, 과학). 후보 카드와 입지를 그대로 평가한다."""
    key, lv = o['key'], o['level']
    sites = M.pool_members(g, M.of(g, rid), o['pool']) if o.get('pool') else [o.get('site') or rid]
    money = food = admin = science = 0.0
    m = g.mods(f.id)
    n = o.get('mult', 1)                     # 광역 슬롯 카드(v1.3.16): 구성 지역 수만큼 산출
    for site in sites:
        r = g.regions[site]
        food0 = food
        old = lv - 1
        if o.get('slot'):
            c = r.b.card(o['slot'])
            old = c['level'] if c else 0
        delta = max(0, lv - old)
        dy = 0.0
        if key == 'farm':
            dy = C.FARM_OUTPUT * delta * g.farm_mult(f.id, site)
            food += C.FARM_FOOD * delta * g.farm_mult(f.id, site) * m.mult('food_prod')
        elif key == 'fishery':
            fm = g.fish_slot_mult(f.id, site, (o.get('slot') or ('coast',))[0])
            dy = C.FISH_OUTPUT * delta * fm
            food += C.FISH_FOOD * delta * fm * m.mult('food_prod')
        elif key == 'bank':
            dy = C.BANK_OUTPUT * (R.g(lv) - R.g(old)) * m.mult('output_bank') * g.leader_bank_mult(f.id, site)
            if r.b['edu'] >= 3:
                dy *= m.mult('educated_output')
            if 'exchange' in r.econ and not g.facility_paused(site):
                dy *= 1 + C.EXCHANGE_BANK_BONUS
        elif key == 'factory':
            # 높은 단계 카드부터 연료가 배정되므로 생산 능력이 남는다고 모든 카드를 만충으로 보지 않는다.
            levels = r.b.levels('factory')
            used = min(sum(levels), max(0, getattr(r, 'fuel_used', 0)))
            after = list(levels)
            if old in after and old:
                after.remove(old)
            after.append(lv)
            new_used = min(sum(after), used + max(0, fuel['spare']))
            dy = R.factory_output(after, new_used) * (1 + m.add('factory_fuel_output') * new_used)
            dy -= R.factory_output(levels, used) * (1 + m.add('factory_fuel_output') * used)
            dy *= m.mult('output_factory')
            if r.b['edu'] >= 3:
                dy *= m.mult('educated_output')
        elif key == 'admin':
            metro = M.of(g, site)
            if M.is_merged_center(g, site):
                k = r.b.mult_of('base')
                new_base = (50 * k + (100 if f.capital in metro['members'] else 0) if lv == 5
                            else C.ADMIN_OUTPUT[min(5, lv)] * k)
                d = new_base - C.ADMIN_OUTPUT[min(5, old)] * k
            else:
                new_base = (50 + (100 / len(metro['members']) if f.capital in metro['members'] else 0)
                            if metro and lv == 5 else C.ADMIN_OUTPUT[min(5, lv)])
                d = new_base - C.ADMIN_OUTPUT[min(5, old)]
            admin += d * m.mult('admin_building_output') * m.mult('admin_output')
        elif key == 'edu':
            metro = M.of(g, site)
            if M.is_merged_center(g, site):
                pop = sum(g.regions[x].pop for x in metro['members'])
                new_base = (6 * pop + (500 if f.capital in metro['members'] else 0) if lv == 5
                            else C.EDU_SCIENCE[min(5, lv)] * pop)
            else:
                pop = r.pop
                new_base = (6 * r.pop + (500 / len(metro['members']) if f.capital in metro['members'] else 0)
                            if metro and lv == 5 else C.EDU_SCIENCE[min(5, lv)] * r.pop)
            science += (new_base - C.EDU_SCIENCE[min(5, old)] * pop) * m.mult('science_edu') * m.mult('science_output') * g.great_person_bonus(site, 'science_mult')
        elif key in ('hydro', 'nuclear', 'extract', 'power'):
            unit = max(C.MARKET_SELL['elec'], 1100 * max(.05, f.tax)) if fuel['spare'] < 0 else C.MARKET_SELL['elec']
            if key in ('hydro', 'nuclear'):
                dy = unit * min(lv, getattr(g.info(site), key)) / max(.05, f.tax)
            elif key == 'extract':
                resource = 'oil' if 'oil' in M.extract_res(g, site) else 'coal'
                unit = max(C.MARKET_SELL[resource], unit if fuel['spare'] < 0 else 0)
                dy = unit * delta / max(.05, f.tax)
            else:
                existing = min(old, max(0, fuel['supply']) / max(1, len(ctx['regs'])))
                extra = min(delta, max(0, fuel['raw_left'])) * max(0, g.power_elec(f.id, 'coal', lv) - 1)
                extra += existing * max(0, g.power_elec(f.id, 'coal', lv) - g.power_elec(f.id, 'coal', max(1, old)))
                dy = extra * unit / max(.05, f.tax)
        elif key == 'port':
            dy = C.BANK_OUTPUT * R.g(m.value('port_bank', 0)) * m.mult('output_bank')
        elif key == 'academy':
            radius = int(m.value('academy_radius', 1))
            nearby = g.land_within(site, radius) | {site}
            planned = sum(p.per_turn * p.remaining for rr in ctx['regs'] if rr.id in nearby
                          for p in g.local_projects(rr.id) if p.kind == 'unit')
            if ctx['enemies']:
                planned += min(10000, max(0, ctx['income']) * 5)
            dy = planned * C.ACADEMY_ADJ * 1.1 / max(1, ctx['horizon']) / max(.05, f.tax)
        elif key == 'specialty':
            # 해당 특산물이 모자랄 때의 행복·성장 가치. 진상 몫은 생산 증가에서 먼저 뺀다.
            share = 1 - 1 / m.value('specialty_tithe', 1e9)
            unhappy = sum(g.eff_happy(x) < 5 for x in ctx['regs'])
            dy = 60 * delta * len(g.info(site).specialties) * min(2, .3 + unhappy) * share
        if key not in ('admin', 'edu'):
            dy *= n
            food = food0 + (food - food0) * n
        money += max(0, dy) * _output_mult(g, f, r)
    return money, food, admin, science


def build_candidates(g, f, r, opts, threat, ctx, fuel, production=1.0):
    """후보 = 할인된 한계가치 / 실제 총비용. 실행할 카드·슬롯을 7번째 값으로 보존한다."""
    out = []
    seen = set()
    gap = ctx['admin_gap']
    admin_price = 1.5 if gap <= 0 else min(45, 7 + 30 * gap / max(1, ctx['admin_cons']))
    if ctx['admin_cover'] < 6 or f.lawless:
        admin_price *= 2.5
    science_target = max(12, ctx['admin_cons'] * .6, ctx['science_due'])
    science_gap = max(0, 1 - ctx['science'] / science_target)
    science_price = 1.5 + 4 * science_gap + (1.5 if f.ai.get('victory_goal') == 'science' else 0)
    science_price += 1.5 if any(p.kind == 'science' for p in ctx['projects']) else 0
    science_price *= max(.2, min(1.4, (1000 + ctx['science'] * 12) / max(1, f.sci_points)))
    for o in opts:
        if not o['ok'] or o['kind'] != 'build' or o['key'] not in (*C.PROD_PAYBACK_KEYS, 'admin', 'edu', 'hydro', 'nuclear', 'specialty', 'academy'):
            continue
        key = o['key']
        factor = slot_factor(g, f, r.id, o, ctx)
        if factor <= 0:
            continue
        ident = (key, o['level'], o.get('slot'), o.get('pool'))
        # 동일한 빈 기본 슬롯에 꽂는 같은 카드만 중복을 뺀다. 하천/해안은 별도 평가한다.
        if ident in seen:
            continue
        seen.add(ident)
        dy, food, admin, science = marginal(g, f, r.id, o, ctx, fuel)
        turns, cost = o['turns'], max(1, o['cost'])
        horizon = max(0, ctx['horizon'] - turns)
        if horizon <= 0:
            continue
        useful_food = min(food, max(0, ctx['food_short'] + ctx['growth'] * 6))
        food_value = useful_food * C.MARKET_BUY['food'] + max(0, food - useful_food) * C.MARKET_SELL['food'] * .2
        if getattr(f, 'food_mode', 'store') == 'ration' and ctx['food_prod'] < ctx['food_cons'] * 1.2:
            food_value += max(0, food - useful_food) * 1.0
        # 행정 생산이 이미 충분하면 다음 해금의 장기 가치만 남기며 과잉 건설을 억제한다.
        admin_value = min(admin, gap) * admin_price + max(0, admin - gap) * (1.0 if f.policy_level < 5 else .15)
        value = (dy * max(.05, f.tax) + food_value + admin_value + science * science_price) * horizon / cost
        if key == 'admin' and gap > 0:
            value += min(6, gap / max(1, admin)) * (2 if ctx['admin_cover'] < turns + 4 else .25)
        if key == 'edu' and r.pop < 2 and any(x.b['edu'] for x in ctx['regs']):
            value *= .5
        if key in ('admin', 'edu') and o['level'] == 4:
            # 광역시·위인 해금의 선택권. 무조건 모든 도시를 4단계로 만들지는 않는다.
            value += .4 if r.id == f.capital or len(M.members(g, r.id)) > 1 else .05
        if key == 'academy':
            value += .15  # 할인 외에도 장교 양성 기반을 소폭 우대한다.
            if not any(x.b['academy'] for x in ctx['regs']) and not any(
                    p['owner'] == f.id and p['kind'] == 'general' for p in g.great_people):
                value += general_plan(g, f, ctx)['value'] / cost
        risk = 1 / (1 + .65 * threat.get(r.id, 0))
        value *= risk * factor * preference(g, f.id, key, rid=r.id)
        if key == 'admin' and gap > 0 and (f.lawless or ctx['admin_cover'] <= ctx['admin_window']):
            # 수익성 높은 시장이 행정 파산 예방을 계속 밀어내지 않게 한다. 빠른 공사부터 착수한다.
            value = max(value, 60 + min(20, gap / max(1, admin)) - turns)
        if key not in ('admin', 'edu'):
            value *= production * f.ai.get('weights', {}).get('economy', 1)
            if f.ai.get('phase', 2) == 1:
                # 국경의 작업 시간에는 평화 편입이라는 대안이 있다. 안쪽 도시의 건설을 먼저 활용한다.
                frontier = any(g.regions[n].owner == NEUTRAL for n in g.world.land_adj[r.id])
                value *= C.AI_P1_FRONTIER_PROD if frontier else C.AI_P1_INTERIOR_PROD
        out.append((value, r.id, 'build', key, None, o['per_turn'], o.get('slot'), o.get('pool')))
    return out


def can_finance(g, f, ctx, option, additional=0):
    window = min(8, max(1, option['turns']))
    costs = sum(p.per_turn * min(window, p.remaining) for p in ctx['projects'])
    costs += (ctx.get('new_commitments', 0) + additional + option['per_turn']) * window
    food_cost = max(0, ctx['food_short'] * window - f.res.get('food', 0)) * C.MARKET_BUY['food']
    net = ctx['income'] - ctx['upkeep']
    return f.money + net * window - costs - food_cost >= min(ctx['money_keep'], max(100, f.money * .25))


def victory_project_allowed(g, f, rid, kind, key):
    """승리 공사는 기본 한 건. 전액 현금 여유와 과학력 완충분이 있는 경우만 병행한다."""
    if not f.is_ai:
        return True
    ctx = snapshot(g, f)
    projects = list({id(p): p for r in ctx['regs'] for p in g.local_projects(r.id)}.values())
    active = [p for p in projects if p.kind in ('science', 'econ') and p.remaining > 0]
    if not active:
        return True
    options = [o for o in g.options(f.id, rid) if o['kind'] == kind and o['key'] == key and o['ok']]
    if not options:
        return False
    option = options[0]
    due = sum(p.per_turn * p.remaining for p in projects) + option['cost']
    cash_keep = ctx['money_keep'] + 12 * (ctx['upkeep'] + ctx['food_bill'])
    if f.money - cash_keep < due * 1.25:
        return False
    science = [(g.science_per_turn_cost(C.SCIENCE[p.key]['tier']), p.remaining)
               for p in active if p.kind == 'science']
    if kind == 'science':
        science.append((g.science_per_turn_cost(C.SCIENCE[key]['tier']), option['turns']))
    peak = sum(points for points, _ in science)
    shortfall = max((sum(points * min(t, turns) for points, turns in science) - ctx['science'] * t
                     for t in {turns for _, turns in science}), default=0)
    return f.sci_points >= 1.5 * max(0, shortfall) + peak * 4


def _replace_for_development(g, f, r, slot, need):
    """검사 후 교체하고, 예상 밖 착수 거절이면 원래 카드·연료 배정을 복원한다."""
    card, energy = dict(r.b.card(slot)), dict(r.energy)
    if not g.demolish_card(f.id, r.id, slot)[0]:
        return False
    ok = g.start_project(f.id, r.id, 'build', need, slot=slot)[0]
    if not ok:
        r.b.place(card['key'], card['level'], slot)
        r.energy = energy
    else:
        f.ai['last_redevelopment'] = [g.turn, r.id, need, True]
    return ok


def redevelop(g, f, threat, ctx):
    """만석 지역의 행정 부족·인구 40만 이상 연구/시장 부재는 가장 낮은 농장부터 교체한다."""
    if g.order_frozen(f.id):
        return False
    legacy_need = 'admin' if ctx['admin_gap'] > 0 and (f.lawless or ctx['admin_cover'] < ctx['admin_window'] + 4) else (
        'edu' if ctx['science'] < max(12, ctx['admin_cons'] * .6) and g.turn > 16 and ctx['net'] > 0 else None)
    choices, fallback = [], []
    for r in ctx['regs']:
        if resource_missing(g, r.id):
            continue  # 필수 행정·교육 재개발도 채굴 예정지 대신 다른 지역에서 한다.
        if M.is_extra(g, r.id) or r.project or r.queue or r.occ or g.resisting(r) or r.flooded or r.b.empty('base'):
            continue
        if threat.get(r.id, 0) >= 1:
            continue
        admin_need = ctx['admin_gap'] > 0 and not r.b['admin'] and (
            f.lawless or sum(g.admin_consumption(x) for x in M.members(g, r.id)) > g.admin_output(r.id))
        city = M.total_pop(g, r.id) >= 40
        need = ('admin' if admin_need else 'edu' if city and not r.b['edu'] else
                'bank' if city and not r.b['bank'] else legacy_need)
        if need is None or r.b[need] or not g.building_allowed(f.id, r.id, need, 1)[0]:
            continue
        cost, turns = g.card_cost(f.id, r.id, need, 1)
        cost *= r.b.mult_of('base')
        if not can_finance(g, f, ctx, dict(turns=turns, per_turn=cost / turns)):
            continue
        farms = [(c['level'], t, idx) for t, idx, c in r.b.cards('farm') if t == 'base']
        if farms:
            level, t, idx = min(farms)
            loss = C.FARM_FOOD * level * r.b.mult_of(t) * g.farm_mult(f.id, r.id) * g.mods(f.id).mult('food_prod')
            window = max(12, turns)
            food_needed = max(0, ctx['food_cons'] - ctx['food_prod'] + loss) * window
            food_bill = max(0, food_needed - f.res.get('food', 0)) * C.MARKET_BUY['food']
            committed = sum(p.per_turn * min(window, p.remaining) for p in ctx['projects'])
            lost_tax = C.FARM_OUTPUT * level * r.b.mult_of(t) * g.farm_mult(f.id, r.id) * _output_mult(g, f, r) * f.tax
            safe_food = (food_needed <= f.res.get('food', 0) or f.auto_food) and (
                f.money + (ctx['income'] - lost_tax - ctx['upkeep']) * window - committed - cost - food_bill >= ctx['money_keep'])
            if safe_food:
                priority = 0 if need == 'admin' else 1 if need == 'edu' else 2
                choices.append((priority, level, r.id, (t, idx), need))
        # 기존 민생 복구의 저손실 생산 카드 대체는 유지하되 농장 교체가 가능하면 농장부터 쓴다.
        if city or need == 'bank' or r.metro is not None or r.sci or r.econ:
            continue
        for t, idx, card in r.b.cards():
            if t != 'base' or card['key'] not in ('bank', 'factory') or card['level'] >= 4:
                continue
            key, level = card['key'], card['level']
            if need == 'edu' and (ctx['science'] > 0 or len(ctx['regs']) <= C.AI_REDEV_SMALL):
                # 정상 가동 중인 유일 생산 기반을 연구 목표 비율 때문에 계속 철거하지 않는다.
                # 지역이 적은 나라는 연구가 0이어도 지킨다(v1.3.24: 1지역 나라가 유일한 은행을 헐고 적자에 빠졌다).
                if key == 'bank' and r.b.count('bank') < 2:
                    continue
                if key == 'factory' and r.fuel_used > 0:
                    continue
            loss = (C.BANK_OUTPUT * R.g(level) if key == 'bank' else
                    R.factory_output(level, min(level, r.fuel_used)))
            if need == 'edu' and ctx['net'] - loss * max(.05, f.tax) <= 0:
                continue  # 교육 칸을 위해 헐었다가 수지가 적자가 되면 확장·재건 모두 멈춘다(v1.3.24)
            benefit = r.pop if need == 'edu' else 5
            fallback.append((loss / max(1, benefit), r.id, (t, idx), need))
    for _, _, rid, slot, need in sorted(choices):
        if _replace_for_development(g, f, g.regions[rid], slot, need):
            return True
    for _, rid, slot, need in sorted(fallback):
        if _replace_for_development(g, f, g.regions[rid], slot, need):
            return True
    return False


def metro_orders(g, f, threat):
    """안전한 작은 생산 권역만 통합한다. 공사 취소·단계 평균에 의한 핵심 시설 손실을 피한다."""
    period = max(4, round(8 / preference(g, f.id, 'metro')))
    if g.turn % period != f.id % period or g.order_frozen(f.id):
        return False
    regs = g.regions_of(f.id)
    centers = [r for r in regs if r.b['admin'] >= 3 and not r.metro and not r.project and not r.queue]
    for center in sorted(centers, key=lambda r: (-r.pop, r.id))[:3]:
        possible = set(M.candidates(g, f.id, center.id))
        selected = [center.id]
        while len(selected) < 5:
            edge = {n for rid in selected for n in g.world.land_adj[rid] if n in possible and n not in selected}
            safe = [n for n in edge if not g.regions[n].project and not g.regions[n].queue
                    and not g.regions[n].sci and not g.regions[n].econ and threat.get(n, 0) < .5
                    and not any(g.regions[x].owner in D.enemies(g, f.id) for x in g.world.land_adj[n])]
            if not safe:
                break
            selected.append(max(safe, key=lambda n: (g.regions[n].pop, n)))
            if threat.get(center.id, 0) >= .5 or not M.check(g, f.id, center.id, selected)[0]:
                continue
            # 5단계 거점이 광역 슬롯 합병(레벨 합 ÷ 지역 수, v1.3.16)으로 사라지면 승리·고급 생산의 선택권을 잃는다.
            merged = M.merge_plan(g, selected)["slots"]["base"]
            if (any(g.info(x).is_oil or g.info(x).is_coal for x in selected)
                    and not any(c and c['key'] == 'extract' for c in merged) and all(merged)):
                continue  # 합병 직후에도 채굴용 기본 슬롯을 하나 남긴다.
            if any(any(g.regions[x].b[key] >= 5 for x in selected)
                   and max((c["level"] for c in merged if c and c["key"] == key), default=0) < 5
                   for key in ('factory', 'bank', 'admin', 'edu')):
                continue
            if any(threat.get(x, 0) > .2 for x in selected) and f.gov != 'constitutional':
                continue
            return g.create_metro(f.id, center.id, selected)[0]
    return metro_annex_orders(g, f, threat)


def metro_annex_orders(g, f, threat):
    """광역시 편입(v1.3.21): 내 광역시와 맞닿은 안전한 지역을 하나씩 더한다(5단계 광역 카드를 잃지 않을 때만)."""
    for mid, m in sorted(M.metros(g).items()):
        if m.get("owner") != f.id or len(m["members"]) >= 8:
            continue
        cb = g.regions[m["center"]].b
        for rid in M.annex_candidates(g, f.id, mid):
            r = g.regions[rid]
            if r.project or r.queue or r.sci or r.econ or threat.get(rid, 0) >= .5:
                continue
            if any(g.regions[x].owner in D.enemies(g, f.id) for x in g.world.land_adj[rid]):
                continue
            rows = M.annex_rows(g, m, rid)
            lost5 = any(max((c["level"] for c in cb.slots.get("base", []) if c and c["key"] == key), default=0) >= 5
                        and max((c["level"] for c in rows.get("base", []) if c and c["key"] == key), default=0) < 5
                        for key in ('factory', 'bank', 'admin', 'edu'))
            if lost5 or not M.check_annex(g, f.id, mid, rid)[0]:
                continue
            return g.annex_to_metro(f.id, mid, rid)[0]
    return False
