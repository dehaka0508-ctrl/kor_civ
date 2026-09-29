"""게임 상태 자료구조."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import config as C

NEUTRAL = -1

ALL_BUILDINGS = ["farm", "fishery", "factory", "bank", "power", "liquefy", "specialty", "extract",
                 "shelter", "aa", "academy", "airport", "port"]
BUILDING_NAMES = {**{k: v["name"] for k, v in C.PROD_BUILDINGS.items()},
                  **{k: v["name"] for k, v in C.DEF_BUILDINGS.items()},
                  **{k: v["name"] for k, v in C.SINGLE_BUILDINGS.items()}}


@dataclass
class Project:
    kind: str                 # build / unit / annex / landmark / capital
    key: str                  # 건물 키, 유닛 키, 편입 대상 구역 ID
    level: int = 0
    turns: int = 1
    progress: int = 0
    per_turn: float = 0.0
    paid: float = 0.0
    border: Optional[str] = None   # 방어선: 인접 구역 ID 또는 "coast"
    stalled: bool = False

    @property
    def remaining(self) -> int:
        return max(0, self.turns - self.progress)


@dataclass
class Region:
    id: str
    owner: int
    pop: float
    happy: float = 0.0
    b: dict = field(default_factory=dict)
    lines: dict = field(default_factory=dict)
    landmark: bool = False
    fuel: str = "auto"
    project: Optional[Project] = None
    occ: Optional[dict] = None          # {"by": fid, "progress": n, "need": n}
    supplied: set = field(default_factory=set)
    famine: float = 0.0
    h_delta: float = 0.0
    phi: float = 1.0
    output: float = 0.0
    food: float = 0.0
    bombed: bool = False
    rebellions: int = 0

    def level_sum(self) -> int:
        return sum(self.b.get(k, 0) for k in ("farm", "fishery", "factory", "bank", "power",
                                              "liquefy", "specialty", "extract"))


@dataclass
class Army:
    id: int
    owner: int
    loc: str
    units: dict = field(default_factory=dict)
    dmg: dict = field(default_factory=dict)
    order: Optional[dict] = None

    def count(self, kinds=None) -> int:
        if kinds is None:
            return sum(self.units.values())
        return sum(n for k, n in self.units.items() if C.UNITS[k]["kind"] in kinds)

    def empty(self) -> bool:
        return sum(self.units.values()) <= 0

    def kinds(self) -> set:
        return {C.UNITS[k]["kind"] for k, n in self.units.items() if n > 0}

    def domain(self) -> str:
        ks = self.kinds()
        if "naval" in ks:
            return "naval"
        if ks == {"air"}:
            return "air"
        return "land"

    def cargo_used(self) -> int:
        return sum(C.UNITS[k].get("cargo", 0) * n for k, n in self.units.items()
                   if C.UNITS[k]["kind"] == "land")

    def cargo_cap(self) -> int:
        return sum(C.UNITS[k].get("capacity", 0) * n for k, n in self.units.items())

    def air_used(self) -> int:
        return sum(n for k, n in self.units.items() if C.UNITS[k]["kind"] == "air")

    def air_cap(self) -> int:
        return sum(C.UNITS[k].get("air_capacity", 0) * n for k, n in self.units.items())

    def label(self) -> str:
        return " ".join(f"{C.UNITS[k]['name']}{n}" for k in C.UNIT_ORDER
                        for n in [self.units.get(k, 0)] if n > 0) or "(빈 부대)"


@dataclass
class Faction:
    id: int
    name: str
    color: str
    leader: str
    leader_name: str
    gov: Optional[str]
    is_ai: bool
    capital: str
    money: float = C.START_MONEY
    res: dict = field(default_factory=dict)
    specialty: dict = field(default_factory=dict)
    tax: float = C.TAX_DEFAULT
    tax_locked_until: int = 0
    alive: bool = True
    auto_food: bool = True
    liquefy: bool = True
    buy_count: dict = field(default_factory=dict)   # 이번 턴 구매 개수(가격 상승용)
    trade_buy: float = 0.0
    trade_sell: float = 0.0
    last: dict = field(default_factory=dict)        # 지난 턴 통계
    pop_mult: float = 1.0
    income_mult: float = 1.0
    aggression: float = 5.0
    econ_streak: int = 0
    explored: set = field(default_factory=set)
    last_seen: dict = field(default_factory=dict)
    ai: dict = field(default_factory=dict)
    rebel_of: Optional[int] = None
    eliminated_turn: Optional[int] = None


@dataclass
class Settings:
    n_enemies: int = 3
    difficulty: int = 2
    fog: int = 1
    victories: tuple = ("conquest", "economic", "peace", "landmark")
    player_leader: str = "sejong"
    player_leader_name: str = ""
    player_name: str = "대한"
    player_start: Optional[str] = None
    ai_leaders: Optional[list] = None
    ai_starts: Optional[list] = None
    seed: Optional[int] = None
    all_ai: bool = False          # 헤드리스 시뮬레이션: 플레이어도 AI가 조종
