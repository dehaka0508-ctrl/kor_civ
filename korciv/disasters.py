"""1턴 예보, 계절 기상, 국지 피해와 수확 이력. 모든 난수는 판의 rng를 사용한다."""
from __future__ import annotations
from . import config as C, rules as R

WEATHER = {
    'drought': ('가뭄', (3, 4, 5), (2, 4), '내륙 비하천 농장 식량·산출 −30%'),
    'rain': ('폭우', (6, 7), (1, 2), '도하 ×0.7, 수력 +1, 침수 가능'),
    'heat': ('폭염', (7, 8), (1, 3), '도하 ×0.95, 하천 어장 −30%, 수력 −1'),
    'snow': ('폭설', (12, 1, 2), (1, 3), '육군 이동 1칸, 산악 돌파 ×0.65, 산출 −10%'),
    'cold': ('한파', (12, 1), (1, 3), '하천 어업 중단, 농장 −50%, 실질 행복도 −3'),
    'typhoon': ('태풍', (8, 9), (1, 2), '경로 동쪽: 함대 체력 −30%, 어업 중단, 침수 / 서쪽: 폭우'),
    'fire': ('산불', (3, 4, 5, 10, 11), (1, 1), '매 턴 건물 1단계 피해·행복도 −3, 인접 확산 가능'),
}


class DisasterMixin:
    def init_disasters(self):
        self.weather = None
        self.forecasts = []
        self.fires = set()
        self.fire_burned = set()
        self.last_cold_end = -999
        self.disaster_notice = ''

    def weather_at(self, rid, kind):
        w = self.weather
        return bool(w and w['kind'] == kind and self.turn < w['until']
                    and (kind != 'snow' or rid not in w.get('exempt', ())))

    def typhoon_danger(self, node, event=None):
        w = event or self.weather
        if not w or w['kind'] != 'typhoon':
            return False
        return node in w.get('danger', ())

    def _typhoon_path(self):
        path = [(125.0 + self.rng.random(), 32.5), (126.1 + self.rng.random(), 35.2),
                (127.0 + self.rng.random(), 38.2), (129.2 + self.rng.random(), 42.7)]
        def east(xy):
            x, y = xy
            for a, b in zip(path, path[1:]):
                if a[1] <= y <= b[1]:
                    line = a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1])
                    return x >= line
            return x >= (path[0][0] if y < path[0][1] else path[-1][0])
        danger = {rid for rid, geo in self.world.geometry.items() if east(geo['label'])}
        danger.update(s for s, xy in self.world.sea_labels.items() if east(xy))
        return path, danger

    def forecast_disaster(self, kind, rid=None, duration=None):
        spec = WEATHER[kind]
        event = {'kind': kind, 'turn': self.turn + 1,
                 'duration': duration or self.rng.randint(*spec[2]), 'region': rid}
        if kind == 'typhoon':
            event['path'], event['danger'] = self._typhoon_path()
        self.forecasts.append(event)
        where = f' · {self.info(rid).name}' if rid else ''
        self.event('alert', f'일기예보: 다음 턴 {spec[0]}{where} — {spec[3]}', region=rid,
                   fids=(self.player_id,))
        return event

    def start_disaster(self, event):
        kind = event['kind']
        if kind == 'fire':
            if not self.fires:
                self.fire_burned = set()
            self.ignite(event['region'])
        else:
            self.weather = dict(event, until=self.turn + event['duration'])
            if kind == 'typhoon' and 'path' not in self.weather:
                self.weather['path'], self.weather['danger'] = self._typhoon_path()
            if kind == 'snow':
                self.weather['exempt'] = {rid for rid in self.world.order
                    if self.info(rid).province in ('경남', '부산', '울산', '경상남도', '부산광역시', '울산광역시')
                    and self.rng.random() < 0.5}
        self.disaster_notice = f'{WEATHER[kind][0]} 발생 — {WEATHER[kind][3]}'
        self.event('alert', self.disaster_notice, region=event.get('region'), fids=(self.player_id,))
        self._mark_weather_damage()

    def _mark_weather_damage(self):
        for rid, r in self.regions.items():
            if r.b.get('farm') and (self.weather_at(rid, 'cold') or
                (self.weather_at(rid, 'drought') and not self.info(rid).coastal
                 and not self.river_farm(rid))):
                self.agri_damage(rid)

    def begin_disaster_turn(self):
        self.disaster_notice = ''
        if self.weather and self.turn >= self.weather['until']:
            if self.weather['kind'] == 'cold':
                self.last_cold_end = self.turn
            self.weather = None
        pending, self.forecasts = self.forecasts, []
        for e in pending:
            if e['turn'] <= self.turn:
                self.start_disaster(e)
            else:
                self.forecasts.append(e)
        month = R.date_of_turn(self.turn + 1)[1]
        if not self.weather and not any(e['kind'] != 'fire' for e in self.forecasts):
            candidates = [k for k, v in WEATHER.items() if k != 'fire' and month in v[1]]
            weights = [2 if k == 'snow' and self.turn - self.last_cold_end <= 1 else 1 for k in candidates]
            if candidates and self.rng.random() < C.WEATHER_CHANCE:
                self.forecast_disaster(self.rng.choices(candidates, weights=weights)[0])
        if not self.fires and not any(e['kind'] == 'fire' for e in self.forecasts) \
                and month in WEATHER['fire'][1] and self.rng.random() < C.FIRE_CHANCE:
            sites = sorted(self.world.mountain_regions)
            if sites:
                self.forecast_disaster('fire', self.rng.choice(sites))
        if self.rng.random() < C.QUAKE_CHANCE:
            self.earthquake(self.rng.choice(self.world.order), self.rng.choices((5, 6, 7, 8, 9),
                            weights=(60, 27, 9, 3, 1))[0])

    def agri_damage(self, rid):
        self.regions[rid].last_agri_damage = self.turn

    def harvest_active(self, rid):
        week = (self.turn - 1) % 48
        start = self.turn - week + 32
        return 32 <= week < 40 and start > 40 and self.regions[rid].last_agri_damage < start - 40

    def weather_farm_mult(self, rid):
        if self.weather_at(rid, 'cold'):
            return 0.5
        mult = 0.7 if self.weather_at(rid, 'drought') and not self.info(rid).coastal and not self.river_farm(rid) else 1.0
        return mult * (1.3 if self.harvest_active(rid) else 1.0)

    def weather_fish_mult(self, rid):
        river = not self.sea_fishery(rid)
        if (river and self.weather_at(rid, 'cold')) or self.typhoon_danger(rid):
            return 0.0
        return 0.7 if river and self.weather_at(rid, 'heat') else 1.0

    def weather_happy(self, rid):
        return (-3 if self.weather_at(rid, 'cold') else 0) - self.regions[rid].fire_scar

    def self_power(self, rid):
        r, info = self.regions[rid], self.info(rid)
        if r.flooded:
            return 0
        hydro = info.hydro if r.b.get('hydro') else 0
        if hydro:
            if self.weather_at(rid, 'rain') or (self.weather_at(rid, 'typhoon') and not self.typhoon_danger(rid)):
                hydro += 1
            elif self.weather_at(rid, 'heat'):
                hydro = max(0, hydro - 1)
        nuclear = info.nuclear if r.b.get('nuclear') and not r.nuclear_destroyed and self.turn >= r.nuclear_off_until else 0
        return hydro + nuclear

    def terrain_multiplier(self, src, target, terrain):
        if terrain['kind'] == '도하':
            if any(self.weather_at(n, 'rain') or self.weather_at(n, 'typhoon') for n in (src, target)):
                return 0.7
            if any(self.weather_at(n, 'heat') for n in (src, target)):
                return 0.95
        if terrain['kind'] == '돌파' and any(self.weather_at(n, 'snow') for n in (src, target)):
            return 0.65
        return terrain['mult']

    def ignite(self, rid):
        if rid is None or rid in self.fire_burned:
            return
        self.fires.add(rid)
        self.fire_burned.add(rid)
        r = self.regions[rid]
        r.fire_turns = 0
        r.fire_recovery = 0
        self.agri_damage(rid)

    def set_flooded(self, rid):
        r = self.regions[rid]
        if not r.flooded:
            r.flooded = True
            self.event('alert', f'{self.info(rid).name} 침수 — 침수 복구 전까지 모든 생산 중단',
                       region=rid, fids=(r.owner,))
        self.agri_damage(rid)

    def disaster_damage(self):
        self._mark_weather_damage()
        burning = set(self.fires)
        for rid, r in self.regions.items():
            if rid not in burning and r.fire_recovery:
                r.fire_scar = max(0, r.fire_scar - r.fire_scar / r.fire_recovery)
                r.fire_recovery -= 1
        spread = set()
        for rid in sorted(burning):
            r = self.regions[rid]
            choices = [('b', k) for k, v in r.b.items() if v > 0]
            choices += [('lines', k) for k, v in r.lines.items() if v > 0]
            if choices:
                attr, key = self.rng.choice(choices)
                getattr(r, attr)[key] -= 1
            r.fire_scar += 3
            r.fire_turns += 1
            self.agri_damage(rid)
            for n in sorted(self.world.land_adj[rid]):
                if n not in self.fire_burned and self.rng.random() < C.FIRE_SPREAD_CHANCE:
                    spread.add(n)
            if self.rng.random() < C.FIRE_OUT_CHANCE:
                self.fires.discard(rid)
                r.fire_recovery = r.fire_turns
        for rid in sorted(spread):
            self.ignite(rid)
            self.event('alert', f'{self.info(rid).name} 산불 확산', region=rid, fids=(self.regions[rid].owner,))
        if self.weather and self.weather['kind'] in ('rain', 'typhoon'):
            for rid, r in self.regions.items():
                p = C.TYPHOON_FLOOD_CHANCE if self.typhoon_danger(rid) else C.FLOOD_CHANCE
                if any(r.b.values()) and not r.flooded and self.rng.random() < p:
                    self.set_flooded(rid)
        if self.weather and self.weather['kind'] == 'typhoon':
            for a in list(self.armies.values()):
                if self.world.is_sea(a.loc) and self.typhoon_danger(a.loc):
                    # 병종별 누적 피해: 각 함선 최대 체력의 30%, 수송 병력은 함선 침몰 규칙을 따른다.
                    for key in list(a.units):
                        if C.UNITS[key]['kind'] == 'naval':
                            self.apply_damage([a], a.hp_max(key) * 0.30,
                                              unit_filter=(key,), rng_round=False)
                    self._validate_capacity(a)

    def apply_quake_tier(self, rid, tier):
        r = self.regions[rid]
        had_nuclear = bool(r.b.get('nuclear'))
        for values in (r.b, r.lines):
            for key, lv in list(values.items()):
                loss = (int(self.rng.random() < .5) if tier == 5 else 1 if tier == 6 else
                        self.rng.randint(1, 2) if tier == 7 else 2 if tier == 8 else lv)
                values[key] = max(0, lv - loss)
        r.pop = max(0.1, r.pop * (1 - {5: 0, 6: .0001, 7: .001, 8: .01, 9: .10}[tier]))
        if had_nuclear and tier == 8:
            r.b['nuclear'] = 1
            r.nuclear_off_until = self.turn + 4
        if self.info(rid).nuclear and tier == 9:
            r.nuclear_destroyed = True
            r.b['nuclear'] = 0
        if tier == 9:
            r.sci.clear()
            r.econ.clear()
        r.quake_until = self.turn + 1
        self.agri_damage(rid)

    def earthquake(self, epicenter, magnitude):
        tiers = {5: (5,), 6: (6, 5), 7: (7, 6, 5), 8: (8, 7, 5), 9: (9, 8, 6, 5)}[magnitude]
        seen, layer = set(), {epicenter}
        for tier in tiers:
            for rid in sorted(layer):
                self.apply_quake_tier(rid, tier)
            seen |= layer
            layer = {n for rid in layer for n in self.world.land_adj[rid]} - seen
        self.disaster_notice = f'{self.info(epicenter).name} 규모 {magnitude} 지진 — {len(seen)}개 지역 피해'
        self.event('alert', self.disaster_notice, region=epicenter, fids=(self.player_id,))

    def disaster_badges(self):
        out = []
        if self.weather:
            w = self.weather
            out.append((f'{WEATHER[w["kind"]][0]} {max(0, w["until"] - self.turn)}턴 남음', WEATHER[w['kind']][3]))
        for e in self.forecasts:
            out.append((f'예보: {WEATHER[e["kind"]][0]}', '다음 턴 발생 · ' + WEATHER[e['kind']][3]))
        return out

    def local_disaster_status(self, rid):
        r = self.regions[rid]
        out = []
        if rid in self.fires:
            out.append(f'산불 {r.fire_turns}턴째 · 매 턴 진화 확률 60% · 행복도 −{r.fire_scar:g}')
        elif r.fire_recovery:
            out.append(f'산불 흔적 회복 {r.fire_recovery}턴 남음 · 행복도 −{r.fire_scar:g}')
        if r.flooded:
            out.append('침수 · 복구 작업 1턴 필요 · 모든 생산 중단')
        if r.quake_until > self.turn:
            out.append(f'지진 피해 · {r.quake_until - self.turn}턴 남음')
        if r.nuclear_destroyed:
            out.append('원전 영구 파괴 · 재건설 불가')
        elif r.nuclear_off_until > self.turn:
            out.append(f'원전 정지 {r.nuclear_off_until - self.turn}턴 남음')
        if self.harvest_active(rid):
            out.append(f'풍년 {(40 - (self.turn - 1) % 48)}턴 남음 · 농장 +30%')
        if self.weather_at(rid, 'typhoon'):
            out.append('태풍 위험 반원(동쪽)' if self.typhoon_danger(rid) else '태풍 가항 반원(서쪽) · 폭우 효과')
        return out
