"""게임 상태 자료구조."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import config as C

NEUTRAL = -1

ALL_BUILDINGS = ["farm", "fishery", "factory", "bank", "power", "specialty", "extract",
                 "shelter", "aa", "academy", "airport", "port"]
BUILDING_NAMES = {**{k: v["name"] for k, v in C.PROD_BUILDINGS.items()},
                  **{k: v["name"] for k, v in C.DEF_BUILDINGS.items()},
                  **{k: v["name"] for k, v in C.SINGLE_BUILDINGS.items()}}


@dataclass
class Project:
    kind: str                 # build / unit / annex / science / capital
    key: str                  # 건물 키, 유닛 키, 편입 대상 구역 ID
    level: int = 0
    turns: int = 1
    progress: int = 0
    per_turn: float = 0.0
    paid: float = 0.0
    border: Optional[str] = None   # 방어선: 인접 구역 ID 또는 "coast"
    stalled: bool = False
    name: Optional[str] = None
    priority: float = 0.0          # 자금 지출 우선순위(작을수록 먼저). 기본은 착수 순서
    funded: bool = False

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
    sci: set = field(default_factory=set)        # 과학승리 시설(lab / observatory / pad)
    econ: set = field(default_factory=set)       # 경제승리 시설(exchange / sez / ifc / currency)
    energy: dict = field(default_factory=dict)   # 수동 연료 배정 {"coal": n, "oil": n, "elec": n} (공장·발전소)
    project: Optional[Project] = None
    occs: dict = field(default_factory=dict)   # 무력 점령 진행 {fid: {"by", "progress", "need"}} (여러 세력 동시 가능)
    supplied: set = field(default_factory=set)
    spec_pin: set = field(default_factory=set)     # 수동 고정 공급 특산물
    spec_block: set = field(default_factory=set)   # 수동 제외 특산물
    focus: bool = False            # 생산 집중(건설·병력 생산을 안 할 때 인구 산출 +15%)
    pop_focus: bool = False        # 인구 성장 집중(건설·병력 생산을 안 할 때 성장률 +0.5%p)
    acquired_seq: int = 0          # 영토를 얻은 순서(수도 0) — '다음 지역' 순회용
    famine: float = 0.0
    h_delta: float = 0.0
    fuel_used: int = 0             # 이번 턴 공장에 들어간 연료 개수
    output: float = 0.0
    food: float = 0.0
    bombed: bool = False
    rebellions: int = 0
    resist: Optional[dict] = None   # 점령 저항 {"turn", "from", "resist", "recover"} (점령 후 36턴)
    mil_hist: int = 0               # 최근 10턴 군 생산 여부(비트, 최하위 = 이번 턴)
    conscript: float = 0.0          # 징집 피로(실질 행복도에서 빠지는 양)

    @property
    def occ(self) -> Optional[dict]:
        """가장 앞선 무력 점령(진행 비율이 가장 높은 것). 없으면 None."""
        if not self.occs:
            return None
        return max(self.occs.values(), key=lambda o: (o["progress"] / max(1, o["need"]), -o.get("seq", 0)))

    @occ.setter
    def occ(self, v):
        self.occs = {} if v is None else {v["by"]: v}

    def level_sum(self) -> int:
        return sum(self.b.get(k, 0) for k in ("farm", "fishery", "factory", "bank", "power",
                                              "specialty", "extract"))


@dataclass
class Army:
    id: int
    owner: int
    loc: str
    units: dict = field(default_factory=dict)
    dmg: dict = field(default_factory=dict)
    order: Optional[dict] = None
    goto: Optional[str] = None      # 여러 턴 자동 이동의 최종 목적지

    def count(self, kinds=None) -> int:
        if kinds is None:
            return sum(self.units.values())
        return sum(n for k, n in self.units.items() if C.UNITS[k]["kind"] in kinds)

    def empty(self) -> bool:
        return sum(self.units.values()) <= 0

    def hp_max(self, k) -> int:
        return C.UNITS[k]["hp"] * self.units.get(k, 0)

    def hp_left(self, k) -> float:
        """같은 유닛끼리 합산한 남은 체력."""
        return max(0.0, self.hp_max(k) - self.dmg.get(k, 0.0))

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
    auto_specialty: bool = True     # 행복도 낮은 지역부터 자동 배분
    auto_energy: bool = True        # 공장·발전소 연료 자동 배정
    buy_count: dict = field(default_factory=dict)   # 이번 턴 구매 개수(가격 상승용)
    trade_buy: float = 0.0
    trade_sell: float = 0.0
    spend: dict = field(default_factory=dict)       # 이번 턴 작업 지출 {종류: 금액}
    refund: float = 0.0                             # 이번 턴 환급
    war_weary: float = 0.0          # 전쟁 피로도 0~200 (실질 행복도 = 행복도 − 전쟁 피로도)
    war_weary_def: float = 0.0      # 그중 선포당한 전쟁에서 쌓인 몫(반란 판정에서는 빼지 않는다)
    last_declare: int = -999        # 마지막으로 선전포고한 턴(전쟁광 평판)
    last_aggr_end: int = -999       # 스스로 선포한 전쟁이 마지막으로 끝난 턴
    warmonger: int = 0              # 1년 안에 잇따라 선포한 횟수
    last: dict = field(default_factory=dict)        # 지난 턴 통계
    pop_mult: float = 1.0
    income_mult: float = 1.0
    aggression: float = 5.0
    econ_streak: int = 0
    science: list = field(default_factory=list)     # 완료한 과학 단계(C.SCIENCE_STEPS 순서)
    explored: set = field(default_factory=set)
    last_seen: dict = field(default_factory=dict)
    ai: dict = field(default_factory=dict)
    rebel_of: Optional[int] = None
    eliminated_turn: Optional[int] = None
    founded_turn: int = 1
    happy_floor_until: int = 0      # 신생 독립국: 이 턴까지 행복도 하한 0
    provisional_used: bool = False  # 김구 '임시정부'를 이미 썼다
    capital_fall_turn: int = -999   # 마지막으로 수도가 함락된 턴
    naval_off_until: int = 0        # 이순신 '백의종군': 이 턴까지 해군 버프 비활성
    met: set = field(default_factory=set)   # 조우한 세력(시야 안에 그 세력의 영토·군대가 들어온 적이 있음)
    flag: Optional[dict] = None     # 직접 만든 국기(없으면 세력 색으로 만든 기본 국기, flags.faction_flag)


@dataclass
class Settings:
    n_enemies: int = 3
    difficulty: int = 2
    fog: int = 1
    victories: tuple = ("conquest", "science", "economic", "diplomatic", "time")
    max_turns: int = C.TIME_VICTORY_TURNS   # 시간 종료 승리 턴
    player_leader: str = "sej"
    player_leader_name: str = ""
    player_name: str = "대한"
    player_start: Optional[str] = None
    player_flag: Optional[dict] = None   # 시작 화면에서 만든 국기
    ai_leaders: Optional[list] = None
    ai_starts: Optional[list] = None
    seed: Optional[int] = None
    all_ai: bool = False          # 헤드리스 시뮬레이션: 플레이어도 AI가 조종
