"""구역 데이터·지도·인접 그래프 로더 (기획서 2절, 12절)."""
from __future__ import annotations

import csv
import json
import os
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

SEA_IDS = ["SEA1", "SEA2", "SEA3", "SEA4", "SEA5", "SEA6"]
SEA_NAMES = {"SEA1": "서북해", "SEA2": "서남해", "SEA3": "남서해",
             "SEA4": "남동해", "SEA5": "동남해", "SEA6": "동북해"}
SEA_DESC = {
    "SEA1": "NLL 북쪽 서해", "SEA2": "NLL 남쪽 서해 (인천~전남 신안)", "SEA3": "진도~광양",
    "SEA4": "하동~부산", "SEA5": "강원 고성 남쪽 동해", "SEA6": "강원 고성 북쪽 동해",
}
SEA_BY_NAME = {v: k for k, v in SEA_NAMES.items()}

# 해역 표시용 다각형 (lon, lat). 육지가 위에 그려지므로 해안선을 정확히 따를 필요는 없다.
SEA_POLYS = {
    "SEA1": [(123.0, 39.82), (124.33, 39.82), (124.6, 40.05), (125.3, 40.0), (125.9, 39.3),
             (126.9, 38.0), (126.9, 37.62), (123.0, 37.62)],
    "SEA2": [(123.0, 37.62), (126.9, 37.62), (127.0, 37.3), (127.0, 35.2), (126.55, 34.75),
             (126.3, 34.45), (125.0, 33.95), (123.0, 33.95)],
    "SEA3": [(123.0, 33.95), (125.0, 33.95), (126.3, 34.45), (126.55, 34.75), (127.0, 35.2),
             (127.78, 35.15), (127.82, 34.65), (126.55, 33.47), (126.55, 32.6), (123.0, 32.6)],
    "SEA4": [(126.55, 32.6), (126.55, 33.47), (127.82, 34.65), (127.78, 35.15), (129.2, 35.45),
             (129.32, 35.3), (130.3, 34.3), (130.3, 32.6)],
    "SEA5": [(130.3, 32.6), (130.3, 34.3), (129.32, 35.3), (129.2, 35.45), (128.7, 37.0),
             (128.3, 38.62), (128.9, 38.62), (132.2, 37.2), (132.2, 32.6)],
    "SEA6": [(128.3, 38.62), (127.2, 39.4), (128.5, 40.6), (130.0, 41.8), (130.5, 42.3),
             (130.7, 42.29), (131.3, 42.38), (132.2, 42.65), (132.2, 37.2), (128.9, 38.62)],
}
SEA_LABELS = {"SEA1": (124.35, 38.75), "SEA2": (125.4, 36.4), "SEA3": (125.8, 33.7),
              "SEA4": (128.6, 34.25), "SEA5": (130.2, 36.6), "SEA6": (130.2, 40.0)}

PROVINCE_ORDER = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
                  "충북", "충남", "전북", "전남", "경북", "경남", "제주", "평양", "남포", "라선",
                  "평북", "평남", "황북", "황남", "함남", "함북", "자강", "양강"]
DO8 = ["경기", "충청", "전라", "경상", "강원", "황해", "평안", "함경"]


@dataclass(frozen=True)
class RegionInfo:
    id: str
    name: str            # 표기명
    short: str           # 광역 약칭을 뺀 이름
    province: str
    ns: str              # 남 / 북 / 남북 병합
    orig: str
    rtype: str
    do8: str
    pop0: float
    coastal: bool
    seas: tuple
    island: str          # "" / 연륙 섬 / 무연륙 섬
    start_port: bool
    farm: int
    fishery: int
    factory: int
    bank: int
    oil: int
    coal: int
    power_self: int
    power_source: str
    power_site: bool     # 기존 화력발전소 소재지(발전소 건설비 50%)
    specialty: str
    note: str
    output0: float
    food0: float

    @property
    def is_oil(self):
        return self.oil > 0

    @property
    def is_coal(self):
        return self.coal > 0

    @property
    def can_fish(self):
        # 어장 조건 '바다·하천 인접': 해안 구역 또는 어장을 이미 가진 구역
        return self.coastal or self.fishery > 0


@dataclass
class SeaInfo:
    id: str
    name: str
    desc: str
    adj: list
    coast: list = field(default_factory=list)


class World:
    """정적인 지도 데이터. 게임 상태와 분리되어 있어 세이브에 넣지 않는다."""

    def __init__(self, data_dir: str = DATA_DIR):
        self.regions: dict[str, RegionInfo] = {}
        self.order: list[str] = []
        with open(os.path.join(data_dir, "regions.csv"), encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                info = self._parse(r)
                self.regions[info.id] = info
                self.order.append(info.id)
        self.name_to_id = {r.name: r.id for r in self.regions.values()}

        with open(os.path.join(data_dir, "map_geometry.json"), encoding="utf-8") as f:
            geo = json.load(f)
        self.geometry = geo["regions"]
        self.province_outlines = geo.get("provinces", {})
        self.do8_outlines = geo.get("do8", {})

        self.land_adj: dict[str, set] = {rid: set() for rid in self.order}
        for a, b in geo["adjacency"]:
            if a in self.land_adj and b in self.land_adj:
                self.land_adj[a].add(b)
                self.land_adj[b].add(a)
        self.bridges: dict[frozenset, str] = {}
        with open(os.path.join(data_dir, "adjacency-overrides.csv"), encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                a, b = self.name_to_id[r["구역A"]], self.name_to_id[r["구역B"]]
                self.land_adj[a].add(b)
                self.land_adj[b].add(a)
                self.bridges[frozenset((a, b))] = r["연결수단"]
        # 지형 경계(도하·산악 돌파). 맞닿지 않은 하구 등도 도하 경로로 인접 처리한다.
        self.terrain: dict[frozenset, dict] = {}
        self.terrain_lines = geo.get("terrain", [])
        tpath = os.path.join(data_dir, "terrain-borders.csv")
        if os.path.exists(tpath):
            with open(tpath, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    a, b = r["구역A_ID"], r["구역B_ID"]
                    kind = "도하" if r["구분"] == "도하" else "돌파"
                    if b not in self.land_adj[a]:
                        # 경계가 실제로 맞닿지 않은 쌍: 강 하구·수로(도하)만 건너는 경로로 인정하고,
                        # 산악 돌파는 인접이 아니므로 무시한다(예: 북청군–김형권군 후치령)
                        if kind != "도하":
                            continue
                        self.land_adj[a].add(b)
                        self.land_adj[b].add(a)
                    self.terrain[frozenset((a, b))] = {
                        "kind": kind, "label": r["구분"],
                        "name": r["지형"], "note": r["근거"], "mult": float(r["공격배수"])}
        self.terrain_lines = [t for t in self.terrain_lines if frozenset((t["a"], t["b"])) in self.terrain]
        # 무연륙 섬은 육상 인접이 없다
        for rid, info in self.regions.items():
            if info.island == "무연륙 섬":
                for n in self.land_adj[rid]:
                    self.land_adj[n].discard(rid)
                self.land_adj[rid] = set()

        self.seas: dict[str, SeaInfo] = {}
        for i, sid in enumerate(SEA_IDS):
            adj = []
            if i > 0:
                adj.append(SEA_IDS[i - 1])
            if i < len(SEA_IDS) - 1:
                adj.append(SEA_IDS[i + 1])
            self.seas[sid] = SeaInfo(sid, SEA_NAMES[sid], SEA_DESC[sid], adj)
        for rid in self.order:
            for sid in self.regions[rid].seas:
                self.seas[sid].coast.append(rid)

    @staticmethod
    def _parse(r) -> RegionInfo:
        name = r["표기명"]
        short = name.split(" ", 1)[1] if " " in name else name
        seas = tuple(SEA_BY_NAME[s.strip()] for s in r["인접해역"].split(",") if s.strip())
        src = r["발전원"] or ""
        return RegionInfo(
            id=r["ID"], name=name, short=short, province=r["광역"], ns=r["남북"], orig=r["원명칭"],
            rtype=r["유형"], do8=r["조선8도"], pop0=float(r["인구"]), coastal=r["해안"] == "Y",
            seas=seas, island=r["섬"] or "", start_port=r["시작항구"] == "Y",
            farm=int(r["농장"]), fishery=int(r["어장"]), factory=int(r["공장"]), bank=int(r["은행"]),
            oil=int(r["정유"]), coal=int(r["탄광"]), power_self=int(r["자체발전"]),
            power_source=src, power_site="화력" in src, specialty=r["특산물"] or "",
            note=r["비고"] or "", output0=float(r["초기산출"] or 0), food0=float(r["식량생산"] or 0),
        )

    # ------------------------------------------------------------ 그래프
    def is_sea(self, node: str) -> bool:
        return node in self.seas

    def node_name(self, node: str) -> str:
        if node in self.seas:
            return self.seas[node].name
        return self.regions[node].name

    def node_neighbors(self, node: str):
        """육상 인접 + 해안-해역 + 해역-해역을 합친 그래프(항공 반경 계산용)."""
        if node in self.seas:
            s = self.seas[node]
            return list(s.adj) + list(s.coast)
        return list(self.land_adj[node]) + list(self.regions[node].seas)

    def distances_from(self, start: str, max_d: int) -> dict:
        return _bfs(self, start, max_d)

    def is_bridge(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self.bridges

    def terrain_between(self, a: str, b: str):
        return self.terrain.get(frozenset((a, b)))


def _bfs(world: World, start: str, max_d: int) -> dict:
    dist = {start: 0}
    q = deque([start])
    while q:
        u = q.popleft()
        if dist[u] >= max_d:
            continue
        for v in world.node_neighbors(u):
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


@lru_cache(maxsize=1)
def load_world() -> World:
    return World()
