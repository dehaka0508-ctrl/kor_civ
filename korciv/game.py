"""게임 엔진: 상태 보관, 명령 처리, 턴 종료 처리(기획서 3절 순서)."""
from __future__ import annotations

import math
import random
from collections import deque

from . import config as C
from . import diplomacy as D
from . import rules as R
from .data import DO8, load_world
from .leaders import LEADER_BY_KEY, GOV_BY_KEY, Mods, ai_pick_government, gov_similar
from .state import NEUTRAL, Army, Faction, Project, Region, Settings, BUILDING_NAMES

SUFFIXES = ("구역", "지구", "시", "군", "구")


def faction_name_from(short: str) -> str:
    for s in SUFFIXES:
        if short.endswith(s) and len(short) > len(s):
            return short[: -len(s)] + "국"
    return short + "국"


def unit_power(key: str) -> float:
    u = C.UNITS[key]
    return max(u.get("atk", 0), u.get("naval", 0), u.get("air", 0), u.get("bomb", 0) / 2)


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
            for attr, v in (("resist", None), ("mil_hist", 0), ("conscript", 0.0)):
                if not hasattr(r, attr):
                    setattr(r, attr, v)
        for a in self.armies.values():
            if not hasattr(a, "goto"):
                a.goto = None
        for f in self.factions:
            if not hasattr(f, "spend"):
                f.spend, f.refund = {}, 0.0
            if not hasattr(f, "war_weary"):
                f.war_weary = 0.0
            if hasattr(f, "war_weary_applied"):     # 예전 방식: 피로가 행복도에 섞여 있었다
                for r in self.regions.values():
                    if r.owner == f.id:
                        r.happy = min(C.HAPPY_MAX, r.happy + f.war_weary_applied)
                del f.war_weary_applied
            for attr, v in (("last_declare", -999), ("last_aggr_end", -999), ("warmonger", 0)):
                if not hasattr(f, attr):
                    setattr(f, attr, v)
        self._morale = {}

    # ------------------------------------------------------------------ 초기화
    def _init_world(self):
        w = self.world
        for rid in w.order:
            info = w.regions[rid]
            b = {k: 0 for k in ("farm", "fishery", "factory", "bank", "power", "liquefy", "specialty",
                                "extract", "shelter", "aa", "academy", "airport", "port")}
            b.update(farm=info.farm, fishery=info.fishery, factory=info.factory, bank=info.bank)
            if info.specialty:
                b["specialty"] = 1
            if info.start_port:
                b["port"] = 1
            self.regions[rid] = Region(id=rid, owner=NEUTRAL, pop=info.pop0, b=b)
            self.new_army(NEUTRAL, rid, {"inf": 1})

        st = self.settings
        n_ai = max(1, min(9, st.n_enemies))
        leaders = [l["key"] for l in LEADER_BY_KEY.values() if l["key"] != "custom"]
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
            self.factions.append(f)
            self._give_start_region(f, rid)
        for f in self.factions:
            if f.is_ai:
                rr = self.regions[f.capital]
                f.gov = ai_pick_government(self.rng, f.aggression, rr.b["factory"], rr.b["bank"])
        if st.all_ai:
            self.finalize_setup()

    def _pick_starts(self, n, requested):
        chosen = []
        for rid in requested:
            if rid and rid in self.regions and rid not in chosen:
                chosen.append(rid)
        candidates = list(self.world.order)
        self.rng.shuffle(candidates)
        for min_d in (4, 3, 2, 1):
            for rid in candidates:
                if len(chosen) >= n:
                    break
                if rid in chosen:
                    continue
                if all(self._land_dist(rid, c, min_d) >= min_d for c in chosen):
                    chosen.append(rid)
            if len(chosen) >= n:
                break
        return chosen[:n]

    def _land_dist(self, a, b, cap):
        dist = self.world.distances_from(a, cap)
        return dist.get(b, cap + 1)

    def _give_start_region(self, f: Faction, rid: str):
        r = self.regions[rid]
        r.owner = f.id
        for army in self.armies_at(rid):
            if army.owner == NEUTRAL:
                army.owner = f.id
        if self.world.regions[rid].island == "무연륙 섬":
            self.new_army(f.id, rid, {"lst": 1})
        f.res = {"food": r.pop * C.START_FOOD_TURNS, **C.START_RESOURCES}

    def finalize_setup(self):
        """정치체제 선택 후 호출: 시작 자금·우호도 적용."""
        for f in self.factions:
            if f.gov is None:
                f.gov = "philosopher" if not f.is_ai else "presidential"
        self._mods.clear()
        for f in self.factions:
            f.money = C.START_MONEY * C.MONEY_SCALE * self.mods(f.id).mult("start_money")
        for a in self.factions:
            for b in self.factions:
                if a.id != b.id and a.is_ai:
                    self.dip.op[(a.id, b.id)] = self.mods(b.id).add("start_opinion") + D.op_baseline(self, a.id, b.id)
        for r in self.regions.values():
            r.output = self.calc_output(r.id, phi=1.0)
            r.food = R.food_output(r.b["farm"], r.b["fishery"])
        for f in self.factions:
            regs = self.regions_of(f.id)
            gdp = sum(r.output for r in regs)
            f.last = {"gdp": gdp, "tax": gdp * f.tax * f.income_mult, "upkeep": self.upkeep(f.id), "net": 0,
                      "food_prod": sum(r.food for r in regs), "food_cons": sum(r.pop for r in regs)}
        self._update_power()
        self._update_fog(initial=True)
        self.setup_done = True

    def set_player_government(self, gov_key: str):
        self.factions[self.player_id].gov = gov_key
        self._mods.pop(self.player_id, None)
        self.finalize_setup()

    # ------------------------------------------------------------------ 기본 조회
    @property
    def player(self) -> Faction:
        return self.factions[self.player_id]

    def mods(self, fid) -> Mods:
        if fid == NEUTRAL:
            return Mods("custom", None)
        m = self._mods.get(fid)
        if m is None:
            f = self.factions[fid]
            m = self._mods[fid] = Mods(f.leader, f.gov)
        return m

    def fname(self, fid) -> str:
        return "중립" if fid == NEUTRAL else self.factions[fid].name

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

    def add_units(self, fid, loc, key, n=1) -> Army:
        kind = C.UNITS[key]["kind"]
        for a in self.armies_at(loc, fid):
            if a.domain() == kind and not a.order:
                a.units[key] = a.units.get(key, 0) + n
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
        for k, v in take.items():
            a.units[k] -= v
        a.units = {k: v for k, v in a.units.items() if v > 0}
        b = self.new_army(a.owner, a.loc, take)
        self._validate_capacity(a)
        return b, ""

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
                return False, "상륙함 수송 칸이 부족합니다(보병1·포병2·전차4, 상륙함당 12)."
            if test.air_used() > test.air_cap() and self.world.is_sea(a.loc):
                return False, "항공모함 탑재 칸이 부족합니다(항모당 8)."
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

    def disband(self, army_id, units: dict):
        a = self.armies.get(army_id)
        if not a:
            return False, "부대가 없습니다."
        in_own = not self.world.is_sea(a.loc) and self.regions[a.loc].owner == a.owner
        for k, v in units.items():
            v = min(v, a.units.get(k, 0))
            if v <= 0:
                continue
            a.units[k] -= v
            if in_own:
                self.regions[a.loc].h_delta += C.UNIT_DISBAND_HAPPY[C.UNITS[k]["weight"]] * v
        a.units = {k: v for k, v in a.units.items() if v > 0}
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
            for k in ("stl", "bmb", "ftr"):
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
                for v in w.land_adj[start]:
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
                for v in w.seas[start].coast:
                    if self.hostile(fid, self.regions[v].owner) and out.get(v, {}).get("action") != "attack":
                        out.setdefault(v, {"action": "bombard", "path": [], "strong": False})
            if (army.units.get("bmb") or army.units.get("stl")) and army.units.get("cv"):
                for v, d in w.distances_from(start, C.AIR_RANGE).items():
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
                elif (army.units.get("bmb") or army.units.get("stl")) and self.hostile(fid, rr.owner):
                    out[v] = {"action": "bombard", "path": [], "strong": False}
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
            return True, f"자동 이동: {self.world.node_name(target)}까지 {len(route)}칸 (매 턴 자동 진행)"
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
            if mode == "surprise" and not any(a.units.get(k) for k in C.SURPRISE_UNITS):
                mode = "assault"
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

        def passable(v):
            if w.is_sea(v) or self.hostile_units_at(fid, v):
                return False
            o = self.regions[v].owner
            return self.friendly_territory(fid, v) or (o != NEUTRAL and not self.hostile(fid, o)
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

    def _can_bombard(self, a, target):
        if self.world.is_sea(target) or not self.hostile(a.owner, self.regions[target].owner):
            return False
        return self._bombard_units(a, target) != {}

    def _bombard_units(self, a, target):
        w = self.world
        out = {}
        if a.units.get("art") and not w.is_sea(a.loc) and target in w.land_adj[a.loc]:
            out["art"] = a.units["art"]
        if a.units.get("dd") and w.is_sea(a.loc) and target in w.seas[a.loc].coast:
            out["dd"] = a.units["dd"]
        bombers = {k: a.units.get(k, 0) for k in ("bmb", "stl") if a.units.get(k)}
        if bombers:
            base_ok = (not w.is_sea(a.loc) and self.regions[a.loc].b["airport"]
                       and self.regions[a.loc].owner == a.owner) or a.units.get("cv")
            if base_ok and w.distances_from(a.loc, C.AIR_RANGE).get(target) is not None:
                out.update(bombers)
        return out

    # ------------------------------------------------------------------ 전투 예측
    def combat_strength(self, fid, armies, target, mode="assault"):
        """공격력 A 와 주 공격 경로를 계산."""
        w = self.world
        m = self.mods(fid)
        tgt_owner = self.regions[target].owner
        mult = self.morale(fid)                  # 사기: 실질 평균 행복도 −10 이하면 감소
        if self.retake_bonus(fid, target):
            mult *= 1 + C.RESIST_RETAKE_ATK      # 저항 중인 옛 영토를 되찾는 공격
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
                    val *= C.AMPHIBIOUS * m.value("amphib_extra", 1.0)
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
        return total, sources, main_src

    def defense_strength(self, fid_att, target, main_src, mode):
        defenders = self.hostile_units_at(fid_att, target)
        rr = self.regions[target]
        dsum = sum(C.UNITS[k]["df"] * n * self.morale(a.owner) for a in defenders for k, n in a.units.items())
        line_level = rr.lines.get(main_src, 0) if main_src else 0
        if rr.owner != NEUTRAL and mode == "assault":
            k = self.mods(rr.owner).value("line_k", C.LINE_BONUS)
            dsum *= 1 + k * line_level
        if rr.owner != NEUTRAL and self.region_count(rr.owner) <= 3:
            dsum *= self.mods(rr.owner).mult("defense_small")
        if rr.owner != NEUTRAL and self.info(target).coastal:
            dsum *= self.mods(rr.owner).mult("def_coast")      # 이순신: 해안 지역 방어
        return dsum, defenders, line_level

    def fx_source(self, fid, key) -> str:
        """효과 key 를 주는 지도자 버프/디버프 또는 정치체제 이름."""
        f = self.factions[fid]
        lead = LEADER_BY_KEY.get(f.leader, {})
        fx = lead.get("fx", {})
        if key in fx:
            nm = lead["buff"][0] if list(fx).index(key) == 0 else lead["debuff"][0]
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
                add(af, "상륙 돌격", C.AMPHIBIOUS * m.value("amphib_extra", 1.0))
        if rr.owner != NEUTRAL and D.at_war(self, fid, rr.owner):
            allies_in = any(D.allied(self, fid, x) and D.at_war(self, x, rr.owner)
                            for x in self.alive_ids() if x != fid)
            if allies_in:
                add(af, self.fx_source(fid, "ally_war_atk"), m.mult("ally_war_atk"))
            elif mode == "assault":
                add(af, self.fx_source(fid, "no_ally_assault"), m.mult("no_ally_assault"))
        add(af, "사기(실질 행복도 낮음)", self.morale(fid))
        if self.retake_bonus(fid, target):
            add(af, "저항 중인 옛 영토 탈환", 1 + C.RESIST_RETAKE_ATK)
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
        for o in def_units:
            add(df, f"{self.fname(o)} 사기", self.morale(o))

        def losses(units_by_army, dmg):
            pool = [(k, n) for k, n in units_by_army.items() if n > 0]
            total = sum(C.UNITS[k]["hp"] * n for k, n in pool)
            out = {}
            if total <= 0:
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
            res.append({"label": label, "def_dmg": dd, "att_dmg": ad, "def_lost": losses(all_def, dd),
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
        def_hp = sum(C.UNITS[k]["hp"] * n for a in defenders for k, n in a.units.items())
        res["def_hp"] = def_hp
        return res

    # ------------------------------------------------------------------ 피해 적용
    def apply_damage(self, armies, dmg, unit_filter=None, rng_round=True):
        """피해를 (수 x 체력) 비율로 나눠 적용. 잃은 유닛 {키: 수} 반환."""
        pool = []
        for a in armies:
            for k, n in a.units.items():
                if n > 0 and (unit_filter is None or k in unit_filter):
                    pool.append((a, k, n))
        total_hp = sum(C.UNITS[k]["hp"] * n for _, k, n in pool)
        lost = {}
        if total_hp <= 0 or dmg <= 0:
            return lost
        for a, k, n in pool:
            hp = C.UNITS[k]["hp"]
            share = dmg * (hp * n) / total_hp
            acc = a.dmg.get(k, 0.0) + share
            dead = min(n, int(acc // hp))
            acc -= dead * hp
            a.units[k] = n - dead
            a.dmg[k] = acc if a.units[k] > 0 else 0.0
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
        disc = 0.0
        if self.regions[rid].b["academy"] and self.regions[rid].owner == fid:
            disc = C.ACADEMY_LOCAL
        else:
            for n in self.world.land_adj[rid]:
                rr = self.regions[n]
                if rr.owner == fid and rr.b["academy"]:
                    disc = max(disc, C.ACADEMY_ADJ)
        return c * (1 - disc)

    def landing_ship_in(self, fid, seas) -> bool:
        """해당 해역(또는 그 해역에 닿은 자국 항구)에 상륙함이 있는가."""
        w = self.world
        for a in self.armies.values():
            if a.owner != fid or not a.units.get("lst"):
                continue
            if a.loc in seas or (not w.is_sea(a.loc) and set(w.regions[a.loc].seas) & set(seas)):
                return True
        return False

    def region_value(self, rid):
        """지역 가치 1~10과 점수 구성 {항목: 점수}."""
        rr = self.regions[rid]
        info = self.info(rid)
        levels = sum(rr.b[k] for k in ("farm", "fishery", "factory", "bank", "power", "liquefy",
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
        cands = set(v for v in w.land_adj[rid] if self.regions[v].owner == NEUTRAL)
        if self.regions[rid].b["port"]:
            for s in w.regions[rid].seas:
                for v in w.seas[s].coast:
                    if self.regions[v].owner == NEUTRAL and not w.island_seas_of(v):
                        cands.add(v)
        # 울릉도·제주도: 섬 전용 해역에 상륙함을 보내야 해안 지역에서 편입할 수 있다
        if w.regions[rid].coastal:
            for v in w.order:
                seas = w.island_seas_of(v)
                if seas and v != rid and self.regions[v].owner == NEUTRAL and self.landing_ship_in(fid, seas):
                    cands.add(v)
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
                        "value": self.region_value(v)[0], "joint": n, "sea": v not in w.land_adj[rid],
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

        def add(kind, key, name, cost, turns, ok=True, why="", level=0, border=None, oil=0):
            turns = max(1, turns)
            if resisting:
                ok, why = False, "점령 저항 중"
            opts.append({"kind": kind, "key": key, "name": name, "cost": cost, "turns": turns,
                         "per_turn": cost / turns, "ok": ok, "why": why, "level": level,
                         "border": border, "oil": oil})

        for key, spec in C.PROD_BUILDINGS.items():
            lv = rr.b[key] + 1
            ok, why = True, ""
            if lv > spec["max"]:
                continue
            if key == "fishery" and not self.can_fish(rid):
                ok, why = False, "바다·하천 인접 지역만"
            if key == "specialty" and not info.specialty:
                ok, why = False, "특산물 지정 지역만"
            if key == "extract" and not (info.is_oil or info.is_coal):
                ok, why = False, "정유·탄광 지역만"
            cost = R.prod_building_cost(key, lv, info.power_site)
            if key == "factory":
                cost *= m.mult("cost_factory")
            add("build", key, spec["name"], cost, self.build_time(fid, key, R.prod_building_turns(lv)),
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
                ok, why = False, "해안 지역만"
            add("build", key, spec["name"], spec["cost"] * C.BUILD_COST_MULT * C.MONEY_SCALE,
                self.build_time(fid, key, spec["turns"]), ok, why, 1)
        for key in C.UNIT_ORDER:
            u = C.UNITS[key]
            ok, why = True, ""
            if u["kind"] == "naval" and not rr.b["port"]:
                ok, why = False, "항구 필요"
            if u["kind"] == "air" and not rr.b["airport"]:
                ok, why = False, "공항 필요"
            if ok and self.factions[fid].res.get("oil", 0) < u["oil"]:
                ok, why = False, f"석유 {u['oil']} 필요"
            per = self.unit_cost(fid, rid, key)
            add("unit", key, u["name"], per * u["turns"], u["turns"], ok, why, oil=u["oil"])
        for t in self.annex_targets(fid, rid):
            name = f"편입: {self.info(t['target']).name} (가치 {t['value']})" + (" (해로)" if t["sea"] else "")
            if t["joint"]:
                n = t["joint"] + 1
                name += f" · 공동 {n}곳 −{R.joint_reduction(n):.0%} (약 {t['eff_turns']}턴)"
            add("annex", t["target"], name, t["cost"], t["turns"])
        if not rr.landmark:
            busy = any(r.project and r.project.kind == "landmark" and r.id == rid for r in self.regions.values())
            turns = m.value("landmark_turns", C.LANDMARK_TURNS)
            lm_mult = self.landmark_cost_mult(fid)
            name = "랜드마크" + (f" (비용 ×{lm_mult:.2f})" if lm_mult > 1 else "")
            add("landmark", "landmark", name, C.LANDMARK_COST_PER_TURN * C.MONEY_SCALE * lm_mult * turns, turns,
                not busy)
        if self.factions[fid].capital != rid:
            y = max(rr.output, self.region_output_estimate(rid))
            add("capital", "capital", "천도(수도 이전)", y * C.CAPITAL_MOVE_COST_MULT, C.CAPITAL_MOVE_TURNS)
        return opts

    def landmark_count(self, fid) -> int:
        """보유한 랜드마크 + 짓고 있는 랜드마크 수."""
        return sum(1 for r in self.regions.values() if r.owner == fid
                   and (r.landmark or (r.project and r.project.kind == "landmark")))

    def landmark_cost_mult(self, fid) -> float:
        """다음 랜드마크 비용 배수: 랜드마크 1개마다 ×1.3."""
        return R.landmark_cost_mult(self.landmark_count(fid))

    def building_effect(self, fid, rid, opt) -> str:
        """행동 메뉴용: 다음 단계 건물의 턴당 생산량/효과."""
        rr = self.regions[rid]
        info = self.info(rid)
        key, lv = opt["key"], opt["level"]
        m = self.mods(fid)
        dg = R.g(lv) - R.g(lv - 1)
        if key == "farm":
            return f"완공 시 턴당 식량 +{C.FOOD_PER_G * dg:.0f}, 산출 +{C.FARM_OUTPUT * dg:.0f}"
        if key == "fishery":
            fm = self.fish_mult(fid, rid)
            kind = "하천" if (not info.coastal and rid in self.world.river_regions) else "바다"
            return (f"{kind} 어장: 턴당 식량 +{C.FOOD_PER_G * dg * fm:.1f}, 산출 +{C.FISH_OUTPUT * dg * fm:.0f}")
        if key == "factory":
            return (f"턴당 산출 +{C.FACTORY_OUTPUT * dg * m.mult('output_factory'):,.0f}(석탄 기준, 연료 1/턴 소비)")
        if key == "bank":
            return f"턴당 산출 +{C.BANK_OUTPUT * dg * m.mult('output_bank'):,.0f}"
        if key == "power":
            return f"석탄·석유 → 전기 턴당 최대 {2 * lv}개 (공장 산출 x1.25)"
        if key == "liquefy":
            return f"석탄 → 석유 턴당 최대 {lv}개"
        if key == "specialty":
            each = " 각" if len(info.specialties) > 1 else ""
            return "특산물 " + "·".join(f"「{sp}」" for sp in info.specialties) + f" 턴당{each} {lv}개"
        if key == "extract":
            what = "석유" if info.is_oil else "석탄"
            return f"{what} 턴당 +1 (합계 {(info.oil or info.coal) + lv}개)"
        if key == "line":
            k = m.value("line_k", C.LINE_BONUS)
            fail = R.surprise_mults(lv)[1][0]
            return (f"이 경계 돌격 방어 x{1 + k * lv:.2f}, 적 기습 성공률 {R.surprise_chance(lv) * 100:.0f}%"
                    f"(실패 시 공격 x{fail:.2f})")
        if key == "shelter":
            return f"폭격 피해 ÷{1 + C.SHELTER_K * lv:.1f}"
        if key == "aa":
            return f"폭격기 피해 x{1 - C.AA_DMG_K * lv:.1f}, 격추 {int(C.AA_SHOOT_K * lv * 100)}%"
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
            if f.res.get("oil", 0) < u["oil"]:
                return False, f"석유 {u['oil']} 필요"
            f.res["oil"] -= u["oil"]
            rr.h_delta += C.UNIT_START_HAPPY[u["weight"]]
        rr.project = Project(kind=kind, key=key, level=opt["level"], turns=opt["turns"],
                             per_turn=opt["per_turn"], border=opt["border"])
        self.proj_counter = getattr(self, "proj_counter", 0) + 1
        rr.project.priority = self.proj_counter
        if kind == "landmark":
            rr.project.name = (name or "").strip()[:16] or self.default_landmark_name(rid)
        label = f"랜드마크 「{rr.project.name}」" if kind == "landmark" else opt["name"]
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
                   and not getattr(r, "focus", False))

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
            kinds = {"annex": ("annex",), "build": ("build", "landmark", "capital"), "unit": ("unit",)}[mode]
            regs.sort(key=lambda r: r.project.kind not in kinds)
        self.set_priority_order(fid, [r.id for r in regs])

    def set_priority_order(self, fid, rids):
        for i, rid in enumerate(rids):
            r = self.regions.get(rid)
            if r and r.owner == fid and r.project:
                r.project.priority = i + 1
        self.proj_counter = max(getattr(self, "proj_counter", 0), len(rids) + 1)

    # ------------------------------------------------------------------ 국가 명령
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
        if f.money <= 0:
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

    def set_fuel(self, fid, rid, fuel):
        rr = self.regions[rid]
        if rr.owner == fid and fuel in ("auto", "coal", "oil", "elec"):
            rr.fuel = fuel
            return True
        return False

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

    def calc_output(self, rid, phi=None, owner=None):
        rr = self.regions[rid]
        owner = rr.owner if owner is None else owner
        m = self.mods(owner)
        phi = rr.phi if phi is None else phi
        y = R.region_output(rr.pop, rr.b["farm"], rr.b["fishery"], rr.b["factory"], rr.b["bank"],
                            rr.landmark, phi, self.fish_mult(owner, rid) if owner != NEUTRAL else 1.0,
                            m.mult("output_bank"), m.mult("output_factory"),
                            1 + C.FOCUS_POP_BONUS if self.focus_active(rr) and owner == rr.owner else 1.0)
        if owner != NEUTRAL and owner == rr.owner:
            y *= R.unhappy_output_mult(self.eff_happy(rr))   # 불행한(실질 행복도) 지역은 산출 감소
        return y

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
        return True, "생산 집중 " + (f"켬: 인구 산출 +{C.FOCUS_POP_BONUS:.0%}" if on else "끔")

    def region_output_estimate(self, rid):
        rr = self.regions[rid]
        if rr.output > 0 and rr.owner != NEUTRAL:
            return rr.output
        return self.calc_output(rid, phi=1.0 if rr.b["factory"] else 1.0)

    def gdp(self, fid) -> float:
        return sum(r.output for r in self.regions.values() if r.owner == fid)

    # ------------------------------------------------------------------ 지역 이전
    def transfer_region(self, rid, new_owner, reason="점령"):
        rr = self.regions[rid]
        old = rr.owner
        if old == new_owner:
            return
        rr.owner = new_owner
        rr.project = None
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
                    for r in rest:
                        r.h_delta += C.CAPITAL_LOST_HAPPY
                    self.event("capital", f"{f_old.name}의 수도가 함락되어 {self.info(newcap.id).name}(으)로 천도했습니다.",
                               region=newcap.id, fids=(old,))
            if self.region_count(old) == 0:
                self.eliminate(old, by=new_owner)
        if new_owner != NEUTRAL:
            f = self.factions[new_owner]
            f.explored.add(rid)

    def eliminate(self, fid, by=None):
        f = self.factions[fid]
        if not f.alive:
            return
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
        """점령 완료. 다른 세력에게서 빼앗은 지역은 '저항' 상태로 시작한다(6턴 산출·생산 없음·행복도 −100,
        이후 24턴 동안 점령 직전 행복도로 회복, 36턴 동안 반란 없음)."""
        rr = self.regions[rid]
        old = rr.owner
        m = self.mods(fid)
        new_h = 0.0 if old == NEUTRAL else rr.happy + m.add("occupied_happy_extra")
        if old != NEUTRAL:
            D.add_war_score(self, fid, old, rr.pop)
        self.transfer_region(rid, fid)
        rr.happy = max(C.HAPPY_MIN, min(C.HAPPY_MAX, new_h))
        if old != NEUTRAL:
            half = bool(m.value("wanggeon_occupy"))         # 왕건: 저항·회복 기간 절반
            rr.resist = {"turn": self.turn, "from": old,
                         "resist": C.RESIST_TURNS // 2 if half else C.RESIST_TURNS,
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
        # 2~5. 이동 → 해전 → 폭격 → 지상 공격
        self._phase_move()
        self._phase_naval()
        self._phase_bombard()
        self._phase_attack()
        # 6. 점령·편입 (먼저 우선순위대로 이번 턴 지출을 정한다)
        self._fund_projects()
        self._phase_claims()                 # 무력 점령·편입: 게이지가 함께 차고 먼저 채운 쪽이 차지
        # 7. 건설·생산 (군 생산에 쓴 지역은 징집 피로 기록)
        drafted = self._phase_projects(("build", "unit", "landmark", "capital"))
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
        # 연말 랭킹
        if self.turn % C.TURNS_PER_YEAR == 0:
            self._year_ranking()
        self._check_victory()
        for f in self.factions:
            f.buy_count = {}
            f.trade_buy = 0.0
            f.trade_sell = 0.0
            f.spend = {}
            f.refund = 0.0
        for a in self.armies.values():
            if a.order and a.order.get("type") in ("move", "attack", "land", "bombard"):
                a.order = None
        self.turn += 1
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
        p = sum(C.NAVAL_DD_POWER * a.units.get("dd", 0)
                + C.NAVAL_BMB_POWER * (a.units.get("bmb", 0) + a.units.get("stl", 0)) for a in fleets)
        if self.coast_controller(sid) == fid:
            p *= 1 + C.COAST_NAVAL_DEF
        return p * self.morale(fid)

    def _naval_battle(self, sid, x, fx, y, fy):
        px, py = self._naval_power(x, fx, sid), self._naval_power(y, fy, sid)
        if px <= 0 and py <= 0:
            return
        r = self.rng.uniform(C.RAND_LO, C.RAND_HI)
        dy, dx = R.battle_damage(px, py, r)
        lx = self._ship_damage(fx, dx, y, sid)
        ly = self._ship_damage(fy, dy, x, sid)
        self._score_units(x, y, ly)
        self._score_units(y, x, lx)
        self.event("battle", f"해전({self.world.seas[sid].name}): {self.fname(x)} 손실 {sum(lx.values())}척, "
                   f"{self.fname(y)} 손실 {sum(ly.values())}척", fids=(x, y))

    def _ship_damage(self, fleets, dmg, enemy, sid):
        lost = {}
        for key in ("dd", "cv", "lst"):
            for a in fleets:
                if a.id not in self.armies:
                    continue
                hp = C.UNITS[key]["hp"]
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
                                ea[0].units[key] = ea[0].units.get(key, 0) + 1
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

    def _bombard(self, a, tgt, units):
        rr = self.regions[tgt]
        m = self.mods(a.owner)
        aa = rr.b["aa"] if rr.owner != NEUTRAL else 0
        bombers = {k: units.get(k, 0) for k in ("bmb", "stl")}
        n_bomb = sum(bombers.values())
        notes = []
        if n_bomb:
            # 공중전: 방어측 전투기 - 호위 전투기
            def_armies = [x for loc in [tgt] + list(self.world.land_adj[tgt])
                          for x in self.hostile_units_at(a.owner, loc) if x.units.get("ftr")]
            def_ftr = sum(x.units["ftr"] for x in def_armies)
            esc = a.units.get("ftr", 0)
            net = max(0, def_ftr - esc)
            shot = min(bombers["bmb"], int(net * C.INTERCEPT_PER_FIGHTER + self.rng.random()))
            fl = int(min(def_ftr, esc) * C.FIGHTER_LOSS + self.rng.random() * 0.999) if min(def_ftr, esc) else 0
            if fl:
                a.units["ftr"] = max(0, a.units.get("ftr", 0) - fl)
                left = fl
                for x in def_armies:
                    t = min(left, x.units["ftr"])
                    x.units["ftr"] -= t
                    left -= t
            # 대공포
            for k in ("bmb", "stl"):
                for _ in range(bombers[k]):
                    if k == "bmb":
                        p = C.AA_SHOOT_K * aa
                    else:
                        p = C.STEALTH_AA_SHOOT if aa >= 5 else 0.0
                    if self.rng.random() < p:
                        shot += 1 if k == "bmb" else 0
                        if k == "stl":
                            bombers["stl"] -= 1
                            a.units["stl"] -= 1
            shot = min(shot, a.units.get("bmb", 0))
            if shot:
                a.units["bmb"] -= shot
                bombers["bmb"] = max(0, bombers["bmb"] - shot)
                notes.append(f"폭격기 {shot}대 격추")
            a.units = {k: v for k, v in a.units.items() if v > 0}
        dmg = units.get("art", 0) * C.UNITS["art"]["bomb"] * m.mult("bomb_art")
        dmg += units.get("dd", 0) * C.UNITS["dd"]["bomb"]
        dmg += bombers.get("bmb", 0) * C.UNITS["bmb"]["bomb"] * (1 - C.AA_DMG_K * aa)
        dmg += bombers.get("stl", 0) * C.UNITS["stl"]["bomb"] * (C.STEALTH_AA_DMG if aa >= 5 else 1.0)
        dmg *= self.rng.uniform(C.RAND_LO, C.RAND_HI) / (1 + C.SHELTER_K * rr.b["shelter"])
        dmg *= self.morale(a.owner)
        defenders = self.hostile_units_at(a.owner, tgt)
        lost = self.apply_damage(defenders, dmg) if defenders else {}
        self._score_units(a.owner, rr.owner, lost)
        # 건물 피해: 포병·함포 30%, 폭격기 60%, 둘 다 90%로 생산·방어 건물(방어선 포함) 하나 −1단계
        guns = units.get("art", 0) + units.get("dd", 0) > 0
        p = R.bomb_building_chance(guns, sum(bombers.values()) > 0)
        if p and self.rng.random() < p:
            hit = self.bomb_targets(tgt)
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
        if a.empty():
            self.remove_army(a)
        self.battle_regions.append(tgt)
        self.event("bomb", f"{self.fname(a.owner)} → {self.info(tgt).name} 폭격: 피해 {dmg:.0f}"
                   + (f", 격파 {sum(lost.values())}" if lost else "") + ("; " + ", ".join(notes) if notes else ""),
                   region=tgt, fids=(a.owner, rr.owner))

    # ---- 5. 지상 공격
    def bomb_targets(self, rid):
        """폭격으로 부술 수 있는 건물: 생산 건물·방공호·대공포 키와 'line:경계' 방어선."""
        rr = self.regions[rid]
        out = [k for k in list(C.PROD_BUILDINGS) + ["shelter", "aa"] if rr.b.get(k, 0) > 0]
        out += [f"line:{b}" for b, lv in sorted(rr.lines.items()) if lv > 0]
        return out

    def _phase_attack(self):
        orders = [a for a in self.armies.values() if a.order and a.order["type"] == "attack"]
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
            else:
                dd *= fail[0]
                ad *= fail[1]
                note = "기습 실패"
        elif line > 0 and dd > ad and rr.owner != NEUTRAL and self.rng.random() < C.ASSAULT_LINE_BREAK:
            rr.lines[main] = line - 1          # 돌격에 밀린 방어선이 무너진다
            note = f"방어선 {line} → {line - 1}단계"
        filt = C.SURPRISE_UNITS if mode == "surprise" else C.ASSAULT_UNITS
        def_owner = defenders[0].owner if defenders else rr.owner
        lost_d = self.apply_damage(defenders, dd)
        lost_a = self.apply_damage([x for x in attackers if x.id in self.armies], ad, unit_filter=filt)
        self._score_units(fid, def_owner, lost_d)
        self._score_units(def_owner, fid, lost_a)
        self.battle_regions.append(tgt)
        self.event("battle", f"{'기습' if mode == 'surprise' else '돌격'}: {self.fname(fid)} → {self.info(tgt).name}"
                   f" (A {A:.0f} / D {Dv:.0f}{', ' + note if note else ''}) 공격측 손실 {sum(lost_a.values())},"
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
        """동시에 완료됐을 때의 우선순위: 대상과 맞닿은(또는 해로로 편입 중인) 내 지역 중 가장 큰 인구."""
        regs = [self.regions[n] for n in self.world.land_adj[rid] if self.regions[n].owner == fid]
        regs += [r for r in self.regions.values() if r.owner == fid and r.project
                 and r.project.kind == "annex" and r.project.key == rid]
        return max((r.pop for r in regs), default=0.0)

    def _phase_claims(self):
        """6. 점령·편입: 무력 점령과 편입 게이지가 함께 차고, 먼저 다 채운 쪽이 그 지역을 차지한다.
        같은 턴에 둘 이상이 다 채우면 대상과 맞닿은 지역의 인구가 많은 쪽이 차지한다."""
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
                           f"맞닿은 지역 인구가 가장 많은 {self.fname(cl[0][1])}이(가) 차지합니다.",
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

    # ---- 6~7. 슬롯 진행
    def _fund_projects(self):
        """세력마다 우선순위 순서로 이번 턴 비용을 낸다. 모자라면 그 작업은 정지(뒤의 더 싼 작업은 진행 가능)."""
        for f in self.factions:
            if not f.alive:
                continue
            self._reserve_food(f)          # 식량 부족이 예상되면 식량 구매가 최우선
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

    def expected_food_balance(self, f) -> float:
        """이번 턴 자원 단계 뒤 예상 식량 비축(비축 + 생산 − 소비)."""
        regs = self.regions_of(f.id)
        prod = sum(0.0 if r.occ or self.resisting(r) else
                   R.food_output(r.b["farm"], r.b["fishery"], self.fish_mult(f.id, r.id)) for r in regs)
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
                       region=p.key, fids=(f.id,))

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
            n = self.joint_count(rr.owner, p.key)
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
                text = f"{name} {BUILDING_NAMES[p.key]} {p.level}단계 완공"
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
        elif p.kind == "landmark":
            rr.landmark = True
            rr.landmark_name = p.name or self.default_landmark_name(rr.id)
            rr.h_delta += C.LANDMARK_HAPPY
            for n in self.world.land_adj[rr.id]:
                if self.regions[n].owner == f.id:
                    self.regions[n].h_delta += C.LANDMARK_ADJ_HAPPY
            text = f"{name} 랜드마크 「{rr.landmark_name}」 완공!"
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
        for r in active:
            info = self.info(r.id)
            if info.is_oil:
                res["oil"] += info.oil + r.b["extract"]
            if info.is_coal:
                res["coal"] += info.coal + r.b["extract"]
            res["elec"] += info.power_self
            if r.b["specialty"]:
                for sp in info.specialties:
                    f.specialty[sp] = f.specialty.get(sp, 0) + r.b["specialty"]
        factories = sorted([r for r in active if r.b["factory"] > 0], key=lambda r: -r.b["factory"])
        want_elec = sum(1 for r in factories if r.fuel in ("auto", "elec"))
        want_coal = sum(1 for r in factories if r.fuel == "coal")
        # 발전소: 석탄(부족하면 석유) -> 전기
        cap = sum(2 * r.b["power"] for r in active)
        need = max(0, want_elec - int(res["elec"]))
        conv = 0
        while conv < min(cap, need):
            if res["coal"] - want_coal >= 1:
                res["coal"] -= 1
            elif res["oil"] > C.OIL_RESERVE_FOR_LIQUEFY:
                res["oil"] -= 1
            else:
                break
            res["elec"] += 1
            conv += 1
        # 석탄액화: 석유 비축이 적을 때 석탄 -> 석유
        lcap = sum(r.b["liquefy"] for r in active)
        if f.liquefy:
            n = 0
            while n < lcap and res["oil"] < C.OIL_RESERVE_FOR_LIQUEFY and res["coal"] - want_coal >= 1:
                res["coal"] -= 1
                res["oil"] += 1
                n += 1
        for r in regs:
            r.phi = 1.0
        for r in factories:
            order = C.FUEL_AUTO_ORDER if r.fuel == "auto" else (r.fuel,)
            r.phi = C.FUEL_PHI["none"]
            for fuel in order:
                if res.get(fuel, 0) >= 1:
                    res[fuel] -= 1
                    r.phi = C.FUEL_PHI[fuel]
                    break
        live = {r.id for r in active}
        for r in regs:
            r.output = self.calc_output(r.id) if r.id in live else 0.0
            r.food = R.food_output(r.b["farm"], r.b["fishery"], self.fish_mult(f.id, r.id)) if r.id in live else 0.0
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
            r.h_delta += C.SPECIALTY_HAPPY * (len(new[r.id] - old[r.id]) - len(old[r.id] - new[r.id]))
            r.supplied = new[r.id]

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

    # ---- 랜드마크 이름
    def default_landmark_name(self, rid) -> str:
        short = self.info(rid).short
        base = short
        for suf in ("구역", "지구", "시", "군", "구"):
            if short.endswith(suf) and len(short) > len(suf):
                base = short[: -len(suf)]
                break
        if len(base) <= 1:   # 광역시 북구·중구처럼 한 글자가 되면 '구'를 붙인다
            base = short
        return f"{base} 타워"

    # ---- 9. 세수·유지비
    def upkeep(self, fid) -> float:
        total = 0.0
        m = self.mods(fid)
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
                total += c
        return total * C.MONEY_SCALE

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
                g = R.pop_growth_rate(self.eff_happy(r)) * f.pop_mult
                cap = info.pop0 * C.POP_CAP_START_MULT + C.POP_CAP_PER_LEVEL * r.level_sum()
                if g > 0 and r.pop < cap:
                    r.pop += r.pop * g * (1 - r.pop / cap)
            if self.eff_happy(r) <= C.MIGRATION_H:
                r.pop *= 1 + C.MIGRATION_POP
            r.pop = max(0.1, r.pop)

    # ---- 11. 행복도
    def _phase_happiness(self):
        per_fac = {}
        for f in self.factions:
            if not f.alive:
                continue
            m = self.mods(f.id)
            t = R.tax_happiness(f.tax * 100, m.value("tax_over10", 1.0), m.value("tax_over15", 1.0))
            t += m.add("happy_turn")
            # 전쟁 피로도: 전쟁 중이면 쌓이고(선포한 쪽 1, 당한 쪽 0.5/턴), 평시엔 턴당 1 회복
            rate = D.war_weary_rate(self, f.id)
            D.add_war_weary(self, f.id, rate if rate else -C.WAR_WEARY_RECOVERY)
            floor = 0.0 if f.happy_floor_until > self.turn else C.HAPPY_MIN
            per_fac[f.id] = (t, m.value("happy_cap", C.HAPPY_MAX), floor)
        for r in self.regions.values():
            r.bombed = False
            if r.owner == NEUTRAL or r.owner not in per_fac:
                r.h_delta = 0.0
                continue
            t, cap, floor = per_fac[r.owner]
            h = (r.happy + r.h_delta + t) * C.HAPPY_DECAY
            r.happy = max(floor, min(cap, h))
            r.h_delta = 0.0
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

    def eff_happy(self, rr) -> float:
        """실질 행복도 = 행복도(저항 반영) − 전쟁 피로도 − 징집 피로. 산출·반란·인구·사기 판정에 쓴다."""
        if rr.owner == NEUTRAL:
            return rr.happy
        f = self.factions[rr.owner]
        h = self.base_happy(rr) - f.war_weary - rr.conscript
        if f.happy_floor_until > self.turn:
            h = max(0.0, h)
        return max(C.HAPPY_MIN, min(C.HAPPY_MAX, h))

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
        p = R.rebellion_probability(self.eff_happy(rr)) * self.mods(fid).mult("rebel_prob")
        if self.mods(fid).value("avg_rebel") and self.avg_happiness(fid) <= -30:
            p *= self.mods(fid).value("avg_rebel")
        return min(1.0, p)

    def _phase_rebellion(self):
        from . import ai
        for f in self.factions:
            if not f.alive:
                continue
            for r in list(self.regions_of(f.id)):
                if self.eff_happy(r) > C.REBEL_THRESHOLD:
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
        Rv = rr.pop * 2 * max(0.0, -self.eff_happy(rr) / 50)
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
        Rv = rr.pop * 2 * max(0.0, -self.eff_happy(rr) / 50)
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
        n_inf = max(1, int(round(Rv / 12)))
        keep_project = rr.project if rr.project and rr.project.kind in ("build", "unit", "landmark") else None
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
        pool = [l["key"] for l in LEADER_BY_KEY.values() if l["key"] != "custom" and l["key"] not in taken]
        lk = self.rng.choice(pool or [l for l in LEADER_BY_KEY if l != "custom"])
        leader = LEADER_BY_KEY[lk]
        name = faction_name_from(info.short)
        if any(f.name == name for f in self.factions):
            name = name[:-1] + " 공화국"
        f = Faction(id=nid, name=name, color=color, leader=lk, leader_name=leader["name"], gov=None,
                    is_ai=True, capital=rid, aggression=leader["aggr"], rebel_of=fid)
        f.gov = ai_pick_government(self.rng, f.aggression, rr.b["factory"], rr.b["bank"])
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
        st = self.settings
        alive = self.alive_ids()
        if not self.player.alive and not st.all_ai:
            self.winner = None
            self.game_over = True
            self.event("gameover", "패배: 모든 영토를 잃었습니다.", fids=(self.player_id,))
            return
        if len(alive) == 1 and "conquest" in st.victories and len(self.factions) > 1:
            self._win((alive[0],), "conquest")
            return
        if "economic" in st.victories:
            gd = {f: self.gdp(f) for f in alive}
            for fid in alive:
                others = sum(v for k, v in gd.items() if k != fid)
                f = self.factions[fid]
                if gd[fid] > C.ECON_VICTORY_RATIO * others and others >= 0:
                    f.econ_streak += 1
                else:
                    f.econ_streak = 0
                if f.econ_streak >= C.ECON_VICTORY_TURNS:
                    self._win((fid,), "economic")
                    return
        if "landmark" in st.victories:
            for fid in alive:
                lm = [r for r in self.regions_of(fid) if r.landmark]
                dos = {self.info(r.id).do8 for r in lm}
                cap = self.regions[self.factions[fid].capital]
                if all(d in dos for d in DO8) and cap.landmark and cap.owner == fid:
                    self._win((fid,), "landmark")
                    return

    def _win(self, fids, kind):
        self.winner = (tuple(fids), kind)
        self.game_over = True
        names = ", ".join(self.fname(f) for f in fids)
        self.event("victory", f"{C.VICTORY_TYPES[kind]}: {names}", fids=fids)

    def _year_ranking(self):
        rows = []
        for f in self.factions:
            if not f.alive:
                continue
            rows.append({"fid": f.id, "name": f.name, "money": f.money, "net": f.last.get("net", 0),
                         "happy": self.avg_happiness(f.id), "pop": self.total_pop(f.id),
                         "regions": self.region_count(f.id)})
        year = R.date_of_turn(self.turn)[0]
        self.rankings[year] = rows
        self.new_ranking = year
        self.event("ranking", f"{year}년 연말 랭킹이 발표되었습니다.")

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

    def _update_fog(self, initial=False):
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
            for rid in vis:
                if rid in self.regions:
                    f.last_seen[rid] = self.regions[rid].owner

    def is_visible(self, fid, node) -> bool:
        return self.settings.fog == 0 or node in self.visible(fid)

    def is_explored(self, fid, node) -> bool:
        if self.settings.fog == 0 or node in self.world.seas:
            return True
        return node in self.factions[fid].explored
