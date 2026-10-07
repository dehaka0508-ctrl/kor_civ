"""구역 데이터·지도·인접 그래프 로더 (기획서 2절, 12절)."""
from __future__ import annotations

import csv
import json
import os
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

SEA_IDS = ["SEA1", "SEA2", "SEA3", "SEA4", "SEA5", "SEA6", "SEA7", "SEA8"]
SEA_NAMES = {"SEA1": "서북해", "SEA2": "서남해", "SEA3": "남서해",
             "SEA4": "남동해", "SEA5": "동남해", "SEA6": "동북해",
             "SEA7": "독도 해역", "SEA8": "제주도 연안"}
SEA_DESC = {
    "SEA1": "NLL 북쪽 서해", "SEA2": "NLL 남쪽 서해 (인천~전남 신안)", "SEA3": "진도~광양",
    "SEA4": "하동~부산", "SEA5": "강원 고성 남쪽 동해", "SEA6": "강원 고성 북쪽 동해",
    "SEA7": "울릉도·독도 주변 (상륙함이 있어야 편입)", "SEA8": "제주도 주변 (상륙함이 있어야 편입)",
}
SEA_ADJ = {"SEA1": ["SEA2"], "SEA2": ["SEA1", "SEA3"], "SEA3": ["SEA2", "SEA4", "SEA8"],
           "SEA4": ["SEA3", "SEA5", "SEA8"], "SEA5": ["SEA4", "SEA6", "SEA7"], "SEA6": ["SEA5", "SEA7"],
           "SEA7": ["SEA5", "SEA6"], "SEA8": ["SEA3", "SEA4"]}
# 섬 전용 해역: 이 해역에만 닿은 섬은 해당 해역에 상륙함이 있어야 편입할 수 있다
ISLAND_SEAS = {"SEA7", "SEA8"}
SEA_BY_NAME = {v: k for k, v in SEA_NAMES.items()}

# 해역 원형 다각형 (lon, lat). tools/build_seas.py가 육지를 잘라내 해안선에 맞춘 모양을
# map_geometry.json의 "seas"에 저장하며, 게임은 그쪽을 쓴다(없으면 이 원형으로 대체).
SEA_POLYS = {
    "SEA1": [(123.0, 39.82), (124.33, 39.82), (124.6, 40.05), (125.3, 40.0), (125.9, 39.3),
             (126.9, 38.0), (126.9, 37.62), (123.0, 37.62)],
    "SEA2": [(123.0, 37.62), (126.9, 37.62), (127.0, 37.3), (127.0, 35.2), (126.55, 34.75),
             (126.3, 34.45), (125.0, 33.95), (123.0, 33.95)],
    "SEA3": [(123.0, 33.95), (125.0, 33.95), (126.3, 34.45), (126.55, 34.75), (127.0, 35.2),
             (127.78, 35.15), (127.82, 34.65), (126.55, 33.47), (126.55, 31.0), (123.0, 31.0)],
    "SEA4": [(126.55, 31.0), (126.55, 33.47), (127.82, 34.65), (127.78, 35.15), (129.2, 35.45),
             (129.32, 35.3), (130.3, 34.3), (130.3, 31.0)],
    "SEA5": [(130.3, 31.0), (130.3, 34.3), (129.32, 35.3), (129.2, 35.45), (128.7, 37.0),
             (128.3, 38.62), (128.9, 38.62), (132.2, 37.2), (132.2, 31.0)],
    "SEA6": [(128.3, 38.62), (127.2, 39.4), (128.5, 40.6), (130.0, 41.8), (130.5, 42.3),
             (130.7, 42.29), (131.3, 42.38), (132.2, 42.65), (132.2, 37.2), (128.9, 38.62)],
    "SEA7": [(130.45, 37.5), (130.6, 37.8), (131.0, 37.92), (131.6, 37.78), (132.15, 37.42),
             (132.1, 37.05), (131.7, 36.95), (131.0, 37.08), (130.55, 37.25)],
    "SEA8": [(125.8, 33.25), (125.95, 32.95), (126.55, 32.85), (127.2, 33.0), (127.35, 33.4),
             (127.0, 33.75), (126.62, 33.82), (126.55, 34.08), (126.2, 34.08), (126.05, 33.8),
             (125.85, 33.6)],
}
SEA_LABELS = {"SEA1": (124.35, 38.75), "SEA2": (125.4, 36.4), "SEA3": (125.8, 33.7),
              "SEA4": (128.6, 34.25), "SEA5": (130.2, 36.6), "SEA6": (130.2, 40.0),
              "SEA7": (131.55, 37.2), "SEA8": (126.55, 33.02)}

PROVINCE_ORDER = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
                  "충북", "충남", "전북", "전남", "경북", "경남", "제주", "평양", "남포", "라선",
                  "개성", "평북", "평남", "황북", "황남", "함남", "함북", "자강", "량강"]
DO8 = ["경기", "충청", "전라", "경상", "강원", "황해", "평안", "함경"]


def display_short(s: str) -> str:
    """지역 이름에서 끝의 시·군·구·구역을 뗀다(영등포구 → 영등포). 한 글자만 남으면 그대로(중구, 남구, 중구역)."""
    for suf in ("구역", "시", "군", "구"):
        if s.endswith(suf) and len(s) - len(suf) >= 2:
            return s[: -len(suf)]
    return s


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
    specialty: str       # 표시용(여러 개면 ", "로 연결)
    specialties: tuple
    note: str
    output0: float
    food0: float
    scenic: str = ""     # 자연경관(지역과 같은 나라의 인접 지역 행복도 +5)
    full: str = ""       # 원래 표기명(시·군·구 포함). 자료 파일의 지명 대조용
    coal_field: str = ""  # 탄전 구분 ①/② (탄광 열은 시작 탄광 단계)

    @property
    def is_oil(self):
        return self.oil > 0

    @property
    def is_coal(self):
        return bool(self.coal_field)      # 탄전(① 탄광 가동 / ② 석탄층): 탄광 건설·증설 가능

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
        self.name_to_id = {r.full: r.id for r in self.regions.values()}
        self.name_to_id.update({r.name: r.id for r in self.regions.values()})

        with open(os.path.join(data_dir, "map_geometry.json"), encoding="utf-8") as f:
            geo = json.load(f)
        self.geometry = geo["regions"]
        self.province_outlines = geo.get("provinces", {})
        self.do8_outlines = geo.get("do8", {})
        self.outlines_open = bool(geo.get("outline_open", False))   # 열린 선(새 형식)인가

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
        self.outer_rivers: set = set()         # 국경 하천을 바깥 경계로 가진 지역
        self.terrain_lines = geo.get("terrain", [])
        tpath = os.path.join(data_dir, "terrain-borders.csv")
        if os.path.exists(tpath):
            with open(tpath, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    a, b = r["구역A_ID"], r["구역B_ID"]
                    kind = "도하" if r["구분"] == "도하" else "돌파"
                    if not b:
                        # 국경 하천(압록강·두만강) 외곽 행: 건너는 경계는 아니고 그리기·하천 어장용
                        if kind == "도하":
                            self.outer_rivers.add(a)
                        continue
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
        self.terrain_lines = [t for t in self.terrain_lines if frozenset((t["a"], t["b"])) in self.terrain
                              or (not t["b"] and t["a"] in self.outer_rivers)]
        # 짝 없이 이어 주는 선(남북 자료가 어긋난 휴전선 부근 등): 그리기 전용
        lpath = os.path.join(data_dir, "terrain-links.json")
        if os.path.exists(lpath):
            with open(lpath, encoding="utf-8") as f:
                for ln in json.load(f):
                    self.terrain_lines.append({"a": "", "b": "", "kind": ln["kind"], "name": ln["name"],
                                               "connector": False, "lines": ln["lines"]})
        # 도하 경계·국경 하천을 가진 지역(하천 어장 가능)
        self.river_regions = {rid for fp, t in self.terrain.items() if t["kind"] == "도하" for rid in fp}
        self.river_regions |= self.outer_rivers
        # 산악 돌파 경계를 가진 지역(산맥과 맞닿은 지역: 천체관측소)
        self.mountain_regions = {rid for fp, t in self.terrain.items() if t["kind"] == "돌파" for rid in fp}
        # 무연륙 섬은 육상 인접이 없다
        for rid, info in self.regions.items():
            if info.island == "무연륙 섬":
                for n in self.land_adj[rid]:
                    self.land_adj[n].discard(rid)
                self.land_adj[rid] = set()

        self.seas: dict[str, SeaInfo] = {}
        for sid in SEA_IDS:
            self.seas[sid] = SeaInfo(sid, SEA_NAMES[sid], SEA_DESC[sid], list(SEA_ADJ[sid]))
        # 해안선에 맞춰 자른 해역 모양: sid -> [{"ext": ring, "holes": [ring...]}]
        self.sea_shapes = geo.get("seas") or {sid: [{"ext": p, "holes": []}] for sid, p in SEA_POLYS.items()}
        for rid in self.order:
            for sid in self.regions[rid].seas:
                self.seas[sid].coast.append(rid)
        # 자연경관: 이 지역 행복도에 영향을 주는 경관 지역(자기 자신 + 육상 인접)
        self.scenic_near = {rid: tuple(n for n in [rid] + sorted(self.land_adj[rid]) if self.regions[n].scenic)
                            for rid in self.order}

    @staticmethod
    def _parse(r) -> RegionInfo:
        full = r["표기명"]
        fshort = full.split(" ", 1)[1] if " " in full else full
        short = display_short(fshort)
        name = full[: len(full) - len(fshort)] + short
        seas = tuple(SEA_BY_NAME[s.strip()] for s in r["인접해역"].split(",") if s.strip())
        src = r["발전원"] or ""
        if "화력" in src and "소재" in src:      # '강릉안인화력 소재(…)' → '화력(강릉안인)'
            src = f"화력({src.split('화력')[0]})"
        specs = tuple(x.strip() for x in (r["특산물"] or "").split(",") if x.strip())
        return RegionInfo(
            id=r["ID"], name=name, short=short, province=r["광역"], ns=r["남북"], orig=r["원명칭"],
            rtype=r["유형"], do8=r["조선8도"], pop0=float(r["인구"]), coastal=r["해안"] == "Y",
            seas=seas, island=r["섬"] or "", start_port=r["시작항구"] == "Y",
            farm=int(r["농장"]), fishery=int(r["어장"]), factory=int(r["공장"]), bank=int(r["은행"]),
            oil=int(r["정유"]), coal=int(r["탄광"]), power_self=int(r["자체발전"]),
            power_source=src, power_site="화력" in src, specialty=", ".join(specs), specialties=specs,
            note=r["비고"] or "", output0=float(r["초기산출"] or 0), food0=float(r["식량생산"] or 0),
            scenic=(r.get("자연경관") or "").strip(), coal_field=(r.get("탄전") or "").strip(), full=full,
        )

    # ------------------------------------------------------------ 그래프
    def is_sea(self, node: str) -> bool:
        return node in self.seas

    def island_seas_of(self, rid: str) -> tuple:
        """섬 전용 해역에만 닿은 섬이면 그 해역들, 아니면 ()."""
        seas = self.regions[rid].seas
        if seas and all(s in ISLAND_SEAS for s in seas):
            return seas
        return ()

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
