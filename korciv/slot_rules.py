"""건물 슬롯(v1.3.8) 엔진 규칙: 슬롯 선택지(신축·증축), 철거, 카드별 산출·효과 문구."""
from __future__ import annotations

from . import config as C, metro as M, rules as R, slots as S
from .state import BUILDING_NAMES, NEUTRAL


class SlotMixin:
    # ------------------------------------------------------------------ 조회
    def slot_projects(self, rid):
        """이 지역 칸을 대상으로 한 실행·대기 공사(앞에서부터). 연속 건설 중에는 실행 중인 것만."""
        ps = self.local_projects(rid)
        if getattr(self, "_continuing", False):
            ps = ps[:1] if self.queue_region(rid).project else []
        return [p for p in ps if p.kind == "build" and getattr(p, "slot", None) and (p.site or rid) == rid]

    def projected_slots(self, rid) -> dict:
        """대기열까지 끝났을 때의 슬롯 {종류: [카드 또는 None]}(카드는 복사본)."""
        b = self.regions[rid].b
        proj = {t: [dict(c) if c else None for c in b.slots.get(t, ())] for t in S.SLOT_TYPES}
        for p in self.slot_projects(rid):
            stype, idx = p.slot
            if stype not in proj or not 0 <= idx < len(proj[stype]):
                continue
            top = S.max_level(p.key, self.info(rid)) if p.chain else p.level
            c = proj[stype][idx]
            if c is None:
                proj[stype][idx] = {"key": p.key, "level": top, "planned": True}
            elif c["key"] == p.key and top > c["level"]:
                c["level"], c["planned"] = top, True
        return proj

    def slot_project(self, rid, slot):
        """그 칸을 대상으로 한 첫 공사(실행 중이면 그것)."""
        for p in self.slot_projects(rid):
            if tuple(p.slot) == tuple(slot):
                return p
        return None

    def slot_key_ok(self, rid, key, stype) -> bool:
        """지역 조건상 이 칸에 아예 지을 수 없는 건물이면 False(목록에서 뺀다)."""
        info = self.info(rid)
        if key not in S.SLOT_KEYS[stype]:
            return False
        if stype == "etc":                    # 기타 슬롯: 댐·원전·특산물 입지만(항구는 장보고 무료 항구로만)
            return key in S.etc_kinds(info)
        if key == "extract":                  # 광역 슬롯: 유전·탄전이 있는 구성 지역이 하나라도 있으면
            return bool(M.extract_res(self, rid))
        return True

    def card_max(self, rid, key) -> int:
        """카드 최대 단계. 광역 슬롯의 농장·어장·공장·시장·발전소·채굴 카드는 6단계까지(광역시 전용)."""
        if key in C.METRO_L6_KEYS and M.is_merged_center(self, rid):
            return 6
        return S.max_level(key, self.info(rid))

    def slot_site(self, rid, stype) -> str:
        """그 슬롯 카드가 있는 지역(광역시 기본·하천·해안 슬롯은 중심, 나머지는 그 지역)."""
        return M.slot_site(self, rid, stype)

    # ------------------------------------------------------------------ 비용
    def card_cost(self, fid, rid, key, lv):
        """(총비용, 소요 턴)."""
        info = self.info(rid)
        if key in C.SITE_POWER:
            eq = C.SITE_POWER[key][1]
            return (R.prod_building_cost("power", eq) * self.building_cost_mult(fid, key),
                    self.build_time(fid, "power", R.prod_building_turns(eq), rid, 1))
        if key in C.SINGLE_BUILDINGS:
            spec = C.SINGLE_BUILDINGS[key]
            return (spec["cost"] * C.BUILD_COST_MULT * C.MONEY_SCALE * self.building_cost_mult(fid, key),
                    self.build_time(fid, key, spec["turns"], rid, 1))
        site = info.power_site or (key == "power" and any(self.info(r).power_site for r in M.slot_regions(self, rid, "base")
                                                             + M.slot_regions(self, rid, "river") + M.slot_regions(self, rid, "coast")))
        cost = R.prod_building_cost(key, lv, site) * self.building_cost_mult(fid, key, lv)
        return cost, self.build_time(fid, key, R.prod_building_turns(lv), rid, lv)

    # ------------------------------------------------------------------ 선택지
    def slot_options(self, fid, rid, add):
        """빈 칸마다 들어갈 수 있는 1단계 건물(종류별로 첫 빈 칸), 꽂힌 카드마다 다음 단계 증축."""
        rr = self.regions[rid]
        proj = self.projected_slots(rid)
        planned_keys = {c["key"] for t in proj for c in proj[t] if c}
        for stype in S.SLOT_TYPES:
            empties = [i for i, c in enumerate(proj[stype]) if c is None]
            if not empties:
                continue
            idx = empties[0]
            for key in S.SLOT_KEYS[stype]:
                if not self.slot_key_ok(rid, key, stype):
                    continue
                if key in S.UNIQUE_KEYS and key in planned_keys:
                    continue
                lv = self.card_max(rid, key) if key in C.SITE_POWER else 1
                cost, turns = self.card_cost(fid, rid, key, lv)
                ok, why = self.building_allowed(fid, rid, key, lv)
                if key == "nuclear" and rr.nuclear_destroyed:
                    ok, why = False, "원전 재건설 영구 불가"
                add("build", key, self.building_name(rid, key), cost, turns, ok, why, level=lv, slot=(stype, idx))
        for stype in S.SLOT_TYPES:
            for idx, c in enumerate(proj[stype]):
                if c is None:
                    continue
                key = c["key"]
                lv = c["level"] + 1
                if lv > self.card_max(rid, key):
                    continue
                cost, turns = self.card_cost(fid, rid, key, lv)
                ok, why = self.building_allowed(fid, rid, key, lv)
                add("build", key, self.building_name(rid, key), cost, turns, ok, why, level=lv, slot=(stype, idx))

    def slot_choices(self, fid, rid, slot, opts=None) -> list:
        """행동 탭에서 고른 칸의 선택지: 빈 칸이면 그 칸에 지을 수 있는 1단계 건물들(그 칸으로 바꿔서),
        건물이 있는 칸이면 그 카드의 다음 단계 증축."""
        opts = self.options(fid, rid) if opts is None else opts
        slot = tuple(slot)
        proj = self.projected_slots(rid)
        lst = proj.get(slot[0], [])
        if not 0 <= slot[1] < len(lst):
            return []
        cur = lst[slot[1]]
        out = []
        for o in opts:
            s0 = o.get("slot")
            if o["kind"] != "build" or not s0 or (o.get("site") or rid) != rid:
                continue
            if cur is None:
                if s0[0] == slot[0] and proj[s0[0]][s0[1]] is None:
                    out.append(dict(o, slot=slot))
            elif tuple(s0) == slot:
                out.append(o)
        return out

    def slot_option_label(self, rid, o) -> str:
        """'[기본 슬롯 2] 농장 건설 · 텃밭' / '[기본 슬롯 1] 농장 2→3단계 증축'."""
        stype, idx = o["slot"]
        head = f"[{S.slot_label((stype, idx))}] "
        key, lv = o["key"], o["level"]
        name = self.slot_kind_name(rid, key, stype)
        if lv <= 1 or key in C.SITE_POWER:
            first = self.building_name(rid, key, 1) if key in C.PROD_LEVEL_NAMES else name
            return head + f"{name} 건설" + (f" · {first}" if first != name else "")
        return head + f"{name} {lv - 1}→{lv}단계 증축"

    def slot_kind_name(self, rid, key, stype=None) -> str:
        """칸 종류까지 붙인 건물 이름: 하천 어장·바다 어장, 화력발전소, 탄광·정유공장."""
        if key == "fishery":
            return "하천 어장" if stype == "river" else "바다 어장" if stype == "coast" else "어장"
        if key == "power":
            return "화력발전소"
        if key == "extract":
            return "정유공장" if "oil" in M.extract_res(self, rid) else "탄광"
        if key == "port" and stype == "etc":
            return "무료 항구"
        return BUILDING_NAMES.get(key, key)

    def card_title(self, rid, key, level, stype=None) -> str:
        """카드에 적는 단계별 고유 이름(예: 대농장·시청·거점국립대학)."""
        if key in ("admin", "edu") or key in C.PROD_LEVEL_NAMES:
            return self.building_name(rid, key, level)
        return self.slot_kind_name(rid, key, stype)

    # ------------------------------------------------------------------ 철거
    def demolish_card(self, fid, rid, slot):
        """슬롯 비우기: 그 칸의 건물을 통째로 철거한다(공사가 걸린 칸은 공사부터 취소)."""
        rr = self.regions.get(rid)
        if rr is None or rr.owner != fid:
            return False, "내 지역이 아닙니다."
        slot = tuple(slot)
        c = rr.b.card(slot)
        if c is None:
            return False, "철거할 건물이 없습니다."
        if self.slot_project(rid, slot) is not None:
            return False, "이 칸에 공사가 잡혀 있습니다. 공사를 먼저 취소하세요."
        if rr.occ or self.resisting(rr):
            return False, "점령 또는 저항 중인 지역입니다."
        name = self.card_title(rid, c["key"], c["level"], slot[0])
        rr.b.remove(slot)
        if c["key"] in ("factory", "power"):
            rr.energy = {}
        return True, f"{S.slot_label(slot)} {name} 철거 — 빈 슬롯"

    def demolish_building(self, fid, rid, key):
        """(예전 방식) 그 종류의 가장 높은 카드를 철거한다."""
        rr = self.regions.get(rid)
        if rr is None or rr.owner != fid:
            return False, "내 지역이 아닙니다."
        pos = rr.b.primary(key) if hasattr(rr.b, "primary") else None
        if pos is None:
            return False, "철거할 건물이 없습니다."
        return self.demolish_card(fid, rid, pos)

    # ------------------------------------------------------------------ 산출
    def fish_slot_mult(self, fid, rid, stype) -> float:
        """어장 카드 배수: 하천 칸 ×0.8, 해안 칸 ×1(해안선 점유 ×1.2), 날씨.
        광역 슬롯은 그 슬롯을 가진 구성 지역들 기준(해안선은 하나라도 점유하면, 날씨는 평균)."""
        sites = M.slot_regions(self, rid, stype)
        if stype == "river":
            base = C.RIVER_FISH_MULT
        else:
            base = 1.0
            if fid != NEUTRAL and any(self.coast_controller(s) == fid for r in sites for s in self.info(r).seas):
                base = 1 + C.COAST_FISH_BONUS
        return base * sum(self.weather_fish_mult(r, river=stype == "river") for r in sites) / len(sites)

    def fishery_eff(self, fid, rid) -> float:
        """어장 카드들의 Σ 단계 × 배수(식량·산출 공통). 광역 슬롯 카드는 구성 지역 수만큼(배수)."""
        b = self.regions[rid].b
        if not hasattr(b, "cards"):
            return b.get("fishery", 0) * self.fish_mult(fid, rid)
        return sum(c["level"] * b.mult_of(t) * self.fish_slot_mult(fid, rid, t) for t, _, c in b.cards("fishery"))

    def extract_amount(self, fid, rr, res=None) -> float:
        """채굴 카드들의 생산(석유는 유전 기본량 + 카드 단계 합, 석탄은 카드 단계 합). 3단계 이상 카드마다 정책 보너스.
        res: "oil"·"coal"(혼돈 판도처럼 둘 다 있으면 따로 센다). 안 주면 그 지역 자원(석유 우선)."""
        info = self.info(rr.id)
        m = self.mods(fid)
        res = res or ("oil" if info.is_oil or "oil" in M.extract_res(self, rr.id) else "coal")
        lv = M.extract_levels(self, rr.id, res)          # 광역 채굴 카드는 유전·탄전 구성 지역 비율로 나눈다
        extra = m.add("extract3_extra") * sum(1 for x in lv if x >= 3)
        base = info.oil if res == "oil" else 0
        return (base + sum(lv) + extra) * m.mult("output_extract")

    def card_effect(self, fid, rid, card, stype) -> str:
        """슬롯 카드 아래에 적는 핵심 효과 요약(광역 슬롯 카드는 구성 지역 수 n 배를 합친 값)."""
        key, lv = card["key"], card["level"]
        info = self.info(rid)
        owner = fid if fid is not None else self.regions[rid].owner
        m = self.mods(owner)
        n = self.regions[rid].b.mult_of(stype) if hasattr(self.regions[rid].b, "mult_of") else 1
        if key == "farm":
            fm = self.farm_mult(owner, rid) if owner != NEUTRAL else 1.0
            return f"식량+{C.FARM_FOOD * lv * n * fm * m.mult('food_prod'):.0f} · 산출+{C.FARM_OUTPUT * lv * n * fm * m.mult('output_prod'):,.0f}"
        if key == "fishery":
            fm = self.fish_slot_mult(owner, rid, stype)
            return f"식량+{C.FISH_FOOD * lv * n * fm * m.mult('food_prod'):.0f} · 산출+{C.FISH_OUTPUT * lv * n * fm * m.mult('output_prod'):,.0f}"
        if key == "factory":
            return f"연료 {lv * n} · 개당 {R.factory_unit(lv) * m.mult('output_factory') * m.mult('output_prod'):,.0f}"
        if key == "bank":
            return f"산출 +{C.BANK_OUTPUT * R.g(lv) * n * m.mult('output_bank') * m.mult('output_prod'):,.0f}"
        if key == "power":
            return f"연료 {lv * n} · 석탄당 전기 {self.power_elec(owner, 'coal', lv):g}"
        if key in C.SITE_POWER:
            return f"전기 +{min(lv, getattr(info, key))}/턴"
        if key == "extract":
            return ("석유" if "oil" in M.extract_res(self, rid) else "석탄") + f" +{lv * n}/턴"
        if key == "admin":
            mt = M.merged(self, rid) if n > 1 else None
            if mt and lv >= 5:
                cap = owner != NEUTRAL and self.factions[owner].capital in mt["members"]
                return f"행정력 +{50 * n + (100 if cap else 0):g}"
            return f"행정력 +{C.ADMIN_OUTPUT[max(0, min(5, lv))] * n:g}"
        if key == "edu":
            per = 6 if n > 1 and lv >= 5 else C.EDU_SCIENCE[max(0, min(5, lv))]
            return f"과학력 {per:g}×인구" + (f"({n}곳)" if n > 1 else "")
        if key == "academy":
            return f"유닛 생산비 −{C.ACADEMY_LOCAL:.0%}"
        if key == "port":
            return "해군 생산·정박" + (" (청해진)" if card.get("free") else "")
        if key == "specialty":
            sps = info.specialties
            return ("「" + sps[0] + "」" + (f" 외 {len(sps) - 1}" if len(sps) > 1 else "") + f" {lv}개/턴") if sps else ""
        return ""

    def etc_placeholders(self, rid) -> dict:
        """기타 슬롯의 빈 칸마다 들어갈 건물(입지에 있는데 아직 없는 댐·원전·특산물 시설을 칸 순서대로)."""
        proj = self.projected_slots(rid).get("etc", [])
        have = {c["key"] for c in proj if c}
        missing = [k for k in S.etc_kinds(self.info(rid)) if k not in have]
        return {i: missing.pop(0) for i, c in enumerate(proj) if c is None and missing}

    def slot_summary(self, rid) -> list:
        """[(슬롯 종류, 칸 번호, 카드 또는 None)] 기본 → 하천 → 해안 → 기타 순.
        광역시 구성 지역은 기본·하천·해안이 중심의 광역 슬롯, 기타는 그 지역의 슬롯(v1.3.16)."""
        out = []
        for t in S.SLOT_TYPES:
            b = self.regions[M.slot_site(self, rid, t)].b
            out += [(t, i, c) for i, c in enumerate(b.slots.get(t, ()))]
        return out

    def slot_counts(self, rid) -> tuple:
        """(채운 칸, 전체 칸) — 광역시는 광역 슬롯 + 그 지역 기타 슬롯."""
        summ = self.slot_summary(rid)
        return sum(1 for _, _, c in summ if c), len(summ)

    def metro_slot_note(self, rid) -> str:
        m = M.merged(self, rid)
        if not m:
            return ""
        return f"{m['name']} 광역 슬롯: 기본·하천·해안 카드는 구성 지역 수만큼 산출합니다."
