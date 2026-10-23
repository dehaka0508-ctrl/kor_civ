"""성장·행정·연구·작업 슬롯의 공통 한계효용과 자원 예산. 상대의 숨은 병력/재고는 읽지 않는다."""
from __future__ import annotations

import math

from . import config as C, diplomacy as D, metro as M, rules as R
from .ai_personality import preference
from .leaders import POLICY_COSTS
from .state import NEUTRAL


def snapshot(g, f, threat=None):
    regs = g.regions_of(f.id)
    threat = threat or {}
    projects = list(g.unique_projects(regs))
    prod, cons = g.admin_balance(f.id)
    science = g.science_production(f.id)
    food_prod = sum(g.food_prod(f.id, r) for r in regs if not r.occ and not g.resisting(r))
    food_cons = sum(r.pop for r in regs) * C.FOOD_PER_POP
    growth = sum(r.pop * max(0, R.pop_growth_rate(g.growth_happy(r), g.density_growth(r.id)))
                 * f.pop_mult * g.mods(f.id).mult('growth') for r in regs if not r.occ and not g.resisting(r))
    enemies = D.enemies(g, f.id)
    # 공개 외교 신호와 기존 시야 기반 정세만 사용한다.
    scan = (f.ai.get('p2') or {}).get('scan', {})
    pressure = max(max(threat.values(), default=0), max((v['T'] for v in scan.values()), default=0))
    horizon = min(64, max(12, 52 - 8 * len(enemies) - 10 * min(2, pressure)))
    if 'time' in g.settings.victories:
        horizon = min(horizon, max(1, g.settings.max_turns - g.turn))
    queued_admin = 0.0
    for r in regs:
        elapsed = 0
        for p in g.local_projects(r.id):
            elapsed += p.remaining
            if elapsed > 8:
                break
            if p.kind == 'build' and p.key == 'admin':
                old = max(0, min(5, p.level - 1))
                queued_admin += (C.ADMIN_OUTPUT[min(5, p.level)] - C.ADMIN_OUTPUT[old]) / max(1, len(M.members(g, r.id)))
    forecast_cons = cons + growth * 8
    admin_gap = max(0, forecast_cons * 1.08 - prod - queued_admin)
    deficit = max(0, cons - prod)
    admin_keep = deficit * 6 + max(0, growth * 8 - max(0, prod - cons)) * 2
    # 필요할 때 무법 상태를 피할 시간을 번다. 생산이 넉넉하면 정책에 쓸 비축을 묶지 않는다.
    cover = f.admin / max(.001, deficit) if deficit else 999.0
    income = g.leader_tax_revenue(f.id)
    upkeep = g.upkeep(f.id)
    committed = sum(p.per_turn for p in projects)
    food_short = max(0, food_cons - food_prod)
    food_bill = max(0, food_short - f.res.get('food', 0) / 6) * C.MARKET_BUY['food']
    food_keep = max(0, food_short * 4 - f.res.get('food', 0)) * C.MARKET_BUY['food']
    money_keep = 200 + upkeep * (5 if enemies or pressure > .7 else 3) + food_keep
    active_science = sum(g.science_per_turn_cost(C.SCIENCE[p.key]['tier']) for p in projects if p.kind == 'science')
    return dict(regs=regs, projects=projects, threat=threat, pressure=pressure, enemies=enemies,
                horizon=horizon, growth=growth, admin_prod=prod, admin_cons=cons, admin_gap=admin_gap,
                admin_keep=admin_keep, admin_cover=cover, science=science, science_due=active_science,
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


def slot_factor(g, f, rid, o, ctx):
    slot = o.get('slot')
    if not slot or o['level'] > 1:
        return 1.0
    proj = g.projected_slots(rid)
    free = sum(c is None for c in proj.get(slot[0], ()))
    r, key = g.regions[rid], o['key']
    if slot[0] == 'base' and free <= 1:
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
    for site in sites:
        r = g.regions[site]
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
            new_base = (50 + (100 / len(metro['members']) if f.capital in metro['members'] else 0)
                        if metro and lv == 5 else C.ADMIN_OUTPUT[min(5, lv)])
            d = new_base - C.ADMIN_OUTPUT[min(5, old)]
            admin += d * m.mult('admin_building_output') * m.mult('admin_output')
        elif key == 'edu':
            metro = M.of(g, site)
            new_base = (6 * r.pop + (500 / len(metro['members']) if f.capital in metro['members'] else 0)
                        if metro and lv == 5 else C.EDU_SCIENCE[min(5, lv)] * r.pop)
            science += (new_base - C.EDU_SCIENCE[min(5, old)] * r.pop) * m.mult('science_edu') * m.mult('science_output') * g.great_person_bonus(site, 'science_mult')
        elif key in ('hydro', 'nuclear', 'extract', 'power'):
            unit = max(C.MARKET_SELL['elec'], 1100 * max(.05, f.tax)) if fuel['spare'] < 0 else C.MARKET_SELL['elec']
            if key in ('hydro', 'nuclear'):
                dy = unit * min(lv, getattr(g.info(site), key)) / max(.05, f.tax)
            elif key == 'extract':
                resource = 'oil' if g.info(site).is_oil else 'coal'
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
            dy = planned * C.ACADEMY_ADJ / max(1, ctx['horizon']) / max(.05, f.tax)
        elif key == 'specialty':
            # 해당 특산물이 모자랄 때의 행복·성장 가치. 진상 몫은 생산 증가에서 먼저 뺀다.
            share = 1 - 1 / m.value('specialty_tithe', 1e9)
            unhappy = sum(g.eff_happy(x) < 5 for x in ctx['regs'])
            dy = 60 * delta * len(g.info(site).specialties) * min(2, .3 + unhappy) * share
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
        risk = 1 / (1 + .65 * threat.get(r.id, 0))
        value *= risk * slot_factor(g, f, r.id, o, ctx) * preference(g, f.id, key, rid=r.id)
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


def redevelop(g, f, threat, ctx):
    """필수 행정/교육용 칸이 없을 때만 손실이 낮은 카드를 교체한다. 공사·승리 거점은 건드리지 않는다."""
    need = 'admin' if ctx['admin_gap'] > 0 and (f.lawless or ctx['admin_cover'] < 8) else (
        'edu' if ctx['science'] < max(12, ctx['admin_cons'] * .6) and g.turn > 16 and ctx['net'] > 0 else None)
    if need is None:
        return False
    choices = []
    for r in ctx['regs']:
        if r.project or r.queue or r.occ or g.resisting(r) or r.metro is not None or r.b[need] or r.b.empty('base'):
            continue
        if threat.get(r.id, 0) >= 1 or r.sci or r.econ:
            continue
        cost, turns = g.card_cost(f.id, r.id, need, 1)
        if not can_finance(g, f, ctx, dict(turns=turns, per_turn=cost / turns)):
            continue
        for t, idx, card in r.b.cards():
            if t != 'base' or card['key'] not in ('bank', 'farm', 'factory') or card['level'] >= 4:
                continue
            key, level = card['key'], card['level']
            if need == 'edu' and ctx['science'] > 0:
                # 정상 가동 중인 유일 생산 기반을 연구 목표 비율 때문에 계속 철거하지 않는다.
                if key == 'bank' and r.b.count('bank') < 2:
                    continue
                if key == 'factory' and r.fuel_used > 0:
                    continue
            if key == 'farm' and ctx['food_prod'] - C.FARM_FOOD * level < ctx['food_cons'] * 1.1:
                continue
            loss = (C.BANK_OUTPUT * R.g(level) if key == 'bank' else
                    C.FARM_OUTPUT * level if key == 'farm' else
                    R.factory_output(level, min(level, r.fuel_used)))
            benefit = r.pop if need == 'edu' else 5
            choices.append((loss / max(1, benefit), r.id, (t, idx)))
    for _, rid, slot in sorted(choices):
        if g.demolish_card(f.id, rid, slot)[0]:
            ok = g.start_project(f.id, rid, 'build', need, slot=slot)[0]
            f.ai['last_redevelopment'] = [g.turn, rid, need, bool(ok)]
            return ok
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
            model = {'members': selected}
            # 5단계 거점이 평균화로 사라지면 승리·고급 생산의 선택권을 잃는다.
            if any(any(g.regions[x].b[key] >= 5 for x in selected) and M.pool_level(g, model, key) < 5
                   for key in ('factory', 'bank', 'admin', 'edu')):
                continue
            if any(threat.get(x, 0) > .2 for x in selected) and f.gov != 'constitutional':
                continue
            return g.create_metro(f.id, center.id, selected)[0]
    return False
