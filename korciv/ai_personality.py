"""개편된 46명 지도자의 행동 선호. 실제 효과·비용은 엔진 계산, 선호는 동률에 가까운 선택을 조정한다."""
from . import diplomacy as D, metro as M
from .state import NEUTRAL

# 1에 더할 선호값. 과거에 삭제된 버프 키를 추측해 가중치로 쓰지 않는다.
PROFILES = {
    'dan': dict(growth=.18, annex=.08, air=-.12, tank=-.10, naval=-.10),
    'jum': dict(art=.15, naval=-.10, port=-.10, general=.06),
    'onz': dict(admin=.05, bank=.05, growth=.10),
    'egg': dict(annex=.15, ally=.12, war=-.10, policy=.08),
    'sur': dict(power=.15, extract=.10, metro=-.12),
    'dae': dict(general=.12, line=.08, war=.05),
    'wan': dict(annex=.08, war=.08, admin=.12),
    'gun': dict(assault=.15, war=.08, artist=.10, general=.10),
    'dog': dict(surprise=.15, protect_capital=.18, artist=.10),
    'tae': dict(protect_capital=.10, admin=.05, general=.08),
    'lee': dict(ally=.15, general=.08, artist=.12),
    'kim': dict(factory=.12, extract=.10, power=.10, trade=-.30),
    'ggt': dict(assault=.12, war=.10, general=.12, admin=.06),
    'gcg': dict(port=.15, bank=.08, ally=.10),
    'jin': dict(academy=.15, inf=.08, tank=.08, general=.08),
    'mur': dict(line=.06, general=.10, annex=.10),
    'sen': dict(science=.15, edu=.15, scientist=.15, protect_capital=.10),
    'muy': dict(ally=.15, assault=.08, general=.08),
    'sun': dict(metro=.15, bank=.08, admin=.12, ally=.08),
    'gon': dict(artist=-.06, general=.10, war=.06, policy=.10),
    'sej': dict(edu=.15, scientist=.15, science=.15, specialty=-.06),
    'hae': dict(ally=.12, trade=.15, bank=.06, policy=-.08),
    'jjo': dict(bank=.15, metro=.10, factory=-.10, power=-.08, extract=-.08),
    'pak': dict(factory=.15, extract=.08, power=.10, focus=.12),
    'kdj': dict(ally=.15, trade=.12, bank=.06, war=-.10),
    'yon': dict(line=.15, protect_capital=.15, general=.08),
    'jan': dict(naval=.12, ally=.10, port=-.05, bank=.08),
    'kgc': dict(line=.12, general=.12, war=-.04, surprise=-.35),
    'jun': dict(inf=.10, tank=.10, art=.10, general=.10, chancellor=-.35),
    'cho': dict(inf=.12, tank=.10, war=-.06, general=.10),
    'yis': dict(naval=.15, general=.05, port=.08),
    'hon': dict(general=.08, assault=.08, artist=.08),
    'gil': dict(war=.05, bank=.10, ally=.06),
    'ahn': dict(focus=.15, growth=.15, tech_military=-.10, war=-.08),
    'kgu': dict(general=.12, ally=.12, protect_capital=.10),
    'kwb': dict(surprise=.15, air=.12, art=.06, general=.08),
    'yan': dict(inf=.12, art=.12, bank=-.04),
    'tai': dict(bank=.08, growth=.08, assault=-.08, art=-.04),
    'kan': dict(tank=.15, naval=-.15, general=.10),
    'yyl': dict(ally=.15, specialty=.08, war=-.10),
    'toy': dict(line=.10, general=.08, naval=-.08),
    'taj': dict(inf=.10, tank=.10, admin=.08, artist=.12),
    'ito': dict(war=.05, admin=.10, general=.10),
    'mac': dict(naval=.12, inf=.10, general=.10),
    'sta': dict(inf=.10, tank=.12, academy=-.35, general=.08),
    'mao': dict(inf=.15, farm=.12, fishery=.12, general=.08),
    'cus': {},
}


def preference(g, fid, action, rid=None, target=None, context=None):
    """전국 선호 × 입지·국경·보급 조건. 현재 상대/입지가 있어야 받는 효과는 그때만 반영한다."""
    f = g.factions[fid]
    leader = f.leader
    value = PROFILES.get(leader, {}).get(action, 0.0)
    if leader == 'yis' and action == 'naval' and g.naval_buff_off(fid):
        value = 0.0
    if leader == 'muy' and action in ('war', 'assault'):
        value += .10 if any(D.allied(g, fid, o) for o in g.alive_ids() if o != fid) else -.18
    if leader == 'gcg' and action == 'war' and D.enemies(g, fid):
        value -= .25
    if leader == 'taj' and action == 'annex' and g.region_count(fid) >= 35:
        value -= min(.25, .03 * (g.region_count(fid) - 34))
    if rid in g.regions:
        r = g.regions[rid]
        if leader == 'onz' and action in ('admin', 'edu', 'bank', 'factory', 'power', 'extract'):
            value += .10 if any(x in g.world.river_regions for x in M.members(g, rid)) else 0
        if leader == 'jjo' and action == 'bank' and (rid == f.capital or M.of(g, rid)):
            value += .12
        if leader == 'yan' and action in ('inf', 'art') and r.unit_chain_count % 3 == 2:
            value += .15
        if leader in ('yon', 'dog') and action in ('line', 'general') and rid == f.capital:
            value += .10
    if target in g.regions:
        r, info = g.regions[target], g.info(target)
        if leader == 'tae' and action in ('war', 'assault') and target not in g.near_capital(fid, 5):
            value -= .12
        if leader == 'dae' and action == 'assault' and rid in g.regions:
            terrain = g.world.terrain_between(rid, target)
            if terrain and terrain['kind'] in ('돌파', '산악 돌파'):
                value += .12
        if leader == 'jan' and action == 'annex' and info.coastal and len(f.coastal_rewards) < 3:
            value += .15
        if leader == 'dan' and action == 'annex' and info.scenic:
            value += .12
        if leader == 'sur' and action == 'annex' and (info.is_coal or info.is_oil):
            value += .12
        if leader == 'gil' and action == 'annex' and info.island:
            value += .15
        if leader == 'wan' and action == 'annex' and target not in g.near_capital(fid):
            value -= .08
        if leader == 'kgu' and action in ('war', 'assault') and target in f.lost_regions:
            value += .20
        if leader == 'hon' and action in ('war', 'assault') and r.owner != NEUTRAL:
            value += .15 * min(1, max(0, -g.eff_happy(r)) / 50)
        if leader == 'mur' and action == 'war' and r.owner in f.attacked_by:
            value += .18
    return 1 + max(-.35, min(.35, value))
