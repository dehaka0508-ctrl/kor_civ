"""게임 엔진: 상태 보관, 명령 처리, 턴 종료 처리(기획서 3절 순서)."""
from __future__ import annotations

import math
import random
from collections import deque

from . import config as C
from . import diplomacy as D
from . import rules as R
from .data import DO8, load_world
from .leaders import LEADER_BY_KEY, GOV_BY_KEY, Mods, ai_pick_government, banned_govs, gov_similar
from .state import NEUTRAL, Army, Faction, Project, Region, Settings, BUILDING_NAMES

SUFFIXES = ("구역", "지구", "시", "군", "구")


def faction_name_from(short: str) -> str:
    for s in SUFFIXES:
        if short.endswith(s) and len(short) > len(s):
            return short[: -len(s)] + "국"
    return short + "국"


def initial_buildings(info) -> dict:
    """게임 시작 시점의 건물 단계(지역 자료 기준). 전장의 안개로 모르는 지역은 지도에 이 상태로 보인다."""
    b = {k: 0 for k in ("farm", "fishery", "factory", "bank", "power", "specialty",
                        "extract", "shelter", "aa", "academy", "airport", "port")}
    b.update(farm=info.farm, fishery=info.fishery, factory=info.factory, bank=info.bank)
    if info.is_coal:
        b["extract"] = info.coal          # 탄광: ① 1단계로 시작, ② 0단계(건설 가능)
    if info.power_source:
        b["power"] = 1                    # 현실 발전소(화력·원자력·수력) 소재지는 1단계로 시작
    if info.specialty:
        b["specialty"] = 1
    if info.start_port:
        b["port"] = 1
    return b


def unit_power(key: str) -> float:
    u = C.UNITS[key]
    return max(u.get("atk", 0), u.get("df", 0), u.get("bomb", 0) / 2)


class Game:
    def __init__(self, settings: Settings | None = None, world=None):
        self.settings = settings or Settings()
        self.world = world or load_world()
        self.rng = random.Random(self.settings.seed)
        self.turn = 1
        self.regions: dict[str, Region] = {}
        self.factions: list[Faction] = []
        self.armies: dict[int, Army] = {}
        self.next_army_id = 1
        self.dip = D.DiploState()
        self.events: list[dict] = []          # 이번 턴(직전 처리) 이벤트
        self.history: list[dict] = []         # 전체 로그(최근 것만 유지)
        self.battle_regions: list[str] = []
        self.pending_rebellions: list[str] = []   # 플레이어 대응 대기
        self.pending_proposals: list[dict] = []   # AI → 플레이어 제안
        self.dialogues: list[dict] = []           # 지도자 대사 팝업 대기 {kind, fid, turn}
        self.rankings: dict[int, list] = {}
        self.new_ranking = None
        self.power: dict[int, float] = {}
        self.hegemon = None
        self.hegemon_share = 0.0
        self.winner = None                     # (fids, victory key)
        self.game_over = False
        self.player_id = 0
        self._mods: dict[int, Mods] = {}
        self._morale: dict[int, float] = {}
        self._visible: dict[int, set] = {}
        self.setup_done = False
        self._init_world()

    # ------------------------------------------------------------------ 직렬화
    def __getstate__(self):
        s = dict(self.__dict__)
        s.pop("world", None)
        s.pop("_keyv", None)
        s["_mods"] = {}
        s["_morale"] = {}
        return s

    def __setstate__(self, s):
        self.__dict__.update(s)
        self.world = load_world()
        for r in self.regions.values():   # 이전 버전 세이브 호환
            for attr in ("spec_pin", "spec_block"):
                if not hasattr(r, attr):
                    setattr(r, attr, set())
            if "occ" in r.__dict__:            # 예전: 점령 하나만 저장
                old = r.__dict__.pop("occ")
                r.occs = {old["by"]: old} if old else {}
            for attr, v in (("resist", None), ("mil_hist", 0), ("conscript", 0.0), ("fuel_used", 0),
                            ("pop_focus", False), ("econ", None), ("lost_project", None)):
                if attr == "econ" and not hasattr(r, attr):
                    r.econ = set()
                    continue
                if not hasattr(r, attr):
                    setattr(r, attr, v)
            if not isinstance(getattr(r, "energy", None), dict):
                r.energy = {}
        for a in self.armies.values():
            if not hasattr(a, "goto"):
                a.goto = None
        for f in self.factions:
            if not hasattr(f, "spend"):
                f.spend, f.refund = {}, 0.0
            if not hasattr(f, "war_weary"):
                f.war_weary = 0.0
            if not hasattr(f, "war_weary_def"):
                f.war_weary_def = 0.0
            if hasattr(f, "war_weary_applied"):     # 예전 방식: 피로가 행복도에 섞여 있었다
                for r in self.regions.values():
                    if r.owner == f.id:
                        r.happy = min(C.HAPPY_MAX, r.happy + f.war_weary_applied)
                del f.war_weary_applied
            for attr, v in (("last_declare", -999), ("last_aggr_end", -999), ("warmonger", 0),
                            ("auto_energy", True), ("capital_fall_turn", -999), ("naval_off_until", 0)):
                if not hasattr(f, attr):
                    setattr(f, attr, v)
        self._morale = {}

    # ------------------------------------------------------------------ 초기화
    def _init_world(self):
        w = self.world
        for rid in w.order:
            info = w.regions[rid]
            b = initial_buildings(info)
            self.regions[rid] = Region(id=rid, owner=NEUTRAL, pop=info.pop0, b=b)
            self.new_army(NEUTRAL, rid, {"inf": 1})

        st = self.settings
        n_ai = max(1, min(9, st.n_enemies))
        leaders = [l["key"] for l in LEADER_BY_KEY.values() if l["key"] != "cus"]
        ai_leaders = list(st.ai_leaders or [])
        pool = [k for k in leaders if k != st.player_leader and k not in ai_leaders]
        self.rng.shuffle(pool)
        while len(ai_leaders) < n_ai:
            ai_leaders.append(pool.pop() if pool else self.rng.choice(leaders))

        starts = self._pick_starts(1 + n_ai, [st.player_start] + list(st.ai_starts or []))
        diff = C.DIFFICULTIES[st.difficulty]
        for i in range(1 + n_ai):
            is_player = i == 0
            lk = st.player_leader if is_player else ai_leaders[i - 1]
            leader = LEADER_BY_KEY[lk]
            rid = starts[i]
            name = st.player_name if is_player else faction_name_from(self.world.regions[rid].short)
            lname = (st.player_leader_name or leader["name"]) if is_player else leader["name"]
            f = Faction(id=i, name=name, color=C.FACTION_COLORS[i % len(C.FACTION_COLORS)], leader=lk,
                        leader_name=lname, gov=None, is_ai=(not is_player) or st.all_ai, capital=rid,
                        aggression=leader["aggr"])
            if not is_player:
                f.pop_mult, f.income_mult = diff[1], diff[2]
            else:
                f.flag = st.player_flag
            self.factions.append(f)
            self._give_start_region(f, rid)
        for f in self.factions:
            if f.is_ai:
                rr = self.regions[f.capital]
                f.gov = ai_pick_government(self.rng, f.aggression, rr.b["factory"], rr.b["bank"],
                                           banned=banned_govs(f.leader))
        if st.all_ai:
            self.finalize_setup()

    def _pick_starts(self, n, requested):
        """시작 수도: 직접 고른 곳은 그대로, 무작위 수도는 다른 모든 수도와 육상 최단 거리 START_MIN_DIST(6)칸 이상
        (5칸 안에 다른 수도 없음). 황해·강원 수도는 한 칸 더(6칸 안에 다른 수도 없음).
        무연륙 섬(제주·서귀포·울릉)은 무작위로 뽑지 않는다(직접 고를 때만).
        여러 번 섞어 보아도 안 되면(국가가 아주 많을 때) 거리를 1칸씩 줄인다."""
        chosen = []
        for rid in requested:
            if rid and rid in self.regions and rid not in chosen:
                chosen.append(rid)
        base = list(chosen)
        w = self.world
        cands = [r for r in w.order
                 if not (C.START_NO_RANDOM_ISLAND and w.regions[r].island == "무연륙 섬")]

        def need(a, b, d):
            return d + (1 if (w.regions[a].do8 in C.START_WIDE_DO8 or w.regions[b].do8 in C.START_WIDE_DO8) else 0)
        for min_d in range(C.START_MIN_DIST, 0, -1):
            for _ in range(C.START_PICK_TRIES):
                picked = list(base)
                self.rng.shuffle(cands)
                for rid in cands:
                    if len(picked) >= n:
                        break
                    if rid in picked:
                        continue
                    if all(self._land_dist(rid, c, need(rid, c, min_d)) >= need(rid, c, min_d) for c in picked):
                        picked.append(rid)
                if len(picked) >= n:
                    return picked[:n]
        return (base + [r for r in cands if r not in base])[:n]

    def _land_dist(self, a, b, cap):
        """육상 최단 거리(cap 이상이면 cap+1)."""
        dist = {a: 0}
        frontier = [a]
        for d in range(1, cap + 1):
            nxt = []
            for u in frontier:
                for v in self.world.land_adj[u]:
                    if v not in dist:
                        dist[v] = d
                        if v == b:
                            return d
                        nxt.append(v)
            frontier = nxt
        return 0 if a == b else cap + 1

    def _give_start_region(self, f: Faction, rid: str):
        r = self.regions[rid]
        r.owner = f.id
        for army in self.armies_at(rid):
            if army.owner == NEUTRAL:
                army.owner = f.id
        if self.world.regions[rid].island == "무연륙 섬":
            self.new_army(f.id, rid, {"lst": 1})
        f.res = {"food": r.pop * C.START_FOOD_TURNS, **C.START_RESOURCES}
        # 시작 도시는 모든 경계(육지 경계·해안선)에 방어선 1단계를 갖고 시작한다(반란국은 해당 없음)
        for n in list(self.world.land_adj[rid]) + (["coast"] if self.world.regions[rid].coastal else []):
            r.lines[n] = max(r.lines.get(n, 0), C.START_LINE_LEVEL)

    def finalize_setup(self):
        """정치체제 선택 후 호출: 시작 자금·우호도 적용."""
        for f in self.factions:
            if f.gov is None:
                f.gov = "philosopher" if not f.is_ai else "presidential"
        self._mods.clear()
        for f in self.factions:
            f.money = C.START_MONEY * C.MONEY_SCALE * self.mods(f.id).mult("start_money")
            self.regions[f.capital].pop *= self.mods(f.id).mult("start_pop")     # 온조왕 '십제'
        for a in self.factions:
            for b in self.factions:
                if a.id != b.id and a.is_ai:
                    self.dip.op[(a.id, b.id)] = self.mods(b.id).add("start_opinion") + D.op_baseline(self, a.id, b.id)
        for r in self.regions.values():
            r.output = self.calc_output(r.id, full=True)
            r.food = R.food_output(r.b["farm"], r.b["fishery"])
        for f in self.factions:
            regs = self.regions_of(f.id)
            gdp = sum(r.output for r in regs)
            f.last = {"gdp": gdp, "tax": gdp * f.tax * f.income_mult, "upkeep": self.upkeep(f.id), "net": 0,
                      "food_prod": sum(r.food for r in regs), "food_cons": sum(r.pop for r in regs)}
        self._update_power()
        self._update_fog(initial=True)
        for f in self.factions:
            if not f.is_ai:
                self.assign_energy(f.id)          # 플레이어: 시작 배정을 한 번 해 둔다(이후는 [자동 배정] 명령)
        self.setup_done = True

    def set_player_government(self, gov_key: str):
        if gov_key in banned_govs(self.player.leader):
            gov_key = "philosopher"              # 고를 수 없는 체제(홍길동 '적서차별')
        self.factions[self.player_id].gov = gov_key
        self._mods.pop(self.player_id, None)
        self.finalize_setup()

    # ------------------------------------------------------------------ 기본 조회
    @property
    def player(self) -> Faction:
        return self.factions[self.player_id]

    def mods(self, fid) -> Mods:
        if fid == NEUTRAL:
            return Mods("cus", None)
        m = self._mods.get(fid)
        if m is None:
            f = self.factions[fid]
            m = self._mods[fid] = Mods(f.leader, f.gov)
        return m

    def fname(self, fid) -> str:
        return "중립" if fid == NEUTRAL else self.factions[fid].name

    UNKNOWN_NAME, UNKNOWN_LEADER = "미지의 국가", "수수께끼의 지도자"

    def has_met(self, viewer, fid) -> bool:
        """viewer 가 fid 세력과 조우했는가(전장의 안개가 없으면 항상 참)."""
        if self.settings.fog == 0 or fid == viewer or fid == NEUTRAL or fid is None:
            return True
        return fid in getattr(self.factions[viewer], "met", set())

    def knows_name(self, viewer, fid) -> bool:
        """세력 이름·수도를 아는가: 안개 '없음'·'지도 공개'는 처음부터, '미탐색'은 조우해야 안다."""
        return self.settings.fog <= 1 or self.has_met(viewer, fid)

    def seen_name(self, fid, viewer=None) -> str:
        """플레이어(또는 viewer)에게 보이는 세력 이름: 이름을 모르면 '미지의 국가'."""
        viewer = self.player_id if viewer is None else viewer
        return self.fname(fid) if self.knows_name(viewer, fid) else self.UNKNOWN_NAME

    def event_for_player(self, e):
        """플레이어에게 보여 줄 이벤트 문장(없으면 None). 조우하지 않은 세력 이름은 '미지의 국가'로 가리고,
        플레이어와 상관없는 사건에 모르는 세력이 끼어 있으면 아예 감춘다(승리·반기 랭킹 제외)."""
        pid = self.player_id
        involved = [f for f in e["fids"] if f is not None and f != NEUTRAL and 0 <= f < len(self.factions)]
        if any(not self.has_met(pid, f) for f in involved) and pid not in e["fids"] \
                and e["kind"] not in ("victory", "ranking", "alert"):
            return None                         # 조우하지 않은 세력들의 일은 모른다
        unknown = [f for f in involved if not self.knows_name(pid, f)]
        text = e["text"]
        for f in sorted(unknown, key=lambda x: -len(self.factions[x].name)):
            text = text.replace(self.factions[f].name, self.UNKNOWN_NAME)
            text = text.replace(self.factions[f].leader_name, self.UNKNOWN_LEADER)
        return text

    def seen_leader(self, fid, viewer=None) -> str:
        viewer = self.player_id if viewer is None else viewer
        return self.factions[fid].leader_name if self.has_met(viewer, fid) else self.UNKNOWN_LEADER

    def alive_ids(self):
        return [f.id for f in self.factions if f.alive]

    def regions_of(self, fid):
        return [r for r in self.regions.values() if r.owner == fid]

    def region_count(self, fid) -> int:
        return sum(1 for r in self.regions.values() if r.owner == fid)

    def info(self, rid):
        return self.world.regions[rid]

    def event(self, kind, text, region=None, fids=()):
        e = {"turn": self.turn, "kind": kind, "text": text, "region": region, "fids": tuple(fids)}
        self.events.append(e)
        self.history.append(e)
        if len(self.history) > 800:
            del self.history[:200]

    def date_label(self):
        return R.date_label(self.turn)

    # ------------------------------------------------------------------ 부대
    def new_army(self, owner, loc, units) -> Army:
        a = Army(self.next_army_id, owner, loc, {k: v for k, v in units.items() if v > 0}, {})
        self.armies[a.id] = a
        self.next_army_id += 1
        return a

    def armies_at(self, loc, owner=None):
        return [a for a in self.armies.values()
                if a.loc == loc and (owner is None or a.owner == owner)]

    @staticmethod
    def _add_to_army(army, key, n):
        """유닛을 더한다. 그 종류가 없던 부대면 예전에 남은 피해 기록을 지워 새 유닛이 다친 채로 오지 않게 한다."""
        if army.units.get(key, 0) <= 0:
            army.dmg.pop(key, None)
        army.units[key] = army.units.get(key, 0) + n

    def _prune_army(self, army):
        """수량 0인 유닛 항목과 그 피해 기록을 지우고, 비면 부대를 없앤다."""
        army.units = {k: v for k, v in army.units.items() if v > 0}
        army.dmg = {k: min(d, army.hp_max(k)) for k, d in army.dmg.items() if k in army.units}
        if not army.units and army.id in self.armies:
            self.remove_army(army)

    def remove_army(self, army):
        self.armies.pop(army.id, None)

    def hostile(self, fid, other) -> bool:
        if other == fid:
            return False
        if other == NEUTRAL or fid == NEUTRAL:
            return True
        return D.at_war(self, fid, other)

    def hostile_units_at(self, fid, loc):
        return [a for a in self.armies_at(loc) if a.owner != fid and self.hostile(fid, a.owner)
                and not a.empty()]

    def friendly_territory(self, fid, rid) -> bool:
        o = self.regions[rid].owner
        return o == fid or (o != NEUTRAL and D.same_coalition(self, fid, o))

    @staticmethod
    def is_science_army(a) -> bool:
        return any(a.units.get(k) for k in C.SCIENCE_UNITS)

    def add_units(self, fid, loc, key, n=1) -> Army:
        kind = C.UNITS[key]["kind"]
        sci = bool(C.UNITS[key].get("science"))
        for a in self.armies_at(loc, fid):
            if a.domain() == kind and not a.order and self.is_science_army(a) == sci:
                self._add_to_army(a, key, n)
                return a
        return self.new_army(fid, loc, {key: n})

    def mil_power(self, fid) -> float:
        return sum(unit_power(k) * n for a in self.armies.values() if a.owner == fid
                   for k, n in a.units.items())

    def army_power(self, army) -> float:
        return sum(unit_power(k) * n for k, n in army.units.items())

    def teleport_home(self, army):
        """가장 가까운 자국 영토로 이동, 없으면 해산."""
        fid = army.owner
        start = army.loc
        seen = {start}
        q = deque([start])
        while q:
            u = q.popleft()
            if not self.world.is_sea(u) and self.regions[u].owner == fid:
                if army.domain() == "naval" and not self.regions[u].b["port"]:
                    pass
                else:
                    army.loc = u
                    army.order = None
                    return
            for v in self.world.node_neighbors(u):
                if v not in seen:
                    seen.add(v)
                    q.append(v)
        self.remove_army(army)

    def split_army(self, army_id, units: dict):
        a = self.armies.get(army_id)
        if not a:
            return None, "부대가 없습니다."
        take = {k: min(v, a.units.get(k, 0)) for k, v in units.items() if v > 0}
        if not take or sum(take.values()) >= a.count():
            return None, "분리할 유닛을 고르세요(전부는 불가)."
        moved_dmg = {}
        for k, v in take.items():
            moved_dmg[k] = self._split_dmg(a, k, v)
            a.units[k] -= v
        a.units = {k: v for k, v in a.units.items() if v > 0}
        a.dmg = {k: d for k, d in a.dmg.items() if k in a.units and d > 0}
        b = self.new_army(a.owner, a.loc, take)
        b.dmg = {k: d for k, d in moved_dmg.items() if d > 0}
        self._validate_capacity(a)
        return b, ""

    @staticmethod
    def _split_dmg(a, k, v) -> float:
        """유닛 k 를 v 개 떼어 낼 때 남은 체력을 수에 비례해 정수로 나눈다(떼어 내는 쪽 내림).
        예: 3개 체력 16/30 에서 1개 → 5/10, 남는 2개 11/20. 떼어 내는 쪽이 가져갈 누적 피해를 반환."""
        n = a.units.get(k, 0)
        hp = C.UNITS[k]["hp"]
        left = int(round(a.hp_left(k)))
        part = left * v // n if n else 0
        rest = left - part
        a.dmg[k] = (n - v) * hp - rest
        return v * hp - part

    def merge_armies(self, a_id, b_id):
        a, b = self.armies.get(a_id), self.armies.get(b_id)
        if not a or not b or a.id == b.id:
            return False, "합칠 부대가 없습니다."
        if a.loc != b.loc or a.owner != b.owner:
            return False, "같은 위치의 내 부대만 합칠 수 있습니다."
        merged = dict(a.units)
        for k, v in b.units.items():
            merged[k] = merged.get(k, 0) + v
        test = Army(0, a.owner, a.loc, merged)
        kinds = test.kinds()
        if "naval" in kinds:
            if test.cargo_used() > test.cargo_cap():
                return False, f"상륙함 수송 칸이 부족합니다(보병1·포병2·전차4, 상륙함당 {C.UNITS['lst']['capacity']})."
            if test.air_used() > test.air_cap() and self.world.is_sea(a.loc):
                return False, f"항공모함 탑재 칸이 부족합니다(항모당 {C.UNITS['cv']['air_capacity']})."
            if test.air_used() > test.air_cap():
                return False, "항공기는 항공모함 탑재 칸만큼만 합칠 수 있습니다."
        elif "air" in kinds and "land" in kinds:
            return False, "공군과 육군은 합칠 수 없습니다."
        a.units = merged
        for k, v in b.dmg.items():
            a.dmg[k] = a.dmg.get(k, 0) + v
        a.order = None
        self.remove_army(b)
        return True, ""

    def boarding_target(self, army_id):
        """[탑승] 대상: 같은 지역에 주둔한 내 함대. 육군은 상륙함이, 공군은 항공모함이 있는 함대."""
        a = self.armies.get(army_id)
        if not a or self.world.is_sea(a.loc):
            return None
        dom = a.domain()
        need = {"land": "lst", "air": "cv"}.get(dom)
        if need is None:
            return None
        for f in self.armies_at(a.loc, a.owner):
            if f.id != a.id and f.domain() == "naval" and f.units.get(need):
                return f
        return None

    def board(self, army_id):
        """육군을 상륙함에, 공군을 항공모함에 태운다(같은 지역의 함대와 합침). (성공, 메시지, 함대)"""
        f = self.boarding_target(army_id)
        if f is None:
            return False, "태울 함대가 없습니다.", None
        ok, msg = self.merge_armies(f.id, army_id)
        return ok, (msg or "탑승 완료"), f

    def disband(self, army_id, units: dict):
        a = self.armies.get(army_id)
        if not a:
            return False, "부대가 없습니다."
        in_own = not self.world.is_sea(a.loc) and self.regions[a.loc].owner == a.owner
        for k, v in units.items():
            v = min(v, a.units.get(k, 0))
            if v <= 0:
                continue
            self._split_dmg(a, k, v)
            a.units[k] -= v
            if in_own:
                self.regions[a.loc].h_delta += C.UNIT_DISBAND_HAPPY[C.UNITS[k]["weight"]] * v
        a.units = {k: v for k, v in a.units.items() if v > 0}
        a.dmg = {k: d for k, d in a.dmg.items() if k in a.units and d > 0}
        if a.empty():
            self.remove_army(a)
        return True, ""

    def _validate_capacity(self, a):
        if a.domain() != "naval":
            return
        while a.cargo_used() > a.cargo_cap():
            for k in ("tank", "art", "inf"):
                if a.units.get(k, 0) > 0:
                    a.units[k] -= 1
                    break
            else:
                break
        while a.air_used() > a.air_cap():
            for k in ("bmb", "ftr"):
                if a.units.get(k, 0) > 0:
                    a.units[k] -= 1
                    break
            else:
                break
        a.units = {k: v for k, v in a.units.items() if v > 0}

    # ------------------------------------------------------------------ 이동 범위
    def can_attack_now(self, fid, target_owner) -> bool:
        if target_owner == NEUTRAL:
            return True
        until = self.dip.no_attack_until.get((fid, target_owner))
        return until is None or self.turn >= until

    def reachable(self, army) -> dict:
        """node -> {"action": move/attack/land/bombard, "path": [...], "strong": bool}"""
        out = {}
        fid = army.owner
        dom = army.domain()
        w = self.world
        if dom == "land" and not w.is_sea(army.loc):
            if army.count(("land",)) == 0:
                return out
            start = army.loc
            # 자국(연합) 영토만 지나는 2칸
            if self.friendly_territory(fid, start) or True:
                frontier = [(start, [])]
                seen = {start}
                for _ in range(C.LAND_STEPS_OWN):
                    nxt = []
                    for u, path in frontier:
                        if not self.friendly_territory(fid, u):
                            continue
                        for v in w.land_adj[u]:
                            if v in seen or not self.friendly_territory(fid, v):
                                continue
                            if self.hostile_units_at(fid, v):
                                continue
                            seen.add(v)
                            out[v] = {"action": "move", "path": path + [v], "strong": True}
                            nxt.append((v, path + [v]))
                    frontier = nxt
            for v in w.land_adj[start]:
                if v in out:
                    continue
                o = self.regions[v].owner
                hostile_units = self.hostile_units_at(fid, v)
                if o == fid or (o != NEUTRAL and not self.hostile(fid, o) and D.has_passage(self, fid, o)):
                    if hostile_units:
                        if self.can_attack_now(fid, hostile_units[0].owner):
                            out[v] = {"action": "attack", "path": [v], "strong": False}
                    else:
                        out[v] = {"action": "move", "path": [v], "strong": False}
                elif self.hostile(fid, o):
                    if not self.can_attack_now(fid, o):
                        continue
                    out[v] = {"action": "attack" if hostile_units else "move", "path": [v], "strong": False}
            if army.units.get("art"):
                for v in self.land_within(start, C.ART_RANGE):
                    if self.hostile(fid, self.regions[v].owner) and v not in out:
                        out[v] = {"action": "bombard", "path": [], "strong": False}
        elif dom == "naval":
            has_cargo = army.count(("land",)) > 0
            start = army.loc
            frontier = [(start, [])]
            seen = {start}
            for step in range(C.NAVAL_STEPS):
                nxt = []
                for u, path in frontier:
                    if w.is_sea(u):
                        nbrs = list(w.seas[u].adj) + list(w.seas[u].coast)
                    else:
                        nbrs = list(w.regions[u].seas)
                    for v in nbrs:
                        if v in seen:
                            continue
                        if w.is_sea(v):
                            seen.add(v)
                            out[v] = {"action": "move", "path": path + [v], "strong": True}
                            nxt.append((v, path + [v]))
                            continue
                        if not w.is_sea(u):
                            continue
                        rr = self.regions[v]
                        if rr.owner == fid and rr.b["port"]:
                            out[v] = {"action": "move", "path": path + [v], "strong": True}
                            seen.add(v)
                        elif has_cargo:
                            hostile_owner = self.hostile(fid, rr.owner)
                            if hostile_owner or self.hostile_units_at(fid, v):
                                tgt_owner = rr.owner
                                if self.can_attack_now(fid, tgt_owner):
                                    out[v] = {"action": "attack", "path": path, "strong": False}
                                    seen.add(v)
                            elif rr.owner == fid or D.has_passage(self, fid, rr.owner):
                                out[v] = {"action": "land", "path": path, "strong": False}
                                seen.add(v)
                frontier = nxt
            if army.units.get("dd") and w.is_sea(start):
                for v in w.distances_from(start, C.NAVAL_BOMB_RANGE):
                    if not w.is_sea(v) and self.hostile(fid, self.regions[v].owner) \
                            and out.get(v, {}).get("action") != "attack":
                        out.setdefault(v, {"action": "bombard", "path": [], "strong": False})
            if army.units.get("bmb") and army.units.get("cv"):
                for v, d in w.distances_from(start, C.BOMB_RANGE).items():
                    if not w.is_sea(v) and self.hostile(fid, self.regions[v].owner) and v not in out:
                        out[v] = {"action": "bombard", "path": [], "strong": False}
        elif dom == "air":
            if w.is_sea(army.loc):
                return out
            dist = w.distances_from(army.loc, C.AIR_RANGE)
            for v, d in dist.items():
                if v == army.loc or w.is_sea(v):
                    continue
                rr = self.regions[v]
                if rr.owner == fid and rr.b["airport"]:
                    out[v] = {"action": "move", "path": [v], "strong": True}
                elif army.units.get("bmb") and d <= C.BOMB_RANGE and self.hostile(fid, rr.owner):
                    out[v] = {"action": "bombard", "path": [], "strong": False}
        if any(army.units.get(k) for k in C.SCIENCE_UNITS):
            # 과학승리 유닛은 싸우거나 남의 땅을 차지할 수 없다: 자국(연합) 영토로의 이동·상륙만
            out = {v: o for v, o in out.items() if o["action"] in ("move", "land")
                   and (w.is_sea(v) or self.friendly_territory(fid, v))}
        return out

    def order_army(self, army_id, target, mode="assault", force_bombard=False):
        a = self.armies.get(army_id)
        if not a or a.owner == NEUTRAL:
            return False, "부대가 없습니다."
        a.goto = None
        if target is None:
            a.order = None
            return True, "명령 취소"
        reach = self.reachable(a)
        if not force_bombard and target not in reach and target != a.loc:
            # 한 턴에 못 가는 곳: 최단 경로로 여러 턴에 걸쳐 자동 이동
            route = self.plan_route(a, target)
            if not route:
                return False, "갈 수 있는 경로가 없습니다."
            a.goto = target
            if not self._goto_step(a):
                a.goto = None
                return False, "이번 턴에 경로를 따라 움직일 수 없습니다."
            return True, f"자동 이동: {self.world.node_name(target)}까지 {len(route)}칸"
        if force_bombard:
            if not self._can_bombard(a, target):
                return False, "폭격할 수 없는 대상입니다."
            a.order = {"type": "bombard", "target": target}
            return True, "폭격 명령"
        opt = reach.get(target)
        if not opt:
            return False, "이번 턴에 갈 수 없는 곳입니다."
        act = opt["action"]
        if act == "bombard":
            a.order = {"type": "bombard", "target": target}
        elif act == "attack":
            if mode == "surprise" and (not any(a.units.get(k) for k in C.SURPRISE_UNITS)
                                       or self.mods(a.owner).value("no_surprise")):
                mode = "assault"                 # 기습할 유닛이 없거나 강감찬 '문신의 신중함'이면 돌격
            a.order = {"type": "attack", "target": target, "mode": mode, "path": opt["path"]}
        elif act == "land":
            a.order = {"type": "land", "target": target, "path": opt["path"]}
        else:
            a.order = {"type": "move", "path": opt["path"]}
        return True, {"move": "이동", "attack": "공격", "land": "상륙", "bombard": "폭격"}[act] + " 명령"

    # ---- 여러 턴 자동 이동
    def plan_route(self, army, target):
        """army 위치에서 target까지 최단 경로(시작 제외). 중간 지점은 지나갈 수 있는 곳만."""
        w = self.world
        fid = army.owner
        dom = army.domain()
        start = army.loc
        if target == start or (target not in self.regions and not w.is_sea(target)):
            return None

        sci = self.is_science_army(army)

        def passable(v):
            if w.is_sea(v) or self.hostile_units_at(fid, v):
                return False
            o = self.regions[v].owner
            return self.friendly_territory(fid, v) or (not sci and o != NEUTRAL and not self.hostile(fid, o)
                                                        and D.has_passage(self, fid, o))

        if dom == "land":
            if w.is_sea(start) or w.is_sea(target):
                return None

            def nbrs(u):
                return w.land_adj[u]
            ok_mid = passable
        elif dom == "naval":
            if not w.is_sea(target):
                rr = self.regions[target]
                if not (rr.owner == fid and rr.b["port"]) and army.count(("land",)) == 0:
                    return None

            def nbrs(u):
                if w.is_sea(u):
                    return list(w.seas[u].adj) + list(w.seas[u].coast)
                return list(w.regions[u].seas)

            def ok_mid(v):
                return w.is_sea(v)
        elif dom == "air":
            if w.is_sea(target) or w.is_sea(start):
                return None
            bases = {r for r, rr in self.regions.items() if rr.owner == fid and rr.b["airport"]}

            def nbrs(u):
                return [v for v in w.distances_from(u, C.AIR_RANGE) if v in bases or v == target]

            def ok_mid(v):
                return v in bases
        else:
            return None
        prev = {start: None}
        q = deque([start])
        while q:
            u = q.popleft()
            if u == target:
                break
            if u != start and not ok_mid(u):
                continue
            for v in nbrs(u):
                if v not in prev:
                    prev[v] = u
                    q.append(v)
        if target not in prev:
            return None
        path = []
        u = target
        while u != start:
            path.append(u)
            u = prev[u]
        return path[::-1]

    def _goto_step(self, a) -> bool:
        """자동 이동 중인 부대에 이번 턴 명령을 준다. 못 움직이면 False."""
        tgt = a.goto
        if not tgt or a.loc == tgt:
            a.goto = None
            return False
        route = self.plan_route(a, tgt)
        if not route:
            return False
        reach = self.reachable(a)
        for node in reversed(route):
            opt = reach.get(node)
            if not opt:
                continue
            if node == tgt and opt["action"] != "bombard":
                if opt["action"] == "attack":
                    a.order = {"type": "attack", "target": node, "mode": "assault", "path": opt["path"]}
                elif opt["action"] == "land":
                    a.order = {"type": "land", "target": node, "path": opt["path"]}
                else:
                    a.order = {"type": "move", "path": opt["path"]}
                a.goto = None          # 마지막 구간
                return True
            if opt["action"] == "move":
                a.order = {"type": "move", "path": opt["path"]}
                return True
        return False

    def _advance_gotos(self):
        for a in list(self.armies.values()):
            if not getattr(a, "goto", None) or a.order:
                continue
            if a.loc == a.goto:
                a.goto = None
                continue
            if not self._goto_step(a):
                if a.owner == self.player_id:
                    self.event("info", f"{self.world.node_name(a.loc)}의 부대: "
                               f"{self.world.node_name(a.goto)}까지 가는 길이 막혀 자동 이동을 멈춥니다.",
                               region=a.loc, fids=(a.owner,))
                a.goto = None

    def land_within(self, rid, k) -> set:
        """육상으로 k칸 이내 지역(자기 제외)."""
        seen, frontier = {rid}, {rid}
        for _ in range(k):
            frontier = {v for u in frontier for v in self.world.land_adj[u]} - seen
            seen |= frontier
        seen.discard(rid)
        return seen

    def _can_bombard(self, a, target):
        if self.world.is_sea(target) or not self.hostile(a.owner, self.regions[target].owner):
            return False
        return self._bombard_units(a, target) != {}

    def _bombard_units(self, a, target):
        w = self.world
        out = {}
        if a.units.get("art") and not w.is_sea(a.loc) and target in self.land_within(a.loc, C.ART_RANGE):
            out["art"] = a.units["art"]
        if a.units.get("dd") and w.is_sea(a.loc) and w.distances_from(a.loc, C.NAVAL_BOMB_RANGE).get(target):
            out["dd"] = a.units["dd"]
        if a.units.get("bmb"):
            base_ok = (not w.is_sea(a.loc) and self.regions[a.loc].b["airport"]
                       and self.regions[a.loc].owner == a.owner) or a.units.get("cv")
            if base_ok and w.distances_from(a.loc, C.BOMB_RANGE).get(target) is not None:
                out["bmb"] = a.units["bmb"]
        return out

    # ------------------------------------------------------------------ 전투 예측
    def air_support(self, fid, target, attack=True):
        """전투기 지상전 지원: target 에서 육상 2칸 이내 fid 소유 공항에 주둔한 전투기(target 자체 제외).
        (지원 전력, 전투기 부대 목록)"""
        if fid == NEUTRAL:
            return 0.0, []
        w = self.world
        near = {target}
        frontier = {target}
        for _ in range(C.FTR_SUPPORT_RANGE):
            frontier = {v for u in frontier for v in w.land_adj[u]} - near
            near |= frontier
        near.discard(target)
        arms = [a for a in self.armies.values() if a.owner == fid and a.units.get("ftr") and a.loc in near
                and not w.is_sea(a.loc) and self.regions[a.loc].owner == fid and self.regions[a.loc].b["airport"]]
        per = C.FTR_SUPPORT_ATK if attack else C.FTR_SUPPORT_DEF
        return per * sum(a.units["ftr"] for a in arms), arms

    def amphib_mult(self, fid) -> float:
        """상륙 돌격 배수: 기본 ×0.8(근초고왕·쿠빌라이 보정), 맥아더 '인천상륙작전'은 감소 없이 +20%."""
        m = self.mods(fid)
        base = 1.0 if m.value("amphib_free") else C.AMPHIBIOUS * m.value("amphib_extra", 1.0)
        return base * m.mult("amphib_atk")

    def inf_wave_on(self, fid, armies) -> bool:
        """마오쩌둥 '국공내전': 이 돌격에 보병을 10 이상 투입했는가."""
        return (self.mods(fid).mult("inf_wave") != 1.0
                and sum(a.units.get("inf", 0) for a in armies) >= C.INF_WAVE_MIN)

    def combat_strength(self, fid, armies, target, mode="assault"):
        """공격력 A 와 주 공격 경로를 계산."""
        w = self.world
        m = self.mods(fid)
        tgt_owner = self.regions[target].owner
        mult = self.morale(fid)                  # 사기: 실질 평균 행복도 −10 이하면 감소
        if tgt_owner != NEUTRAL and any(self.regions[target].lines.values()):
            mult *= m.mult("atk_vs_line")        # 당 태종 '안시성': 방어선이 있는 지역
        if self.retake_bonus(fid, target):
            mult *= 1 + C.RESIST_RETAKE_ATK      # 저항 중인 옛 영토를 되찾는 공격
        if self.multi_attack_on(fid, target):
            mult *= m.mult("multi_attack")      # 홍길동 '신출귀몰': 한 국가의 두 지역 이상 동시 공격
        if mode == "assault" and self.inf_wave_on(fid, armies):
            mult *= m.mult("inf_wave")          # 마오쩌둥 '국공내전': 보병 10 이상 돌격
        total = 0.0
        contrib = {}
        sources = set()
        for a in armies:
            amph = w.is_sea(a.loc)
            val = 0.0
            for k, n in a.units.items():
                if k not in (C.SURPRISE_UNITS if mode == "surprise" else C.ASSAULT_UNITS):
                    continue
                atk = C.UNITS[k]["atk"] * n
                if k == "inf":
                    atk *= m.mult("atk_inf")
                val += atk
            if not amph:
                terr = w.terrain_between(a.loc, target)
                if terr:
                    val *= terr["mult"]          # 도하·산악 돌파
                elif w.is_bridge(a.loc, target):
                    val *= C.BRIDGE_ATTACK_MULT
            if mode == "assault":
                val *= m.mult("atk_assault")
                if amph:
                    val *= self.amphib_mult(fid)
            if tgt_owner != NEUTRAL and D.at_war(self, fid, tgt_owner):
                allies_in = any(D.allied(self, fid, x) and D.at_war(self, x, tgt_owner)
                                for x in self.alive_ids() if x != fid)
                if allies_in:
                    val *= m.mult("ally_war_atk")
                elif mode == "assault":
                    val *= m.mult("no_ally_assault")
            val *= mult
            total += val
            src = "coast" if amph else a.loc
            contrib[src] = contrib.get(src, 0) + val
            sources.add(a.loc)
        main_src = max(contrib, key=contrib.get) if contrib else None
        if armies:
            total += self.air_support(fid, target, True)[0] * mult      # 근처 공항 전투기 지원
        return total, sources, main_src

    def defense_strength(self, fid_att, target, main_src, mode):
        defenders = self.hostile_units_at(fid_att, target)
        rr = self.regions[target]
        dsum = sum(C.UNITS[k]["df"] * n * self.morale(a.owner) for a in defenders for k, n in a.units.items())
        if rr.owner != NEUTRAL and defenders and self.hostile(fid_att, rr.owner):
            dsum += self.air_support(rr.owner, target, False)[0] * self.morale(rr.owner)   # 근처 공항 전투기 방어 지원
        line_level = rr.lines.get(main_src, 0) if main_src else 0
        if rr.owner != NEUTRAL and mode == "assault":
            k = self.mods(rr.owner).value("line_k", C.LINE_BONUS)
            dsum *= 1 + k * line_level
        if rr.owner != NEUTRAL and self.region_count(rr.owner) <= 3:
            dsum *= self.mods(rr.owner).mult("defense_small")
        if rr.owner != NEUTRAL and self.info(target).coastal:
            dsum *= self.mods(rr.owner).mult("def_coast")      # 이순신: 해안 지역 방어
        if self.ambushed(rr.owner, fid_att):
            dsum *= 1 - self.mods(rr.owner).value("ambushed_def")   # 선덕여왕 '대야성 함락'
        return dsum, defenders, line_level

    def ambushed(self, fid, attacker) -> bool:
        """선덕여왕 '대야성 함락': attacker 의 선전포고를 받은 지 4턴이 안 됐다."""
        if fid == NEUTRAL or not self.mods(fid).value("ambushed_def"):
            return False
        w = self.dip.wars.get(D.pair(fid, attacker))
        return bool(w) and w.get("aggressor") == attacker and self.turn - w["start"] < C.AMBUSH_TURNS

    def fx_source(self, fid, key) -> str:
        """효과 key 를 주는 지도자 버프/디버프 또는 정치체제 이름."""
        f = self.factions[fid]
        lead = LEADER_BY_KEY.get(f.leader, {})
        fx = lead.get("fx", {})
        if key in fx:
            dkeys = lead["dkeys"] if "dkeys" in lead else [list(fx)[-1]]
            nm = lead["debuff"][0] if key in dkeys else lead["buff"][0]
            return f"{lead['name']} '{nm}'"
        gov = GOV_BY_KEY.get(f.gov or "", {})
        if key in gov.get("fx", {}):
            return gov["name"]
        return "효과"

    def battle_breakdown(self, army, target, mode="assault"):
        """전투 확인 창용: 양측 병력, 적용되는 보정(이름, 배수), 예상 결과."""
        w = self.world
        fid = army.owner
        m = self.mods(fid)
        rr = self.regions[target]
        pv = self.preview_attack(army, target, mode)
        if pv is None:
            return None
        allowed = C.SURPRISE_UNITS if mode == "surprise" else C.ASSAULT_UNITS
        att_units = {k: n for k, n in army.units.items() if k in allowed and n > 0}
        defenders = self.hostile_units_at(fid, target)
        def_units = {}
        for a in defenders:
            d = def_units.setdefault(a.owner, {})
            for k, n in a.units.items():
                d[k] = d.get(k, 0) + n
        af, df = [], []

        def add(lst, label, mult):
            if abs(mult - 1.0) >= 0.005:
                lst.append((label, mult))
        amph = w.is_sea(army.loc)
        if not amph:
            terr = w.terrain_between(army.loc, target)
            if terr:
                add(af, f"{terr['kind']}({terr['name']})", terr["mult"])
        if att_units.get("inf"):
            add(af, self.fx_source(fid, "atk_inf") + " — 보병", m.mult("atk_inf"))
        if mode == "assault":
            add(af, self.fx_source(fid, "atk_assault"), m.mult("atk_assault"))
            if amph:
                add(af, "상륙 돌격", self.amphib_mult(fid))
            if self.inf_wave_on(fid, [army]):
                add(af, self.fx_source(fid, "inf_wave"), m.mult("inf_wave"))
        if rr.owner != NEUTRAL and D.at_war(self, fid, rr.owner):
            allies_in = any(D.allied(self, fid, x) and D.at_war(self, x, rr.owner)
                            for x in self.alive_ids() if x != fid)
            if allies_in:
                add(af, self.fx_source(fid, "ally_war_atk"), m.mult("ally_war_atk"))
            elif mode == "assault":
                add(af, self.fx_source(fid, "no_ally_assault"), m.mult("no_ally_assault"))
        add(af, "사기(실질 행복도 낮음)", self.morale(fid))
        if rr.owner != NEUTRAL and any(rr.lines.values()):
            add(af, self.fx_source(fid, "atk_vs_line"), m.mult("atk_vs_line"))
        ap, aa = self.air_support(fid, target, True)
        if ap:
            af.append((f"전투기 {sum(x.units['ftr'] for x in aa)}대 지원 (+{ap:.0f})", 1 + ap / max(1.0, pv["A"] - ap)))
        if self.retake_bonus(fid, target):
            add(af, "저항 중인 옛 영토 탈환", 1 + C.RESIST_RETAKE_ATK)
        if self.multi_attack_on(fid, target):
            add(af, self.fx_source(fid, "multi_attack"), m.mult("multi_attack"))
        line = pv["line"]
        if rr.owner != NEUTRAL:
            om = self.mods(rr.owner)
            if mode == "assault" and line:
                k = om.value("line_k", C.LINE_BONUS)
                add(df, f"방어선 {line}단계", 1 + k * line)
            if self.region_count(rr.owner) <= 3:
                add(df, self.fx_source(rr.owner, "defense_small"), om.mult("defense_small"))
            if self.info(target).coastal:
                add(df, self.fx_source(rr.owner, "def_coast"), om.mult("def_coast"))
            if self.ambushed(rr.owner, fid):
                add(df, self.fx_source(rr.owner, "ambushed_def"), 1 - om.value("ambushed_def"))
        for o in def_units:
            add(df, f"{self.fname(o)} 사기", self.morale(o))
        if rr.owner != NEUTRAL:
            dp, da = self.air_support(rr.owner, target, False)
            if dp:
                df.append((f"전투기 {sum(x.units['ftr'] for x in da)}대 지원 (+{dp:.0f})", 1 + dp / max(1.0, pv["D"] - dp)))

        def losses(units_by_army, dmg, order=None):
            pool = [(k, n) for k, n in units_by_army.items() if n > 0]
            total = sum(C.UNITS[k]["hp"] * n for k, n in pool)
            out = {}
            if total <= 0:
                return out
            if order is not None:            # 방어측: 전차 > 보병 > 포병 > 공군 순서로
                rank = {k: i for i, k in enumerate(order)}
                left = dmg
                for k, n in sorted(pool, key=lambda x: rank.get(x[0], len(order))):
                    dead = min(n, int(left // C.UNITS[k]["hp"]))
                    if dead:
                        out[k] = dead
                    left -= min(left, C.UNITS[k]["hp"] * n)
                    if left <= 0:
                        break
                return out
            for k, n in pool:
                share = dmg * C.UNITS[k]["hp"] * n / total
                dead = min(n, int(share // C.UNITS[k]["hp"]))
                if dead:
                    out[k] = dead
            return out
        all_def = {}
        for d in def_units.values():
            for k, n in d.items():
                all_def[k] = all_def.get(k, 0) + n
        outcomes = []
        if mode == "surprise":
            p = pv["surprise_p"]
            outcomes.append((f"기습 성공({p * 100:.0f}%)", pv["def_dmg_win"], pv["att_dmg_win"]))
            outcomes.append((f"기습 실패({(1 - p) * 100:.0f}%)", pv["def_dmg_fail"], pv["att_dmg_fail"]))
        else:
            outcomes.append(("예상", pv["def_dmg"], pv["att_dmg"]))
        res = []
        for label, dd, ad in outcomes:
            res.append({"label": label, "def_dmg": dd, "att_dmg": ad, "def_lost": losses(all_def, dd, C.ASSAULT_DAMAGE_ORDER if mode == "assault" else None),
                        "att_lost": losses(att_units, ad), "capture": dd >= pv["def_hp"] * 0.95})
        return {"preview": pv, "att_units": att_units, "def_units": def_units, "att_factors": af,
                "def_factors": df, "outcomes": res, "target_owner": rr.owner}

    def preview_attack(self, army, target, mode="assault"):
        """예상 교전 결과(r=1). 반환 dict: A, D, 기대 피해, 기습 성공률."""
        if self.world.is_sea(target):
            return None
        A, sources, main = self.combat_strength(army.owner, [army], target, mode)
        if len(sources) > 1 and mode == "assault":
            A *= 1 + C.FLANK_BONUS * (len(sources) - 1)
        Dv, defenders, line = self.defense_strength(army.owner, target, main, mode)
        dd, ad = R.battle_damage(A, Dv, 1.0)
        res = {"A": A, "D": Dv, "def_dmg": dd, "att_dmg": ad, "line": line, "defenders": sum(
            a.count() for a in defenders)}
        if not self.world.is_sea(army.loc):
            res["terrain"] = self.world.terrain_between(army.loc, target)
        if mode == "surprise":
            rr = self.regions[target]
            lv = rr.lines.get(main, 0)
            p = R.surprise_chance(lv, self.mods(army.owner).add("surprise"))
            win, fail = R.surprise_mults(lv)
            res["surprise_p"] = p
            res["def_dmg_win"] = dd * win[0]
            res["att_dmg_win"] = ad * win[1]
            res["def_dmg_fail"] = dd * fail[0]
            res["att_dmg_fail"] = ad * fail[1]
        res["def_hp"] = sum(a.hp_left(k) for a in defenders for k in a.units)
        return res

    # ------------------------------------------------------------------ 피해 적용
    def apply_damage(self, armies, dmg, unit_filter=None, rng_round=True, order=None, spread="share"):
        """피해 적용. 잃은 유닛 {키: 수} 반환.
        spread="share": (수 x 체력) 비율로 나눔 / order=(키, ...): 그 순서로 먼저 채움(돌격 방어측) /
        spread="random": 유닛 하나하나에 무작위로 나눔(폭격)."""
        pool = []
        acted = self.__dict__.setdefault("_acted", set())
        for a in armies:
            acted.add(a.id)                  # 전투·폭격에 휘말린 부대는 이번 턴 회복하지 않는다
            for k, n in a.units.items():
                if n > 0 and (unit_filter is None or k in unit_filter):
                    pool.append((a, k, n))
        total_hp = sum(C.UNITS[k]["hp"] * n for _, k, n in pool)
        lost = {}
        if total_hp <= 0 or dmg <= 0:
            return lost
        shares = {}
        if order is not None:
            rank = {k: i for i, k in enumerate(order)}
            left = dmg
            for a, k, n in sorted(pool, key=lambda x: (rank.get(x[1], len(order)), x[0].id)):
                cap = C.UNITS[k]["hp"] * n - a.dmg.get(k, 0.0)
                take = min(left, max(0.0, cap))
                shares[(a.id, k)] = take
                left -= take
                if left <= 1e-9:
                    break
        elif spread == "random":
            units = [(a.id, k) for a, k, n in pool for _ in range(n)]
            chunks = max(1, min(400, int(math.ceil(dmg / 2.5))))
            for _ in range(chunks):
                key = units[self.rng.randrange(len(units))]
                shares[key] = shares.get(key, 0.0) + dmg / chunks
        else:
            for a, k, n in pool:
                shares[(a.id, k)] = dmg * (C.UNITS[k]["hp"] * n) / total_hp
        for a, k, n in pool:
            share = shares.get((a.id, k), 0.0)
            if share <= 0:
                continue
            hp = C.UNITS[k]["hp"]
            acc = a.dmg.get(k, 0.0) + share
            dead = min(n, int(acc // hp + 1e-9))
            acc -= dead * hp
            a.units[k] = n - dead
            a.dmg[k] = max(0.0, acc) if a.units[k] > 0 else 0.0
            if dead:
                lost[k] = lost.get(k, 0) + dead
        for a in armies:
            a.units = {k: v for k, v in a.units.items() if v > 0}
            if a.domain() == "naval":
                self._validate_capacity(a)
            if a.empty():
                self.remove_army(a)
        return lost

    def units_value(self, lost: dict) -> float:
        return sum(C.UNITS[k]["cost"] * C.UNITS[k]["turns"] * n for k, n in lost.items())

    # ------------------------------------------------------------------ 건설·생산 옵션
    def build_time(self, fid, key, base_turns):
        m = self.mods(fid)
        mult = m.mult("build_time_all")
        if key in C.PROD_BUILDINGS:
            mult *= m.mult("build_time_prod")
        if key == "factory":
            mult *= m.mult("build_time_factory")
        if key in C.INDUSTRY_BUILDINGS:
            mult *= m.mult("build_time_industry")     # 정조 '문체반정'
        return max(1, int(math.floor(base_turns * mult + 0.5)))

    def unit_cost(self, fid, rid, key) -> float:
        m = self.mods(fid)
        u = C.UNITS[key]
        c = u["cost"] * C.MONEY_SCALE * m.mult("cost_mil")
        if key == "inf" and self.turn <= C.TURNS_PER_YEAR:
            c *= m.mult("inf_cost_early")
        if key == "tank":
            c *= m.mult("cost_tank")
        if u["kind"] == "naval":
            c *= m.mult("cost_naval")
        if u["kind"] == "air":
            c *= m.mult("cost_air")
        if key != "inf":
            c *= m.mult("cost_noninf")                # 단군왕검 '신화 시대'
        disc = 0.0
        if self.regions[rid].b["academy"] and self.regions[rid].owner == fid:
            disc = C.ACADEMY_LOCAL
        else:
            for n in self.world.land_adj[rid]:
                rr = self.regions[n]
                if rr.owner == fid and rr.b["academy"]:
                    disc = max(disc, C.ACADEMY_ADJ)
        return c * (1 - disc)

    def region_value(self, rid):
        """지역 가치 1~10과 점수 구성 {항목: 점수}."""
        rr = self.regions[rid]
        info = self.info(rid)
        levels = sum(rr.b[k] for k in ("farm", "fishery", "factory", "bank", "power",
                                       "specialty", "extract"))
        singles = sum(rr.b[k] for k in ("port", "airport", "academy"))
        parts = R.region_value_parts(self.region_output_estimate(rid), rr.pop, levels, singles,
                                     info.oil, info.coal, info.power_self, info.power_site,
                                     rr.b["extract"], len(info.specialties))
        return R.region_value(sum(parts.values())), parts

    def neutral_turns(self, fid, rid) -> int:
        """중립 지역 편입·무력 점령에 걸리는 턴(지역 가치 기준)."""
        return R.value_turns(self.region_value(rid)[0], self.mods(fid).mult("occ_time"))

    def annex_cost(self, fid, rid) -> float:
        return R.annex_cost(self.region_output_estimate(rid), self.region_count(fid))

    def annex_targets(self, fid, rid):
        w = self.world
        cands = set(v for v in w.land_adj[rid] if self.regions[v].owner == NEUTRAL)   # 육상 인접만(해로 편입 없음)
        joint = {}
        for r in self.regions.values():
            if r.owner == fid and r.project and r.project.kind == "annex":
                joint[r.project.key] = joint.get(r.project.key, 0) + 1
        out = []
        for v in sorted(cands):
            rr = self.regions[v]
            if fid in rr.occs:
                continue                          # 내 군대가 이미 점령 중
            base = self.neutral_turns(fid, v)
            n = joint.get(v, 0)
            out.append({"target": v, "turns": base, "cost": self.annex_cost(fid, v),
                        "value": self.region_value(v)[0], "joint": n, "sea": False,
                        "eff_turns": R.joint_turns(base, n + 1),
                        # 다른 세력의 점령·편입이 끝나기까지 남은 턴(가장 빠른 것). 경쟁 판단용
                        "rival_left": self.rival_left(fid, v)})
        return out

    def options(self, fid, rid):
        """이 지역 슬롯에 넣을 수 있는 선택지 목록."""
        rr = self.regions[rid]
        info = self.info(rid)
        m = self.mods(fid)
        opts = []
        resisting = self.resisting(rr)
        frozen = self.order_frozen(fid)

        def add(kind, key, name, cost, turns, ok=True, why="", level=0, border=None, oil=0):
            turns = max(1, turns)
            if resisting:
                ok, why = False, "점령 저항 중"
            elif frozen and kind != "annex":
                ok, why = False, frozen
            opts.append({"kind": kind, "key": key, "name": name, "cost": cost, "turns": turns,
                         "per_turn": cost / turns, "ok": ok, "why": why, "level": level,
                         "border": border, "oil": oil})

        for key, spec in C.PROD_BUILDINGS.items():
            lv = rr.b[key] + 1
            ok, why = True, ""
            if lv > spec["max"]:
                continue
            # 지역 조건상 영영 지을 수 없는 시설은 목록에 넣지 않는다
            if key == "fishery" and not self.can_fish(rid):
                continue
            if key == "specialty" and not info.specialty:
                continue
            if key == "extract" and not (info.is_oil or info.is_coal):
                continue
            cost = R.prod_building_cost(key, lv, info.power_site)
            if key == "factory":
                cost *= m.mult("cost_factory")
            add("build", key, self.building_name(rid, key), cost, self.build_time(fid, key, R.prod_building_turns(lv)),
                ok, why, lv)
        for key in ("shelter", "aa"):
            lv = rr.b[key] + 1
            if lv <= 5:
                add("build", key, C.DEF_BUILDINGS[key]["name"], R.def_building_cost(key, lv),
                    self.build_time(fid, key, R.def_building_turns(lv)), level=lv)
        borders = sorted(self.world.land_adj[rid]) + (["coast"] if info.coastal else [])
        for bkey in borders:
            lv = rr.lines.get(bkey, 0) + 1
            if lv > 5:
                continue
            nm = "해안선" if bkey == "coast" else self.info(bkey).name
            add("build", "line", f"방어선({nm})", R.def_building_cost("line", lv) * m.mult("cost_line"),
                self.build_time(fid, "line", R.def_building_turns(lv)), level=lv, border=bkey)
        for key, spec in C.SINGLE_BUILDINGS.items():
            if rr.b[key]:
                continue
            ok, why = True, ""
            if key == "port" and not info.coastal:
                continue
            add("build", key, spec["name"], spec["cost"] * C.BUILD_COST_MULT * C.MONEY_SCALE,
                self.build_time(fid, key, spec["turns"]), ok, why, 1)
        for key in C.BUILD_UNITS:
            u = C.UNITS[key]
            ok, why = True, ""
            if u["kind"] == "naval" and not info.coastal:
                continue                      # 내륙 지역: 해군은 아예 표시하지 않는다(항구도 지을 수 없음)
            if u["kind"] == "naval" and not rr.b["port"]:
                ok, why = False, "항구 필요"
            if u["kind"] == "air" and not rr.b["airport"]:
                ok, why = False, "공항 필요"
            if ok and not self.can_pay_oil(fid, u["oil"]):
                ok, why = False, f"석유 {u['oil']} 필요(석탄 {u['oil'] * C.OIL_AS_COAL}로 대체 가능)"
            per = self.unit_cost(fid, rid, key)
            add("unit", key, u["name"], per * u["turns"], u["turns"], ok, why, oil=u["oil"])
        for t in self.annex_targets(fid, rid):
            name = f"편입: {self.info(t['target']).name} [{t['value']}]"
            if t["joint"]:
                n = t["joint"] + 1
                name += f" · 공동 {n}곳 −{R.joint_reduction(n):.0%} (약 {t['eff_turns']}턴)"
            add("annex", t["target"], name, t["cost"], t["turns"])
        for step in self.science_available(fid):
            if not self.science_site_ok(fid, rid, step):
                continue
            busy = self.science_busy(fid, step)
            turns = self.science_turns(fid)
            k = C.SCIENCE_STEPS.index(step)
            name = f"과학 {k + 1}단계: {C.SCIENCE[step]['name']}"
            add("science", step, name, self.science_step_cost(fid, step), turns,
                busy is None, "" if busy is None else f"{self.info(busy).name}에서 진행 중", level=k + 1)
        for step in self.econ_available(fid):
            if not self.econ_site_ok(fid, rid, step):
                continue
            spec = C.ECON[step]
            turns = spec["turns"]
            k = C.ECON_STEPS.index(step) + 2
            name = f"경제 {k}단계: {spec['name']}"
            busy = self.econ_busy(fid, step) if step != "exchange" else None
            add("econ", step, name, spec["per_turn"] * C.MONEY_SCALE * turns, turns,
                busy is None, "" if busy is None else f"{self.info(busy).name}에서 진행 중", level=k)
        if self.factions[fid].capital != rid:
            y = max(rr.output, self.region_output_estimate(rid))
            add("capital", "capital", "천도(수도 이전)", y * C.CAPITAL_MOVE_COST_MULT, C.CAPITAL_MOVE_TURNS)
        return opts

    # ---- 과학승리
    def science_turns(self, fid) -> int:
        return int(self.mods(fid).value("science_turns", C.SCIENCE_TURNS))

    def science_step_cost(self, fid, step) -> float:
        """과학 단계 총비용: 턴당 10만 × 1.1^단계 × 턴 수 × 지도자 보정."""
        spec = C.SCIENCE[step]
        per = C.SCIENCE_COST_PER_TURN * R.science_cost_mult(spec["tier"])
        return per * C.MONEY_SCALE * self.mods(fid).mult("cost_science") * self.science_turns(fid)

    def science_units_alive(self, fid) -> dict:
        out = {}
        for a in self.armies.values():
            if a.owner == fid:
                for k in C.SCIENCE_UNITS:
                    if a.units.get(k):
                        out[k] = out.get(k, 0) + a.units[k]
        return out

    def science_available(self, fid) -> list:
        """지금 착수할 수 있는 과학 단계들: 아직 안 한 첫 단계 + 완료했지만 그 유닛을 잃은 유닛 단계."""
        done = self.factions[fid].science
        out = []
        nxt = next((st for st in C.SCIENCE_STEPS if st not in done), None)
        if nxt is not None:
            out.append(nxt)
        alive = self.science_units_alive(fid)
        for st in C.SCIENCE_UNITS:
            if st in done and not alive.get(st) and self.science_busy(fid, st) is None:
                out.append(st)
        return out

    def science_next(self, fid):
        """AI·현황용: 다음으로 할 과학 단계(없으면 None)."""
        av = self.science_available(fid)
        return av[0] if av else None

    def science_busy(self, fid, step):
        """그 단계를 진행 중인 지역 ID(없으면 None)."""
        for r in self.regions.values():
            if r.owner == fid and r.project and r.project.kind == "science" and r.project.key == step:
                return r.id
        return None

    def science_site_ok(self, fid, rid, step) -> bool:
        """그 단계를 이 지역에서 진행할 수 있는가(위치 조건)."""
        rr, info = self.regions[rid], self.info(rid)
        if step == "lab":
            return self.factions[fid].capital == rid
        if step == "observatory":
            return rid in self.world.mountain_regions
        if step == "budget":
            return rr.b["bank"] >= 5
        if step == "pad":
            return info.coastal
        if step in ("booster", "module"):
            return rr.b["factory"] >= 5
        if step == "propellant":
            return info.is_oil
        return False

    def science_sites(self, fid, step):
        return [r.id for r in self.regions_of(fid) if self.science_site_ok(fid, r.id, step)]

    def launch_ready(self, fid):
        """과학승리 판정: 7단계를 모두 마치고, 내 발사대 지역 한 곳에 세 유닛이 모두 있으면 그 지역 ID."""
        f = self.factions[fid]
        if any(st not in f.science for st in C.SCIENCE_STEPS):
            return None
        for r in self.regions_of(fid):
            if "pad" not in r.sci:
                continue
            have = set()
            for a in self.armies_at(r.id, fid):
                have |= {k for k in C.SCIENCE_UNITS if a.units.get(k)}
            if have == set(C.SCIENCE_UNITS):
                return r.id
        return None

    # ---- 경제승리(기축통화)
    def econ_enabled(self) -> bool:
        return "economic" in self.settings.victories

    def finance_cluster(self, fid) -> set:
        """수도를 포함해 서로 맞닿은(육상 인접) 한 덩어리의 금융 단지(은행 5단계) 지역. 수도가 금융 단지가 아니면 빈 집합."""
        cap = self.factions[fid].capital
        rr = self.regions.get(cap)
        if not rr or rr.owner != fid or rr.b["bank"] < 5:
            return set()
        seen, stack = {cap}, [cap]
        while stack:
            u = stack.pop()
            for v in self.world.land_adj[u]:
                if v not in seen and self.regions[v].owner == fid and self.regions[v].b["bank"] >= 5:
                    seen.add(v)
                    stack.append(v)
        return seen

    def econ_buildings(self, fid, key) -> list:
        return [r.id for r in self.regions_of(fid) if key in r.econ]

    def econ_need(self, fid, n) -> int:
        """관계 조건 국가 수: 살아 있는 다른 나라가 그보다 적으면 남은 나라 전부."""
        return min(n, len(self.alive_ids()) - 1)

    def econ_ready(self, fid, step) -> tuple:
        """위치와 상관없는 단계 조건 (충족 여부, 설명). 착수할 때와 건설 중 매 턴 확인한다."""
        cap = self.factions[fid].capital
        if step == "exchange":
            n = len(self.finance_cluster(fid))
            return n >= C.ECON_CLUSTER, f"금융 권역 {n}/{C.ECON_CLUSTER}곳"
        if step == "sez":
            ex = self.econ_buildings(fid, "exchange")
            ok = cap in ex and len(ex) >= C.ECON_EXCHANGES
            return ok, f"증권거래소 {len(ex)}/{C.ECON_EXCHANGES}곳" + ("" if cap in ex else "(수도 포함)")
        n, al = D.econ_partners(self, fid)
        if step == "ifc":
            if not self.econ_buildings(fid, "sez"):
                return False, "경제특구 필요"
            need = self.econ_need(fid, C.ECON_IFC_FRIENDS)
            return n >= need, f"우호 선언 이상 {n}/{need}개국"
        if step == "currency":
            if not self.econ_buildings(fid, "ifc"):
                return False, "국제금융센터 필요"
            need = self.econ_need(fid, C.ECON_CURRENCY_FRIENDS)
            need_al = min(C.ECON_CURRENCY_ALLIES, need)
            return n >= need and al >= need_al, f"우호 선언 이상 {n}/{need}개국 · 동맹 {al}/{need_al}"
        return False, ""

    def econ_site_ok(self, fid, rid, step) -> bool:
        """그 단계를 이 지역에서 지을 수 있는가(위치 조건)."""
        rr = self.regions[rid]
        if rr.owner != fid or step in rr.econ:
            return False
        if step == "exchange":
            return rid in self.finance_cluster(fid)
        if step in ("sez", "currency"):
            return rid == self.factions[fid].capital
        if step == "ifc":
            return "exchange" in rr.econ
        return False

    def econ_busy(self, fid, step):
        """그 단계를 건설 중인 지역 ID(없으면 None)."""
        for r in self.regions_of(fid):
            if r.project and r.project.kind == "econ" and r.project.key == step:
                return r.id
        return None

    def econ_available(self, fid) -> list:
        """지금 착수할 수 있는 경제 단계(증권거래소는 여러 곳, 나머지는 나라에 하나)."""
        if not self.econ_enabled():
            return []
        out = []
        for step in C.ECON_STEPS:
            if step != "exchange" and self.econ_buildings(fid, step):
                continue
            if self.econ_ready(fid, step)[0]:
                out.append(step)
        return out

    def econ_stage(self, fid) -> int:
        """경제승리 진척(0~5): 금융 권역 → 증권거래소 3곳 → 경제특구 → 국제금융센터 → 기축통화."""
        if self.econ_buildings(fid, "currency"):
            return 5
        if self.econ_buildings(fid, "ifc"):
            return 4
        if self.econ_buildings(fid, "sez"):
            return 3
        if self.econ_ready(fid, "sez")[0]:
            return 2
        return 1 if self.econ_ready(fid, "exchange")[0] else 0

    def econ_progress(self, fid) -> float:
        """0~1. 기축통화 건설 중이면 진행도만큼 더한다."""
        st = self.econ_stage(fid)
        rid = self.econ_busy(fid, "currency")
        if rid is not None:
            p = self.regions[rid].project
            return min(1.0, (4 + p.progress / max(1, p.turns)) / C.ECON_STAGES)
        return st / C.ECON_STAGES

    def victory_threat(self, fid) -> float:
        """승리에 가까운 정도에 따른 견제 강도(0~1): 과학·경제 진척이 절반을 넘으면 오르기 시작한다."""
        cache = self.__dict__.setdefault("_vthreat", {})
        key = (self.turn, fid)
        if key not in cache:
            if len(cache) > 64:
                cache.clear()
            f = self.factions[fid]
            p = 0.0
            if "science" in self.settings.victories:
                p = len(f.science) / len(C.SCIENCE_STEPS)
            if self.econ_enabled():
                p = max(p, self.econ_progress(fid))
            cache[key] = max(0.0, (p - C.VICTORY_THREAT_FROM) / (1 - C.VICTORY_THREAT_FROM))
        return cache[key]

    def _pause_econ(self, rr, why):
        """건설 중 조건이 깨짐: 중단하고 낸 돈의 50% 환급. 진행도는 사라져 조건이 돌아오면 처음부터 다시 짓는다."""
        p = rr.project
        f = self.factions[rr.owner]
        refund = p.paid * C.ECON_PAUSE_REFUND
        f.money += refund
        rr.project = None
        spec = C.ECON[p.key]
        self.event("info", f"{self.info(rr.id).name} {spec['name']} 건설 중단: {why} — {refund:,.0f} 환급 "
                   f"(다시 지으려면 처음부터)", region=rr.id, fids=(f.id,))

    def _check_econ_projects(self, f):
        for rr in self.regions_of(f.id):
            p = rr.project
            if not p or p.kind != "econ":
                continue
            ok, why = self.econ_ready(f.id, p.key)
            if ok and not self.econ_site_ok(f.id, rr.id, p.key):
                ok, why = False, "위치 조건"
            if not ok:
                self._pause_econ(rr, why)

    def econ_alert(self, fid, text):
        """다른 나라의 국제금융센터 완공·기축통화 착수: 플레이어에게만 알림."""
        if fid != self.player_id:
            self.event("alert", text, region=self.factions[fid].capital, fids=(fid,))

    def order_frozen(self, fid) -> str:
        """박혁거세 '교대 계승': 매년 12월 4주차에는 건설·생산 명령 불가. 막힌 이유(없으면 빈 문자열)."""
        if self.mods(fid).value("dec_freeze") and R.date_of_turn(self.turn)[1:] == (12, 4):
            return "교대 계승(12월 4주)"
        return ""

    def building_name(self, rid, key, level=None) -> str:
        """건물 이름. 채굴 시설은 지역에 따라 '정유공장 증설'·'탄광 증설',
        농장·어장·공장·은행은 단계별 이름(level 을 주면, 예: 공장 5단계 → 공업 단지)."""
        if key == "extract":
            return "정유공장 증설" if self.info(rid).is_oil else "탄광 증설"
        if level and key in C.PROD_LEVEL_NAMES:
            return C.PROD_LEVEL_NAMES[key][min(level, 5) - 1]
        return BUILDING_NAMES.get(key, key)

    def build_label(self, rid, key, level) -> str:
        """'공업 단지 건설'(단계 이름이 있는 생산 건물) 또는 '발전소 2단계'."""
        if key in C.PROD_LEVEL_NAMES:
            return f"{self.building_name(rid, key, level)} 건설"
        return f"{self.building_name(rid, key)} {level}단계"

    def building_effect(self, fid, rid, opt) -> str:
        """행동 메뉴용: 다음 단계 건물의 턴당 생산량/효과."""
        rr = self.regions[rid]
        info = self.info(rid)
        key, lv = opt["key"], opt["level"]
        m = self.mods(fid)
        dg = R.g(lv) - R.g(lv - 1)
        if key == "farm":
            return f"턴당 식량 +{C.FOOD_PER_G:.0f}, 산출 +{C.FARM_OUTPUT * m.mult('output_prod'):.0f}"
        if key == "fishery":
            fm = self.fish_mult(fid, rid)
            kind = "하천" if (not info.coastal and rid in self.world.river_regions) else "바다"
            return (f"{kind} 어장: 턴당 식량 +{round(C.FOOD_PER_G * fm, 1):g}, "
                    f"산출 +{C.FISH_OUTPUT * fm * m.mult('output_prod'):.0f}")
        if key == "factory":
            per = C.FACTORY_UNIT_OUTPUT[lv - 1] * m.mult('output_factory') * m.mult('output_prod')
            return f"연료 최대 {lv}개/턴, 1개당 산출 {per:,.0f}"
        if key == "bank":
            return f"턴당 산출 +{C.BANK_OUTPUT * dg * m.mult('output_bank') * m.mult('output_prod'):,.0f}"
        if key == "power":
            return (f"연료 최대 {lv}개/턴 → 전기 (석탄 1 → 전기 {C.POWER_ELEC['coal']}, "
                    f"석유 1 → 전기 {C.POWER_ELEC['oil']})")
        if key == "specialty":
            each = " 각" if len(info.specialties) > 1 else ""
            return "특산물 " + "·".join(f"「{sp}」" for sp in info.specialties) + f" 턴당{each} {lv}개"
        if key == "extract":
            if info.is_oil:
                return f"석유 {info.oil + lv - 1}+1/턴"
            return f"석탄 {lv - 1}+1/턴"
        if key == "line":
            k = m.value("line_k", C.LINE_BONUS)
            return f"돌격 방어 +{k * lv * 100:.0f}%"
        if key == "shelter":
            return f"폭격 방어 +{C.SHELTER_K * lv * 100:.0f}%"
        if key == "aa":
            per = C.AA_PER_LEVEL
            return f"요격 데미지 {min(lv - 1, C.AA_MAX_LEVEL) * per:g}+{per:g}"
        if key == "academy":
            return "이 지역 유닛 생산비 −25%, 인접 −10%"
        if key == "airport":
            return f"공군 {C.AIRPORT_CAPACITY}대 주둔·출격"
        if key == "port":
            return "해군 생산·정박"
        return ""

    def start_project(self, fid, rid, kind, key, border=None, name=None):
        rr = self.regions.get(rid)
        if not rr or rr.owner != fid:
            return False, "내 지역이 아닙니다."
        if rr.project:
            return False, "이 지역 슬롯은 이미 사용 중입니다."
        if rr.occ:
            return False, "점령당하는 중인 지역입니다."
        if self.resisting(rr):
            return False, "점령 저항 중인 지역은 생산할 수 없습니다."
        opt = next((o for o in self.options(fid, rid) if o["kind"] == kind and o["key"] == key
                    and (border is None or o["border"] == border)), None)
        if not opt:
            return False, "선택할 수 없는 항목입니다."
        if not opt["ok"]:
            return False, opt["why"]
        f = self.factions[fid]
        if kind == "unit":
            u = C.UNITS[key]
            if not self.can_pay_oil(fid, u["oil"]):
                return False, f"석유 {u['oil']} 필요"
            self.pay_oil(fid, u["oil"])
            rr.h_delta += C.UNIT_START_HAPPY[u["weight"]]
        rr.project = Project(kind=kind, key=key, level=opt["level"], turns=opt["turns"],
                             per_turn=opt["per_turn"], border=opt["border"])
        self.proj_counter = getattr(self, "proj_counter", 0) + 1
        rr.project.priority = self.proj_counter
        label = opt["name"]
        if kind == "econ":
            if key == "currency":
                self.econ_alert(fid, f"{self.fname(fid)}이(가) 기축통화 지정을 시작했습니다. "
                                     f"{opt['turns']}턴 뒤 완료되면 경제승리입니다!")
        return True, f"{label} 착수 ({opt['turns']}턴, 턴당 {opt['per_turn']:,.0f})"

    def cancel_project(self, fid, rid):
        rr = self.regions.get(rid)
        if not rr or rr.owner != fid or not rr.project:
            return False, "취소할 작업이 없습니다."
        refund = rr.project.paid * C.PROJECT_REFUND
        self.factions[fid].money += refund
        rr.project = None
        return True, f"취소: {refund:,.0f} 환급"

    def review_order(self, fid):
        """수도부터 영토를 얻은 순서대로."""
        cap = self.factions[fid].capital
        regs = self.regions_of(fid)
        return [r.id for r in sorted(regs, key=lambda r: (r.id != cap, getattr(r, "acquired_seq", 0), r.id))]

    def idle_slots(self, fid) -> int:
        return sum(1 for r in self.regions.values() if r.owner == fid and not r.project and not r.occ
                   and not self.resisting(r) and not getattr(r, "focus", False))

    def projects_by_priority(self, fid):
        """자금 지출 우선순위 순서의 (지역, 작업) 목록."""
        regs = [r for r in self.regions.values() if r.owner == fid and r.project]
        return sorted(regs, key=lambda r: (r.project.priority, r.id))

    PRIORITY_SORTS = {"annex": "중립 지역 편입 우선", "build": "건설 우선", "unit": "유닛 생산 우선",
                      "short": "적은 턴 수 우선"}

    def sort_priority(self, fid, mode):
        """지출 우선순위 자동 정렬. 고른 종류를 앞으로(그 안에서는 기존 순서), short 는 남은 턴이 적은 순."""
        regs = self.projects_by_priority(fid)
        if mode == "short":
            regs.sort(key=lambda r: self.project_left(r.id))
        else:
            kinds = {"annex": ("annex",), "build": ("build", "science", "econ", "capital"), "unit": ("unit",)}[mode]
            regs.sort(key=lambda r: r.project.kind not in kinds)
        self.set_priority_order(fid, [r.id for r in regs])

    def set_priority_order(self, fid, rids):
        for i, rid in enumerate(rids):
            r = self.regions.get(rid)
            if r and r.owner == fid and r.project:
                r.project.priority = i + 1
        self.proj_counter = max(getattr(self, "proj_counter", 0), len(rids) + 1)

    # ------------------------------------------------------------------ 국가 명령
    def tax_base(self, fid) -> float:
        """행복도가 오르지도 내리지도 않는 기준 세율(%). 기본 10, 전제군주제 12."""
        return 10.0 + self.mods(fid).add("tax_base")

    def tax_happy(self, fid, t_pct) -> float:
        """세율 t%일 때 턴당 행복도 변화."""
        m = self.mods(fid)
        return R.tax_happiness(t_pct, m.value("tax_over10", 1.0), m.value("tax_over15", 1.0), self.tax_base(fid))

    def tax_max(self, fid):
        return self.mods(fid).value("tax_max", C.TAX_MAX)

    def set_tax(self, fid, t):
        f = self.factions[fid]
        t = max(0.0, min(self.tax_max(fid), round(t, 2)))
        if abs(t - f.tax) < 1e-9:
            return True, ""
        if f.tax_locked_until > self.turn:
            name = LEADER_BY_KEY.get(f.leader, {}).get("debuff", ("세율 잠금",))[0]
            return False, f"{name}: 턴 {f.tax_locked_until}까지 세율을 바꿀 수 없습니다."
        f.tax = t
        lock = self.mods(fid).value("tax_lock", 0)
        if lock:
            f.tax_locked_until = self.turn + lock
        return True, f"세율 {t*100:.0f}%"

    def buy_price(self, fid, res) -> float:
        f = self.factions[fid]
        p = C.MARKET_BUY[res] * C.MONEY_SCALE * self.mods(fid).mult("market_buy")
        if res != "food":
            p *= (1 + C.MARKET_STEP) ** f.buy_count.get(res, 0)
        return p

    def sell_price(self, fid, res) -> float:
        return C.MARKET_SELL[res] * C.MONEY_SCALE * self.mods(fid).mult("market_sell")

    def buy_cost(self, fid, res, qty) -> float:
        """qty 개를 지금 살 때 드는 돈(같은 턴 추가 구매 +10% 반영)."""
        f = self.factions[fid]
        base = C.MARKET_BUY[res] * C.MONEY_SCALE * self.mods(fid).mult("market_buy")
        if res == "food":
            return base * qty
        k = f.buy_count.get(res, 0)
        r = 1 + C.MARKET_STEP
        return base * r ** k * (r ** qty - 1) / (r - 1)

    def max_buyable(self, fid, res) -> int:
        f = self.factions[fid]
        if f.money <= 0 or res in C.UNBUYABLE:
            return 0
        lo, hi = 0, 1
        while self.buy_cost(fid, res, hi) <= f.money and hi < 10 ** 7:
            hi *= 2
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.buy_cost(fid, res, mid) <= f.money + 1e-6:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def market_buy(self, fid, res, qty):
        f = self.factions[fid]
        if res in C.UNBUYABLE:
            return 0, 0.0                    # 석유·석탄은 돈으로 살 수 없다(판매만)
        bought = 0
        spent = 0.0
        for _ in range(int(qty)):
            p = self.buy_price(fid, res)
            if f.money < p:
                break
            f.money -= p
            spent += p
            f.res[res] = f.res.get(res, 0) + 1
            if res != "food":
                f.buy_count[res] = f.buy_count.get(res, 0) + 1
            bought += 1
        f.trade_buy += spent
        return bought, spent

    def market_sell(self, fid, res, qty):
        f = self.factions[fid]
        q = int(min(qty, math.floor(f.res.get(res, 0))))
        if q <= 0:
            return 0, 0.0
        gain = q * self.sell_price(fid, res)
        f.res[res] -= q
        f.money += gain
        f.trade_sell += gain
        return q, gain

    # ------------------------------------------------------------------ 에너지
    def can_pay_oil(self, fid, n) -> bool:
        f = self.factions[fid]
        return f.res.get("oil", 0) + f.res.get("coal", 0) / C.OIL_AS_COAL >= n - 1e-9

    def pay_oil(self, fid, n):
        """석유 n 을 낸다. 모자라면 부족분 × 2 만큼 석탄으로."""
        f = self.factions[fid]
        use = min(n, f.res.get("oil", 0))
        f.res["oil"] = f.res.get("oil", 0) - use
        f.res["coal"] = f.res.get("coal", 0) - (n - use) * C.OIL_AS_COAL

    def energy_mined(self, fid) -> dict:
        """이번 턴 채굴·자체 발전(점령당하는 중·저항 지역 제외)."""
        out = {"oil": 0, "coal": 0, "elec": 0}
        for r in self.regions_of(fid):
            if r.occ or self.resisting(r):
                continue
            info = self.info(r.id)
            if info.is_oil:
                out["oil"] += info.oil + r.b["extract"]
            elif info.is_coal:
                out["coal"] += r.b["extract"]
            out["elec"] += info.power_self
        return out

    def energy_sites(self, fid):
        """연료를 받는 시설: (발전소 지역들, 공장 지역들). 공장은 단계가 높은 순."""
        act = [r for r in self.regions_of(fid) if not r.occ and not self.resisting(r)]
        plants = sorted([r for r in act if r.b["power"] > 0], key=lambda r: (-r.b["power"], r.id))
        facts = sorted([r for r in act if r.b["factory"] > 0], key=lambda r: (-r.b["factory"], r.id))
        return plants, facts

    def auto_energy_plan(self, fid, stock, oil_reserve=None) -> dict:
        """자원 자동 배정 우선순위: ① 발전소에 석유 → ② 발전소에 석탄 → ③ 공장에 전기 → ④ 공장에 석탄 →
        ⑤ 공장에 석유. 발전소·공장 모두 단계가 높은 곳부터 채운다.
        oil_reserve: 남겨 둘 석유(AI는 군 생산용 AUTO_OIL_RESERVE, 플레이어 명령은 0).
        반환 {"p": {rid: {coal, oil}}, "f": {rid: {coal, oil, elec}}}"""
        plants, facts = self.energy_sites(fid)
        reserve = C.AUTO_OIL_RESERVE if oil_reserve is None else oil_reserve
        left = {"oil": max(0, int(stock["oil"]) - reserve), "coal": int(stock["coal"]), "elec": int(stock["elec"])}
        plan = {r.id: {"coal": 0, "oil": 0} for r in plants}
        room = {r.id: r.b["power"] for r in plants}
        for key in ("oil", "coal"):                       # ①② 발전소: 석유 먼저, 그다음 석탄
            for r in plants:
                k = min(room[r.id], left[key])
                plan[r.id][key] += k
                room[r.id] -= k
                left[key] -= k
        left["elec"] += sum(C.POWER_ELEC["oil"] * a["oil"] + C.POWER_ELEC["coal"] * a["coal"] for a in plan.values())
        fplan = {r.id: {"coal": 0, "oil": 0, "elec": 0} for r in facts}
        froom = {r.id: r.b["factory"] for r in facts}
        for key in ("elec", "coal", "oil"):               # ③④⑤ 공장: 전기 → 석탄 → 석유, 단계 높은 공장부터
            for r in facts:
                k = min(froom[r.id], left[key])
                fplan[r.id][key] += k
                froom[r.id] -= k
                left[key] -= k
        return {"p": plan, "f": fplan}

    def assign_energy(self, fid):
        """[자동 배정] 명령: 턴마다 생산되는 양(채굴·자체 발전)을 기준으로 우선순위대로 배정해 수동 배정에
        적어 둔다(다음에 누를 때까지 그대로, 재고는 쓰지 않으니 매 턴 같은 배정을 유지할 수 있다)."""
        f = self.factions[fid]
        mined = self.energy_mined(fid)
        want = self.auto_energy_plan(fid, {k: float(mined[k]) for k in C.ENERGY}, oil_reserve=0)
        for r in self.regions_of(fid):
            r.energy = {}
        for rid, a in want["p"].items():
            self.regions[rid].energy["p"] = dict(a)
        for rid, a in want["f"].items():
            self.regions[rid].energy["f"] = dict(a)
        f.auto_energy = False
        plan = self.energy_plan(fid)
        units = sum(a["units"] for a in plan["factories"].values())
        cap = sum(self.regions[rid].b["factory"] for rid in plan["factories"])
        return units, cap

    def energy_plan(self, fid) -> dict:
        """이번 턴 에너지 흐름(실제 처리와 같은 순서): 채굴 → 발전소 투입 → 전기 생산 → 공장 투입.
        배정량이 재고보다 많으면 순서대로 있는 만큼만 쓴다.
        반환: stock(지금 재고), mined, plants{rid: {coal, oil, elec_out}}, factories{rid: {coal, oil, elec, units}},
              after(턴 뒤 재고)"""
        f = self.factions[fid]
        stock = {k: float(f.res.get(k, 0)) for k in C.ENERGY}
        mined = self.energy_mined(fid)
        s = {k: stock[k] + mined[k] for k in C.ENERGY}
        plants, facts = self.energy_sites(fid)
        if f.auto_energy:
            want = self.auto_energy_plan(fid, s)
        else:
            want = {"p": {r.id: (r.energy or {}).get("p", {}) for r in plants},
                    "f": {r.id: (r.energy or {}).get("f", {}) for r in facts}}
        out_p, out_f = {}, {}
        for r in plants:
            a = want["p"].get(r.id, {})
            room = r.b["power"]
            used = {}
            for key in ("oil", "coal"):
                k = int(max(0, min(a.get(key, 0), room, s[key])))
                used[key] = k
                room -= k
                s[key] -= k
            e = C.POWER_ELEC["oil"] * used["oil"] + C.POWER_ELEC["coal"] * used["coal"]
            s["elec"] += e
            out_p[r.id] = {"coal": used["coal"], "oil": used["oil"], "elec_out": e}
        for r in facts:
            a = want["f"].get(r.id, {})
            room = r.b["factory"]
            used = {}
            for key in ("elec", "coal", "oil"):
                k = int(max(0, min(a.get(key, 0), room, s[key])))
                used[key] = k
                room -= k
                s[key] -= k
            used["units"] = used["elec"] + used["coal"] + used["oil"]
            out_f[r.id] = used
        return {"stock": stock, "mined": mined, "plants": out_p, "factories": out_f, "after": s}

    def set_energy(self, fid, rid, site, key, n):
        """수동 배정(자동 배정을 끈 상태). site "p" 발전소(석탄·석유), "f" 공장(전기·석탄·석유). 합계 ≤ 단계."""
        rr = self.regions[rid]
        if rr.owner != fid or site not in ("p", "f"):
            return False
        cap = rr.b["power"] if site == "p" else rr.b["factory"]
        if cap <= 0 or (site == "p" and key == "elec") or key not in ("coal", "oil", "elec"):
            return False
        en = dict(rr.energy or {})
        e = dict(en.get(site, {}))
        e[key] = 0
        e[key] = max(0, min(int(n), cap - sum(e.values())))
        en[site] = e
        rr.energy = en
        return True

    def set_auto_energy(self, fid, on):
        """자동 배정을 끄면 지금 자동안을 수동 배정의 출발점으로 복사한다."""
        f = self.factions[fid]
        if f.auto_energy and not on:
            f.auto_energy = True
            plan = self.energy_plan(fid)
            for r in self.regions_of(fid):
                r.energy = {}
            for rid, a in plan["plants"].items():
                self.regions[rid].energy["p"] = {"coal": a["coal"], "oil": a["oil"]}
            for rid, a in plan["factories"].items():
                self.regions[rid].energy["f"] = {"coal": a["coal"], "oil": a["oil"], "elec": a["elec"]}
        f.auto_energy = bool(on)

    # ------------------------------------------------------------------ 산출 계산
    def coast_controller(self, sea_id):
        owners = {self.regions[r].owner for r in self.world.seas[sea_id].coast}
        if len(owners) == 1:
            o = owners.pop()
            return None if o == NEUTRAL else o
        return None

    def can_fish(self, rid) -> bool:
        """바다(해안) 또는 하천(도하 경계) 인접 지역."""
        info = self.info(rid)
        return info.coastal or info.fishery > 0 or rid in self.world.river_regions

    def fish_mult(self, fid, rid):
        info = self.info(rid)
        if not info.coastal and rid in self.world.river_regions:
            return C.RIVER_FISH_MULT          # 하천 어장
        for s in info.seas:
            if self.coast_controller(s) == fid:
                return 1 + C.COAST_FISH_BONUS
        return 1.0

    def calc_output(self, rid, full=False, owner=None):
        """full=True 면 공장에 연료가 가득 들어간다고 보고 계산(추정·미리보기용)."""
        rr = self.regions[rid]
        owner = rr.owner if owner is None else owner
        m = self.mods(owner)
        phi = None if full else getattr(rr, "fuel_used", 0)
        y = R.region_output(rr.pop, rr.b["farm"], rr.b["fishery"], rr.b["factory"], rr.b["bank"],
                            phi, self.fish_mult(owner, rid) if owner != NEUTRAL else 1.0,
                            m.mult("output_bank") * (1 + C.EXCHANGE_BANK_BONUS if "exchange" in rr.econ else 1.0),
                            m.mult("output_factory"),
                            1 + C.FOCUS_POP_BONUS if self.focus_active(rr) and owner == rr.owner else 1.0,
                            m.mult("output_prod"), m.mult("output_farm"))
        pb = m.value("port_bank", 0)
        if pb and rr.b["port"] and owner != NEUTRAL:
            # 근초고왕 '해상 왕국': 항구가 있는 지역은 은행 3단계만큼 산출이 더 난다
            y += C.BANK_OUTPUT * R.g(pb) * m.mult("output_bank") * m.mult("output_prod")
        if owner != NEUTRAL and owner == rr.owner:
            y *= R.unhappy_output_mult(self.eff_happy(rr))   # 불행한(실질 행복도) 지역은 산출 감소
            if rid == self.factions[owner].capital:
                y *= 1 + C.CAPITAL_OUTPUT_BONUS * m.value("capital_bonus_mult", 1.0)   # 수도 (선왕 '5경 분산': 절반)
            far = m.value("far_output", 0)
            if far and rid not in self.near_capital(owner):
                y *= 1 - far                                  # 왕건 '호족 연합': 수도에서 먼 지역
            far = m.value("far_output_gov", 0)
            if far and rid not in self.near_capital(owner, 3):
                y *= 1 - far                                  # 전제군주제: 수도에서 3칸 밖 지역
            if self.turn <= m.value("early_output_turns", 0):
                y *= m.mult("early_output")                   # 김대중 '외환위기 수습': 첫 12턴
            y *= 1 + C.HAEDONG_OUTPUT * self.haedong_steps(owner)   # 발해 선왕 '해동성국'
        return y

    def near_capital(self, fid, dist=2) -> set:
        """수도에서 육상 dist칸 이내 지역."""
        cap = self.factions[fid].capital
        cache = self.__dict__.setdefault("_near_cap", {})
        key = (cap, dist)
        if key not in cache:
            near = {cap}
            frontier = {cap}
            for _ in range(dist):
                frontier = {v for u in frontier for v in self.world.land_adj[u]} - near
                near |= frontier
            cache[key] = near
        return cache[key]

    # ---- 생산 집중
    @staticmethod
    def focus_active(rr) -> bool:
        """건설·병력 생산을 하지 않는 동안에만 효과(편입은 해당 없음)."""
        return getattr(rr, "focus", False) and (rr.project is None or rr.project.kind == "annex")

    def set_focus(self, fid, rid, on):
        rr = self.regions[rid]
        if rr.owner != fid:
            return False, "내 지역이 아닙니다."
        rr.focus = bool(on)
        if on:
            rr.pop_focus = False             # 집중은 하나만
        return True, "생산 집중 " + (f"켬: 인구 산출 +{C.FOCUS_POP_BONUS:.0%}" if on else "끔")

    def set_pop_focus(self, fid, rid, on):
        rr = self.regions[rid]
        if rr.owner != fid:
            return False, "내 지역이 아닙니다."
        if on and self.growth_happy(rr) < C.POP_FOCUS_MIN_H:
            return False, f"행복도(전쟁 피로 제외) {C.POP_FOCUS_MIN_H} 이상에서만 쓸 수 있습니다."
        rr.pop_focus = bool(on)
        if on:
            rr.focus = False
        return True, "인구 성장 집중 " + (f"켬: 성장률 턴당 +{C.POP_FOCUS_GROWTH * 100:g}%p" if on else "끔")

    def pop_focus_active(self, rr) -> bool:
        """건설·병력 생산을 하지 않고 실질 행복도 5 이상일 때만 효과."""
        return (getattr(rr, "pop_focus", False) and (rr.project is None or rr.project.kind == "annex")
                and self.growth_happy(rr) >= C.POP_FOCUS_MIN_H)

    def crowd_thresholds(self, rid) -> tuple:
        """과밀 행복도 감소가 시작되는 인구 (−2, −4)."""
        p0 = self.info(rid).pop0
        for top, a, b in C.CROWD_TIERS:
            if top is None or p0 <= top:
                return p0 * (1 + a), p0 * (1 + b)

    def crowd_penalty(self, rr) -> float:
        """과밀: 시작 인구 대비 크게 늘면 그 지역 행복도 −2, 더 늘면 −4."""
        t1, t2 = self.crowd_thresholds(rr.id)
        if rr.pop >= t2:
            return C.CROWD_HAPPY[1]
        if rr.pop >= t1:
            return C.CROWD_HAPPY[0]
        return 0.0

    def growth_happy(self, rr) -> float:
        """인구 성장 판정용 행복도: 실질 행복도에서 전쟁 피로만 뺀 것(전쟁 피로는 성장에 영향 없음)."""
        if rr.owner == NEUTRAL:
            return rr.happy
        f = self.factions[rr.owner]
        h = (self.base_happy(rr) - rr.conscript - self.minority_penalty(rr.owner) + self.scenic_bonus(rr)
             + self.crowd_penalty(rr))
        if f.happy_floor_until > self.turn:
            h = max(0.0, h)
        return max(C.HAPPY_MIN, min(C.HAPPY_MAX, h))

    def region_output_estimate(self, rid):
        rr = self.regions[rid]
        if rr.output > 0 and rr.owner != NEUTRAL:
            return rr.output
        return self.calc_output(rid, full=True)

    def gdp(self, fid) -> float:
        return sum(r.output for r in self.regions.values() if r.owner == fid)

    # ------------------------------------------------------------------ 지역 이전
    def transfer_region(self, rid, new_owner, reason="점령"):
        rr = self.regions[rid]
        old = rr.owner
        if old == new_owner:
            return
        # 과학·경제 공사(과학 유닛 생산 포함): 적에게 점령당하면 멈춘다. 저항·회복 기간 안에 원래 주인이 되찾으면
        # 이어서 짓고, 그 밖(기간이 지남·다른 나라에 넘어감)이면 낸 돈의 50%를 돌려받는다
        lp = getattr(rr, "lost_project", None)
        resume = None
        if lp is not None:
            rs = rr.resist
            if (lp["fid"] == new_owner and rs and rs.get("from") == new_owner
                    and self.resist_phase(rr)[0] in ("resist", "recover")):
                resume = lp["project"]
            else:
                self._refund_lost_project(rr)
            rr.lost_project = None
        p = rr.project
        if p is not None and p.kind in ("science", "econ") and old != NEUTRAL:
            if new_owner != NEUTRAL and reason == "점령":
                p.stalled, p.funded = True, False
                rr.lost_project = {"fid": old, "project": p}
            else:
                rr.lost_project = {"fid": old, "project": p}
                self._refund_lost_project(rr)
                rr.lost_project = None
        rr.owner = new_owner
        rr.project = resume
        rr.econ = set()                  # 경제승리 시설은 점령당하면 사라진다
        prev_occs = dict(rr.occs)
        rr.occs = {}
        rr.supplied = set()
        rr.resist = None
        rr.mil_hist = 0
        rr.conscript = 0.0
        self.acq_counter = getattr(self, "acq_counter", 0) + 1
        rr.acquired_seq = self.acq_counter
        if old != NEUTRAL and new_owner != NEUTRAL:
            w = self.dip.wars.get(D.pair(old, new_owner))
            if w is not None:
                taken = w.setdefault("taken", {})
                taken[new_owner] = taken.get(new_owner, 0) + 1
        if old == NEUTRAL and new_owner != NEUTRAL:
            # 가로채기: 이 지역을 편입하던 다른 세력의 작업은 즉시 취소·환급
            for other in self.regions.values():
                p = other.project
                if p and p.kind == "annex" and p.key == rid and other.owner not in (NEUTRAL, new_owner):
                    self._cancel_hijacked(other, new_owner)
            for by in prev_occs:
                if by in (NEUTRAL, new_owner):
                    continue
                victim = self.factions[by]
                if victim.is_ai:
                    D.add_opinion(self, victim.id, new_owner, C.OP_HIJACK)
                self.event("info", f"{self.info(rid).name}을(를) {self.fname(new_owner)}이(가) 먼저 차지해 "
                           f"{victim.name}의 점령이 취소되었습니다.", region=rid, fids=(victim.id,))
        # 경쟁에서 진 세력의 병력은 (전쟁 중이 아니면) 자국 영토로 돌아간다
        if new_owner != NEUTRAL:
            for army in list(self.armies_at(rid)):
                if army.owner not in (NEUTRAL, new_owner, old) and not self.hostile(army.owner, new_owner) \
                        and not D.has_passage(self, army.owner, new_owner):
                    self.teleport_home(army)
            # 영토 경쟁: 이 중립 지역과 맞닿은 다른 세력은 먼저 가져간 쪽을 못마땅하게 여긴다
            rivals = {self.regions[n].owner for n in self.world.land_adj[rid]} - {NEUTRAL, new_owner}
            for b in rivals:
                if not D.allied(self, b, new_owner) and not D.at_war(self, b, new_owner):
                    D.add_opinion(self, b, new_owner, C.OP_LAND_GRAB)
        if old != NEUTRAL:
            for army in list(self.armies_at(rid, old)):
                self.teleport_home(army)
            f_old = self.factions[old]
            if f_old.capital == rid:
                rest = self.regions_of(old)
                if rest:
                    newcap = max(rest, key=lambda r: r.pop)
                    f_old.capital = newcap.id
                    f_old.capital_fall_turn = self.turn
                    for r in rest:
                        r.h_delta += C.CAPITAL_LOST_HAPPY
                    self.event("capital", f"{f_old.name}의 수도가 함락되어 {self.info(newcap.id).name}(으)로 천도했습니다.",
                               region=newcap.id, fids=(old,))
            if self.region_count(old) == 0:
                self.eliminate(old, by=new_owner)
        if new_owner != NEUTRAL:
            f = self.factions[new_owner]
            f.explored.add(rid)

    def _refund_lost_project(self, rr):
        """점령으로 멈춘 과학·경제 공사를 되찾지 못함: 원래 주인에게 낸 돈의 50% 환급."""
        lp = getattr(rr, "lost_project", None)
        if not lp:
            return
        rr.lost_project = None
        f = self.factions[lp["fid"]]
        p = lp["project"]
        if not f.alive or p.paid <= 0:
            return
        refund = p.paid * C.LOST_PROJECT_REFUND
        f.money += refund
        self.event("info", f"{self.info(rr.id).name}의 {p.name or p.key} 공사를 되찾지 못했습니다 — {refund:,.0f} 환급",
                   region=rr.id, fids=(f.id,))

    def eliminate(self, fid, by=None):
        f = self.factions[fid]
        if not f.alive:
            return
        if self._provisional_government(fid, by):
            return                                        # 김구 '임시정부': 멸망 대신 부활
        f.alive = False
        f.eliminated_turn = self.turn
        for r in self.regions.values():
            if r.owner == fid:
                r.owner = NEUTRAL
                r.project = None
                r.occ = None
        for a in list(self.armies.values()):
            if a.owner == fid:
                self.remove_army(a)
        for p in list(self.dip.wars):
            if fid in p:
                del self.dip.wars[p]
        for store in (self.dip.nonaggr, self.dip.passage, self.dip.alliance):
            for p in list(store):
                if fid in p:
                    del store[p]
        self.dip.friends = {p for p in self.dip.friends if fid not in p}
        cid = D.coalition_of(self, fid)
        if cid is not None:
            self.dip.coalitions[cid]["members"].discard(fid)
            if len(self.dip.coalitions[cid]["members"]) < 2:
                del self.dip.coalitions[cid]
        for r in self.regions.values():
            r.occs.pop(fid, None)
        who = f" ({self.fname(by)}에 의해)" if by not in (None, NEUTRAL) else ""
        self.event("eliminated", f"{f.name}이(가) 멸망했습니다{who}.", fids=(fid,))
        if by == self.player_id and fid != self.player_id:
            self.queue_dialogue("defeated", fid)          # 플레이어에게 멸망하는 지도자의 마지막 말
        elif fid == self.player_id and by not in (None, NEUTRAL):
            self.queue_dialogue("victory", by)            # 플레이어를 멸망시킨 지도자

    def _provisional_government(self, fid, by=None) -> bool:
        """김구 '임시정부': 멸망하면 한 번, 직전에 우호도가 가장 높던 나라(전쟁 중이 아닌)의
        국경 지역(수도 제외) 한 곳에서 그 나라와 동맹으로 부활한다. 부활하면 True."""
        f = self.factions[fid]
        if not self.mods(fid).value("provisional_gov") or getattr(f, "provisional_used", False):
            return False
        hosts = [x for x in self.alive_ids() if x not in (fid, by) and not D.at_war(self, fid, x)]
        hosts.sort(key=lambda x: (-D.opinion(self, fid, x), x))
        foes = set(D.enemies(self, fid))
        for host in hosts:
            cap = self.factions[host].capital
            border = [r.id for r in self.regions_of(host) if r.id != cap and not r.occ
                      and any(self.regions[n].owner != host for n in self.world.land_adj[r.id])]
            if not border:
                continue
            # 지금 싸우는 적과 맞닿지 않은 곳을 먼저 고른다(부활하자마자 다시 무너지지 않게)
            safe = [rid for rid in border if not any(self.regions[n].owner in foes for n in self.world.land_adj[rid])]
            rid = self.rng.choice(sorted(safe or border))
            f.provisional_used = True
            self.transfer_region(rid, fid, reason="임시정부")
            rr = self.regions[rid]
            f.capital = rid
            rr.happy = max(rr.happy, 0.0)
            f.happy_floor_until = self.turn + C.REBEL_HAPPY_FLOOR_TURNS
            self.new_army(fid, rid, {"inf": C.PROVISIONAL_INF})
            p = D.pair(fid, host)
            D._dip_attr(self, "declared")[p] = self.turn
            self.dip.nonaggr[p] = max(self.dip.nonaggr.get(p, 0), self.turn + C.TREATY_TURNS)
            self.dip.alliance[p] = self.turn
            for a, b in ((fid, host), (host, fid)):
                self.dip.op[(a, b)] = max(D.opinion(self, a, b), C.ALLIANCE_MIN)
            self._mods.pop(fid, None)
            self.event("capital", f"임시정부: {f.name}이(가) {self.fname(host)}의 {self.info(rid).name}에서 "
                                  f"다시 일어나 {self.fname(host)}와(과) 동맹을 맺었습니다.", region=rid, fids=(fid, host))
            return True
        return False

    def begin_occupation(self, fid, rid):
        rr = self.regions[rid]
        if rr.owner == fid or not self.hostile(fid, rr.owner):
            return
        if self.hostile_units_at(fid, rid):
            return
        if fid in rr.occs:
            return                              # 이미 점령 중(다른 세력의 점령과 별개로 진행)
        if rr.owner != NEUTRAL:
            # 적국 영토는 지키는 병력이 없으면 들어서는 즉시 차지하고 저항 기간이 시작된다
            self.complete_occupation(fid, rid)
            return
        need = self.neutral_turns(fid, rid)
        self.occ_seq = getattr(self, "occ_seq", 0) + 1
        rr.occs[fid] = {"by": fid, "progress": 0, "need": need, "seq": self.occ_seq}
        self.event("occupy", f"{self.fname(fid)}이(가) {self.info(rid).name} 점령을 시작했습니다 ({need}턴).",
                   region=rid, fids=(fid, rr.owner))

    def complete_occupation(self, fid, rid):
        """점령 완료. 다른 세력에게서 빼앗은 지역은 '저항' 상태로 시작한다(4턴 산출·생산 없음·행복도 −100,
        이후 24턴 동안 점령 직전 행복도로 회복, 36턴 동안 반란 없음)."""
        rr = self.regions[rid]
        old = rr.owner
        m = self.mods(fid)
        # 원래 주인이 저항·회복 중인 옛 땅을 되찾으면: 새 저항 없이 빼앗기기 전 행복도로 복구
        phase = self.resist_phase(rr)[0]
        retake = old != NEUTRAL and rr.resist and rr.resist.get("from") == fid and phase in ("resist", "recover")
        h_before = rr.resist.get("h0", rr.happy) if retake else rr.happy
        new_h = 0.0 if old == NEUTRAL else rr.happy + m.add("occupied_happy_extra")
        if old != NEUTRAL:
            D.add_war_score(self, fid, old, rr.pop)
        self.transfer_region(rid, fid)
        if retake:
            rr.happy = max(C.HAPPY_MIN, min(C.HAPPY_MAX, h_before))
            self.event("captured", f"{self.fname(fid)}이(가) {self.info(rid).name}을(를) 되찾았습니다 "
                       f"({self.fname(old)}에게서, 저항 없이 복구).", region=rid, fids=(fid, old))
            return
        rr.happy = max(C.HAPPY_MIN, min(C.HAPPY_MAX, new_h))
        if old != NEUTRAL:
            half = bool(m.value("wanggeon_occupy"))         # 왕건: 저항·회복 기간 절반
            n_res = C.RESIST_TURNS // 2 if half else C.RESIST_TURNS
            n_res = int(n_res * m.mult("resist_time") + 0.5)    # 광개토대왕 '약탈경제': +50%
            rr.resist = {"turn": self.turn, "from": old, "h0": h_before,
                         "resist": n_res,
                         "recover": C.RESIST_RECOVER_TURNS // 2 if half else C.RESIST_RECOVER_TURNS}
        self.event("captured", f"{self.fname(fid)}이(가) {self.info(rid).name}을(를) 차지했습니다"
                   + (f" ({self.fname(old)}에게서, 저항 {rr.resist['resist']}턴)." if old != NEUTRAL else "."),
                   region=rid, fids=(fid, old))

    # ------------------------------------------------------------------ 턴 종료
    def end_turn(self):
        if self.game_over:
            return
        from . import ai
        self.events = []
        self.battle_regions = []
        self.new_ranking = None
        self._morale = {}
        self._acted = set()
        # 대응하지 않은 플레이어 반란은 AI 규칙으로 처리
        for rid in list(self.pending_rebellions):
            rr = self.regions[rid]
            if rr.owner != NEUTRAL:
                ai.handle_rebellion(self, rr.owner, rid)
        self.pending_rebellions = []
        self.pending_proposals = []
        pf = self.player
        if pf.alive and not pf.is_ai and pf.ai.get("auto_slots"):
            ai.auto_slots(self, pf.id, military=pf.ai.get("auto_military", False))
        for f in self.factions:
            if f.alive and f.is_ai:
                ai.plan_turn(self, f.id)
        # 1. 외교: 제안·선전포고는 즉시 처리된다. 여기서는 턴 단위 갱신만.
        # 2~5. 이동 → 해전 → 폭격 → 지상 공격 (명령을 받은 부대는 이번 턴 회복하지 않는다)
        self._acted.update(a.id for a in self.armies.values() if a.order)
        self._phase_move()
        self._phase_naval()
        self._phase_bombard()
        self._phase_attack()
        self._phase_guerrilla()
        # 6. 점령·편입 (먼저 우선순위대로 이번 턴 지출을 정한다)
        self._fund_projects()
        self._phase_claims()                 # 무력 점령·편입: 게이지가 함께 차고 먼저 채운 쪽이 차지
        # 7. 건설·생산 (군 생산에 쓴 지역은 징집 피로 기록)
        drafted = self._phase_projects(("build", "unit", "science", "econ", "capital"))
        self._phase_conscription(drafted)
        # 8~9. 자원, 세수·유지비
        for f in self.factions:
            if f.alive:
                self._phase_resources(f)
                self._phase_tax(f)
        # 10~11. 인구, 행복도
        self._phase_population()
        self._phase_happiness()
        D.update_turn(self)
        self._update_power()
        self._check_victory()
        for f in self.factions:
            f.buy_count = {}
            f.trade_buy = 0.0
            f.trade_sell = 0.0
            f.spend = {}
            f.refund = 0.0
        # 전투·폭격·상륙으로 유닛이 줄어든 부대 정리(0대 항목, 없어진 유닛의 피해 기록, 빈 부대)
        for a in list(self.armies.values()):
            self._prune_army(a)
        self._phase_heal()
        for a in self.armies.values():
            if a.order and a.order.get("type") in ("move", "attack", "land", "bombard"):
                a.order = None
        self.turn += 1
        # 반기 랭킹: 해마다 1주차·25주차(첫해 제외, 첫 발표는 2년 차 1주차)
        if self.turn > C.TURNS_PER_YEAR and (self.turn - 1) % C.TURNS_PER_YEAR in C.RANKING_WEEKS:
            self._half_ranking()
        # 12. 다음 턴 시작: 반란 판정
        self._phase_rebellion()
        self._update_fog()
        self._advance_gotos()
        if self.player.alive and self.player.is_ai is False:
            ai.propose_to_player(self)

    # ---- 2. 이동
    def _phase_move(self):
        w = self.world
        movers = [a for a in self.armies.values() if a.order and a.owner != NEUTRAL]
        # 서로 맞바꾸는 이동은 경계에서 조우전
        land_moves = {}
        for a in movers:
            if a.domain() == "land" and a.order["type"] in ("move", "attack") and len(a.order.get("path", [])) >= 1:
                land_moves[a.id] = (a.loc, a.order["path"][0])
        done = set()
        for aid, (src, dst) in land_moves.items():
            for bid, (src2, dst2) in land_moves.items():
                if aid >= bid or aid in done or bid in done:
                    continue
                a, b = self.armies.get(aid), self.armies.get(bid)
                if not a or not b:
                    continue
                if src == dst2 and dst == src2 and self.hostile(a.owner, b.owner):
                    self._encounter(a, b)
                    done.update((aid, bid))
        self.rng.shuffle(movers)
        for a in movers:
            if a.id not in self.armies or not a.order:
                continue
            t = a.order["type"]
            if t == "move":
                self._exec_move(a, a.order["path"])
            elif t in ("attack", "land") and w.is_sea(a.loc) or (t in ("attack", "land") and a.domain() == "naval"):
                # 함대는 먼저 해역 경로를 따라 이동
                path = a.order.get("path", [])
                for node in path:
                    a.loc = node
                if t == "land":
                    self._unload(a, a.order["target"])

    def _encounter(self, a, b):
        pa = sum(C.UNITS[k]["atk"] * n for k, n in a.units.items())
        pb = sum(C.UNITS[k]["atk"] * n for k, n in b.units.items())
        r = self.rng.uniform(C.RAND_LO, C.RAND_HI)
        db, da = R.battle_damage(pa, pb, r)
        la = self.apply_damage([a], da)
        lb = self.apply_damage([b], db)
        border = f"{self.info(a.loc).name}–{self.info(b.loc).name}"
        self.event("battle", f"조우전({border}): {self.fname(a.owner)} 손실 {self.units_value(la):,.0f}, "
                   f"{self.fname(b.owner)} 손실 {self.units_value(lb):,.0f}", region=a.loc, fids=(a.owner, b.owner))
        self.battle_regions += [a.loc, b.loc]
        self._score_units(a.owner, b.owner, lb)
        self._score_units(b.owner, a.owner, la)
        a_alive, b_alive = a.id in self.armies, b.id in self.armies
        if a_alive and b_alive:
            a.order = None
            b.order = None
        elif a_alive:
            a.order = {"type": "move", "path": a.order["path"]}
        elif b_alive:
            b.order = {"type": "move", "path": b.order["path"]}

    def _score_units(self, winner, loser, lost):
        if winner != NEUTRAL and loser != NEUTRAL:
            D.add_war_score(self, winner, loser, self.units_value(lost) / 1000)
            w = self.dip.wars.get(D.pair(winner, loser))
            if w is not None and lost:
                kills = w.setdefault("kills", {})            # 강화 성과 판정용: 처치한 유닛 수
                kills[winner] = kills.get(winner, 0) + sum(lost.values())
            k = self.mods(loser).value("bounty")
            if k and lost:                       # 김원봉 '현상금': 잃은 유닛 생산비의 50%를 상대가 얻는다
                self.factions[winner].money += self.units_value(lost) * k * C.MONEY_SCALE

    def _exec_move(self, a, path):
        w = self.world
        for i, node in enumerate(path):
            if not w.is_sea(node) and self.hostile_units_at(a.owner, node):
                if node in w.land_adj.get(a.loc, ()) and a.domain() == "land":
                    a.order = {"type": "attack", "target": node, "mode": "assault", "path": [node]}
                else:
                    a.order = None
                return
            a.loc = node
        a.order = None
        if not w.is_sea(a.loc) and a.domain() == "land":
            rr = self.regions[a.loc]
            if self.hostile(a.owner, rr.owner):
                self.begin_occupation(a.owner, a.loc)

    def _unload(self, a, target):
        cargo = {k: n for k, n in a.units.items() if C.UNITS[k]["kind"] == "land"}
        if not cargo:
            return
        for k in cargo:
            a.units.pop(k)
            a.dmg.pop(k, None)
        self.new_army(a.owner, target, cargo)
        a.order = None

    # ---- 3. 해전
    def _phase_naval(self):
        for sid in self.world.seas:
            fleets = [a for a in self.armies_at(sid) if a.domain() == "naval"]
            owners = sorted({a.owner for a in fleets})
            for i, x in enumerate(owners):
                for y in owners[i + 1:]:
                    if not D.at_war(self, x, y):
                        continue
                    fx = [a for a in self.armies_at(sid, x) if a.domain() == "naval"]
                    fy = [a for a in self.armies_at(sid, y) if a.domain() == "naval"]
                    if fx and fy:
                        self._naval_battle(sid, x, fx, y, fy)

    def _naval_power(self, fid, fleets, sid):
        p = sum(C.NAVAL_DD_POWER * a.units.get("dd", 0) + C.NAVAL_BMB_POWER * a.units.get("bmb", 0) for a in fleets)
        if self.coast_controller(sid) == fid:
            p *= 1 + C.COAST_NAVAL_DEF
        return p * self.morale(fid) * self.lead_mult(fid, "naval_power")   # 이순신: 해전 +30%

    def naval_buff_off(self, fid) -> bool:
        """이순신 '백의종군': 해전에서 진 뒤 12턴 동안 해군 버프 비활성."""
        return getattr(self.factions[fid], "naval_off_until", 0) > self.turn

    def lead_mult(self, fid, key) -> float:
        """mods.mult(key). 백의종군 중이면 지도자 해군 버프분을 뺀다."""
        v = self.mods(fid).mult(key)
        if key in ("naval_power", "naval_bomb") and self.naval_buff_off(fid):
            lv = LEADER_BY_KEY.get(self.factions[fid].leader, {}).get("fx", {}).get(key, 0)
            v /= 1 + lv
        return v

    def _naval_battle(self, sid, x, fx, y, fy):
        px, py = self._naval_power(x, fx, sid), self._naval_power(y, fy, sid)
        if px <= 0 and py <= 0:
            return
        r = self.rng.uniform(C.RAND_LO, C.RAND_HI)
        dy, dx = R.battle_damage(px, py, r)
        for loser, lp, wp in ((x, px, py), (y, py, px)):
            off = self.mods(loser).value("naval_loss_off")
            if off and lp < wp:
                self.factions[loser].naval_off_until = self.turn + off
                self.event("info", f"{self.fname(loser)}: 해전 패배로 {off}턴 동안 "
                           f"{self.fx_source(loser, 'naval_loss_off')} — 해군 버프 비활성", fids=(loser,))
        lx = self._ship_damage(fx, dx, y, sid)
        ly = self._ship_damage(fy, dy, x, sid)
        self._score_units(x, y, ly)
        self._score_units(y, x, lx)
        self.event("battle", f"해전({self.world.seas[sid].name}): {self.fname(x)} 손실 {sum(lx.values())}척, "
                   f"{self.fname(y)} 손실 {sum(ly.values())}척", fids=(x, y))

    def _ship_damage(self, fleets, dmg, enemy, sid):
        lost = {}
        self.__dict__.setdefault("_acted", set()).update(a.id for a in fleets)
        for key in ("dd", "cv", "lst"):
            for a in fleets:
                if a.id not in self.armies:
                    continue
                hp = C.UNITS[key]["hp"]
                while a.units.get(key, 0) > 0 and a.dmg.get(key, 0.0) >= hp:
                    a.units[key] -= 1                # 합칠 때 합산된 누적 피해가 한 척 체력을 넘으면
                    a.dmg[key] -= hp
                    lost[key] = lost.get(key, 0) + 1
                while dmg > 0 and a.units.get(key, 0) > 0:
                    need = hp - a.dmg.get(key, 0.0)
                    if dmg >= need:
                        dmg -= need
                        a.units[key] -= 1
                        a.dmg[key] = 0.0
                        lost[key] = lost.get(key, 0) + 1
                        if self.rng.random() < C.CAPTURE_CHANCE:
                            ea = self.armies_at(sid, enemy)
                            if ea:
                                self._add_to_army(ea[0], key, 1)
                    else:
                        a.dmg[key] = a.dmg.get(key, 0.0) + dmg
                        dmg = 0
        for a in fleets:
            if a.id in self.armies:
                a.units = {k: v for k, v in a.units.items() if v > 0}
                self._validate_capacity(a)
                # 배가 모두 가라앉으면 타고 있던 병력·항공기도 잃는다
                if a.empty() or a.domain() != "naval":
                    self.remove_army(a)
        return lost

    # ---- 4. 폭격
    def _phase_bombard(self):
        orders = [a for a in self.armies.values() if a.order and a.order["type"] == "bombard"]
        self.rng.shuffle(orders)
        for a in orders:
            if a.id not in self.armies:
                continue
            tgt = a.order["target"]
            if self.world.is_sea(tgt) or not self.hostile(a.owner, self.regions[tgt].owner):
                continue
            units = self._bombard_units(a, tgt)
            if units:
                self._bombard(a, tgt, units)

    def air_defense(self, fid_att, tgt):
        """폭격기를 요격하는 힘: 대상 지역 대공포(단계당 10, 최대 5단계) + 대상·인접 지역의 적 전투기(대당 30)."""
        rr = self.regions[tgt]
        aa = min(C.AA_MAX_LEVEL, rr.b["aa"]) if rr.owner != NEUTRAL else 0
        ftr = sum(x.units.get("ftr", 0) for loc in [tgt] + list(self.world.land_adj[tgt])
                  for x in self.hostile_units_at(fid_att, loc))
        return aa * C.AA_PER_LEVEL + ftr * C.UNITS["ftr"]["intercept"], aa, ftr

    def _bombard(self, a, tgt, units):
        rr = self.regions[tgt]
        m = self.mods(a.owner)
        notes = []
        n_bmb = units.get("bmb", 0)
        if n_bmb:
            # 요격: 대공포·전투기가 폭격 전에 폭격기에 피해(전투기는 반격받지 않는다)
            ad, aa, ftr = self.air_defense(a.owner, tgt)
            if ad > 0:
                hit = C.DAMAGE_K * self.rng.uniform(C.RAND_LO, C.RAND_HI) * ad
                shot = self.apply_damage([a], hit, unit_filter=("bmb",)).get("bmb", 0)
                if shot:
                    notes.append(f"폭격기 {shot}대 격추(대공포 {aa}단계·전투기 {ftr}대)")
            n_bmb = a.units.get("bmb", 0) if a.id in self.armies else 0
        dmg = units.get("art", 0) * C.UNITS["art"]["bomb"] * m.mult("bomb_art")
        dmg += units.get("dd", 0) * C.UNITS["dd"]["bomb"] * self.lead_mult(a.owner, "naval_bomb")
        dmg += n_bmb * C.UNITS["bmb"]["bomb"]
        bombers = {"bmb": n_bmb}
        dmg *= self.rng.uniform(C.RAND_LO, C.RAND_HI) / (1 + C.SHELTER_K * rr.b["shelter"])
        dmg *= self.morale(a.owner)
        defenders = self.hostile_units_at(a.owner, tgt)
        lost = self.apply_damage(defenders, dmg, spread="random") if defenders else {}
        self._score_units(a.owner, rr.owner, lost)
        # 건물 피해: 포병·함포 30%, 폭격기 60%, 둘 다 90%로 생산·방어 건물(방어선 포함) 하나 −1단계
        guns = units.get("art", 0) + units.get("dd", 0) > 0
        p = R.bomb_building_chance(guns, sum(bombers.values()) > 0)
        if p and self.rng.random() < p:
            hit = self.bomb_targets(tgt)
            if units.get("dd", 0) and rr.b.get("port"):
                hit = ["port"]                    # 함포 사격은 항구를 먼저 노린다(상륙·해군 기지 무력화)
            if hit:
                k = self.rng.choice(hit)
                if k.startswith("line:"):
                    border = k[5:]
                    rr.lines[border] -= 1
                    nm = "해안선" if border == "coast" else self.info(border).name
                    notes.append(f"방어선({nm}) 1단계 파괴")
                else:
                    rr.b[k] -= 1
                    notes.append(f"{BUILDING_NAMES.get(k, k)} 1단계 파괴")
        if not rr.bombed:
            rr.h_delta += C.BOMBED_HAPPY
            rr.bombed = True
        if a.id in self.armies and a.empty():
            self.remove_army(a)
        self.battle_regions.append(tgt)
        self.event("bomb", f"{self.fname(a.owner)} → {self.info(tgt).name} 폭격: 피해 {dmg:.1f}"
                   + (f", 격파 {sum(lost.values())}" if lost else "") + ("; " + ", ".join(notes) if notes else ""),
                   region=tgt, fids=(a.owner, rr.owner))

    # ---- 5. 지상 공격
    def bomb_targets(self, rid):
        """폭격으로 부술 수 있는 건물: 생산 건물·방공호·대공포 키와 'line:경계' 방어선."""
        rr = self.regions[rid]
        out = [k for k in list(C.PROD_BUILDINGS) + ["shelter", "aa"] if rr.b.get(k, 0) > 0]
        out += [f"line:{b}" for b, lv in sorted(rr.lines.items()) if lv > 0]
        return out

    def multi_attack_on(self, fid, target) -> bool:
        """홍길동 '신출귀몰': 이번 턴 target 주인의 지역을 두 곳 이상 공격하는가(미리보기는 target 포함)."""
        o = self.regions[target].owner
        if not self.mods(fid).value("multi_attack") or o == NEUTRAL or o == fid:
            return False
        return len(self.attack_targets(fid, o) | {target}) >= 2

    def attack_targets(self, fid, owner) -> set:
        """이번 턴 fid 가 owner 의 지역 중 공격 명령을 내린 곳(홍길동 '신출귀몰' 판정)."""
        snap = getattr(self, "_attack_snap", None)
        if snap is None:
            snap = self._attack_orders_by_owner()
        return snap.get((fid, owner), set())

    def _attack_orders_by_owner(self) -> dict:
        out = {}
        for a in self.armies.values():
            if a.owner != NEUTRAL and a.order and a.order["type"] == "attack":
                tgt = a.order["target"]
                o = self.regions[tgt].owner if tgt in self.regions else NEUTRAL
                if o != NEUTRAL:
                    out.setdefault((a.owner, o), set()).add(tgt)
        return out

    def _phase_attack(self):
        orders = [a for a in self.armies.values() if a.order and a.order["type"] == "attack"]
        self._attack_snap = self._attack_orders_by_owner()
        try:
            self._phase_attack_inner(orders)
        finally:
            self._attack_snap = None

    def _phase_attack_inner(self, orders):
        by_target = {}
        for a in orders:
            by_target.setdefault(a.order["target"], []).append(a)
        for mode in ("surprise", "assault"):
            targets = list(by_target)
            self.rng.shuffle(targets)
            for tgt in targets:
                groups = {}
                for a in by_target[tgt]:
                    if a.id in self.armies and a.order and a.order.get("mode", "assault") == mode:
                        groups.setdefault(a.owner, []).append(a)
                fids = list(groups)
                self.rng.shuffle(fids)
                for fid in fids:
                    valid = [a for a in groups[fid] if self._attack_valid(a, tgt)]
                    if valid:
                        self._ground_battle(fid, valid, tgt, mode, by_target[tgt])

    def _attack_valid(self, a, tgt):
        w = self.world
        if a.id not in self.armies:
            return False
        rr = self.regions[tgt]
        if w.is_sea(a.loc):
            ok = tgt in w.seas[a.loc].coast and a.count(("land",)) > 0
        else:
            ok = tgt in w.land_adj[a.loc]
        if not ok:
            return False
        if rr.owner == a.owner and not self.hostile_units_at(a.owner, tgt):
            return False
        return self.hostile(a.owner, rr.owner) or bool(self.hostile_units_at(a.owner, tgt))

    def _ground_battle(self, fid, armies, tgt, mode, all_attackers):
        w = self.world
        rr = self.regions[tgt]
        # 상륙: 함대에서 병력을 내려 공격 부대로
        attackers = []
        for a in armies:
            if w.is_sea(a.loc):
                cargo = {k: n for k, n in a.units.items() if C.UNITS[k]["kind"] == "land"}
                lst = a.units.get("lst", 0)
                for k in cargo:
                    a.units.pop(k)
                    a.dmg.pop(k, None)
                land = self.new_army(fid, a.loc, cargo)
                land.order = {"type": "attack", "target": tgt, "mode": mode}
                attackers.append(land)
                if lst and mode == "assault":
                    attackers.append(a)
            else:
                attackers.append(a)
        defenders = self.hostile_units_at(fid, tgt)
        if not defenders:
            self._advance(fid, attackers, tgt)
            return
        A, sources, main = self.combat_strength(fid, attackers, tgt, mode)
        if mode == "assault":
            ally_src = {x.loc for x in all_attackers if x.owner != fid and x.id in self.armies
                        and D.allied(self, fid, x.owner)}
            n = len(sources | ally_src)
            A *= 1 + C.FLANK_BONUS * (n - 1)
        Dv, defenders, line = self.defense_strength(fid, tgt, main, mode)
        r = self.rng.uniform(C.RAND_LO, C.RAND_HI)
        dd, ad = R.battle_damage(A, Dv, r)
        note = ""
        if mode == "surprise":
            lv = rr.lines.get(main, 0)
            win, fail = R.surprise_mults(lv)
            if self.rng.random() < R.surprise_chance(lv, self.mods(fid).add("surprise")):
                dd *= win[0]
                ad *= win[1]
                note = "기습 성공"
                if self.mods(fid).value("sabotage") and any(a.units.get("inf") for a in attackers):
                    note += self._sabotage(rr)               # 김원봉 '의열단'
            else:
                dd *= fail[0]
                ad *= fail[1]
                note = "기습 실패"
        elif line > 0 and dd > ad and rr.owner != NEUTRAL and self.rng.random() < C.ASSAULT_LINE_BREAK:
            rr.lines[main] = line - 1          # 돌격에 밀린 방어선이 무너진다
            note = f"방어선 {line} → {line - 1}단계"
        filt = C.SURPRISE_UNITS if mode == "surprise" else C.ASSAULT_UNITS
        def_owner = defenders[0].owner if defenders else rr.owner
        dd, ad = self._leader_battle_mods(fid, def_owner, attackers, defenders, main, tgt, dd, ad)
        # 지원 전투기는 기여한 전력 비율만큼 피해를 나눠 입는다
        a_air, a_air_arms = self.air_support(fid, tgt, True)
        a_air *= self.morale(fid)
        d_air, d_air_arms = (self.air_support(rr.owner, tgt, False) if rr.owner != NEUTRAL else (0.0, []))
        d_air *= self.morale(rr.owner) if rr.owner != NEUTRAL else 1.0
        base_a = A / (1 + C.FLANK_BONUS * (n - 1)) if mode == "assault" else A
        fa = min(0.9, a_air / base_a) if base_a > 0 and a_air_arms else 0.0
        # 돌격의 방어측 피해는 전차 > 보병 > 포병 > 공군(지원 전투기 포함) 순서로 채운다(기습은 비율대로)
        pool = list(defenders) + [x for x in d_air_arms if x not in defenders]
        lost_d = self.apply_damage(pool, dd, order=C.ASSAULT_DAMAGE_ORDER if mode == "assault" else None)
        lost_a = self.apply_damage([x for x in attackers if x.id in self.armies], ad * (1 - fa), unit_filter=filt)
        if fa:
            for k, v in self.apply_damage(a_air_arms, ad * fa, unit_filter=("ftr",)).items():
                lost_a[k] = lost_a.get(k, 0) + v
        self._score_units(fid, def_owner, lost_d)
        self._score_units(def_owner, fid, lost_a)
        self.battle_regions.append(tgt)
        self.event("battle", f"{'기습' if mode == 'surprise' else '돌격'}: {self.fname(fid)} → {self.info(tgt).name}"
                   f" (A {A:.1f} / D {Dv:.1f}{', ' + note if note else ''}) 공격측 손실 {sum(lost_a.values())},"
                   f" 방어측 손실 {sum(lost_d.values())}", region=tgt, fids=(fid, def_owner, rr.owner))
        # 남은 상륙 병력이 바다에 있으면 함대로 복귀
        survivors = [x for x in attackers if x.id in self.armies]
        if not self.hostile_units_at(fid, tgt):
            self._advance(fid, survivors, tgt)
        else:
            for x in survivors:
                x.order = None
                if w.is_sea(x.loc) and x.domain() == "land":
                    fleet = next((f for f in self.armies_at(x.loc, fid) if f.domain() == "naval"), None)
                    if fleet:
                        self.merge_armies(fleet.id, x.id)
                    else:
                        self.remove_army(x)

    def _leader_battle_mods(self, fid, def_owner, attackers, defenders, main, tgt, dd, ad):
        """지도자 전투 효과로 (방어측 피해, 공격측 피해) 보정."""
        am = self.mods(fid)
        dm = self.mods(def_owner) if def_owner != NEUTRAL else None
        # 강감찬 '귀주대첩': 강을 건너 공격해 온 적의 피해 +50%
        if dm is not None and dm.mult("river_def_dmg") != 1.0 and main and main != "coast":
            terr = self.world.terrain_between(main, tgt)
            if terr and terr["kind"] == "도하":
                ad *= dm.mult("river_def_dmg")
        # 맥아더 '자기과신': 상대 병력이 더 많은 전투에서 받는 피해 +20%
        n_att = sum(a.count(("land",)) for a in attackers if a.id in self.armies)
        n_def = sum(a.count() for a in defenders)
        if n_def > n_att:
            ad *= am.mult("outnumbered_dmg")
        if dm is not None and n_att > n_def:
            dd *= dm.mult("outnumbered_dmg")
        # 스탈린 '대숙청': 전투에서 지면(준 피해보다 받은 피해가 크면) 받는 피해 +3(보병 체력 10 기준)
        if ad > dd and am.value("loss_dmg"):
            ad += am.value("loss_dmg")
        elif dd > ad and dm is not None and dm.value("loss_dmg"):
            dd += dm.value("loss_dmg")
        return dd, ad

    def _sabotage(self, rr) -> str:
        """김원봉 '의열단': 대상 지역의 생산·군사 건물 하나를 1단계 낮춘다."""
        keys = [k for k in list(C.PROD_BUILDINGS) + list(C.DEF_BUILDINGS) + list(C.SINGLE_BUILDINGS)
                if k in rr.b and k != "line" and rr.b[k] > 0]
        if not keys:
            return ""
        k = self.rng.choice(sorted(keys))
        rr.b[k] -= 1
        return f", 의열단 파괴: {BUILDING_NAMES.get(k, k)} {rr.b[k] + 1} → {rr.b[k]}단계"

    def _phase_heal(self):
        """이번 턴에 이동·공격·폭격·점령을 하지 않고 전투에도 휘말리지 않은 부대는 체력 10% 회복."""
        acted = self.__dict__.get("_acted", set())
        for a in self.armies.values():
            if not a.dmg or a.id in acted or a.order or a.owner == NEUTRAL:
                continue
            rr = self.regions.get(a.loc)
            if rr is not None and a.owner in rr.occs:
                continue                     # 점령 중
            for k in list(a.dmg):
                d = a.dmg[k] - C.HEAL_RATE * a.hp_max(k)
                if d > 1e-9:
                    a.dmg[k] = d
                else:
                    del a.dmg[k]

    def _phase_guerrilla(self):
        """이토 히로부미 '정미의병': 저항 중인 점령지의 주둔 부대가 보병 2개와 (보정 없이) 싸운 만큼 피해."""
        for f in self.factions:
            n = f.alive and self.mods(f.id).value("guerrilla")
            if not n:
                continue
            for rr in self.regions_of(f.id):
                if not self.resisting(rr):
                    continue
                arms = [a for a in self.armies_at(rr.id, f.id) if a.domain() == "land"]
                if not arms:
                    continue
                A = C.UNITS["inf"]["atk"] * n
                Dv = sum(C.UNITS[k]["df"] * c for a in arms for k, c in a.units.items())
                dmg = R.battle_damage(A, Dv, self.rng.uniform(C.RAND_LO, C.RAND_HI))[0]
                lost = self.apply_damage(arms, dmg)
                if lost:
                    self.event("battle", f"의병 습격: {self.info(rr.id).name}의 {f.name} 주둔군 손실 "
                               f"{sum(lost.values())}", region=rr.id, fids=(f.id,))

    def _advance(self, fid, attackers, tgt):
        moved = False
        for x in attackers:
            if x.id not in self.armies:
                continue
            x.order = None
            if x.domain() == "naval":
                continue
            x.loc = tgt
            moved = True
        if moved:
            rr = self.regions[tgt]
            if self.hostile(fid, rr.owner):
                self.begin_occupation(fid, tgt)

    # ---- 6. 점령
    def _advance_occupations(self):
        """무력 점령 게이지를 올린다. 이번 턴에 다 찬 (지역, 세력) 목록을 돌려준다.
        여러 세력이 같은 지역을 동시에 점령할 수 있고, 다른 세력 병력이 들어와도 점령은 끊기지 않는다
        (적대 병력이 있는 동안만 멈춘다). 내 병력이 떠나거나 더는 적대 관계가 아니면 내 점령만 취소된다."""
        done = []
        for rr in self.regions.values():
            for fid in list(rr.occs):
                o = rr.occs[fid]
                if not self.factions[fid].alive or not self.hostile(fid, rr.owner):
                    del rr.occs[fid]
                    continue
                if not any(a.count(("land",)) > 0 for a in self.armies_at(rr.id, fid)):
                    del rr.occs[fid]
                    self.event("occupy", f"{self.info(rr.id).name} 점령이 중단되었습니다.", region=rr.id, fids=(fid,))
                    continue
                if self.hostile_units_at(fid, rr.id):
                    continue
                o["progress"] += 1
                if o["progress"] >= o["need"]:
                    done.append((rr.id, fid))
        return done

    def rival_left(self, fid, rid) -> int | None:
        """fid 외 다른 세력이 이 지역을 차지하기까지 남은 턴(무력 점령·편입 중 가장 빠른 것). 없으면 None."""
        rr = self.regions[rid]
        best = None
        for by, o in rr.occs.items():
            if by != fid:
                left = max(0, o["need"] - o["progress"])
                best = left if best is None else min(best, left)
        for r in self.regions.values():
            p = r.project
            if p and p.kind == "annex" and p.key == rid and r.owner not in (fid, NEUTRAL):
                left = self.project_left(r.id)
                best = left if best is None else min(best, left)
        return best

    def claim_pop(self, fid, rid) -> float:
        """동시에 완료됐을 때의 우선순위: 대상과 맞닿은 내 지역들의 인구 합."""
        regs = {n: self.regions[n] for n in self.world.land_adj[rid] if self.regions[n].owner == fid}
        regs.update({r.id: r for r in self.regions.values() if r.owner == fid and r.project
                     and r.project.kind == "annex" and r.project.key == rid})
        return sum(r.pop for r in regs.values())

    def _phase_claims(self):
        """6. 점령·편입: 무력 점령과 편입 게이지가 함께 차고, 먼저 다 채운 쪽이 그 지역을 차지한다.
        같은 턴에 둘 이상이 다 채우면 대상과 맞닿은 지역의 인구 합이 많은 쪽이 차지한다."""
        claims = {}
        for rid, fid in self._advance_occupations():
            claims.setdefault(rid, []).append(("occ", fid, None))
        for (fid, tgt), (lead, members) in self._advance_annexes().items():
            claims.setdefault(tgt, []).append(("annex", fid, (lead, members)))
        for rid, cl in claims.items():
            if len(cl) > 1:
                cl.sort(key=lambda c: (-self.claim_pop(c[1], rid), c[1]))
                names = ", ".join(self.fname(c[1]) for c in cl)
                self.event("info", f"{self.info(rid).name}: {names}이(가) 같은 턴에 점령·편입을 마쳐 "
                           f"맞닿은 지역 인구 합이 가장 많은 {self.fname(cl[0][1])}이(가) 차지합니다.",
                           region=rid, fids=tuple(c[1] for c in cl))
            kind, fid, extra = cl[0]
            if kind == "occ":
                if fid in self.regions[rid].occs:
                    self.complete_occupation(fid, rid)
            else:
                lead, members = extra
                p = lead.project
                if p is None or p.key != rid:
                    continue
                for r in members:
                    r.project = None
                self._complete_project(self.factions[fid], lead, p)
                if len(members) > 1:
                    self.event("complete", f"{self.info(rid).name}: {len(members)}개 지역 공동 편입 완료",
                               region=rid, fids=(fid,))
        # 경쟁에서 진 편입(대상이 이미 다른 세력 땅)은 다음 턴을 기다리지 않고 바로 취소·전액 환급
        for rr in self.regions.values():
            p = rr.project
            if p and p.kind == "annex" and rr.owner != NEUTRAL and self.regions[p.key].owner != NEUTRAL:
                self._cancel_hijacked(rr, self.regions[p.key].owner)

    # ---- 6~7. 슬롯 진행
    def _fund_projects(self):
        """세력마다 우선순위 순서로 이번 턴 비용을 낸다. 모자라면 그 작업은 정지(뒤의 더 싼 작업은 진행 가능)."""
        for f in self.factions:
            if not f.alive:
                continue
            self._reserve_food(f)          # 식량 부족이 예상되면 식량 구매가 최우선
            self._check_econ_projects(f)   # 경제 단계 건설 중 조건이 깨졌으면 중단·환급
            for rr in self.projects_by_priority(f.id):
                p = rr.project
                p.funded = False
                if rr.occ:
                    p.stalled = True
                    continue
                if p.kind == "annex":
                    tgt = self.regions[p.key]
                    if tgt.owner != NEUTRAL:
                        self._cancel_hijacked(rr, tgt.owner)
                        continue
                if f.money < p.per_turn:
                    p.stalled = True
                    continue
                f.money -= p.per_turn
                p.paid += p.per_turn
                f.spend[p.kind] = f.spend.get(p.kind, 0.0) + p.per_turn
                p.funded = True
                p.stalled = False

    def food_prod(self, fid, r) -> float:
        """한 지역의 식량 생산(스탈린 '집단농장' 농장 +15%, 마오쩌둥 '해로운 새' −15%)."""
        m = self.mods(fid)
        return R.food_output(r.b["farm"] * m.mult("output_farm"), r.b["fishery"],
                             self.fish_mult(fid, r.id)) * m.mult("food_prod")

    def expected_food_balance(self, f) -> float:
        """이번 턴 자원 단계 뒤 예상 식량 비축(비축 + 생산 − 소비)."""
        regs = self.regions_of(f.id)
        prod = sum(0.0 if r.occ or self.resisting(r) else
                   self.food_prod(f.id, r) for r in regs)
        cons = sum(r.pop for r in regs) * C.FOOD_PER_POP
        return f.res.get("food", 0) + prod - cons

    def _reserve_food(self, f):
        if f.auto_food:
            short = self.expected_food_balance(f)
            if short < 0:
                self.market_buy(f.id, "food", math.ceil(-short))

    def _cancel_hijacked(self, rr, taker):
        """편입하던 중립 지역을 다른 세력이 가져감: 작업 취소, 낸 비용 전액 환급, 빼앗긴 AI는 우호도 하락."""
        p = rr.project
        f = self.factions[rr.owner]
        f.money += p.paid
        f.refund += p.paid
        rr.project = None
        if taker not in (NEUTRAL, f.id):
            if f.is_ai:
                D.add_opinion(self, f.id, taker, C.OP_HIJACK)
            self.event("info", f"{self.info(p.key).name}을(를) {self.fname(taker)}이(가) 먼저 차지해 "
                       f"{self.info(rr.id).name}의 편입이 취소되었습니다 (환급 {p.paid:,.0f}).",
                       region=p.key, fids=(f.id, taker))

    def _phase_projects(self, kinds):
        """진행. 이번 턴 군 유닛 생산에 쓴 지역 ID 집합을 돌려준다."""
        drafted = set()
        for rr in list(self.regions.values()):
            p = rr.project
            if not p or p.kind not in kinds or p.kind == "annex" or rr.owner == NEUTRAL \
                    or not getattr(p, "funded", False):
                continue
            f = self.factions[rr.owner]
            p.funded = False
            p.progress += 1
            if p.kind == "unit":
                drafted.add(rr.id)
            if p.progress >= p.turns:
                rr.project = None
                self._complete_project(f, rr, p)
        return drafted

    def project_left(self, rid) -> int:
        """남은 턴. 공동 편입은 함께하는 지역 수에 따른 속도로 계산."""
        rr = self.regions[rid]
        p = rr.project
        if not p:
            return 0
        rest = max(0.0, p.turns - p.progress)
        if p.kind == "annex":
            # 공동 편입: 함께하는 지역들의 진행도는 공유된다(막 합류한 지역도 가장 앞선 진행도 기준)
            members = [r.project for r in self.regions.values() if r.owner == rr.owner and r.project
                       and r.project.kind == "annex" and r.project.key == p.key]
            n = len(members)
            rest = max(0.0, max(m.turns for m in members) - max(m.progress for m in members))
            rest *= 1 - R.joint_reduction(n)
        return max(1, math.ceil(rest - 1e-9)) if rest > 0 else 0

    def joint_count(self, fid, target) -> int:
        return sum(1 for r in self.regions.values()
                   if r.owner == fid and r.project and r.project.kind == "annex" and r.project.key == target)

    def _advance_annexes(self):
        """편입 게이지를 올린다(같은 세력이 같은 대상을 여러 지역에서 편입하면 진행도를 함께 쌓는다).
        이번 턴에 다 찬 것을 {(세력, 대상): (대표 지역, 참여 지역들)} 로 돌려준다."""
        groups = {}
        for rr in self.regions.values():
            p = rr.project
            if p and p.kind == "annex" and rr.owner != NEUTRAL:
                groups.setdefault((rr.owner, p.key), []).append(rr)
        done = {}
        for (fid, tgt), members in groups.items():
            funded = [rr for rr in members if getattr(rr.project, "funded", False)]
            if not funded:
                continue
            step = 1 / (1 - R.joint_reduction(len(funded)))
            prog = max(rr.project.progress for rr in members) + step
            for rr in members:
                rr.project.progress = prog
                rr.project.funded = False
            need = max(rr.project.turns for rr in members)
            if prog >= need - 1e-9:
                done[(fid, tgt)] = (max(funded, key=lambda r: r.project.paid), members)
        return done

    def _complete_project(self, f, rr, p):
        name = self.info(rr.id).name
        if p.kind == "build":
            if p.key == "line":
                rr.lines[p.border] = p.level
                nm = "해안선" if p.border == "coast" else self.info(p.border).name
                text = f"{name} 방어선({nm}) {p.level}단계 완공"
            else:
                rr.b[p.key] = p.level
                text = (f"{name} {self.building_name(rr.id, p.key, p.level)} 완공" if p.key in C.PROD_LEVEL_NAMES
                        else f"{name} {self.building_name(rr.id, p.key)} {p.level}단계 완공")
        elif p.kind == "unit":
            self.add_units(f.id, rr.id, p.key, 1)
            text = f"{name}에서 {C.UNITS[p.key]['name']} 생산 완료"
        elif p.kind == "annex":
            tgt = self.regions[p.key]
            garrison = [a for a in self.armies_at(tgt.id) if a.owner == NEUTRAL]
            self.transfer_region(tgt.id, f.id, reason="편입")
            tgt.happy = 0.0
            for a in garrison:
                a.owner = f.id
            text = f"{self.info(tgt.id).name} 편입 완료"
            self.event("captured", f"{f.name}이(가) {self.info(tgt.id).name}을(를) 편입했습니다.",
                       region=tgt.id, fids=(f.id,))
        elif p.kind == "science":
            spec = C.SCIENCE[p.key]
            if spec["unit"]:
                self.add_units(f.id, rr.id, p.key, 1)
            else:
                rr.sci.add(p.key)
            if p.key not in f.science:
                f.science.append(p.key)
            k = C.SCIENCE_STEPS.index(p.key) + 1
            text = f"{name} 과학 {k}단계 「{spec['name']}」 완료!"
            if k == len(C.SCIENCE_STEPS):
                text += " 세 유닛을 발사대 지역에 모으고 턴을 마치면 발사합니다."
            self.event("science", f"{f.name}이(가) 과학 {k}단계 「{spec['name']}」을(를) 완료했습니다.",
                       region=rr.id, fids=(f.id,))
        elif p.kind == "econ":
            spec = C.ECON[p.key]
            rr.econ.add(p.key)
            text = f"{name} {spec['name']} 완공!"
            self.event("econ", f"{f.name}이(가) {name}에 {spec['name']}을(를) 세웠습니다.", region=rr.id, fids=(f.id,))
            if p.key == "ifc":
                self.econ_alert(f.id, f"{f.name}이(가) 국제금융센터를 완공했습니다. 기축통화 지정만 남았습니다!")
            if p.key == "currency":
                self._win((f.id,), "economic")
        elif p.kind == "capital":
            f.capital = rr.id
            for r in self.regions_of(f.id):
                r.h_delta += C.CAPITAL_MOVE_HAPPY
            text = f"{name}(으)로 천도 완료"
        else:
            text = "완료"
        self.event("complete", text, region=rr.id, fids=(f.id,))

    # ---- 8. 자원
    def _phase_resources(self, f: Faction):
        regs = self.regions_of(f.id)
        active = [r for r in regs if not r.occ and not self.resisting(r)]   # 점령당하는 중·저항 지역은 생산 없음
        res = f.res
        made = {}
        for r in active:
            info = self.info(r.id)
            if r.b["specialty"]:
                for sp in info.specialties:
                    made[sp] = made.get(sp, 0) + r.b["specialty"]
        tithe = self.mods(f.id).value("specialty_tithe")     # 세종대왕 '고기 없이는 못살아'
        if tithe:
            cut = sum(made.values()) // int(tithe)
            for _ in range(cut):                              # 가장 많이 나는 특산물부터 1개씩 수라상으로
                sp = max(made, key=lambda k: (made[k], k))
                made[sp] -= 1
            f.last["specialty_tithe"] = cut
        if self.mods(f.id).value("tribute") and any(r.id == f.capital for r in active):
            n = sum(1 for x in self.alive_ids() if x != f.id and D.declared_friends(self, f.id, x))
            if n:                                             # 야율융서 '전연의 맹약': 우호 선언 1곳마다 공물 1
                made[C.TRIBUTE_SPECIALTY] = made.get(C.TRIBUTE_SPECIALTY, 0) + n * self.mods(f.id).value("tribute")
        for sp, n in made.items():
            if n > 0:
                f.specialty[sp] = f.specialty.get(sp, 0) + n
        # 에너지: 채굴 → 발전소 → 전기 → 공장 (미리보기와 같은 계산)
        plan = self.energy_plan(f.id)
        for k in C.ENERGY:
            res[k] = plan["after"][k]
        for r in regs:
            r.fuel_used = plan["factories"].get(r.id, {}).get("units", 0)
        f.last["energy"] = plan
        live = {r.id for r in active}
        for r in regs:
            r.output = self.calc_output(r.id) if r.id in live else 0.0
            r.food = self.food_prod(f.id, r) if r.id in live else 0.0
        prod = sum(r.food for r in regs)
        cons = sum(r.pop for r in regs) * C.FOOD_PER_POP
        res["food"] += prod - cons
        if res["food"] < 0 and f.auto_food:
            self.market_buy(f.id, "food", math.ceil(-res["food"]))
        famine = 0.0
        if res["food"] < 0:
            famine = min(1.0, -res["food"] / max(1.0, cons))
            res["food"] = 0.0
            self.event("famine", f"{f.name}: 식량 부족 (기근 {famine*100:.0f}%)", fids=(f.id,))
        for r in regs:
            r.famine = famine
            if famine:
                r.h_delta += C.FAMINE_HAPPY * famine
        self._distribute_specialties(f, regs)
        f.last.update(food_prod=prod, food_cons=cons, famine=famine)

    def _distribute_specialties(self, f, regs):
        """① 수동 고정 → ② 기존 공급 유지 → ③ 자동: 행복도 낮은 지역부터. 제외 지정은 건너뛴다."""
        stock = f.specialty
        old = {r.id: set(r.supplied) for r in regs}
        new = {r.id: set() for r in regs}

        def give(r, kind):
            if (len(new[r.id]) >= C.SPECIALTY_MAX_TYPES or kind in new[r.id] or kind in r.spec_block
                    or stock.get(kind, 0) < 1):
                return
            stock[kind] -= 1
            new[r.id].add(kind)

        order = sorted(regs, key=lambda r: (r.happy, r.id))
        for r in order:
            for kind in sorted(r.spec_pin):
                give(r, kind)
        for r in order:
            for kind in sorted(old[r.id]):
                give(r, kind)
        if f.auto_specialty:
            for r in order:
                for kind in sorted(stock, key=lambda k: (-stock[k], k)):
                    if len(new[r.id]) >= C.SPECIALTY_MAX_TYPES:
                        break
                    give(r, kind)
        for r in regs:
            r.supplied = new[r.id]          # 행복도는 공급받는 동안 턴당 +0.1/종 (_phase_happiness)

    def specialty_kinds(self, fid):
        """이 세력이 가진(재고 또는 생산) 특산물 종류."""
        f = self.factions[fid]
        kinds = {k for k, v in f.specialty.items() if v > 0}
        kinds |= {sp for r in self.regions_of(fid) if r.b["specialty"] for sp in self.info(r.id).specialties}
        return sorted(kinds)

    def set_specialty(self, fid, rid, kind, state):
        """state: pin(고정 공급) / block(제외) / auto(수동 지정 해제). 다음 자원 단계에 반영."""
        r = self.regions[rid]
        if r.owner != fid:
            return False, "내 지역이 아닙니다."
        r.spec_pin.discard(kind)
        r.spec_block.discard(kind)
        if state == "pin":
            if len(r.spec_pin) >= C.SPECIALTY_MAX_TYPES:
                return False, f"한 지역에는 최대 {C.SPECIALTY_MAX_TYPES}종까지 공급합니다."
            r.spec_pin.add(kind)
        elif state == "block":
            r.spec_block.add(kind)
        return True, ""

    # ---- 9. 세수·유지비
    def upkeep(self, fid) -> float:
        return sum(self.upkeep_breakdown(fid).values())

    def upkeep_breakdown(self, fid) -> dict:
        """유닛 종류별 턴당 유지비(바다 위 해군 2배·지도자 효과·보급로 차단 반영)."""
        out = {}
        m = self.mods(fid)
        cut = m.value("cut_supply", 0)
        linked = self.supply_linked(fid) if cut else None
        for a in self.armies.values():
            if a.owner != fid:
                continue
            at_sea = self.world.is_sea(a.loc)
            for k, n in a.units.items():
                u = C.UNITS[k]
                c = u["upkeep"] * n
                if u["kind"] == "naval" and at_sea:
                    c *= C.NAVAL_AT_SEA_UPKEEP
                if u["kind"] == "land":
                    c *= m.mult("upkeep_land")
                if cut and a.loc not in linked:
                    c *= 1 + cut                     # 히데요시 '보급로 차단'
                out[k] = out.get(k, 0.0) + c * C.MONEY_SCALE
        return out

    def supply_linked(self, fid) -> set:
        """수도에서 자국 영토를 따라 육로로 닿는 지역 + 그 육상 인접 지역(전선)."""
        cap = self.factions[fid].capital
        if self.regions[cap].owner != fid:
            return set()
        seen, stack = {cap}, [cap]
        while stack:
            u = stack.pop()
            for v in self.world.land_adj[u]:
                if v not in seen and self.regions[v].owner == fid:
                    seen.add(v)
                    stack.append(v)
        return seen | {v for u in seen for v in self.world.land_adj[u]}

    def _phase_tax(self, f: Faction):
        gdp = self.gdp(f.id)
        revenue = gdp * f.tax * f.income_mult
        up = self.upkeep(f.id)
        f.money += revenue - up
        spent = sum(f.spend.values())
        f.last.update(gdp=gdp, tax=revenue, upkeep=up, buy=f.trade_buy, sell=f.trade_sell,
                      spend=dict(f.spend), refund=f.refund,
                      net=revenue + f.trade_sell + f.refund - up - f.trade_buy - spent)
        if f.money < 0:
            for r in self.regions_of(f.id):
                r.h_delta += C.DEBT_HAPPY

    # ---- 10. 인구
    def _phase_population(self):
        for r in self.regions.values():
            if r.owner == NEUTRAL:
                continue
            f = self.factions[r.owner]
            info = self.info(r.id)
            if r.famine > 0:
                r.pop *= 1 + C.FAMINE_POP * r.famine
            else:
                # 인구 상한 없음. 성장은 전쟁 피로를 뺀 행복도로 판정하고, 과밀 행복도 감소가 브레이크
                g = R.pop_growth_rate(self.growth_happy(r)) * f.pop_mult
                if self.pop_focus_active(r):
                    g += C.POP_FOCUS_GROWTH          # 인구 성장 집중
                if g > 0:
                    r.pop += r.pop * g
            if self.eff_happy(r) <= C.MIGRATION_H:        # 이주는 전쟁 피로를 포함한 실질 행복도로 판정
                r.pop *= 1 + C.MIGRATION_POP
            r.pop = max(0.1, r.pop)

    # ---- 11. 행복도
    def _phase_happiness(self):
        per_fac = {}
        for f in self.factions:
            if not f.alive:
                continue
            m = self.mods(f.id)
            t = self.tax_happy(f.id, f.tax * 100)
            t += m.add("happy_turn")
            # 전쟁 피로도: 전쟁 중이면 쌓이고(선포한 쪽 1, 당한 쪽 0.5/턴), 평시엔 턴당 1 회복
            rate = D.war_weary_rate(self, f.id)
            if rate:
                D.add_war_weary(self, f.id, rate, defensive=D.war_weary_defensive(self, f.id))
            else:
                D.add_war_weary(self, f.id, -C.WAR_WEARY_RECOVERY * m.mult("war_weary_recovery"))
            floor = 0.0 if f.happy_floor_until > self.turn else C.HAPPY_MIN
            per_fac[f.id] = (t, m.value("happy_cap", C.HAPPY_MAX), floor)
        for r in self.regions.values():
            r.bombed = False
            if r.owner == NEUTRAL or r.owner not in per_fac:
                r.h_delta = 0.0
                continue
            t, cap, floor = per_fac[r.owner]
            spec = C.SPECIALTY_HAPPY_TURN * len(r.supplied)      # 특산물: 공급받는 종류마다 턴당
            h = (r.happy + r.h_delta + t + spec) * C.HAPPY_DECAY
            r.happy = max(floor, min(cap, h))
            r.h_delta = 0.0
            lp = getattr(r, "lost_project", None)
            if lp is not None and self.resist_phase(r)[0] not in ("resist", "recover"):
                self._refund_lost_project(r)        # 탈환 기간(저항 + 회복)이 지났다
            if r.resist and self.turn - r.resist["turn"] >= C.RESIST_NO_REBEL_TURNS - 1:
                r.resist = None
        self._morale = {}

    def _phase_conscription(self, drafted):
        """징집 피로: 최근 10턴 중 군 생산 턴 수 n. n ≥ 6이면 감소량을 올리고, n ≤ 3이면 빠르게 회복."""
        mask = (1 << C.CONSCRIPT_WINDOW) - 1
        for r in self.regions.values():
            if r.owner == NEUTRAL:
                continue
            r.mil_hist = ((r.mil_hist << 1) | (1 if r.id in drafted else 0)) & mask
            n = bin(r.mil_hist).count("1")
            pen = R.conscript_penalty(n)
            if pen > r.conscript:
                r.conscript = pen
            elif n <= C.CONSCRIPT_RECOVER_N:
                r.conscript = max(0.0, r.conscript - C.CONSCRIPT_RECOVERY)

    def drafted_turns(self, rid) -> int:
        return bin(self.regions[rid].mil_hist).count("1")

    # ---- 실질 행복도·저항·사기
    def resist_phase(self, rr):
        """점령 저항 단계와 경과 턴: ('resist' 산출 0·행복도 −100 | 'recover' 회복 중 | 'calm' 반란만 없음 | None)."""
        rs = rr.resist
        if not rs or rr.owner == NEUTRAL:
            return None, 0
        k = self.turn - rs["turn"]
        if k < rs["resist"]:
            return "resist", k
        if k < rs["resist"] + rs["recover"]:
            return "recover", k
        if k < C.RESIST_NO_REBEL_TURNS:
            return "calm", k
        return None, k

    def resisting(self, rr) -> bool:
        return self.resist_phase(rr)[0] == "resist"

    def base_happy(self, rr) -> float:
        """저항을 반영한 행복도(전쟁 피로·징집 피로 제외)."""
        phase, k = self.resist_phase(rr)
        if phase == "resist":
            return C.RESIST_HAPPY
        if phase == "recover":
            rs = rr.resist
            frac = (k - rs["resist"] + 1) / rs["recover"]
            return C.RESIST_HAPPY + (rr.happy - C.RESIST_HAPPY) * frac
        return rr.happy

    def eff_happy(self, rr, rebel=False) -> float:
        """실질 행복도 = 행복도(저항 반영) − 전쟁 피로도 − 징집 피로. 산출·인구·사기 판정에 쓴다.
        rebel=True(반란 판정): 선포당한 전쟁에서 쌓인 전쟁 피로는 빼지 않고, 나머지는 ×1.2로 반영한다."""
        if rr.owner == NEUTRAL:
            return rr.happy
        f = self.factions[rr.owner]
        weary = f.war_weary
        if rebel:
            weary = (weary - getattr(f, "war_weary_def", 0.0)) * C.REBEL_WEARY_MULT
        h = (self.base_happy(rr) - weary - rr.conscript - self.minority_penalty(rr.owner)
             + self.scenic_bonus(rr) + self.crowd_penalty(rr))
        if f.happy_floor_until > self.turn:
            h = max(0.0, h)
        return max(C.HAPPY_MIN, min(C.HAPPY_MAX, h))

    def rebel_happy(self, rr) -> float:
        """반란 판정용 행복도: 실질 행복도에서 선포당한 전쟁의 피로만 되돌린 값."""
        return self.eff_happy(rr, rebel=True)

    def scenic_bonus(self, rr) -> float:
        """자연경관: 경관 지역과, 그 지역 주인의 인접 지역에 행복도 +5(경관마다)."""
        if rr.owner == NEUTRAL:
            return 0.0
        return C.SCENIC_HAPPY * sum(1 for n in self.world.scenic_near[rr.id] if self.regions[n].owner == rr.owner)

    def haedong_steps(self, fid) -> float:
        """발해 선왕 '해동성국': 영토가 20곳을 넘을 때마다 1단계(최대 5). 단계마다 전 지역 산출 +2%."""
        if fid == NEUTRAL or not self.mods(fid).value("haedong"):
            return 0.0
        cache = self.__dict__.setdefault("_haedong", {})
        stamp = getattr(self, "acq_counter", 0)
        hit = cache.get(fid)
        if hit is None or hit[0] != stamp:
            n = self.region_count(fid)
            hit = (stamp, float(min(C.HAEDONG_MAX, max(0, (n - 1) // C.HAEDONG_STEP))))
            cache[fid] = hit
        return hit[1]

    def minority_penalty(self, fid) -> float:
        """홍타이지 '소수민족': 보유 지역이 30곳을 넘으면 넘는 1곳마다 전 지역 행복도 −0.3."""
        k = self.mods(fid).value("minority_rule")
        if not k:
            return 0.0
        cache = self.__dict__.setdefault("_minority", {})
        stamp = getattr(self, "acq_counter", 0)
        hit = cache.get(fid)
        if hit is None or hit[0] != stamp:
            hit = (stamp, k * max(0, self.region_count(fid) - C.MINORITY_REGIONS))
            cache[fid] = hit
        return hit[1]

    def avg_happiness(self, fid, effective=True) -> float:
        """평균 행복도. effective=False 면 전쟁 피로·징집 피로·저항을 빼기 전 행복도."""
        regs = self.regions_of(fid)
        if not regs:
            return 0.0
        if effective:
            return sum(self.eff_happy(r) for r in regs) / len(regs)
        return sum(r.happy for r in regs) / len(regs)

    def morale(self, fid) -> float:
        """사기(전투력 배수): 실질 평균 행복도 −10 이하부터 산출 감소와 같은 곡선."""
        if fid == NEUTRAL:
            return 1.0
        v = self._morale.get(fid)
        if v is None:
            v = R.unhappy_combat_mult(self.avg_happiness(fid))
            self._morale[fid] = v
        return v

    def retake_bonus(self, fid, rid) -> bool:
        """저항 중인 지역을 원래 주인이 공격하면 공격력 +20%."""
        rr = self.regions[rid]
        return bool(rr.resist) and rr.resist.get("from") == fid and self.resisting(rr)

    def total_pop(self, fid) -> float:
        return sum(r.pop for r in self.regions_of(fid))

    # ---- 12. 반란
    def rebellion_chance(self, fid, rid) -> float:
        rr = self.regions[rid]
        if self.resist_phase(rr)[0]:
            return 0.0                        # 점령 후 36턴은 반란 없음
        p = R.rebellion_probability(self.rebel_happy(rr)) * self.mods(fid).mult("rebel_prob")
        if self.mods(fid).value("avg_rebel") and self.avg_happiness(fid) <= -30:
            p *= self.mods(fid).value("avg_rebel")
        k = self.mods(fid).value("capital_fall_rebel")      # 연개소문 '삼형제의 내분'
        if k and self.turn - getattr(self.factions[fid], "capital_fall_turn", -999) < C.CAPITAL_FALL_TURNS:
            p *= k
        return min(1.0, p)

    def _phase_rebellion(self):
        from . import ai
        for f in self.factions:
            if not f.alive:
                continue
            for r in list(self.regions_of(f.id)):
                if self.rebel_happy(r) > C.REBEL_THRESHOLD:
                    continue
                if self.rng.random() < self.rebellion_chance(f.id, r.id):
                    r.rebellions += 1
                    self.event("rebel", f"{self.info(r.id).name}에서 반란이 일어났습니다!", region=r.id, fids=(f.id,))
                    if f.is_ai:
                        ai.handle_rebellion(self, f.id, r.id)
                    else:
                        self.pending_rebellions.append(r.id)

    def suppress_chance(self, fid, rid) -> float:
        rr = self.regions[rid]
        S = sum(C.UNITS[k]["df"] * n for a in self.armies_at(rid, fid) for k, n in a.units.items())
        Rv = rr.pop * 2 * max(0.0, -self.rebel_happy(rr) / 50)
        p = S / (S + Rv) if S + Rv > 0 else 0.0
        return max(0.0, min(1.0, p + self.mods(fid).add("suppress")))

    def rebellion_accept_cost(self, fid, rid) -> float:
        return self.region_output_estimate(rid) * C.REBEL_ACCEPT_TURNS

    def resolve_rebellion(self, fid, rid, choice):
        """choice: pay / tax / suppress. 결과 메시지 반환."""
        rr = self.regions[rid]
        f = self.factions[fid]
        if rid in self.pending_rebellions:
            self.pending_rebellions.remove(rid)
        if rr.owner != fid:
            return "이미 내 지역이 아닙니다."
        name = self.info(rid).name
        if choice == "pay":
            cost = self.rebellion_accept_cost(fid, rid)
            if f.money < cost:
                choice = "tax"
            else:
                f.money -= cost
                rr.happy = min(C.HAPPY_MAX, rr.happy + C.REBEL_ACCEPT_HAPPY)
                msg = f"{name}: 요구 수용(산출 4턴분 {cost:,.0f} 지불), 행복도 +20"
                self.event("rebel", msg, region=rid, fids=(fid,))
                return msg
        if choice == "tax":
            f.tax = max(0.0, round(f.tax - C.REBEL_ACCEPT_TAX_CUT, 2))
            rr.happy = min(C.HAPPY_MAX, rr.happy + C.REBEL_ACCEPT_HAPPY)
            msg = f"{name}: 요구 수용(세율 5%p 인하 → {f.tax*100:.0f}%), 행복도 +20"
            self.event("rebel", msg, region=rid, fids=(fid,))
            return msg
        p = self.suppress_chance(fid, rid)
        Rv = rr.pop * 2 * max(0.0, -self.rebel_happy(rr) / 50)
        if self.rng.random() < p:
            rr.happy = min(C.HAPPY_MAX, rr.happy + C.REBEL_SUPPRESS_HAPPY)
            for a in self.armies_at(rid, fid):
                for k, n in list(a.units.items()):
                    loss = int(n * C.REBEL_SUPPRESS_LOSS + self.rng.random())
                    a.units[k] = max(0, n - loss)
                a.units = {k: v for k, v in a.units.items() if v > 0}
                if a.empty():
                    self.remove_army(a)
            msg = f"{name}: 반란 진압 성공 (행복도 +5, 진압 병력 10% 손실)"
            self.event("rebel", msg, region=rid, fids=(fid,))
            return msg
        # 진압 실패 → 반란 지역이 독립(그 지역을 수도로 하는 국가)
        last = len(self.regions_of(fid)) <= 1
        nf, joined = self._spawn_rebel(fid, rid, Rv)
        if last:
            msg = f"{name}: 진압 실패. 마지막 영토가 {nf.name}(으)로 독립해 멸망했습니다."
        elif joined:
            msg = f"{name}: 진압 실패! 기존 반란 세력 {nf.name}에 합류했습니다."
        else:
            msg = f"{name}: 진압 실패! {nf.name}(으)로 분리독립했습니다."
        self.event("rebel", msg, region=rid, fids=(fid, nf.id))
        return msg

    def rebel_children(self, fid):
        return [f for f in self.factions if f.alive and f.rebel_of == fid]

    def _spawn_rebel(self, fid, rid, Rv):
        """반란 지역 rid 를 수도로 하는 새 국가. 지역 상태(건물·인구·산출·공사)는 그대로 계승."""
        rr = self.regions[rid]
        n_inf = max(1, int(round(Rv / 12))) + int(self.mods(fid).value("rebel_extra_inf", 0))   # 궁예 '관심법'
        keep_project = rr.project if rr.project and rr.project.kind in ("build", "unit") else None
        siblings = self.rebel_children(fid)
        if len(siblings) >= C.REBEL_MAX_PER_PARENT or len(self.factions) >= C.MAX_FACTIONS:
            if siblings:
                adj = [s for s in siblings if any(self.regions[n].owner == s.id for n in self.world.land_adj[rid])]
                target = (adj or sorted(siblings, key=lambda s: -self.region_count(s.id)))[0]
                self.transfer_region(rid, target.id, reason="독립")
                rr.project = keep_project
                self.new_army(target.id, rid, {"inf": n_inf})
                if target.happy_floor_until > self.turn:
                    rr.happy = max(rr.happy, 0.0)
                return target, True
            self.transfer_region(rid, NEUTRAL, reason="독립")
            rr.happy = 0.0
            self.new_army(NEUTRAL, rid, {"inf": n_inf})
            return type("Neutral", (), {"name": "중립 지역", "id": NEUTRAL})(), True
        nid = len(self.factions)
        info = self.info(rid)
        used = {f.color for f in self.factions if f.alive}
        palette = C.FACTION_COLORS + C.REBEL_COLORS
        color = next((c for c in palette if c not in used), palette[nid % len(palette)])
        taken = {f.leader for f in self.factions if f.alive}
        pool = [l["key"] for l in LEADER_BY_KEY.values() if l["key"] != "cus" and l["key"] not in taken]
        lk = self.rng.choice(pool or [l for l in LEADER_BY_KEY if l != "cus"])
        leader = LEADER_BY_KEY[lk]
        name = faction_name_from(info.short)
        if any(f.name == name for f in self.factions):
            name = name[:-1] + " 공화국"
        f = Faction(id=nid, name=name, color=color, leader=lk, leader_name=leader["name"], gov=None,
                    is_ai=True, capital=rid, aggression=leader["aggr"], rebel_of=fid)
        f.gov = ai_pick_government(self.rng, f.aggression, rr.b["factory"], rr.b["bank"], banned=banned_govs(lk))
        diff = C.DIFFICULTIES[self.settings.difficulty]
        f.pop_mult, f.income_mult = diff[1], diff[2]
        f.res = {"food": rr.pop * C.START_FOOD_TURNS, **C.START_RESOURCES}
        f.money = C.START_MONEY * C.MONEY_SCALE
        f.founded_turn = self.turn
        f.happy_floor_until = self.turn + C.REBEL_HAPPY_FLOOR_TURNS
        self.factions.append(f)
        self.transfer_region(rid, nid, reason="독립")
        rr.project = keep_project            # 진행 중이던 공사·생산 계승
        rr.happy = max(rr.happy, 0.0)
        f.last = {"gdp": rr.output, "tax": rr.output * f.tax, "upkeep": 0, "net": 0,
                  "food_prod": rr.food, "food_cons": rr.pop}
        self.new_army(nid, rid, {"inf": n_inf})
        for other in self.factions:
            if other.id != nid:
                self.dip.op[(nid, other.id)] = D.op_baseline(self, nid, other.id)
                if other.is_ai:
                    self.dip.op[(other.id, nid)] = D.op_baseline(self, other.id, nid)
        # 같은 국가에서 독립한 세력끼리: 체제가 같거나 유사하면 우호, 다르면 적대
        for sib in siblings:
            v = C.REBEL_SIBLING_OPINION if gov_similar(f.gov, sib.gov) else -C.REBEL_SIBLING_OPINION
            self.dip.op[(nid, sib.id)] = v
            self.dip.op[(sib.id, nid)] = v
        D._start_war(self, nid, fid, happiness=False)  # 독립 전쟁은 선전포고 행복도 벌칙 없음
        self.dip.op[(nid, fid)] = -100
        if self.factions[fid].is_ai:
            self.dip.op[(fid, nid)] = -100
        if self.mods(fid).value("rebel_ally_enemy"):          # 견훤 '금산사 유폐'
            foes = [e for e in D.enemies(self, fid) if e != nid and self.factions[e].alive]
            if foes:
                e = max(foes, key=lambda x: self.power.get(x, 0))
                self.dip.alliance[D.pair(nid, e)] = self.turn
                self.event("diplo", f"{f.name}이(가) {self.fname(e)}와(과) 동맹을 맺었습니다 "
                           f"({self.fx_source(fid, 'rebel_ally_enemy')}).", fids=(nid, e, fid))
        return f, False

    # ------------------------------------------------------------------ 국력·패권
    def _update_power(self):
        alive = self.alive_ids()
        if not alive:
            return
        mils = {f: self.mil_power(f) for f in alive}
        gdps = {f: self.gdp(f) or sum(self.region_output_estimate(r.id) for r in self.regions_of(f))
                for f in alive}
        am = sum(mils.values()) / len(alive) or 1.0
        ag = sum(gdps.values()) / len(alive) or 1.0
        self.power = {f: 0.6 * mils[f] / am + 0.4 * gdps[f] / ag for f in alive}
        total = sum(self.power.values()) or 1.0
        ranked = sorted(alive, key=lambda f: -self.power[f])
        self.hegemon, self.hegemon_share = None, 0.0
        if len(ranked) >= 2:
            top, second = ranked[0], ranked[1]
            s = self.power[top] / total
            if s >= C.HEGEMON_SHARE and self.power[top] >= C.HEGEMON_LEAD * self.power[second]:
                self.hegemon, self.hegemon_share = top, s

    def border_power_matrix(self):
        """(b, a) -> a 영토와 맞닿은 b 영토에 배치된 b 의 전력."""
        out = {}
        for army in self.armies.values():
            b = army.owner
            if b == NEUTRAL or self.world.is_sea(army.loc):
                continue
            if self.regions[army.loc].owner != b:
                continue
            pw = self.army_power(army)
            seen = set()
            for n in self.world.land_adj[army.loc]:
                a = self.regions[n].owner
                if a not in (NEUTRAL, b) and a not in seen:
                    seen.add(a)
                    out[(b, a)] = out.get((b, a), 0.0) + pw
        return out

    # ------------------------------------------------------------------ 승리
    def _check_victory(self):
        if self.game_over:
            return                          # 이번 턴 기축통화 완공 등으로 이미 끝났다
        st = self.settings
        alive = self.alive_ids()
        if not self.player.alive and not st.all_ai:
            self.winner = None
            self.game_over = True
            self.event("gameover", "패배: 모든 영토를 잃었습니다.", fids=(self.player_id,))
            return
        if "conquest" in st.victories and len(self.factions) > 1:
            if len(alive) == 1:
                self._win((alive[0],), "conquest")
                return
            for fid in alive:
                if self.conquest_status(fid)["ok"]:
                    self._win((fid,), "conquest")
                    return
        if "science" in st.victories:
            for fid in alive:
                if self.launch_ready(fid):
                    self._win((fid,), "science")
                    return
        if "diplomatic" in st.victories and len(alive) >= 2:
            cid = D.coalition_of(self, alive[0])
            if cid is not None and set(alive) <= self.dip.coalitions[cid]["members"]:
                self._win(tuple(alive), "diplomatic")
                return
        if "time" in st.victories and self.turn >= getattr(st, "max_turns", C.TIME_VICTORY_TURNS) and alive:
            sc = self.time_scores()
            best = max(alive, key=lambda f: (sc[f], self.gdp(f)))
            self._win((best,), "time")
            return

    def neutral_gdp(self) -> float:
        """중립 지역의 산출 합(경제승리 분모용). 턴마다 한 번 계산해 둔다."""
        c = getattr(self, "_neutral_gdp", None)
        if c is None or c[0] != self.turn:
            v = sum(self.region_output_estimate(r.id) for r in self.regions.values() if r.owner == NEUTRAL)
            c = (self.turn, v)
            self._neutral_gdp = c
        return c[1]

    def world_gdp(self, gd=None) -> float:
        """경제승리 분모: 살아 있는 모든 세력의 GDP + 중립 지역 산출."""
        if gd is None:
            gd = {f: self.gdp(f) for f in self.alive_ids()}
        return sum(gd.values()) + self.neutral_gdp()

    def start_nations(self) -> int:
        """시작할 때의 국가 수(플레이어 포함, 반란국 제외)."""
        return sum(1 for f in self.factions if f.rebel_of is None)


    def can_rebel(self, rr) -> bool:
        """이 지역에서 반란이 일어날 수 있는가(반란 판정 행복도 −50 이하이고 확률 > 0)."""
        return (rr.owner != NEUTRAL and self.rebel_happy(rr) <= C.REBEL_THRESHOLD
                and self.rebellion_chance(rr.owner, rr.id) > 0)

    def conquest_status(self, fid) -> dict:
        """정복승리 진행: 지역 수, 필요 지역 수, 반란 가능 지역 수."""
        regs = self.regions_of(fid)
        need = math.ceil(len(self.regions) * C.CONQUEST_SHARE - 1e-9)
        risky = sum(1 for r in regs if self.can_rebel(r)) if len(regs) >= need else None
        return {"have": len(regs), "need": need, "risky": risky, "ok": len(regs) >= need and risky == 0}

    def time_scores(self) -> dict:
        """시간 종료 승리 점수: (지역 비율 + GDP 비율 + 인구 비율) / 3 × 100."""
        alive = self.alive_ids()
        regs = {f: self.region_count(f) for f in alive}
        gdp = {f: self.gdp(f) for f in alive}
        pop = {f: self.total_pop(f) for f in alive}
        tr, tg, tp = (sum(d.values()) or 1 for d in (regs, gdp, pop))
        return {f: (regs[f] / tr + gdp[f] / tg + pop[f] / tp) / 3 * 100 for f in alive}

    def _win(self, fids, kind):
        self.winner = (tuple(fids), kind)
        self.game_over = True
        names = ", ".join(self.fname(f) for f in fids)
        self.event("victory", f"{C.VICTORY_TYPES[kind]}: {names}", fids=fids)

    RANKING_COLS = (("regions", "지역 수"), ("pop", "인구(만)"), ("happy", "행복도"),
                    ("gdp", "턴당 GDP(전국 비율)"), ("science", "과학승리"), ("econ", "경제승리"))

    def ranking_label(self, turn) -> str:
        """발표 턴 → '2026년 하반기'(1주차 발표는 지난해 하반기, 25주차 발표는 올해 상반기)."""
        y, m, w = R.date_of_turn(turn)
        return f"{y - 1}년 하반기" if (turn - 1) % C.TURNS_PER_YEAR == 0 else f"{y}년 상반기"

    def _half_ranking(self):
        world = self.world_gdp() or 1
        rows = []
        for f in self.factions:
            if not f.alive:
                continue
            gdp = self.gdp(f.id)
            rows.append({"fid": f.id, "regions": self.region_count(f.id), "pop": self.total_pop(f.id),
                         "happy": self.avg_happiness(f.id), "gdp": gdp, "gdp_share": gdp / world,
                         "science": len(f.science), "econ": self.econ_stage(f.id)})
        self.rankings[self.turn] = rows
        self.new_ranking = self.turn
        self.event("ranking", f"{self.ranking_label(self.turn)} 랭킹이 발표되었습니다.")

    # ------------------------------------------------------------------ 전장의 안개
    def visible(self, fid) -> set:
        if self.settings.fog == 0:
            return set(self.regions) | set(self.world.seas)
        v = self._visible.get(fid)
        if v is None:
            v = self._compute_visible(fid)
            self._visible[fid] = v
        return v

    def _compute_visible(self, fid):
        w = self.world
        vis = set()
        sources = [r.id for r in self.regions.values() if r.owner == fid or
                   (r.owner != NEUTRAL and D.allied(self, fid, r.owner))]
        sources += [a.loc for a in self.armies.values() if a.owner == fid or
                    (a.owner != NEUTRAL and D.allied(self, fid, a.owner))]
        for s in sources:
            vis.add(s)
            vis.update(w.node_neighbors(s))
        return vis

    def queue_dialogue(self, kind, speaker):
        """플레이어에게 보일 지도자 대사 팝업을 쌓는다(전원 AI 시뮬레이션에서는 쌓지 않음)."""
        from . import dialogue as DLG
        if self.settings.all_ai or speaker in (None, NEUTRAL) or speaker == self.player_id:
            return
        if not (0 <= speaker < len(self.factions)) or not DLG.line(self.factions[speaker].leader, kind):
            return
        q = self.__dict__.setdefault("dialogues", [])
        if not any(d["kind"] == kind and d["fid"] == speaker for d in q):
            q.append({"kind": kind, "fid": speaker, "turn": self.turn})

    def _update_fog(self, initial=False):
        """시야·탐색·조우 갱신 후 '첫 만남' 대사 팝업 판정."""
        self._update_fog_inner(initial)
        self._update_greetings(initial)

    def _update_greetings(self, initial=False):
        """첫 만남 인사: 안개 설정과 관계없이 '미탐색'(안개 최대)과 같은 판정 — 실제 시야(동맹 시야 포함)에
        그 나라의 영토나 군대가 들어와야 만난다. 다 보이는 설정이라도 가까이 와야 인사한다(게임 시작 때는 인사 없음)."""
        if not self.factions or self.settings.all_ai:
            return
        pl = self.factions[self.player_id]
        if not pl.alive:
            return
        vis = self._compute_visible(pl.id)
        seen = {self.regions[n].owner for n in vis if n in self.regions}
        seen |= {a.owner for a in self.armies.values() if a.loc in vis}
        seen -= {NEUTRAL, pl.id}
        first = not hasattr(pl, "contact")         # 예전 세이브: 지금 보이는 나라는 인사 없이 만난 것으로
        if first:
            pl.contact = set()
        new = sorted(x for x in seen - pl.contact if self.factions[x].alive)
        pl.contact |= set(new)
        if not (initial or first):
            for o in new:
                self.queue_dialogue("meet", o)

    def _update_fog_inner(self, initial=False):
        self._visible = {}
        for f in self.factions:
            if not f.alive:
                continue
            vis = self.visible(f.id)
            if initial and self.settings.fog == 1:
                f.explored = set(self.regions)
                for rid, r in self.regions.items():
                    f.last_seen[rid] = r.owner
            f.explored |= {v for v in vis if v in self.regions}
            if not hasattr(f, "met"):          # 예전 세이브
                f.met = set()
            for rid in vis:
                if rid in self.regions:
                    o = self.regions[rid].owner
                    f.last_seen[rid] = o
                    if o != NEUTRAL:
                        f.met.add(o)
        # 조우: 시야 안에 다른 세력의 군대가 들어온 적이 있어도 만난 것으로 친다
        if self.settings.fog == 0:
            return                             # 안개가 없으면 모두 아는 사이(has_met 이 항상 참)
        vis = {f.id: self.visible(f.id) for f in self.factions if f.alive}
        for a in self.armies.values():
            if a.owner == NEUTRAL:
                continue
            for fid, v in vis.items():
                if a.owner != fid and a.loc in v:
                    self.factions[fid].met.add(a.owner)
        # 동맹·연합끼리는 시야(위 visible)뿐 아니라 '만난 세력'도 공유한다
        alive = [f for f in self.factions if f.alive]
        changed = True
        while changed:
            changed = False
            for f in alive:
                for o in alive:
                    if o.id != f.id and D.allied(self, f.id, o.id) and not o.met <= f.met | {f.id}:
                        f.met |= o.met - {f.id}
                        changed = True
                    if o.id != f.id and D.allied(self, f.id, o.id):
                        f.met.add(o.id)

    def is_visible(self, fid, node) -> bool:
        return self.settings.fog == 0 or node in self.visible(fid)

    def is_explored(self, fid, node) -> bool:
        if self.settings.fog == 0 or node in self.world.seas:
            return True
        return node in self.factions[fid].explored
