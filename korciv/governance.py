"""행정·교육 산출, 건설 허가, 수도 수복과 점령지 행정 건물 정리."""
from __future__ import annotations

from . import config as C, diplomacy as D, metro as M
from .state import NEUTRAL
from .text import josa
from .leaders import GOV_OFFICES


class GovernanceMixin:
    def office_building(self, rid):
        """현재 수도의 슬롯 밖 집무실. 소유권·체제·인구에서 매번 계산해 이전 시 중복을 막는다."""
        r = self.regions[rid]
        if r.owner == NEUTRAL:
            return None
        f = self.factions[r.owner]
        if not f.alive or f.capital != rid or f.gov not in GOV_OFFICES:
            return None
        return dict(name=GOV_OFFICES[f.gov], output=max(30.0, M.total_pop(self, rid)))   # 광역시 수도: 광역시 인구

    def office_output(self, rid, population=None):
        office = self.office_building(rid)
        if not office:
            return 0.0
        return office["output"] if population is None else max(30.0, population)

    def admin_output(self, rid):
        r = self.regions[rid]
        mt_ = M.of(self, rid)
        if mt_ and mt_["center"] != rid:
            return 0.0               # 광역시는 하나의 지역(v1.3.17): 중심이 광역시 전체 행정력을 낸다
        office = self.office_output(rid)
        if mt_:                      # 집무실(수도 칸)이 광역시 안이면 중심에서(광역시 인구로)
            cap = self.factions[r.owner].capital if r.owner != NEUTRAL else None
            office = self.office_output(cap) if cap in mt_["members"] else 0.0
        if r.owner == NEUTRAL or r.occ or self.resisting(r) or r.flooded:
            return office
        f, m = self.factions[r.owner], self.mods(r.owner)
        metro = M.of(self, rid)
        lv = max(0, min(5, r.b.get("admin", 0)))
        n = r.b.mult_of("base") if hasattr(r.b, "mult_of") else 1     # 광역 슬롯 시청: 구성 지역 수만큼(v1.3.16)
        base = C.ADMIN_OUTPUT[lv] * n
        if metro and lv == 5:
            if M.merged(self, rid):
                base = 50 * n + (100 if f.capital in metro["members"] and n > 1 else 0)
            else:
                base = 50 + 100 / len(metro["members"]) if f.capital in metro["members"] else 50
        value = base * m.mult("admin_building_output") + m.add("admin_each")
        if f.capital in M.members(self, rid):
            value += m.add("capital_admin")
        value += self.great_person_bonus(rid, "admin_add")
        return value * m.mult("admin_output") + office

    def admin_consumption(self, rid):
        r = self.regions[rid]
        return r.pop * (0.5 if self.resisting(r) else 1.0) if r.owner != NEUTRAL else 0.0

    def admin_balance(self, fid):
        regs = self.regions_of(fid)
        return sum(self.admin_output(r.id) for r in regs), sum(self.admin_consumption(r.id) for r in regs)

    def science_output(self, rid):
        r = self.regions[rid]
        if M.is_extra(self, rid):
            return 0.0               # 광역시: 중심이 광역시 전체 과학력(구성 지역 인구 전체)
        if r.owner == NEUTRAL or r.occ or self.resisting(r) or r.flooded:
            return 0.0
        lv = max(0, min(5, r.b.get("edu", 0)))
        metro = M.of(self, rid)
        pop = r.pop
        if M.is_merged_center(self, rid):     # 광역 슬롯 연구 건물: 구성 지역 인구 전체(v1.3.16)
            pop = sum(self.regions[x].pop for x in metro["members"])
        base = C.EDU_SCIENCE[lv] * pop
        if metro and lv == 5:
            base = 6 * pop
            if self.factions[r.owner].capital in metro["members"]:
                base += 500 if M.merged(self, rid) else 500 / len(metro["members"])
        m = self.mods(r.owner)
        return base * m.mult("science_edu") * m.mult("science_output") * self.great_person_bonus(rid, "science_mult")

    def science_production(self, fid):
        return sum(self.science_output(r.id) for r in self.regions_of(fid))

    def _phase_knowledge(self, f):
        prod, cons = self.admin_balance(f.id)
        net = prod - cons
        f.admin = max(0.0, f.admin + net)
        if f.admin <= 0 and net < 0:
            f.admin_deficit_turns += 1
        else:
            f.admin_deficit_turns = 0
        before = f.lawless
        f.lawless = f.admin_deficit_turns >= C.LAWLESS_TURNS + self.mods(f.id).add("lawless_grace")
        if f.lawless:
            for r in self.regions_of(f.id):
                r.h_delta += C.LAWLESS_HAPPY
        if f.lawless != before:
            self.event("info", f"{f.name}: " + ("행정력 부족으로 무법 상태" if f.lawless else "무법 상태 해제"), fids=(f.id,))
        science = self.science_production(f.id)
        f.sci_points += science
        f.last.update(admin_prod=prod, admin_cons=cons, admin_net=net, science_prod=science)

    def building_cost_mult(self, fid, key, level=1):
        m = self.mods(fid)
        value = m.mult("cost_build") * m.mult("cost_" + key)
        if key == "edu" and level <= 2:
            value *= m.mult("cost_edu_low")
        return value

    def building_tech(self, rid, key):
        if key == "extract":
            return M.extract_res(self, rid)          # 광역 슬롯: 구성 지역 전체의 자원
        return (key,) if key in ("farm", "fishery", "factory", "bank", "power") else ()

    def building_allowed(self, fid, rid, key, level, pool=None):
        """착수와 대기 작업 실행 때 동일한 허가 검사를 사용한다."""
        if fid == NEUTRAL or not 0 <= fid < len(self.factions):
            return False, "국가가 없습니다."
        f = self.factions[fid]
        if key == "academy" and self.mods(fid).value("no_academy"):
            return False, "대숙청: 사관학교 건설 불가"
        if key == "nuclear" and self.settings.mode != "standard" and "power" not in f.techs:
            return False, "대용량 전력망 기술 필요"
        if level >= 4:
            techs = (pool,) if pool in ("oil", "coal") else self.building_tech(rid, key)
            if any(tech not in f.techs for tech in techs):
                return False, "4단계 이상 증축 기술 필요"
        if key not in ("admin", "edu"):
            return True, ""
        metro = M.of(self, rid)
        members = metro["members"] if metro else [rid]
        capital = f.capital in members
        if level >= 5 and not capital:
            return False, "수도 또는 수도가 포함된 특별시에만 5단계 건설 가능"
        if key == "admin" and level == 4:
            for site in members:
                for n in self.world.land_adj[site]:
                    if n in members or self.regions[n].owner != fid:
                        continue
                    other = self.regions[n]
                    # 실행 중뿐 아니라 예약도 잡아 동시 4단계 착수 경쟁을 막는다.
                    reserved = any(p.kind == "build" and p.key == "admin" and p.level >= 4
                                   for p in self.local_projects(n))
                    if self.blevel(n, "admin") >= 4 or reserved:
                        return False, "인접한 자국 지역에 도청 또는 도청 공사가 있습니다."
        return True, ""

    def _cancel_capital_projects(self, fid, keys, restored):
        """수복으로 중복되는 5단계 공사는 낸 비용 전액 환급."""
        seen = set()
        for r in self.regions_of(fid):
            if M.center_of(self, r.id) != r.id:
                continue
            for p in list(self.local_projects(r.id)):
                if id(p) in seen:
                    continue
                seen.add(id(p))
                if p.kind != "build" or p.key not in keys or p.level != 5:
                    continue
                if restored in self.project_sites(r.id, p):
                    continue
                self.factions[fid].money += p.paid
                self.factions[fid].refund += p.paid
                if r.project is p:
                    self._clear_project(r)
                else:
                    r.queue[:] = [q for q in r.queue if q is not p]
        self.promote_queues()

    def _downgrade_capital(self, fid, oldcap, newcap, keys=("admin", "edu")):
        if oldcap not in self.regions or oldcap == newcap:
            return
        old_members = M.members(self, oldcap)
        if newcap in old_members:
            return
        for rid in old_members:
            r = self.regions[rid]
            if r.owner == fid:
                for key in keys:
                    if r.b.get(key, 0) >= 5:
                        r.b[key] = 4
        for metro in M.metros(self).values():
            if metro["owner"] == fid:
                metro["special"] = newcap in metro["members"]

    def _government_before_transfer(self, rr, old, new_owner, reason):
        if old == NEUTRAL or reason != "점령" or new_owner == NEUTRAL:
            return
        f = self.factions[old]
        self._expire_capital_claim(f)
        if f.capital in M.members(self, rr.id):
            war = self.dip.wars.get(D.pair(old, new_owner))
            same_capture = (getattr(self, "_metro_capture", False) and f.lost_capital
                            and f.lost_capital["rid"] in M.members(self, rr.id))
            if not same_capture and not f.lost_capital:
                f.lost_capital = {"rid": f.capital, "war_with": new_owner, "turn": self.turn,
                                  "until": self.turn + C.RESIST_NO_REBEL_TURNS,
                                  "war_start": war.get("start") if war else None}
            if rr.b.get("admin", 0) == 5 or rr.b.get("edu", 0) == 5:
                if not rr.lost_gov_complex:
                    rr.lost_gov_complex = {"fid": old, "admin5": rr.b.get("admin", 0) == 5,
                                           "edu5": rr.b.get("edu", 0) == 5, "turn": self.turn}
        if rr.b.get("admin", 0) >= 4 and not rr.occupied_admin:
            rr.occupied_admin = {"fid": old, "turn": self.turn}

    def _government_after_transfer(self, rr, old, new_owner, reason):
        # 함락된 장군은 소멸, 민간 위인은 자국 수도로 피신한다.
        for person in list(self.great_people):
            if person["loc"] != rr.id or person["owner"] == new_owner:
                continue
            owner = self.factions[person["owner"]]
            if person["kind"] == "general" or not owner.alive or self.regions[owner.capital].owner != owner.id:
                self.great_people.remove(person)
            else:
                person["loc"] = M.node(self, owner.capital)
        if new_owner == NEUTRAL:
            return
        f = self.factions[new_owner]
        self._expire_capital_claim(f)
        lost = f.lost_capital
        if reason == "점령" and lost and lost["rid"] == rr.id:
            if self.turn < lost.get("until", lost["turn"] + C.RESIST_NO_REBEL_TURNS):
                self._downgrade_capital(new_owner, f.capital, rr.id)
                f.capital = rr.id
                f.lost_capital = None
                self.event("capital", f"{f.name}: 수복한 {josa(self.info(rr.id).name, '으로/로')} 수도 복귀",
                           region=rr.id, fids=(new_owner,))
        complex_ = rr.lost_gov_complex
        if complex_ and complex_["fid"] == new_owner and self.turn - complex_["turn"] < C.RESIST_NO_REBEL_TURNS:
            keys = tuple(k for k in ("admin", "edu") if complex_.get(k + "5"))
            self._cancel_capital_projects(new_owner, keys, rr.id)
            for r in self.regions_of(new_owner):
                if r.id not in M.members(self, rr.id):
                    for key in keys:
                        r.b[key] = min(r.b.get(key, 0), 4)
            for key in keys:
                rr.b[key] = 5
            rr.lost_gov_complex = None
        if rr.occupied_admin and rr.occupied_admin["fid"] == new_owner:
            rr.occupied_admin = None

    def _expire_capital_claim(self, f):
        lost = f.lost_capital
        if lost and self.turn >= lost.get("until", lost["turn"] + C.RESIST_NO_REBEL_TURNS):
            f.lost_capital = None

    def _settle_government_buildings(self):
        for f in self.factions:
            self._expire_capital_claim(f)
        for rr in self.regions.values():
            complex_ = rr.lost_gov_complex
            if complex_ and rr.owner != complex_["fid"]:
                if not self.resisting(rr):
                    for key in ("admin", "edu"):
                        if complex_.get(key + "5"):
                            rr.b[key] = min(rr.b.get(key, 0), 4)
                if self.turn - complex_["turn"] >= C.RESIST_NO_REBEL_TURNS:
                    rr.lost_gov_complex = None
            occ = rr.occupied_admin
            if occ and self.turn - occ["turn"] >= C.RESIST_NO_REBEL_TURNS:
                if rr.owner != occ["fid"] and rr.b.get("admin", 0) >= 4:
                    own_metro = set(M.members(self, rr.id))
                    if any(n not in own_metro and self.regions[n].owner == rr.owner
                           and self.regions[n].b.get("admin", 0) >= 4 for n in self.world.land_adj[rr.id]):
                        rr.b["admin"] = 3
                rr.occupied_admin = None
