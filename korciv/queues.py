"""지역 작업 예약. 실행 객체를 그대로 옮겨 진행도·납부액·연속 생산을 보존한다."""
from __future__ import annotations
from . import config as C, metro as M
from .state import Project, NEUTRAL


class QueueMixin:
    def queue_region(self, rid):
        return self.regions[M.center_of(self, rid)]

    def local_projects(self, rid):
        r = self.queue_region(rid)
        return ([r.project] if r.project else []) + r.queue

    def project_sites(self, rid, p):
        m = M.get(self, p.metro)
        if m and p.pool:
            return M.pool_members(self, m, p.pool)
        return [p.site or rid]

    def reserved_level(self, rid, key, border=None, pool=None):
        r = self.regions[rid]
        level = r.lines.get(border, 0) if key == 'line' else r.b.get(key, 0)
        ps = self.local_projects(rid)
        if getattr(self, '_continuing', False):
            ps = ps[:1] if self.queue_region(rid).project else []
        for p in ps:
            if p.kind != 'build' or p.key != key or p.border != border:
                continue
            if rid not in self.project_sites(M.center_of(self, rid), p):
                continue
            top = (M.max_level(key) if p.metro is not None else C.PROD_BUILDINGS.get(key, {}).get('max', 5)) if p.chain else p.level
            level = max(level, top)
        return level

    def projected_buildings(self, rid):
        return {k: self.reserved_level(rid, k) for k in self.regions[rid].b}

    def _set_active(self, rid, p):
        old = self.queue_region(rid).project
        if old is not None and old is not p and old.group is not None:
            for r in self.regions.values():
                if r.project is old:
                    r.project = None
        sites = list(p.group['lines']) if p is not None and p.group is not None else M.members(self, rid)
        for site in sites:
            r = self.regions[site]
            if p is not None and p.group is not None and r.project is not None and r.project is not p:
                self.queue_region(site).queue.insert(0, r.project)
            if p is not None:
                self.queue_region(site).queue[:] = [q for q in self.queue_region(site).queue if q is not p]
            self.regions[site].project = p

    def _activate_project(self, rid, p):
        r = self.queue_region(rid)
        if not p.started:
            if p.kind != 'annex' and self.order_frozen(r.owner):
                p.stalled, p.blocked_reason = True, self.order_frozen(r.owner)
                return False
            if p.kind != 'unit':
                r.unit_chain_count = 0
            if p.kind == 'unit':
                oil = self.unit_oil(r.owner, p.key)
                if not self.can_pay_oil(r.owner, oil):
                    p.stalled, p.blocked_reason = True, f'석유 {oil} 필요'
                    return False
                self.pay_oil(r.owner, oil)
                p.happy_cost = 0 if self.mods(r.owner).value("unit_happy_free") else C.UNIT_START_HAPPY[C.UNITS[p.key]['weight']]
                r.h_delta += p.happy_cost
            p.started = True
        return True

    def promote_queue(self, rid):
        r = self.queue_region(rid)
        if r.owner == NEUTRAL or r.project or not r.queue:
            return
        p = r.queue.pop(0)
        p.funded = False
        self._set_active(r.id, p)
        self._activate_project(r.id, p)

    def promote_queues(self):
        for r in self.regions.values():
            if M.center_of(self, r.id) == r.id:
                self.promote_queue(r.id)

    def move_queued_project(self, fid, rid, index, target):
        r = self.queue_region(rid)
        ps = self.local_projects(rid)
        if r.owner != fid or not (0 <= index < len(ps) and 0 <= target < len(ps)):
            return False, '잘못된 작업 순서입니다.'
        ps.insert(target, ps.pop(index))
        r.queue = ps[1:]
        self._set_active(r.id, ps[0])
        for p in ps:
            p.funded = False
        self._activate_project(r.id, ps[0])
        return True, f'작업을 {target + 1}번으로 이동했습니다.'

    def cancel_queued_project(self, fid, rid, index):
        if index == 0:
            return self.cancel_project(fid, rid)
        r = self.queue_region(rid)
        if r.owner != fid or not 1 <= index <= len(r.queue):
            return False, '삭제할 대기 작업이 없습니다.'
        p = r.queue.pop(index - 1)
        refund = p.paid * C.PROJECT_REFUND
        self.factions[fid].money += refund
        if p.kind == 'unit' and p.started:
            r.h_delta -= p.happy_cost if p.happy_cost is not None else C.UNIT_START_HAPPY[C.UNITS[p.key]['weight']]
        return True, f'대기 작업 삭제: {refund:,.0f} 환급'

    def cancel_project(self, fid, rid):
        r = self.queue_region(rid)
        p = r.project
        if r.owner != fid or p is None:
            return False, '취소할 작업이 없습니다.'
        refund = p.paid * C.PROJECT_REFUND
        self.factions[fid].money += refund
        if p.kind == 'unit' and p.started:
            r.h_delta -= p.happy_cost if p.happy_cost is not None else C.UNIT_START_HAPPY[C.UNITS[p.key]['weight']]
        self._clear_project(r)
        self.promote_queues()
        extra = ' · 행복도 회복' if p.kind == 'unit' and p.started else ''
        return True, f'취소: {refund:,.0f} 환급{extra}'

    def queued_options(self, fid, rid, opts):
        """특수 작업 중복 예약과 부지 초과를 공통 검사한다."""
        ps = self.local_projects(rid)
        for o in opts:
            key, kind = o['key'], o['kind']
            if kind == 'build':
                m = M.of(self, rid)
                sites = M.pool_members(self, m, o['pool']) if m and o.get('pool') else [o.get('site') or rid]
                for site in sites:
                    allowed, reason = self.building_allowed(fid, site, key, o["level"], pool=o.get("pool"))
                    if not allowed:
                        o["ok"], o["why"] = False, reason
                if not all(self.area_build_ok(s, key, o['level']) for s in sites):
                    o['ok'], o['why'] = False, C.AREA_SHORTAGE
            elif kind != 'unit' and any(p.kind == kind and p.key == key for p in ps):
                o['ok'], o['why'] = False, '이미 실행 중이거나 대기열에 예약된 작업입니다.'
            if kind in ('science', 'capital') or (kind == 'econ' and key != 'exchange'):
                if any(p.kind == kind and p.key == key for r in self.regions_of(fid)
                       for p in r.queue):
                    o['ok'], o['why'] = False, '다른 대기열에 예약된 작업입니다.'
        return opts

    def start_project(self, fid, rid, kind, key, border=None, name=None, site=None, pool=None):
        if rid not in self.regions or self.regions[rid].owner != fid:
            return False, '내 지역이 아닙니다.'
        r = self.queue_region(rid)
        if r.occ or self.resisting(r):
            return False, '점령 또는 저항 중인 지역입니다.'
        opts = [o for o in self.options(fid, rid) if o['kind'] == kind and o['key'] == key
                and (border is None or o.get('border') == border)
                and (pool is None or o.get('pool') == pool)]
        if site and len(opts) > 1:
            opts = [o for o in opts if o.get('site') == site] or opts
        if not opts:
            return False, '선택할 수 없는 항목입니다.'
        o = opts[0]
        if not o['ok']:
            return False, o['why']
        if kind == "repair" and self.mods(fid).value("flood_instant"):
            self.regions[o.get("site") or rid].flooded = False
            return True, "침수 복구 즉시 완료"
        m = M.of(self, rid)
        self.proj_counter = getattr(self, 'proj_counter', 0) + 1
        label = o['name']
        if kind == 'build' and key in C.PROD_LEVEL_NAMES and not m:
            label = self.build_label(rid, key, o['level'])
        elif kind == 'annex':
            label = f'편입: {self.info(key).name}'
        p = Project(kind=kind, key=key, level=o['level'], turns=o['turns'], per_turn=o['per_turn'],
                    border=o.get('border'), name=name or label, priority=self.proj_counter,
                    metro=m['id'] if m else None, site=o.get('site') or rid, pool=o.get('pool'), started=False)
        if r.project:
            r.queue.append(p)
            state = '대기열 추가'
        else:
            self._set_active(r.id, p)
            self._activate_project(r.id, p)
            state = '착수'
        self._last_started = p
        if not self.factions[fid].is_ai:
            for rrid in M.members(self, rid):
                self.release_focus(self.regions[rrid])
                self.regions[rrid].pop_focus = False
        if kind == 'econ' and key == 'currency' and r.project is p:
            self.econ_alert(fid, f'{self.fname(fid)} 기축통화 지정 착수 — {p.turns}턴 뒤 경제승리')
        turns = self.project_left(r.id) if r.project is p and kind == 'annex' else p.turns
        return True, f'{label} {state} ({turns}턴, 턴당 {p.per_turn:,.0f})'

    def project_ready(self, rid, p):
        r = self.queue_region(rid)
        why = ''
        if p.kind in ('science', 'econ') and any(self.facility_paused(x.id) and (x.sci if p.kind == 'science' else x.econ) for x in self.regions_of(r.owner)):
            p.blocked_reason = '의열단: 과학·경제 시설 4턴 정지'
            return False
        if p.group is not None:
            return True
        if p.kind == 'build':
            m = M.get(self, p.metro)
            if m and p.pool and p.level > M.pool_level(self, m, p.pool) + 1:
                why = '이전 단계 건설이 먼저 필요합니다.'
            for s in self.project_sites(r.id, p):
                rr = self.regions[s]
                allowed, reason = self.building_allowed(r.owner, s, p.key, p.level, pool=p.pool)
                if not allowed:
                    why = reason
                lv = rr.lines.get(p.border, 0) if p.key == 'line' else rr.b.get(p.key, 0)
                if not p.pool and p.level > lv + 1:
                    why = '이전 단계 건설이 먼저 필요합니다.'
                elif p.key == 'nuclear' and rr.nuclear_destroyed:
                    why = '지진으로 원전 재건설이 영구 금지된 지역입니다.'
                elif not self.area_build_ok(s, p.key, p.level, projected=False):
                    why = C.AREA_SHORTAGE
        elif p.kind == 'unit':
            s = self.regions[p.site or rid]
            if not self.unit_spec(r.owner, p.key)["available"]:
                why = "항공모함 강습단 기술 필요"
            if C.UNITS[p.key]['kind'] == 'naval' and not s.b.get('port'):
                why = '항구 필요'
        elif p.kind == 'science' and not self.science_site_ok(r.owner, p.site or rid, p.key):
            why = '과학 시설 위치 조건이 충족되지 않습니다.'
        p.blocked_reason = why
        return not why and self._activate_project(r.id, p)
