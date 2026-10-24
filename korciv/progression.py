"""행정 정책, 과학 기술, 전 세계 공통 위인 풀."""
from __future__ import annotations

import math

from . import config as C
from . import metro as M
from .leaders import POLICIES, POLICY_COSTS, POLICY_COMPLETION


TECHS = {
    "inf": dict(name="기계화보병 편제", cost=800, kind="unit", description="기계화보병: 공15/방15/체15"),
    "art": dict(name="자주포 체계", cost=1200, kind="unit", description="자주포: 공18/방18/폭20/체12"),
    "tank": dict(name="주력전차 개발", cost=1800, kind="unit", description="전차: 공25/방25/체55"),
    "lst": dict(name="대형 수송선 건조", cost=1000, kind="unit", description="수송선: 수송14/체35"),
    "dd": dict(name="이지스 전투체계", cost=1400, kind="unit", description="이지스함: 공30/방30/폭30/체75"),
    "cv": dict(name="항공모함 강습단", cost=2000, kind="unit", description="항공모함 생산 해금: 함재기6/체100"),
    "ftr": dict(name="초음속 전투기", cost=2000, kind="unit", description="전투기: 방35/요격35/체35"),
    "bmb": dict(name="스텔스 항법", cost=2800, kind="unit", description="스텔스폭격기: 폭55/체30, 요격 피해 -40%"),
    "farm": dict(name="현대 농업", cost=1000, kind="building", description="농장 4~5단계, 광역시 6단계 해금"),
    "fishery": dict(name="원양·양식 수산업", cost=1000, kind="building", description="어장 4~5단계, 광역시 6단계 해금"),
    "factory": dict(name="스마트 공정", cost=2000, kind="building", description="공장 4~5단계, 광역시 6단계 해금"),
    "bank": dict(name="현대 금융·유통", cost=1800, kind="building", description="시장 4~5단계, 광역시 6단계 해금"),
    "extract": dict(name="자원 채굴 고도화", cost=1500, kind="building", description="탄광·정유공장 4~5단계, 광역시 6단계 해금"),
    "power": dict(name="대용량 전력망", cost=1800, kind="building", description="화력 4~5단계, 원자력발전소 건설 해금"),
    "aerospace": dict(name="우주항공공학", cost=3500, kind="victory", description="항공우주연구소 및 과학승리 해금"),
}

BASE_UNITS = {
    "inf": dict(name="보병", atk=10, df=10, hp=10, cost=250, turns=1),
    "art": dict(name="박격포", atk=12, df=12, bomb=12, hp=10, cost=400, turns=2),
    "tank": dict(name="장갑차", atk=16, df=16, hp=35, cost=600, turns=3, oil=1),
    "lst": dict(name="상륙함", capacity=8, hp=20, cost=500, turns=2, oil=1),
    "dd": dict(name="구축함", atk=20, df=20, bomb=20, hp=50, cost=1000, turns=3, oil=1),
    "cv": dict(name="항공모함", air_capacity=6, hp=100, cost=1500, turns=4, oil=2),
    "ftr": dict(name="공격기", df=22, intercept=22, hp=25, cost=650, turns=3, oil=1),
    "bmb": dict(name="폭격기", bomb=35, hp=20, cost=900, turns=3, oil=1),
}
MODERN_UNITS = {
    "inf": dict(name="기계화보병", atk=15, df=15, hp=15, cost=300),
    "art": dict(name="자주포", atk=18, df=18, bomb=20, hp=12, cost=550),
    "tank": dict(name="전차", atk=25, df=25, hp=55, cost=800),
    "lst": dict(name="수송선", capacity=14, hp=35, cost=600),
    "dd": dict(name="이지스함", atk=30, df=30, bomb=30, hp=75, cost=1200),
    "cv": {},
    "ftr": dict(name="전투기", df=35, intercept=35, hp=35, cost=800),
    "bmb": dict(name="스텔스폭격기", bomb=55, hp=30, cost=1100, interception_damage=.6),
}


def unit_spec_for(techs, key):
    """전역 config를 바꾸지 않고 세력별 병종 정보를 돌려준다."""
    spec = dict(C.UNITS[key])
    spec.update(BASE_UNITS.get(key, {}))
    if key in techs:
        spec.update(MODERN_UNITS.get(key, {}))
    spec["available"] = key != "cv" or "cv" in techs
    if not spec.get("science"):
        spec["upkeep"] = round(spec["cost"] * spec["turns"] * C.UPKEEP_RATIO, 2)
    return spec


GP_POOLS = {
    "scientist": tuple("관륵 아사달 담징 김대성 최무선 장영실 이천 이순지 최석정 허준 김정호 정약용 이제마 지석영 이태규 석주명 우장춘 유경로 허문회 이임학 이휘소 김순경".split()),
    "chancellor": tuple("창조리 거칠부 김춘추 명림답부 을파소 성충 서희 신돈 정몽주 김종서 정도전 황희 맹사성 조광조 이황 송시열 류성룡 이원익 이항복 김육 채제공 김홍집 여운형 조소앙".split()),
    "general": tuple("을지문덕 양만춘 온달 이사부 김유신 관창 계백 흑치상지 장문휴 신숭겸 척준경 양규 윤관 배중손 이종무 권율 김시민 이억기 곽재우 임경업 이완 김좌진 홍범도 지청천 채명신".split()),
    "artist": tuple("솔거 왕산악 우륵 옥보고 백결선생 이녕 서구방 정지상 이규보 이색 안견 김시습 박연 신사임당 황진이 정철 한석봉 허균 허난설헌 정선 김홍도 신윤복 김정희 김삿갓 장승업 나운규 윤동주 이상 백남준 조수미 김광석 조용필 BTS".split()),
}
GREAT_PEOPLE = {
    "scientist": dict(name="위대한 과학자", currency="sci_points", names=GP_POOLS["scientist"],
                      description="지역 과학력 +30%. 소모: 연구·과학 공사 단축 또는 과학력 8턴분."),
    "chancellor": dict(name="위대한 재상", currency="admin", names=GP_POOLS["chancellor"],
                       description="지역 행정력 +30·금전 +15%. 소모: 행정·경제 공사 50% 단축."),
    "general": dict(name="위대한 장군", currency="admin", names=GP_POOLS["general"],
                    description="주둔 방어력 +25%, 출격 공격력 +20%. 지역당 한 명 적용."),
    "artist": dict(name="위대한 예술가", currency="admin", names=GP_POOLS["artist"],
                   description="소모: 지역 행복도 +25, 자국 전 지역 +8, 전쟁 피로 -10."),
}


class ProgressionMixin:
    @staticmethod
    def migrate_resource_techs(techs):
        """옛 기술 하나라도 배웠으면 통합 기술을 계승한다. 재고·포인트를 소급 변경하지 않는다."""
        if techs.intersection(('coal', 'oil')):
            techs.difference_update(('coal', 'oil'))
            techs.add('extract')

    def policy_level(self, fid):
        return max(0, min(5, int(getattr(self.factions[fid], "policy_level", 0))))

    def unlock_policy(self, fid):
        f = self.factions[fid] if isinstance(fid, int) and 0 <= fid < len(self.factions) else None
        if f is not None and getattr(f, "rebel", False):
            return False, "반군은 정책을 해금할 수 없습니다."
        if not f or not f.alive or f.gov not in POLICIES:
            return False, "정책을 해금할 정치체제가 없습니다."
        level = self.policy_level(fid)
        if level >= 5:
            return False, "이미 모든 정책을 해금했습니다."
        stage = POLICIES[f.gov][level]
        if f.admin < stage["cost"]:
            return False, f"행정력 {stage['cost']:,}이 필요합니다."
        f.admin -= stage["cost"]
        f.policy_level = level + 1
        self._mods.pop(fid, None)
        self._progression_changed()
        self.event("info", f"{self.fname(fid)}: {stage['name']} 정책 해금", fids=(fid,))
        return True, stage["name"] + (" · 체제 완성" if f.policy_level == 5 else "")

    def unlock_tech(self, fid, key):
        f = self.factions[fid] if isinstance(fid, int) and 0 <= fid < len(self.factions) else None
        if not f or not f.alive or key not in TECHS:
            return False, "연구할 기술이 없습니다."
        if getattr(f, "rebel", False):
            return False, "반군은 과학을 연구할 수 없습니다."
        if key in f.techs:
            return False, "이미 해금한 기술입니다."
        spec = TECHS[key]
        cost = self.tech_cost(fid, key)
        if f.sci_points < cost:
            return False, f"과학력 {cost:,.0f}이 필요합니다."
        old_hp = self.unit_spec(fid, key)["hp"] if spec["kind"] == "unit" else None
        f.sci_points -= cost
        f.techs.add(key)
        if old_hp:
            new_hp = self.unit_spec(fid, key)["hp"]
            for army in self.armies.values():
                if army.owner == fid:
                    army.techs = f.techs
                    if army.units.get(key):
                        army.dmg[key] = army.dmg.get(key, 0) * new_hp / old_hp
        self._progression_changed()
        self.event("info", f"{self.fname(fid)}: {spec['name']} 기술 해금", fids=(fid,))
        return True, spec["name"]

    def tech_cost(self, fid, key):
        return TECHS[key]["cost"] * (self.mods(fid).mult("military_tech_cost") if TECHS[key]["kind"] == "unit" else 1)

    def unit_spec(self, fid, key):
        f = self.factions[fid] if isinstance(fid, int) and 0 <= fid < len(self.factions) else None
        spec = unit_spec_for(getattr(f, "techs", ()), key)
        if f and self.mods(fid).value("multiwar_def_flat"):
            from . import diplomacy as D
            if len(D.enemies(self, fid)) >= 2:
                spec["df"] = max(0, spec["df"] - self.mods(fid).value("multiwar_def_flat"))
        return spec

    @staticmethod
    def science_per_turn_cost(tier):
        return round(200 * (1.15 ** tier))

    def great_person_cost(self, fid, kind):
        if kind not in GREAT_PEOPLE or not isinstance(fid, int) or not 0 <= fid < len(self.factions):
            return math.inf
        count = max(0, int(self.great_people_bought.get(kind, 0)))
        base = (600, 1000, 1500, 2200)[count] if count < 4 else 2200 + 800 * (count - 3)
        return float(base * self.mods(fid).mult("gp_" + kind + "_cost"))

    def can_recruit_great_person(self, fid, kind, rid=None):
        f = self.factions[fid] if isinstance(fid, int) and 0 <= fid < len(self.factions) else None
        if not f or not f.alive or kind not in GREAT_PEOPLE:
            return False, "위인을 맞이할 국가 또는 분야가 없습니다."
        if getattr(f, "rebel", False):
            return False, "반군은 위인을 맞이할 수 없습니다."
        if kind == "chancellor" and self.mods(fid).value("no_chancellor"):
            return False, "문신 숙청: 위대한 재상 구매 불가"
        rid = rid or f.capital
        rr = self.regions.get(rid)
        if rr is None or rr.owner != fid:
            return False, "자국 지역에만 위인을 배치할 수 있습니다."
        if f.leader == "sej" and kind == "scientist" and rr.b.get("edu", 0) < 4:
            return False, "집현전: 연구 4단계 이상 지역에서 과학자를 구매하세요."
        regs = list(self.regions_of(fid))
        gates = {
            "scientist": (any(r.b.get("edu", 0) >= 4 for r in regs), "종합대학(연구 4단계)이 필요합니다."),
            "chancellor": (any(r.b.get("admin", 0) >= 4 for r in regs), "도청(행정 4단계)이 필요합니다."),
            "general": (any(r.b.get("academy", 0) >= 1 for r in regs), "사관학교가 필요합니다."),
            "artist": (any(r.b.get("admin", 0) >= 3 and
                           (r.b.get("specialty", 0) >= 3 or self.info(r.id).scenic) for r in regs),
                       "시청이 있는 특산물 3단계 또는 자연경관 지역이 필요합니다."),
        }
        if not gates[kind][0]:
            return False, gates[kind][1]
        if all(name in self.spawned_great_people for name in GP_POOLS[kind]):
            return False, "이 분야의 모든 위인이 이미 등장했습니다."
        cost = self.great_person_cost(fid, kind)
        currency = GREAT_PEOPLE[kind]["currency"]
        if getattr(f, currency) < cost:
            return False, f"{'과학력' if currency == 'sci_points' else '행정력'} {cost:,.0f}이 필요합니다."
        return True, ""

    def recruit_great_person(self, fid, kind, rid=None):
        ok, reason = self.can_recruit_great_person(fid, kind, rid)
        if not ok:
            return False, reason
        f = self.factions[fid]
        rid = rid or f.capital
        # 시대순 등장: 목록 순서는 세이브·시드와 무관하게 전 세계에서 한 번만 소모된다.
        name = next(name for name in GP_POOLS[kind] if name not in self.spawned_great_people)
        currency = GREAT_PEOPLE[kind]["currency"]
        setattr(f, currency, getattr(f, currency) - self.great_person_cost(fid, kind))
        self.spawned_great_people.add(name)
        self.great_people_bought[kind] = self.great_people_bought.get(kind, 0) + 1
        gid = self.next_great_person_id
        self.next_great_person_id += 1
        self.great_people.append(dict(id=gid, owner=fid, kind=kind, name=name, loc=rid))
        self._progression_changed()
        self.event("info", f"{self.fname(fid)}에 {GREAT_PEOPLE[kind]['name']} {name} 등장",
                   region=rid, fids=(fid,))
        return True, f"{GREAT_PEOPLE[kind]['name']} {name}"

    def great_people_at(self, rid, kind=None):
        return [gp for gp in self.great_people
                if gp["loc"] == rid and (kind is None or gp["kind"] == kind)]

    def sync_general_escorts(self):
        """전투에 동행한 장군은 생존 부대를 따라가며, 타국에서 호위가 사라지면 퇴장한다."""
        for gp in list(getattr(self, "great_people", [])):
            if gp["kind"] != "general":
                continue
            escort = self.armies.get(gp.get("escort"))
            if escort is not None and escort.owner == gp["owner"]:
                gp["loc"] = escort.loc
                continue
            gp.pop("escort", None)
            rr = self.regions.get(gp["loc"])
            if rr is not None and rr.owner == gp["owner"]:
                continue
            troops = self.armies_at(gp["loc"], gp["owner"])
            if troops:
                gp["escort"] = max(troops, key=lambda a: a.count()).id
            else:
                self.great_people.remove(gp)

    def great_person_bonus(self, rid, key, fid=None):
        rr = self.regions.get(rid)
        owner = fid if fid is not None else (rr.owner if rr else None)
        from . import metro as M
        if rr is not None and getattr(rr, "metro", None) is not None:
            if key == "admin_add" and M.is_extra(self, rid):
                return 0.0                       # 광역시: 더하는 효과는 중심(광역시 전체)에서 한 번
            sites = set(M.members(self, rid))    # 광역시 어디에 있어도 광역시 전체에(하나의 지역, v1.3.17)
            people = [gp for gp in self.great_people if gp["loc"] in sites and gp["owner"] == owner]
        else:
            people = [gp for gp in self.great_people_at(rid) if gp["owner"] == owner]
        count = lambda kind: sum(gp["kind"] == kind for gp in people)
        bonuses = {"science_mult": 1 + .3 * count("scientist"),
                   "admin_add": 30 * count("chancellor"),
                   "output_mult": 1 + .15 * count("chancellor"),
                   "defense_mult": 1.25 if count("general") else 1.0,
                   "attack_mult": 1.2 if count("general") else 1.0}
        return bonuses.get(key, 1.0 if key.endswith("_mult") else 0.0)

    def move_great_person(self, gid, rid):
        gp = next((p for p in self.great_people if p["id"] == gid), None)
        rr = self.regions.get(rid)
        if not gp or not rr or rr.owner != gp["owner"]:
            return False, "위인은 자국 지역으로만 이동할 수 있습니다."
        if not self.factions[gp["owner"]].alive:
            return False, "멸망한 국가의 위인은 이동할 수 없습니다."
        gp["loc"] = M.node(self, rid) if rid in self.regions else rid      # 광역시는 한 칸
        gp.pop("escort", None)
        self._progression_changed()
        return True, f"{gp['name']} 이동"

    def activate_great_person(self, gid, mode="project"):
        gp = next((p for p in self.great_people if p["id"] == gid), None)
        if not gp:
            return False, "위인이 없습니다."
        rr = self.regions.get(gp["loc"])
        fid, kind = gp["owner"], gp["kind"]
        if rr is None or rr.owner != fid or not self.factions[fid].alive:
            return False, "자국 지역에서만 위인을 사용할 수 있습니다."
        f = self.factions[fid]
        if kind == "general":
            return False, "장군은 지역에 주둔하여 전투를 지휘합니다."
        if kind == "artist":
            from . import metro as M
            target = M.center_of(self, rr.id)
            for region in self.regions_of(fid):
                region.happy = min(C.HAPPY_MAX, region.happy + 8 + (25 if M.center_of(self, region.id) == target else 0))
            from . import diplomacy as D
            D.add_war_weary(self, fid, -10)
            result = "행복도 상승 및 전쟁 피로 -10"
        elif kind == "scientist" and mode == "science":
            amount = self.science_production(fid) * 8
            if amount <= 0:
                return False, "현재 과학력 산출이 없어 위인을 사용할 수 없습니다."
            f.sci_points += amount
            result = f"과학력 +{amount:,.0f}"
        elif mode == "project":
            project = rr.project
            eligible = (project is not None and
                        ((kind == "scientist" and
                          (project.kind == "science" or (project.kind == "build" and project.key == "edu"))) or
                         (kind == "chancellor" and
                          (project.kind == "econ" or (project.kind == "build" and project.key == "admin")))))
            if not eligible:
                return False, "이 위인이 도울 수 있는 공사가 진행 중이지 않습니다."
            remaining = project.remaining
            target = math.ceil(remaining / 2)
            if kind == "scientist":
                target = max(3, target)
            if target >= remaining:
                return False, "남은 공사 기간이 짧아 단축할 수 없습니다."
            project.turns = project.progress + target
            result = f"남은 공사 {remaining}턴 → {target}턴"
        else:
            return False, "지원하지 않는 위인 행동입니다."
        self.great_people.remove(gp)
        self._progression_changed()
        self.event("info", f"{gp['name']}: {result}", region=rr.id, fids=(fid,))
        return True, result

    def _progression_changed(self):
        """같은 턴의 재조회에도 정책·위인·기술 변경이 즉시 반영된다."""
        for name in ("_cache", "_combat_cache", "_economy_cache", "_morale"):
            cache = getattr(self, name, None)
            if isinstance(cache, dict):
                cache.clear()
