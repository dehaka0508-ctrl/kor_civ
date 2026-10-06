"""하천·산맥을 지역 경계를 따라 끊김 없이 잇는다 (개발용, shapely 필요).

각 하천·산맥은 실제 물길·능선을 따라 찍은 경유점(위도·경도)으로 정의한다.
지역 경계(이웃한 두 지역이 맞닿은 선)를 간선으로 하는 그래프에서, 경유점 선에 가까운 경계일수록
비용이 싸도록 최단 경로를 찾는다. 경로 위 간선이 곧 (지역A, 지역B) 지형 경계가 된다.
- 기존 terrain-borders.csv 의 같은 이름 행(다리·고개 근거가 있는 행)은 비용을 깎아 우선 지나가게 한다.
- 지류(소양강·북한강·남한강 등)와 갈래 산맥(소백·묘향 등)은 본류 경로 위 가장 가까운 점에서 끝나게 해 이어진다.
- 압록강·두만강은 나라 밖 경계(중국·러시아)라 짝 지역이 없다: 구역B 를 비운 '외곽' 행으로 저장한다
  (그리기·하천 어장용, 건너는 경계 아님). 물길은 Natural Earth 10m 하천 선을 쓴다.

  python tools/route_terrain.py --ne <ne_10m_rivers_lake_centerlines.geojson> [--preview out.png]
  python tools/build_map.py && python tools/build_outlines.py
"""
from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import os
import sys
from collections import defaultdict

from shapely.geometry import LineString, Point, box, shape
from shapely.ops import linemerge, unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
DATA = os.path.join(ROOT, "korciv", "data")
TPATH = os.path.join(DATA, "terrain-borders.csv")
KX = math.cos(math.radians(37.5))        # 경도 1도의 상대 길이

# ------------------------------------------------------------------ 경유점 (위도, 경도), 상류/시작 → 하구/끝
RIVERS = {
    "청천강": [(40.45, 126.62), (40.17, 126.27), (39.98, 126.14), (39.85, 125.98), (39.70, 125.88),
             (39.62, 125.68), (39.57, 125.48), (39.54, 125.38)],
    "대동강": [(39.95, 126.75), (39.75, 126.30), (39.55, 126.10), (39.43, 125.95), (39.30, 125.92), (39.15, 125.85),
             (39.03, 125.75), (38.90, 125.60), (38.73, 125.40), (38.70, 125.20)],
    "예성강": [(38.85, 126.60), (38.50, 126.53), (38.33, 126.40), (38.15, 126.47), (37.98, 126.43),
             (37.88, 126.42)],
    "임진강": [(38.85, 127.30), (38.62, 127.10), (38.40, 126.95), (38.22, 126.98), (38.10, 127.02),
             (38.03, 127.05), (37.97, 126.95), (37.90, 126.82), (37.82, 126.72), (37.77, 126.68)],
    "한강(본류)": [(37.53, 127.31), (37.57, 127.20), (37.54, 127.10), (37.52, 127.00), (37.53, 126.90),
              (37.57, 126.82), (37.63, 126.73), (37.75, 126.62), (37.78, 126.50)],
    "북한강": [(38.55, 127.95), (38.35, 127.75), (38.20, 127.70), (38.10, 127.70), (37.95, 127.72),
            (37.88, 127.70), (37.80, 127.55), (37.72, 127.43), (37.62, 127.35), (37.53, 127.31)],
    "소양강": [(38.05, 128.17), (38.05, 128.05), (37.98, 127.90), (37.93, 127.80), (37.89, 127.73)],
    "남한강": [(37.38, 128.66), (37.18, 128.47), (37.05, 128.42), (36.98, 128.35), (37.00, 128.15),
            (36.99, 127.93), (37.15, 127.78), (37.30, 127.63), (37.45, 127.50), (37.53, 127.31)],
    "금강": [(35.70, 127.55), (35.95, 127.65), (36.15, 127.70), (36.30, 127.62), (36.43, 127.48),
           (36.48, 127.30), (36.47, 127.12), (36.30, 126.92), (36.15, 126.92), (36.05, 126.75), (36.00, 126.60)],
    "만경강": [(35.93, 127.22), (35.94, 127.15), (35.91, 127.05), (35.89, 126.93), (35.90, 126.82), (35.90, 126.75)],
    "영산강": [(35.33, 127.00), (35.22, 126.92), (35.12, 126.80), (35.02, 126.70), (34.92, 126.62),
            (34.80, 126.48), (34.78, 126.40)],
    "섬진강": [(35.70, 127.35), (35.55, 127.22), (35.40, 127.15), (35.27, 127.28), (35.20, 127.45),
            (35.13, 127.62), (35.05, 127.75), (34.93, 127.77)],
    "낙동강": [(37.07, 129.00), (36.95, 128.95), (36.80, 128.88), (36.62, 128.80), (36.55, 128.55), (36.50, 128.30),
            (36.30, 128.30), (36.12, 128.38), (35.90, 128.42), (35.70, 128.40), (35.50, 128.45),
            (35.40, 128.62), (35.35, 128.80), (35.25, 128.95), (35.08, 128.95)],
}
# 지류: 본류 경로에 닿으면 끝난다
TRIBUTARY = {"북한강": "한강(본류)", "남한강": "한강(본류)", "소양강": "북한강"}
BORDER_RIVERS = {"압록강": "Yalu", "두만강": "Tumen"}     # 나라 밖 경계(외곽)
BORDER_ESTUARY_ONLY = {"압록강"}                            # 하구 섬 경계 등 기존 짝 행은 유지

RANGES = {
    "낭림산맥": [(41.30, 127.00), (40.90, 126.95), (40.50, 126.90), (40.10, 126.90), (39.70, 126.95),
              (39.35, 127.05)],
    "마천령산맥": [(41.98, 128.62), (41.92, 128.81), (41.57, 129.05), (41.19, 128.99), (40.90, 129.03), (40.65, 129.15)],
    "함경산맥": [(42.20, 129.30), (41.70, 129.10), (41.30, 128.65), (40.90, 128.20), (40.55, 127.80), (40.15, 127.45)],
    "묘향산맥": [(40.25, 126.85), (40.00, 126.45), (39.80, 126.15), (39.60, 125.85), (39.45, 125.55)],
    "멸악산맥": [(38.85, 126.60), (38.62, 126.10), (38.45, 125.65), (38.35, 125.35), (38.22, 125.05), (38.12, 124.75)],
    "태백산맥": [(39.05, 127.35), (38.65, 128.05), (38.12, 128.45), (37.80, 128.55), (37.45, 128.75),
              (37.10, 128.95), (36.70, 129.10), (36.20, 129.15), (35.80, 129.15), (35.50, 129.10),
              (35.30, 129.10)],
    "소백산맥": [(37.10, 128.90), (36.95, 128.45), (36.78, 128.07), (36.54, 127.87), (36.20, 127.98),
              (35.86, 127.75), (35.55, 127.65), (35.36, 127.72)],
    "차령산맥": [(37.55, 128.30), (37.30, 127.90), (37.00, 127.50), (36.75, 127.15), (36.50, 126.80),
              (36.35, 126.60)],
}
BRANCH = {"소백산맥": "태백산맥", "묘향산맥": "낭림산맥", "차령산맥": "태백산맥"}
BRANCH_AT_START = {"소백산맥", "묘향산맥", "차령산맥"}      # 시작점이 본맥에 붙는다
NE_GUIDE = {"낙동강": "Nakdong", "남한강": "Namhan", "한강(본류)": "Han"}   # 물길 선은 Natural Earth 선을 쓴다      # 시작점이 본맥에 붙는다

# 실제 물길·능선이 지역 경계를 이루는 것으로 확인한 짝: 경로가 꼭 지나가도록 비용을 깎는다
FORCE = {
    "소양강": [("강원 인제군", "강원 양구군"), ("강원 춘천시", "강원 양구군")],
    "북한강": [("강원 금강군", "강원 창도군"), ("강원 창도군", "강원 김화군"), ("강원 김화군", "강원 화천군"),
            ("강원 화천군", "강원 춘천시"), ("경기 가평군", "경기 남양주시"), ("경기 남양주시", "경기 양평군")],
    "섬진강": [("전남 광양시", "경남 하동군")],
    "만경강": [("전북 익산시", "전북 완주군"), ("전북 익산시", "전북 김제시"), ("전북 군산시", "전북 김제시")],
    "낙동강": [("경북 상주시", "경북 의성군"), ("경북 상주시", "경북 구미시"), ("경북 칠곡군", "경북 성주군")],
    "마천령산맥": [("량강 백암군", "함북 연사군"), ("량강 백암군", "함북 어랑군"), ("량강 백암군", "함북 길주군")],
    "낭림산맥": [("자강 화평군", "량강 김형직군"), ("자강 랑림군", "함남 장진군"), ("자강 룡림군", "함남 장진군"),
              ("평남 대흥군", "함남 장진군"), ("평남 맹산군", "함남 요덕군")],
}
FORCE_START = {"소양강", "북한강", "만경강", "낭림산맥"}     # 첫 확인 짝에서 바로 시작한다

RIVER_MULT, RANGE_MULT = 0.9, 0.9


def km(p, q):
    return math.hypot((p[0] - q[0]) * KX, p[1] - q[1]) * 111.0


def load():
    import build_map
    geom, adj_geom, by_name = build_map.load_geometry()
    with open(os.path.join(DATA, "map_geometry.json"), encoding="utf-8") as f:
        adjacency = json.load(f)["adjacency"]
    return geom, by_name, adjacency


def shared_lines(ga, gb, cross):
    for tol in ((0.02,) if cross else (0.0008, 0.004, 0.01)):
        shared = ga.boundary.intersection(gb.buffer(tol))
        if shared.length >= 0.003:
            break
    if shared.is_empty or shared.length < 0.003:
        return []
    merged = linemerge(shared) if shared.geom_type != "LineString" else shared
    out = []
    for ln in getattr(merged, "geoms", [merged]):
        if ln.geom_type == "LineString" and ln.length >= 0.002:
            out.append(ln)
    return out


class Graph:
    """지역 경계 그래프: 노드 = 경계 끝점(세 지역이 만나는 점 등), 간선 = 두 지역의 맞닿은 선."""

    def __init__(self, geom, by_name, adjacency):
        self.id2name = {r["ID"]: n for n, r in by_name.items()}
        src = {}
        for n, r in by_name.items():
            src[r["ID"]] = "M" if r["남북"] == "남북 병합" else ("S" if r["남북"] == "남" else "N")
        raw = []
        for a, b in adjacency:
            cross = {src[a], src[b]} == {"S", "N"} or "M" in (src[a], src[b])
            for ln in shared_lines(geom[self.id2name[a]], geom[self.id2name[b]], cross):
                raw.append((a, b, ln))
        # 끝점 모으기(가까운 점은 한 노드로)
        pts = []
        for _, _, ln in raw:
            pts += [ln.coords[0], ln.coords[-1]]
        self.nodes = []
        cell = defaultdict(list)
        R = 0.012

        def node_of(p):
            cx, cy = int(p[0] / R), int(p[1] / R)
            best = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for i in cell[(cx + dx, cy + dy)]:
                        q = self.nodes[i]
                        d = math.hypot(p[0] - q[0], p[1] - q[1])
                        if d < R and (best is None or d < best[0]):
                            best = (d, i)
            if best:
                return best[1]
            self.nodes.append(p)
            cell[(cx, cy)].append(len(self.nodes) - 1)
            return len(self.nodes) - 1
        self.edges = []          # (u, v, a, b, line)
        self.adj = defaultdict(list)
        for a, b, ln in raw:
            u, v = node_of(ln.coords[0]), node_of(ln.coords[-1])
            if u == v:
                continue
            e = len(self.edges)
            self.edges.append((u, v, a, b, ln))
            self.adj[u].append(e)
            self.adj[v].append(e)
        # 남북 자료가 만나는 휴전선 등에서 끝점이 조금 어긋나 그래프가 끊긴다: 가까운 노드끼리 가상 간선(짝 없음)
        linked = {frozenset(e[:2]) for e in self.edges}
        seam = set()
        for u, v, a, b, _ in self.edges:
            if src[a] != src[b] or "M" in (src[a], src[b]):
                seam |= {u, v}
        for i, p in enumerate(self.nodes):
            for j in range(i + 1, len(self.nodes)):
                q = self.nodes[j]
                lim = 0.06 if (i in seam and j in seam) else 0.035
                if abs(p[0] - q[0]) < lim and abs(p[1] - q[1]) < lim and frozenset((i, j)) not in linked \
                        and math.hypot(p[0] - q[0], p[1] - q[1]) < lim:
                    e = len(self.edges)
                    self.edges.append((i, j, None, None, LineString([p, q])))
                    self.adj[i].append(e)
                    self.adj[j].append(e)

        # 가장 큰 연결 성분(섬·하구 건너편의 떨어진 조각 제외)
        par = list(range(len(self.nodes)))

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for u, v, *_ in self.edges:
            par[find(u)] = find(v)
        roots = defaultdict(int)
        for i in range(len(self.nodes)):
            roots[find(i)] += 1
        big = max(roots, key=roots.get)
        self.main = [i for i in range(len(self.nodes)) if find(i) == big]

    def nearest_node(self, lonlat, allowed=None):
        cand = allowed if allowed is not None else self.main
        return min(cand, key=lambda i: km(self.nodes[i], lonlat))

    def route(self, wps, start, end, anchors=frozenset(), sigma=3.0, used=frozenset(), guide_line=None,
              force=frozenset()):
        """경유점 선(wps, (lon,lat))을 따라 start→end 최단 경로. 간선 번호 목록.
        used: 이미 다른 하천·산맥이 지나는 짝 — 겹치지 않도록 비용을 크게 올린다."""
        if guide_line is not None:
            guide = unary_union([LineString([(x * KX, y) for x, y in ln.coords])
                                 for ln in getattr(guide_line, "geoms", [guide_line])])
        else:
            guide = LineString([(x * KX, y) for x, y in wps])
        cost = {}
        for e, (u, v, a, b, ln) in enumerate(self.edges):
            L = ln.length * 111.0 * (KX + 1) / 2
            ds = [guide.distance(Point(x * KX, y)) * 111.0 for x, y in
                  (ln.interpolate(t, normalized=True).coords[0] for t in (0.1, 0.3, 0.5, 0.7, 0.9))]
            d = sum(ds) / len(ds)
            c = (L + 0.5) * (1 + (d / sigma) ** 2)
            if a is not None and frozenset((a, b)) in force:
                c = (L + 0.5) * 0.2          # 확인된 짝: 거리와 상관없이 지나간다
            elif a is None:
                c *= 1.5                     # 가상 간선은 꼭 필요할 때만
            elif frozenset((a, b)) in anchors:
                c *= 0.35
            if a is not None and frozenset((a, b)) in used:
                c *= 6
            cost[e] = c
        ends = end if isinstance(end, set) else {end}
        dist = {start: 0.0}
        prev = {}
        pq = [(0.0, start)]
        while pq:
            d, u = heapq.heappop(pq)
            if u in ends:
                path = []
                while u != start:
                    e = prev[u]
                    path.append(e)
                    uu, vv = self.edges[e][:2]
                    u = uu if vv == u else vv
                return path[::-1]
            if d > dist.get(u, 1e18):
                continue
            for e in self.adj[u]:
                uu, vv = self.edges[e][:2]
                w = vv if uu == u else uu
                nd = d + cost[e]
                if nd < dist.get(w, 1e18):
                    dist[w] = nd
                    prev[w] = e
                    heapq.heappush(pq, (nd, w))
        raise SystemExit("경로 없음")


def loop_erase(G, path, start, keep=()):
    """간선 걸음에서 되돌아간 고리를 지워 단순 경로로 만든다(구간을 이으며 생긴 왕복 가지 제거).
    keep(확인된 짝 간선)이 든 고리는 지우지 않는다."""
    nodes, edges = [start], []
    for e in path:
        u, v = G.edges[e][:2]
        nxt = v if u == nodes[-1] else u
        if nxt in nodes and not (set(edges[nodes.index(nxt):]) | {e}) & set(keep):
            i = nodes.index(nxt)
            nodes, edges = nodes[:i + 1], edges[:i]
        else:
            nodes.append(nxt)
            edges.append(e)
    return edges


def check_rivers(G, routes, geom, id2name):
    """하천 점검: 경로가 한 줄로 이어지는지, 하구가 바다에 닿는지(지류는 본류 경로에 닿는지)."""
    from shapely.geometry import Polygon
    with open(os.path.join(DATA, "map_geometry.json"), encoding="utf-8") as f:
        seas = json.load(f)["seas"]
    sea = unary_union([Polygon(p["ext"]).buffer(0) for polys in seas.values() for p in polys])
    bad = []
    for name in RIVERS:
        path = routes[name]
        # 이어짐: 연속한 간선이 노드를 공유
        nodes = []
        for e in path:
            u, v = G.edges[e][:2]
            if not nodes:
                nodes = [u, v] if path[1:] and v in G.edges[path[1]][:2] else [v, u]
                continue
            if nodes[-1] == u:
                nodes.append(v)
            elif nodes[-1] == v:
                nodes.append(u)
            else:
                bad.append(f"{name}: 끊김")
                break
        last = Point(G.nodes[nodes[-1]])
        if name in TRIBUTARY:
            main = {n for e in routes[TRIBUTARY[name]] for n in G.edges[e][:2]}
            ok = nodes[-1] in main
            where = f"본류({TRIBUTARY[name]}) 합류" if ok else "본류에 안 닿음"
        else:
            d = sea.distance(last) * 111
            ok = d < 3.0
            where = f"하구 해안까지 {d:.1f}km"
        if not ok:
            bad.append(f"{name}: {where}")
        print(f"  점검 {name}: 간선 {len(path)}개, {where}")
    if bad:
        raise SystemExit("하천 점검 실패: " + "; ".join(bad))


def read_rows():
    with open(TPATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def outer_rows(geom, by_name):
    """압록강·두만강: 국경 하천을 바깥 경계로 가진 북한 지역(구역B 빈 '외곽' 행)."""
    import build_map
    rows = []
    for ko in build_map.BORDER_RIVERS:
        for n in geom:
            if by_name[n]["남북"] == "남":
                continue
            if sum(ln.length for ln in build_map.outer_river_lines(geom, n, ko)) >= 0.03:
                rows.append({"구분": "도하", "지형": ko, "구역A": n, "구역A_ID": by_name[n]["ID"], "구역B": "",
                             "구역B_ID": "", "근거": "국경 하천(외곽)", "신뢰도": "높음",
                             "좌표검증": "Natural Earth 10m 하천 선", "공격배수": f"{RIVER_MULT:g}"})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ne", required=True, help="ne_10m_rivers_lake_centerlines.geojson")
    ap.add_argument("--preview")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    geom, by_name, adjacency = load()
    id2name = {r["ID"]: n for n, r in by_name.items()}
    G = Graph(geom, by_name, adjacency)
    print(f"경계 그래프: 노드 {len(G.nodes)} 간선 {len(G.edges)}")
    old = read_rows()
    by_feat = defaultdict(list)
    for r in old:
        by_feat[r["지형"]].append(r)
    adj_set = {frozenset(p) for p in adjacency}

    routes = {}
    used = set()
    with open(a.ne, encoding="utf-8") as f:
        ne = json.load(f)["features"]

    def do(name, wps_latlon, parent=None, at_start=False, kind="도하"):
        wps = [(lon, lat) for lat, lon in wps_latlon]
        anchors = {frozenset((r["구역A_ID"], r["구역B_ID"])) for r in by_feat.get(name, [])}
        force = {frozenset((by_name[x]["ID"], by_name[y]["ID"])) for x, y in FORCE.get(name, [])}
        # 확인된 짝의 경계 중점을 경유점 사이에 끼워 넣는다(안내선이 그 경계를 지나도록)
        if force:
            base = LineString(wps)
            mids = []
            for e, (u, v, a_, b_, ln) in enumerate(G.edges):
                if a_ is not None and frozenset((a_, b_)) in force:
                    m = ln.interpolate(0.5, normalized=True)
                    mids.append((base.project(m), (m.x, m.y)))
            pts = [(base.project(Point(p)), p) for p in wps] + mids
            wps = [p for _, p in sorted(pts)]
        if parent:
            pnodes = {n for e in routes[parent] for n in G.edges[e][:2]}
            joint = wps[0] if at_start else wps[-1]
            jn = G.nearest_node(joint, pnodes)
            other = G.nearest_node(wps[-1] if at_start else wps[0])
            start, end = (jn, other) if at_start else (other, jn)
        else:
            start, end = G.nearest_node(wps[0]), G.nearest_node(wps[-1])
        gl = None
        if name in NE_GUIDE:
            gl = unary_union([shape(f["geometry"]) for f in ne if f["properties"].get("name") == NE_GUIDE[name]])
            gl = gl.intersection(box(124.0, 33.0, 131.0, 43.2))     # 같은 이름의 중국 하천(漢江 등) 제외
        if gl is not None and force:
            gl = unary_union([gl, LineString(wps)])
        # 확인된 짝은 적힌 순서(흐름 순서)대로 반드시 지나간다: 구간별로 나눠 잇는다
        fedges = []
        for x, y in FORCE.get(name, []):
            k = frozenset((by_name[x]["ID"], by_name[y]["ID"]))
            fedges += [e for e, ed in enumerate(G.edges) if ed[2] is not None and frozenset(ed[2:4]) == k][:1]
        path, cur = [], start
        end_pt = G.nodes[min(end) if isinstance(end, set) else end]
        for i, fe in enumerate(fedges):
            u, v = G.edges[fe][:2]
            if i == 0 and name in FORCE_START and not (parent and at_start):
                # 첫 짝: 다음 목표에 가까운 쪽 끝으로 빠져나가고, 그 앞은 잇지 않는다
                nxt = G.edges[fedges[1]][4].interpolate(0.5, normalized=True).coords[0] if len(fedges) > 1 else end_pt
                near_, far_ = (u, v) if km(G.nodes[v], nxt) <= km(G.nodes[u], nxt) else (v, u)
                cur = near_
                start = near_
            else:
                near_, far_ = (u, v) if km(G.nodes[u], G.nodes[cur]) <= km(G.nodes[v], G.nodes[cur]) else (v, u)
            seg = G.route(wps, cur, near_, anchors, used=used - force, guide_line=gl, force=force) if near_ != cur else []
            if fe in seg:
                # 가는 길에 이미 이 짝을 지났다: 거기서 끊고 그 끝에서 이어 간다
                k = seg.index(fe)
                walk = cur
                for e2 in seg[:k + 1]:
                    a2, b2 = G.edges[e2][:2]
                    walk = b2 if a2 == walk else a2
                path += seg[:k + 1]
                cur = walk
                continue
            path += seg
            path.append(fe)
            cur = far_
        ends = end if isinstance(end, set) else {end}
        if cur not in ends:
            path += G.route(wps, cur, end, anchors, used=used - force, guide_line=gl, force=force)
        routes[name] = loop_erase(G, path, start, keep=fedges)
        used.update(frozenset(G.edges[e][2:4]) for e in routes[name] if G.edges[e][2])

    # 하천 우선: 하천은 수원에서 바다(또는 본류)까지 반드시 이어져야 하므로 먼저 경계를 차지하고(본류 → 지류),
    # 산맥은 그다음에 놓여 하천이 쓴 경계를 피한다(산맥은 끊기거나 낮은 곳이 있어도 된다).
    for name in ("한강(본류)", "청천강", "대동강", "예성강", "임진강", "금강", "만경강", "영산강", "섬진강", "낙동강",
                 "북한강", "남한강", "소양강"):
        do(name, RIVERS[name], TRIBUTARY.get(name))
    for name in ("태백산맥", "낭림산맥", "마천령산맥", "소백산맥", "차령산맥", "묘향산맥", "멸악산맥", "함경산맥"):
        do(name, RANGES[name], BRANCH.get(name), at_start=name in BRANCH_AT_START)
    check_rivers(G, routes, geom, id2name)

    out = []
    seen = set()
    for name, path in routes.items():
        kind = "산악 돌파" if name.endswith("산맥") else "도하"
        oldrows = {frozenset((r["구역A_ID"], r["구역B_ID"])): r for r in by_feat.get(name, [])}
        for e in path:
            a_, b_ = G.edges[e][2:4]
            if a_ is None:
                continue
            key = frozenset((a_, b_))
            if key in seen:
                continue
            seen.add(key)
            r = oldrows.get(key)
            if r:
                out.append(r)
            else:
                out.append({"구분": kind, "지형": name, "구역A": id2name[a_], "구역A_ID": a_, "구역B": id2name[b_],
                            "구역B_ID": b_, "근거": "경로 연결(경유점 기반 자동 배치)", "신뢰도": "보통",
                            "좌표검증": "지역 경계 그래프 최단 경로",
                            "공격배수": f"{RIVER_MULT if kind == '도하' else RANGE_MULT:g}"})
        # 맞닿지 않은 하구 연결(기존 근거 행)은 유지
        for key, r in oldrows.items():
            if key not in adj_set and key not in seen:
                seen.add(key)
                out.append(r)
    for name in BORDER_ESTUARY_ONLY:
        for r in by_feat.get(name, []):
            key = frozenset((r["구역A_ID"], r["구역B_ID"]))
            if key not in seen:
                seen.add(key)
                out.append(r)
    out += outer_rows(geom, by_name)
    print(f"행 {len(old)} → {len(out)}")
    if a.list:
        for name, path in routes.items():
            seq = []
            for e in path:
                a_, b_ = G.edges[e][2:4]
                seq.append("·" if a_ is None else f"{id2name[a_].split()[-1]}|{id2name[b_].split()[-1]}")
            print(f"[{name}] " + " → ".join(seq))
    if a.preview:
        base, ext = os.path.splitext(a.preview)
        preview(a.preview, geom, by_name, G, routes, RIVERS, RANGES, out, ne_path=a.ne)
        for tag, bb in (("nw", (124.2, 38.6, 127.6, 41.2)), ("ne", (126.6, 39.6, 130.8, 43.1)),
                        ("mid", (125.6, 36.9, 129.2, 39.2)), ("se", (127.4, 34.9, 129.6, 37.3)),
                        ("sw", (125.9, 34.5, 128.0, 36.8))):
            preview(f"{base}_{tag}{ext}", geom, by_name, G, routes, RIVERS, RANGES, out, bbox=bb, S=700, ne_path=a.ne)
    # 짝 없는 연결(휴전선 자료 어긋남 등 가상 간선)도 선으로 그려 하천·산맥이 끊겨 보이지 않게 한다
    links = []
    for name, path in routes.items():
        segs = [[[round(x, 4), round(y, 4)] for x, y in G.edges[e][4].coords] for e in path if G.edges[e][2] is None]
        if segs:
            links.append({"name": name, "kind": "산악 돌파" if name.endswith("산맥") else "도하", "lines": segs})
    if not a.dry:
        with open(os.path.join(DATA, "terrain-links.json"), "w", encoding="utf-8") as f:
            json.dump(links, f, ensure_ascii=False, indent=1)
        with open(TPATH, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(old[0].keys()))
            w.writeheader()
            w.writerows(out)


def preview(out_path, geom, by_name, G, routes, rivers, ranges, rows, bbox=(124.2, 33.0, 130.8, 43.1), S=260,
            ne_path=None):
    """확인용 그림: 지역(이름), 경유점(분홍), 경로(하천 파랑·산맥 초록), 가상 간선(자홍), NE 하천(하늘)."""
    from PIL import Image, ImageDraw, ImageFont
    x0, y0, x1, y1 = bbox
    W, H = int((x1 - x0) * KX * S), int((y1 - y0) * S)

    def P(p):
        return ((p[0] - x0) * KX * S, (y1 - p[1]) * S)
    im = Image.new("RGB", (W, H), (235, 240, 245))
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(os.path.join(ROOT, "korciv", "assets", "fonts", "Pretendard-Regular.ttf"), max(9, S // 22))
    for n, g in geom.items():
        for poly in getattr(g, "geoms", [g]):
            d.polygon([P(p) for p in poly.exterior.coords], fill=(250, 250, 245), outline=(170, 170, 170))
    if ne_path:
        with open(ne_path, encoding="utf-8") as f:
            for ft in json.load(f)["features"]:
                g = shape(ft["geometry"])
                for ln in getattr(g, "geoms", [g]):
                    d.line([P(p) for p in ln.coords], fill=(120, 200, 255), width=3)
    for name, wps in list(rivers.items()) + list(ranges.items()):
        d.line([P((lon, lat)) for lat, lon in wps], fill=(255, 140, 140), width=2)
    for name, path in routes.items():
        col = (20, 90, 220) if not name.endswith("산맥") else (90, 160, 30)
        for e in path:
            d.line([P(p) for p in G.edges[e][4].coords], fill=col if G.edges[e][2] else (255, 0, 255), width=4)
    for n, g in geom.items():
        c = g.representative_point()
        if x0 < c.x < x1 and y0 < c.y < y1:
            d.text(P((c.x, c.y)), n.split()[-1], fill=(90, 90, 90), font=font, anchor="mm")
    im.save(out_path)


if __name__ == "__main__":
    main()
