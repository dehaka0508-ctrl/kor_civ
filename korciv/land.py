"""인구밀도 성장과 혼돈 판도. 지도 원본은 공유하되 혼돈 판도는 별도로 복사한다."""
from __future__ import annotations

import copy
from dataclasses import replace
from . import config as C, metro as M, rules as R


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
    """면적(v1.3.8): 인구밀도에 따른 성장률에만 쓴다(기본 슬롯 칸 수는 slots.capacity)."""
    def density_growth(self, rid):
        if getattr(self.regions[rid], "metro", None) is not None:      # 광역시: 인구 합 ÷ 면적 합
            return R.density_growth_max(M.total_pop(self, rid) * 10000 / M.total_area(self, rid))
        return R.density_growth_max(self.regions[rid].pop * 10000 / self.info(rid).area_km2)

    def growth_scale(self, rid):
        return min(C.DENSITY_BONUS_SCALE_MAX, self.density_growth(rid) / C.G_MAX)
