"""건물 슬롯(v1.3.8): 지역마다 기본·하천·해안 슬롯에 건물 카드를 꽂는다.

- 기본 슬롯: 면적에 따라 2~6칸. 농장·공장·시장·행정·연구·사관학교·지하자원 시설(탄광·정유공장)
- 하천 슬롯: 하천과 맞닿은 지역(내륙 어장이 있는 지역 포함) 1칸. 하천 어장·화력발전소
- 해안 슬롯: 바다와 맞닿은 지역 1칸. 항구·바다 어장·화력발전소
- 기타 슬롯(v1.3.9): 위 세 슬롯을 차지하지 않는 입지 건물 — 수력발전소(댐)·원자력발전소·특산물 시설의
  자리가 입지마다 한 칸씩 있고, 장보고 '청해진 해상왕'의 무료 항구는 기타 슬롯에 한 칸을 더 붙여 꽂는다.
- 방어 건물·공항·과학·경제 시설은 슬롯을 쓰지 않는다.

카드는 {"key": 건물 키, "level": 단계}, 빈 칸은 None. 같은 생산 건물을 여러 칸에 지을 수 있고(행정·연구·
사관학교·항구·수력·원자력·특산물 시설은 지역에 하나), 산출·연료는 카드마다 따로 계산해 더한다.

지역의 r.b 는 Buildings(사전)다. 슬롯 건물 키의 값은 그 종류 카드 가운데 가장 높은 단계(없으면 0)로, 승리·위인·
광역시 조건처럼 '○○ n단계 지역'을 볼 때 그대로 쓴다. 슬롯 건물 키에 값을 쓰면 가장 높은 카드의 단계가 바뀌고
(0 이하면 그 카드를 빼고), 그 종류 카드가 없으면 빈 슬롯에 새 카드를 꽂는다(빈 슬롯이 없으면 그대로).
pygame 없이 엔진·화면·도구가 함께 쓴다.
"""
from __future__ import annotations

from . import config as C

SLOT_TYPES = ("base", "river", "coast", "etc")
SLOT_NAMES = {"base": "기본", "river": "하천", "coast": "해안", "etc": "기타"}
SLOT_KEYS = {
    "base": ("farm", "factory", "bank", "admin", "edu", "academy", "extract"),
    "river": ("fishery", "power"),
    "coast": ("port", "fishery", "power"),
    "etc": ("hydro", "nuclear", "specialty", "port"),
}
# 기타 슬롯에 입지마다 한 칸씩 자리가 있는 건물(항구는 장보고 무료 항구만 기타 슬롯에)
ETC_KEYS = ("hydro", "nuclear", "specialty")
CARD_KEYS = frozenset(k for keys in SLOT_KEYS.values() for k in keys)
# 지역에 하나만 지을 수 있는 카드(행정·연구·사관학교·항구, 댐·원전·특산물 시설은 입지가 하나)
UNIQUE_KEYS = frozenset(("admin", "edu", "academy", "port", "hydro", "nuclear", "specialty"))
# 같은 건물을 여러 칸에 지을 수 있는 생산 건물
STACK_KEYS = ("farm", "fishery", "factory", "bank", "power", "extract")
# 슬롯을 정하지 않고 카드를 꽂을 때(광역시 통합 건물·예전 세이브) 고르는 순서. 항구는 해안 슬롯에만 짓는다
PREFER = {"fishery": ("coast", "river"), "power": ("river", "coast"), "port": ("coast",)}
# 면적(km²) 상한 → 기본 슬롯 칸 수. 1,000km² 초과는 6칸
BASE_SLOT_AREA = ((100, 2), (300, 3), (600, 4), (1000, 5))
BASE_SLOT_MAX = 6

# 시험·검사 도구 전용: r.b[키] = 단계 로 건물을 억지로 넣을 때 빈 칸이 없으면 칸을 하나 늘린다(게임은 늘 False).
GROW_WHEN_FULL = False

ALL_BUILDINGS = ("admin", "edu", "farm", "fishery", "factory", "bank", "power", "specialty", "extract", "hydro", "nuclear",
                 "shelter", "aa", "academy", "airport", "port")


def base_slot_count(area_km2) -> int:
    for top, n in BASE_SLOT_AREA:
        if area_km2 <= top:
            return n
    return BASE_SLOT_MAX


def has_river_slot(world, rid) -> bool:
    """하천 슬롯: 도하 경계·국경 하천·내륙 하천에 맞닿은 지역, 바다와 닿지 않았는데 어장이 있는 지역."""
    info = world.regions[rid]
    return rid in world.river_regions or (info.fishery > 0 and not info.coastal)


def etc_kinds(info) -> list:
    """그 지역 기타 슬롯에 자리가 있는 건물(댐·원전·특산물 입지)."""
    return [k for k in ETC_KEYS if (info.specialty if k == "specialty" else getattr(info, k, 0))]


def capacity(world, rid) -> dict:
    """{"base": 2~6, "river": 0~1, "coast": 0~1, "etc": 0~3}(기타 슬롯의 무료 항구 칸은 따로 붙는다)"""
    info = world.regions[rid]
    return {"base": base_slot_count(info.area_km2), "river": int(has_river_slot(world, rid)),
            "coast": int(bool(info.coastal)), "etc": len(etc_kinds(info))}


def start_port_bonus(info, mode="standard") -> bool:
    """시작할 때 항구를 받는 지역(현실: 시작 항구 16곳, 개척·혼돈: 무연륙 섬). v1.3.9: 항구를 받은 만큼
    해안 슬롯을 1칸 더 준다(기본 제공 항구가 어장·발전소 자리를 빼앗지 않게)."""
    if not info.coastal:
        return False
    return bool(info.start_port) if mode == "standard" else info.island == "무연륙 섬"


def give_start_port(b):
    """해안 슬롯 맨 앞에 칸을 하나 더 만들고 시작 항구를 꽂는다(새 판을 만들 때만 — 칸 번호가 밀린다)."""
    b.slots["coast"].insert(0, None)
    b.place("port", 1, ("coast", 0))


def slot_lengths(world, rid, mode="standard", free=0) -> dict:
    """그 지역 슬롯 칸 수(시작 항구 덤 해안 칸, 기타 슬롯에 붙인 무료 카드 free 장 포함)."""
    cap = capacity(world, rid)
    cap["coast"] += int(start_port_bonus(world.regions[rid], mode))
    cap["etc"] += int(free)
    return cap


def slot_types_for(key) -> tuple:
    """이 건물을 꽂을 수 있는 슬롯 종류(고르는 순서대로)."""
    if key in PREFER:
        return PREFER[key]
    return tuple(t for t in SLOT_TYPES if key in SLOT_KEYS[t])


def max_level(key, info=None) -> int:
    """카드 한 장의 최대 단계(광역시 6단계는 metro 쪽에서). 댐·원전은 그 입지의 자체 발전량으로 고정."""
    if key in ("hydro", "nuclear"):
        return max(1, int(getattr(info, key, 1) or 1)) if info is not None else 1
    if key in C.SINGLE_BUILDINGS:
        return 1
    return C.PROD_BUILDINGS[key]["max"]


def slot_label(slot) -> str:
    """('base', 0) → '기본 슬롯 1'"""
    stype, idx = slot
    return f"{SLOT_NAMES[stype]} 슬롯 {idx + 1}"


class Buildings(dict):
    """r.b: 건물 키 → 단계(슬롯 건물은 최고 단계). 슬롯은 self.slots = {"base": [...], "river": [...], "coast": [...]}."""

    def __init__(self, cap=None, values=None):
        super().__init__()
        cap = cap or {}
        self.slots = {t: [None] * int(cap.get(t, 0)) for t in SLOT_TYPES}
        for k in ALL_BUILDINGS:
            dict.__setitem__(self, k, 0)
        if values:
            self.update(values)

    # ---- 피클·복사: 사전 값과 슬롯을 그대로(값을 다시 쓰며 카드를 만들지 않는다)
    def __reduce__(self):
        return (_restore, (dict(self), self.slots, getattr(self, "xmult", None)))

    def __copy__(self):
        return _restore(dict(self), {t: list(v) for t, v in self.slots.items()}, dict(getattr(self, "xmult", None) or {}))

    def mult_of(self, stype) -> int:
        """광역 슬롯 배수(v1.3.16): 광역시 중심에 모은 카드는 그 슬롯을 가진 구성 지역 수만큼 산출한다(보통 1)."""
        xm = getattr(self, "xmult", None)
        return int(xm.get(stype, 1)) if xm else 1

    # ---- 조회
    def cards(self, key=None):
        """(슬롯 종류, 칸 번호, 카드). key 를 주면 그 건물만."""
        for t in SLOT_TYPES:
            for i, c in enumerate(self.slots.get(t, ())):
                if c is not None and (key is None or c["key"] == key):
                    yield t, i, c

    def levels(self, key) -> list:
        """그 건물 카드들의 단계(높은 순). 광역 슬롯 카드는 배수만큼 되풀이한다(산출 계산용)."""
        return sorted((c["level"] for t, _, c in self.cards(key) for _ in range(self.mult_of(t))), reverse=True)

    def cap(self, key) -> int:
        """그 건물 카드들의 단계 합(공장·발전소 연료 칸, 농장·어장·채굴 산출, 광역 슬롯은 배수 포함)."""
        if key not in CARD_KEYS:
            return dict.get(self, key, 0)
        return sum(c["level"] * self.mult_of(t) for t, _, c in self.cards(key))

    def count(self, key) -> int:
        return sum(1 for _ in self.cards(key))

    def card(self, slot):
        stype, idx = slot
        lst = self.slots.get(stype, ())
        return lst[idx] if 0 <= idx < len(lst) else None

    def valid(self, slot) -> bool:
        stype, idx = slot
        return stype in self.slots and 0 <= idx < len(self.slots[stype])

    def primary(self, key):
        """가장 높은 단계의 카드 자리(같으면 앞 칸)."""
        best = None
        for t, i, c in self.cards(key):
            if best is None or c["level"] > best[2]:
                best = (t, i, c["level"])
        return (best[0], best[1]) if best else None

    def empty(self, stype) -> list:
        return [i for i, c in enumerate(self.slots.get(stype, ())) if c is None]

    def free(self, key):
        """그 건물을 새로 꽂을 빈 칸(없으면 None)."""
        if key not in CARD_KEYS or (key in UNIQUE_KEYS and self.count(key)):
            return None
        for t in slot_types_for(key):
            e = self.empty(t)
            if e:
                return t, e[0]
        return None

    def total(self) -> int:
        return sum(len(v) for v in self.slots.values())

    def free_cards(self) -> int:
        """기타 슬롯에 붙인 무료 카드(장보고 항구) 수."""
        return sum(1 for c in self.slots.get("etc", ()) if c and c.get("free"))

    def used(self) -> int:
        return sum(1 for _ in self.cards())

    # ---- 변경
    def place(self, key, level, slot=None) -> bool:
        """카드를 꽂는다(slot 을 안 주면 고르는 순서대로 빈 칸). 못 꽂으면 False."""
        level = int(level)
        if level <= 0 or key not in CARD_KEYS:
            return False
        if slot is None:
            slot = self.free(key)
            if slot is None:
                return False
        stype, idx = slot
        if not self.valid(slot) or self.slots[stype][idx] is not None or key not in SLOT_KEYS[stype]:
            return False
        if key in UNIQUE_KEYS and self.count(key):
            return False
        self.slots[stype][idx] = {"key": key, "level": level}
        self._sync(key)
        return True

    def add_free(self, key, level=1) -> bool:
        """기타 슬롯에 칸을 하나 붙여 무료 카드를 꽂는다(장보고 무료 항구). 다른 슬롯은 차지하지 않는다."""
        if key in UNIQUE_KEYS and self.count(key):
            return False
        lst = self.slots.setdefault("etc", [])
        lst.append({"key": key, "level": int(level), "free": True})
        self._sync(key)
        return True

    def remove(self, slot):
        """그 칸을 비운다(무료로 붙인 기타 칸은 칸째 없앤다). 뺀 카드를 돌려준다."""
        if not self.valid(slot):
            return None
        stype, idx = slot
        c = self.slots[stype][idx]
        self.slots[stype][idx] = None
        if c is not None and c.get("free") and stype == "etc" and idx == len(self.slots[stype]) - 1:
            self.slots[stype].pop()
        if c is not None:
            self._sync(c["key"])
        return c

    def set_card(self, slot, level):
        """그 칸 카드의 단계를 바꾼다(0 이하면 비운다)."""
        c = self.card(slot)
        if c is None:
            return
        if level <= 0:
            self.remove(slot)
            return
        c["level"] = int(level)
        self._sync(c["key"])

    def clear_cards(self):
        for t in SLOT_TYPES:
            lst = self.slots.get(t, [])
            self.slots[t] = [None] * (len(lst) - sum(1 for c in lst if c and c.get("free")))
        for k in CARD_KEYS:
            dict.__setitem__(self, k, 0)

    def reset(self, values):
        """r.b = {...}: 카드를 모두 빼고 값을 새로 쓴다(슬롯 칸 수는 그대로)."""
        self.clear_cards()
        for k in list(dict.keys(self)):
            dict.__setitem__(self, k, 0)
        self.update(values)

    def _sync(self, key):
        dict.__setitem__(self, key, max((c["level"] for _, _, c in self.cards(key)), default=0))

    def resync(self):
        for k in CARD_KEYS:
            self._sync(k)

    def __setitem__(self, key, value):
        if key not in CARD_KEYS or not hasattr(self, "slots"):
            dict.__setitem__(self, key, value)
            return
        value = int(value)
        pos = self.primary(key)
        if pos is None:
            # (광역 슬롯에 합쳐진 구성 지역은 기본 슬롯이 비어 있다 — 시험 도구도 칸을 늘리지 않는다)
            if value > 0 and not self.place(key, value) and GROW_WHEN_FULL and self.slots.get("base"):
                stype = slot_types_for(key)[0]
                self.slots[stype].append(None)
                self.place(key, value, (stype, len(self.slots[stype]) - 1))
            self._sync(key)
        else:
            self.set_card(pos, value)

    def update(self, other=(), **kw):
        items = list(other.items()) if hasattr(other, "items") else list(other)
        for k, v in items + list(kw.items()):
            self[k] = v

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return default


def _restore(values, slots, xmult=None):
    b = Buildings.__new__(Buildings)
    dict.update(b, values)
    b.slots = slots
    if xmult:
        b.xmult = xmult
    return b


def round_half_up(v) -> int:
    import math
    return int(math.floor(v + 0.5 + 1e-9))


def split_average(total, n) -> list:
    """광역시 합병 단계(v1.3.16): 레벨 합 ÷ 지역 수를 반올림(하나라도 있으면 최소 1). 평균이 5를 넘으면 5단계 카드
    하나에 (평균 − 5)를 반올림한 카드를 더 붙인다(예: 4곳 합 3 → [1], 10 → [3], 22 → [5, 1])."""
    if total <= 0 or n <= 0:
        return []
    avg = total / n
    out = []
    while avg > 5 + 1e-9:
        out.append(5)
        avg -= 5
    last = round_half_up(avg)
    if last >= 1:
        out.append(last)
    return out or [1]


def new(world, rid, values=None) -> Buildings:
    return Buildings(capacity(world, rid), values)


# ------------------------------------------------------------------ 현실 모드 시작 카드(v1.3.8)
def _scaled(old, pop, area=0.0, farm=False) -> int:
    """자료의 1~2단계를 인구·면적 규모에 맞춰 1~3단계로."""
    if old <= 0:
        return 0
    if old >= 2 and (area >= 600 if farm else pop >= 50):
        return 3
    if old >= 2 or pop >= 30:
        return 2
    return 1


def admin_start_level(pop) -> int:
    """시작 인구 20만 미만 없음 / 20~50만 주민센터 / 50~100만 구청 / 100만 이상 시청."""
    return 0 if pop < 20 else 1 if pop < 50 else 2 if pop < 100 else 3


def initial(world, rid, pop=None) -> Buildings:
    """현실 모드 시작 건물: regions.csv 와 인구 규모로 0~3단계 카드를 슬롯 칸 수 안에서 꽂는다.
    시작 항구는 해안 슬롯을 1칸 더 만들어 꽂는다(v1.3.9)."""
    info = world.regions[rid]
    pop = info.pop0 if pop is None else pop
    b = new(world, rid)
    if start_port_bonus(info, "standard"):
        give_start_port(b)
    src = info.power_source or ""
    thermal = bool(src) and not info.hydro and not info.nuclear      # 화력발전소 소재지(댐·원전은 기타 슬롯)
    coastal_plant = thermal and info.coastal
    plant_lv = max(1, min(2, int(info.power_self or 0)))
    fish_used = False
    # 0. 기타 슬롯(v1.3.9): 댐·원전·특산물 시설은 입지 칸에(다른 슬롯을 차지하지 않는다)
    for key in etc_kinds(info):
        b.place(key, 1 if key == "specialty" else max_level(key, info))
    # 1. 해안 슬롯(항구를 꽂은 덤 칸 말고 남은 칸): 해안 화력발전소 > 바다 어장
    if b.empty("coast"):
        spot = ("coast", b.empty("coast")[0])
        if coastal_plant:
            b.place("power", plant_lv, spot)
        elif info.fishery > 0:
            b.place("fishery", min(3, _scaled(info.fishery, pop)), spot)
            fish_used = True
    # 2. 하천 슬롯: 내륙 화력발전소 > 하천 어장
    if b.slots["river"]:
        if thermal and not coastal_plant:
            b.place("power", plant_lv, ("river", 0))
        elif info.fishery > 0 and not fish_used:
            b.place("fishery", min(2, _scaled(info.fishery, pop)), ("river", 0))
    # 3. 기본 슬롯: 행정 → 연구 → 지하자원 → 시장·공장·농장
    b.place("admin", admin_start_level(pop))
    if rid in C.INITIAL_EDU:
        b.place("edu", 2)
    if info.oil > 0 or info.coal > 0:
        b.place("extract", 2 if max(info.oil, info.coal) >= 2 else 1)
    urban = info.rtype != "군"
    order = ("bank", "factory", "farm") if urban else ("farm", "factory", "bank")
    want = []
    for key in order:
        old = getattr(info, key)
        lv = _scaled(old, pop, info.area_km2, farm=key == "farm")
        if lv:
            want.append((key, lv))
    for key, lv in want:
        b.place(key, lv)
    # 기본 슬롯 5~6칸의 넉넉한 지역(대농업군·산업도시): 주력 건물(가장 높은 단계, 같으면 도심·농촌 순서) 카드를 한 장 더
    if want and len(b.slots["base"]) >= 5 and b.empty("base"):
        b.place(*max(want, key=lambda kv: (kv[1], -order.index(kv[0]))))
    return b


# ------------------------------------------------------------------ 예전 세이브(면적·주거 지구 시절) 옮기기
MIGRATE_ORDER = ("admin", "edu", "academy", "extract", "factory", "bank", "farm")


def from_legacy(world, rid, old: dict, mode="standard") -> tuple:
    """예전 r.b 사전 → Buildings. 슬롯에 들어가지 않는 건물은 버린다. (Buildings, 버린 [(키, 단계)])"""
    b = new(world, rid)
    if start_port_bonus(world.regions[rid], mode):
        b.slots["coast"].append(None)                 # 시작 항구 덤 칸(v1.3.9)
    dropped = []
    for k, v in old.items():
        if k not in CARD_KEYS and k in ALL_BUILDINGS:
            dict.__setitem__(b, k, v)
    # 기타: 원전·댐·특산물 시설, 해안·하천: 발전소 > 항구 > 어장 순으로 자리를 잡는다
    for key in ("nuclear", "hydro", "specialty", "power", "port", "fishery"):
        lv = int(old.get(key, 0) or 0)
        if lv <= 0:
            continue
        if key in ("hydro", "nuclear"):
            lv = max_level(key, world.regions[rid])
        if not b.place(key, lv):
            dropped.append((key, lv))
    base = sorted((k for k in MIGRATE_ORDER if int(old.get(k, 0) or 0) > 0),
                  key=lambda k: (MIGRATE_ORDER.index(k) >= 4, -int(old.get(k, 0)), MIGRATE_ORDER.index(k)))
    for key in base:
        lv = int(old[key])
        if not b.place(key, lv):
            dropped.append((key, lv))
    if int(old.get("housing", 0) or 0) > 0:
        dropped.append(("housing", int(old["housing"])))
    return b, dropped


def migrate_etc(world, rid, b, mode="standard") -> bool:
    """v1.3.8 세이브(기타 슬롯 전): 하천·해안 슬롯의 댐·원전 카드와 슬롯 밖 특산물 시설 단계를 기타 슬롯으로 옮기고,
    시작 항구 지역에 해안 슬롯 1칸을 더 붙인다(칸 번호가 밀리지 않게 뒤에)."""
    if "etc" in b.slots:
        return False
    b.slots["etc"] = [None] * capacity(world, rid)["etc"]
    if start_port_bonus(world.regions[rid], mode):
        b.slots["coast"].append(None)
    for t in ("river", "coast"):
        for i, c in enumerate(b.slots.get(t, [])):
            if c and c["key"] in ("hydro", "nuclear"):
                b.slots[t][i] = None
                b.place(c["key"], c["level"])
    sp = int(dict.get(b, "specialty", 0) or 0)
    dict.__setitem__(b, "specialty", 0)
    if sp > 0:
        b.place("specialty", sp)
    b.resync()
    return True
