"""면적 할당량과 판별 시작 상태. 지도 원본은 공유하되 혼돈 판도는 별도로 복사한다."""
from __future__ import annotations

import copy
from dataclasses import replace
from . import config as C, rules as R


def fit_initial(info, b):
    """초기 인구를 보존하며 모든 지역에 15% 이상의 여유 부지를 확보한다."""
    b = dict(b)
    b.setdefault('housing', 0)
    limit = info.area_km2 * 0.85
    while R.area_usage(info.pop0, b)[0] > limit and b['housing'] < 5:
        b['housing'] += 1
    # 농업 부지부터 정리. 수력·원전은 현실 모드에서 가동 상태를 보존한다.
    for key in ('farm', 'fishery', 'bank', 'factory', 'power', 'extract', 'specialty'):
        while b.get(key, 0) and R.area_usage(info.pop0, b)[0] > limit:
            b[key] -= 1
    return b


def chaos_world(world, rng):
    w = copy.copy(world)
    w.regions = {rid: replace(i, oil=0, coal=0, coal_field='', power_self=0,
                              hydro=0, nuclear=0, power_source='', power_site=False)
                 for rid, i in world.regions.items()}

    def pick(n, predicate):
        buckets = {}
        for rid in w.order:
            if predicate(w.regions[rid]):
                buckets.setdefault(w.regions[rid].do8, []).append(rid)
        for vals in buckets.values():
            rng.shuffle(vals)
        out = []
        while len(out) < n and any(buckets.values()):
            provinces = sorted(k for k, vals in buckets.items() if vals)
            rng.shuffle(provinces)
            for p in provinces:
                out.append(buckets[p].pop())
                if len(out) == n:
                    break
        return out

    # 추첨마다 새 권역 버킷: 서로 다른 자원의 중복 입지를 허용한다.
    for key, lo, hi in (('oil', 5, 10), ('coal', 20, 30), ('nuclear', 4, 10), ('hydro', 8, 12)):
        eligible = (lambda i: i.coastal) if key == 'nuclear' else (
            (lambda i: not i.coastal or i.id in w.river_regions or i.id in w.mountain_regions)
            if key == 'hydro' else (lambda i: True))
        for rid in pick(rng.randint(lo, hi), eligible):
            i = w.regions[rid]
            values = {key: rng.randint(2, 3) if key == 'nuclear' else rng.randint(1, 2)}
            if key == 'coal':
                values.update(coal=1, coal_field='①')
            if key in ('hydro', 'nuclear'):
                values['power_self'] = i.power_self + values[key]
                values['power_source'] = '·'.join(x for x in (i.power_source, '수력' if key == 'hydro' else '원자력') if x)
            w.regions[rid] = replace(i, **values)
    return w


class LandMixin:
    def _policy_area(self, rid, b):
        r = self.regions[rid]
        total, people, built = R.area_usage(r.pop, b)
        m = self.mods(r.owner)
        # 복지 정책은 주거 지구가 있는 지역의 인구 점유 면적을 추가로 20% 절감한다.
        used = C.POP_AREA_PER_10K[max(0, min(6, b.get("housing", 0)))]
        efficiency = m.add("housing_efficiency") if b.get("housing", 0) else 0.0
        per = used * max(0.01, 1 - efficiency)
        people = r.pop * per
        for key in ("farm", "fishery"):
            built += b.get(key, 0) * C.BUILDING_AREA_PER_LEVEL[key] * (m.mult(key + "_area") - 1)
        return people + built, people, built

    def area_usage(self, rid, projected=False):
        b = self.projected_buildings(rid) if projected else self.regions[rid].b
        return self._policy_area(rid, b)

    def population_capacity(self, rid):
        r = self.regions[rid]
        _, _, built = self.area_usage(rid)
        _, people, _ = self._policy_area(rid, r.b)
        return max(0.0, (self.info(rid).area_km2 - built) / max(1e-9, people / max(1e-9, r.pop)))

    def density_growth(self, rid):
        return R.density_growth_max(self.regions[rid].pop * 10000 / self.info(rid).area_km2)

    def growth_scale(self, rid):
        return min(C.DENSITY_BONUS_SCALE_MAX, self.density_growth(rid) / C.G_MAX)

    def area_build_ok(self, rid, key, level, projected=True):
        if key == 'housing' or key not in (C.BUILDING_AREA_PER_LEVEL | C.BUILDING_AREA_LEVELS):
            return True
        b = dict(self.projected_buildings(rid) if projected else self.regions[rid].b)
        b[key] = max(b.get(key, 0), level)
        return self._policy_area(rid, b)[0] <= self.info(rid).area_km2 + 1e-8

    def demolish_building(self, fid, rid, key):
        from . import metro as M
        r = self.regions[rid]
        if r.owner != fid or not r.b.get(key) or key not in C.PROD_BUILDINGS:
            return False, '철거할 생산 건물이 없습니다.'
        members = M.members(self, rid)
        for site in members:
            rr = self.regions[site]
            rr.b[key] = max(0, rr.b.get(key, 0) - 1)
        return True, f'{C.PROD_BUILDINGS[key]["name"]} 1단계 철거'
