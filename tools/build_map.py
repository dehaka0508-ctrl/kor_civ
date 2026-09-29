"""지도 경계·인접 그래프 생성 스크립트.

게임 실행에는 필요 없고, korciv/data/map_geometry.json 을 다시 만들 때만 쓴다.

필요 패키지: shapely, numpy (pip install shapely)

원자료
- 남한: vuski/admdongkor 행정동 경계 ver20260701 (CC BY 4.0, 원자료 통계청 SGIS)
  2026-07 인천 개편(제물포·영종·서해·검단구)과 전남광주통합특별시가 반영된 판이다.
- 북한: geoBoundaries PRK ADM2 (gbOpen, CC BY 4.0)
  평양 중심 17개 구역+승호구역, 라선 2개 구역은 원자료에 경계가 없어서
  대표 좌표 기반 보로노이 분할로 근사한다(아래 PYONGYANG_SEEDS, RASON_SEEDS).

사용법
    python tools/build_map.py            # 캐시에 없으면 내려받는다
    python tools/build_map.py --report   # 인접 목록 요약 출력
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import urllib.request
from collections import defaultdict

from shapely.geometry import MultiPolygon, Point, Polygon, shape, mapping
from shapely.ops import unary_union, voronoi_diagram

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "korciv", "data")
CACHE = os.path.join(ROOT, "tools", "_cache")

SK_URL = ("https://raw.githubusercontent.com/vuski/admdongkor/master/"
          "ver20260701/HangJeongDong_ver20260701.geojson")
NK_URL = ("https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/"
          "releaseData/gbOpen/PRK/ADM2/geoBoundaries-PRK-ADM2_simplified.geojson")

SIDO_ABBR = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "대전광역시": "대전", "울산광역시": "울산", "경기도": "경기", "강원특별자치도": "강원",
    "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "경상북도": "경북",
    "경상남도": "경남", "제주특별자치도": "제주",
}
GWANGJU_GU = {"동구", "서구", "남구", "북구", "광산구"}

# geoBoundaries PRK ADM2 shapeName -> 게임 표기명
NK_NAMES = {
    # 강원(북)
    "Wonsan City": "강원 원산시", "Munchon City": "강원 문천시", "Kosan": "강원 고산군",
    "Anbyon": "강원 안변군", "Phyonggang": "강원 평강군", "Thongchon": "강원 통천군",
    "Chonnae": "강원 천내군", "Sepho": "강원 세포군", "Ichon": "강원 이천군",
    "Kimhwa": "강원 김화군", "Kumgang": "강원 금강군", "Changdo": "강원 창도군",
    "Phangyo": "강원 판교군", "Hoeyang": "강원 회양군", "Popdong": "강원 법동군",
    "Cholwon": "강원 철원군", "Kosong": "강원 고성군",
    # 평양
    "Kangdong": "평양 강동군", "Kangnam": "평양 강남군", "Unjong Dist.": "평양 은정구역",
    # 남포
    "Nampo City": "남포 항구구역", "Kangso": "남포 강서구역", "Onchon": "남포 온천군",
    "Chollima": "남포 천리마구역", "Taean": "남포 대안구역", "Ryonggang": "남포 룡강군",
    # 평북
    "Sinuiju City": "평북 신의주시", "Kusong City": "평북 구성시", "Jongju City": "평북 정주시",
    "Sakju": "평북 삭주군", "Kujang": "평북 구장군", "Ryongchon": "평북 룡천군",
    "Sonchon": "평북 선천군", "Nyongbyon": "평북 녕변군", "Yomju": "평북 염주군",
    "Phihyon": "평북 피현군", "Uiju": "평북 의주군", "Thaechon": "평북 태천군",
    "Tongrim": "평북 동림군", "Unjon": "평북 운전군", "Pakchon": "평북 박천군",
    "Kwaksan": "평북 곽산군", "Cholsan": "평북 철산군", "Taegwan": "평북 대관군",
    "Hyangsan": "평북 향산군", "Chonma": "평북 천마군", "Pyokdong": "평북 벽동군",
    "Tongchang": "평북 동창군", "Changsong": "평북 창성군", "Sindo": "평북 신도군",
    # 평남
    "Kaechon City": "평남 개천시", "Sunchon City": "평남 순천시", "Pyongsong City": "평남 평성시",
    "Anju City": "평남 안주시", "Tokchon City": "평남 덕천시", "Pyongwon": "평남 평원군",
    "Sukchon": "평남 숙천군", "Songchon": "평남 성천군", "Mundok": "평남 문덕군",
    "Pukchang": "평남 북창군", "Taedong": "평남 대동군", "Jungsan": "평남 증산군",
    "Hoechang": "평남 회창군", "Chongnam": "평남 청남구", "Yangdok": "평남 양덕군",
    "Sinyang": "평남 신양군", "Tukjang": "평남 득장지구", "Maengsan": "평남 맹산군",
    "Taehung": "평남 대흥군", "Nyongwon": "평남 녕원군",
    # 황북
    "Kaesong City": "황북 개성시", "Sariwon City": "황북 사리원시", "Hwangju": "황북 황주군",
    "Songrim City": "황북 송림시", "Pongsan": "황북 봉산군", "Phyongsan": "황북 평산군",
    "Koksan": "황북 곡산군", "Unpha": "황북 은파군", "Sohung": "황북 서흥군",
    "Sangwon": "황북 상원군", "Sinkye": "황북 신계군", "Junghwa": "황북 중화군",
    "Suan": "황북 수안군", "Yonthan": "황북 연탄군", "Rinsan": "황북 린산군",
    "Jangphung": "황북 장풍군", "Kumchon": "황북 금천군", "Yonsan": "황북 연산군",
    "Sinphyong": "황북 신평군", "Thosan": "황북 토산군",
    # 황남
    "Ongjin": "황남 옹진군", "Haeju City": "황남 해주시", "Paechon": "황남 배천군",
    "Yonan": "황남 연안군", "Chongdan": "황남 청단군", "Sinchon": "황남 신천군",
    "Anak": "황남 안악군", "Jaerong": "황남 재령군", "Unryul": "황남 은률군",
    "Kangryong": "황남 강령군", "Unchon": "황남 은천군", "Jangyon": "황남 장연군",
    "Pyoksong": "황남 벽성군", "Ryongyon": "황남 룡연군", "Kwail": "황남 과일군",
    "Samchon": "황남 삼천군", "Sinwon": "황남 신원군", "Pongchon": "황남 봉천군",
    "Thaethan": "황남 태탄군", "Songhwa": "황남 송화군",
    # 함남
    "Hamhung City": "함남 함흥시", "Tanchon City": "함남 단천시", "Kumya": "함남 금야군",
    "Jongphyong": "함남 정평군", "Pukchong": "함남 북청군", "Sinpho City": "함남 신포시",
    "Hongwon": "함남 홍원군", "Hamju": "함남 함주군", "Riwon": "함남 리원군",
    "Hochon": "함남 허천군", "Sinhung": "함남 신흥군", "Yonggwang": "함남 영광군",
    "Toksong": "함남 덕성군", "Sudong": "함남 수동구", "Kowon": "함남 고원군",
    "Jangjin": "함남 장진군", "Rakwon": "함남 락원군", "Pujon": "함남 부전군",
    "Yodok": "함남 요덕군", "Kumho": "함남 금호지구",
    # 함북
    "Chongjin City": "함북 청진시", "Kim Chaek City": "함북 김책시", "Hoeryong City": "함북 회령시",
    "Kilju": "함북 길주군", "Onsong": "함북 온성군", "Musan": "함북 무산군",
    "Kyongwon": "함북 경원군", "Kyongsong": "함북 경성군", "Myonggan": "함북 명간군",
    "Kyonghung": "함북 경흥군", "Orang": "함북 어랑군", "Hwadae": "함북 화대군",
    "Myongchon": "함북 명천군", "Puryong": "함북 부령군", "Yonsa": "함북 연사군",
    # 자강
    "Kanggye City": "자강 강계시", "Huichon City": "자강 희천시", "Manpho City": "자강 만포시",
    "Jonchon": "자강 전천군", "Songgan": "자강 성간군", "Wiwon": "자강 위원군",
    "Janggang": "자강 장강군", "Jasong": "자강 자성군", "Tongsin": "자강 동신군",
    "Chosan": "자강 초산군", "Usi": "자강 우시군", "Hwaphyong": "자강 화평군",
    "Sijung": "자강 시중군", "Junggang": "자강 중강군", "Songwon": "자강 송원군",
    "Rangrim": "자강 랑림군", "Ryongrim": "자강 룡림군", "Kophung": "자강 고풍군",
    # 양강
    "Hyesan City": "양강 혜산시", "Kabsan": "양강 갑산군", "Paekam": "양강 백암군",
    "Unhung": "양강 운흥군", "Kim Hyong Jik": "양강 김형직군", "Phungso": "양강 풍서군",
    "Kim Jong Suk": "양강 김정숙군", "Samsu": "양강 삼수군", "Kim Hyong Gwon": "양강 김형권군",
    "Pochon": "양강 보천군", "Taehongdan": "양강 대홍단군", "Samjiyon": "양강 삼지연시",
}

# 평양(원자료 한 폴리곤) 분할용 대표 좌표 (lon, lat). 근사값.
PYONGYANG_SEEDS = {
    "평양 중구역": (125.750, 39.020), "평양 모란봉구역": (125.760, 39.048),
    "평양 서성구역": (125.728, 39.055), "평양 보통강구역": (125.718, 39.033),
    "평양 평천구역": (125.722, 39.003), "평양 만경대구역": (125.655, 38.995),
    "평양 락랑구역": (125.745, 38.965), "평양 선교구역": (125.778, 39.002),
    "평양 동대원구역": (125.785, 39.025), "평양 대동강구역": (125.793, 39.045),
    "평양 사동구역": (125.870, 39.030), "평양 대성구역": (125.820, 39.075),
    "평양 룡성구역": (125.800, 39.130), "평양 삼석구역": (125.930, 39.090),
    "평양 형제산구역": (125.665, 39.075), "평양 순안구역": (125.680, 39.200),
    "평양 력포구역": (125.860, 38.955), "황북 승호구역": (125.990, 38.990),
}
RASON_SEEDS = {"라선 라진구역": (130.300, 42.240), "라선 선봉구역": (130.420, 42.390)}


def fetch(url: str, name: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        print(f"download {url}")
        urllib.request.urlretrieve(url, path)
    return path


def load_regions():
    with open(os.path.join(DATA, "regions.csv"), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sk_display_name(sidonm: str, sggnm: str) -> str:
    if sidonm == "세종특별자치시":
        return "세종시"
    m = re.match(r"^(.+?시)(.+구)$", sggnm)
    if m:  # 수원시권선구 -> 수원시
        sggnm = m.group(1)
    if sidonm == "전남광주통합특별시":
        prefix = "광주" if sggnm in GWANGJU_GU else "전남"
    else:
        prefix = SIDO_ABBR[sidonm]
    return f"{prefix} {sggnm}"


def voronoi_split(poly, seeds: dict):
    from shapely.geometry import MultiPoint
    mp = MultiPoint([Point(*xy) for xy in seeds.values()])
    cells = voronoi_diagram(mp, envelope=poly.envelope.buffer(0.5))
    out = {}
    for name, xy in seeds.items():
        p = Point(*xy)
        cell = next(c for c in cells.geoms if c.contains(p))
        piece = cell.intersection(poly)
        if piece.is_empty:
            raise SystemExit(f"빈 분할 조각: {name}")
        out[name] = piece
    return out


def polygons_of(geom):
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def connect_rivers(terrain, adjacency, geom, id2name, src):
    """강(수계)마다 도하 경계 조각이 끊기지 않도록, 끊긴 조각 사이를 실제 지역 경계선을 따라가는
    가장 짧은 경로로 잇는다. 경로에 쓰인 경계도 같은 강의 도하 경계(자동)가 된다."""
    import networkx as nx
    from shapely.ops import linemerge

    GRID = 0.002

    def key(x, y):
        return (round(x / GRID), round(y / GRID))

    G = nx.Graph()

    def add_line(coords, pair):
        prev = None
        for x, y in coords:
            k = key(x, y)
            if prev is not None and k != prev:
                d = math.hypot(k[0] - prev[0], k[1] - prev[1]) * GRID
                if G.has_edge(prev, k):
                    G[prev][k]["pairs"].add(pair)
                else:
                    G.add_edge(prev, k, w=d, pairs={pair})
                G.nodes[k]["xy"] = (x, y)
                G.nodes[prev].setdefault("xy", (x, y))
            else:
                G.add_node(k, xy=(x, y))
            prev = k

    # 모든 인접 쌍의 공유 경계선
    for a, b in adjacency:
        ga, gb = geom[id2name[a]], geom[id2name[b]]
        cross = {src[id2name[a]], src[id2name[b]]} != {src[id2name[a]]}
        tol = 0.02 if cross else 0.0008
        shared = ga.boundary.intersection(gb.buffer(tol))
        if shared.is_empty:
            continue
        merged = linemerge(shared) if shared.geom_type not in ("LineString",) else shared
        for ln in getattr(merged, "geoms", [merged]):
            if ln.geom_type == "LineString" and ln.length >= 0.001:
                add_line(ln.simplify(0.001).coords, (a, b))
    # 지형 파일의 연결선(하구 등)
    for t in terrain:
        if t["connector"]:
            for ln in t["lines"]:
                add_line(ln, tuple(sorted((t["a"], t["b"]))))

    # 경계선 끝점(교차점 부근)이 서로 붙지 않은 곳을 600m 이내 가장 가까운 점과 잇는다
    cell = defaultdict(list)
    for n in G.nodes:
        cell[(n[0] // 3, n[1] // 3)].append(n)
    for n in [n for n in G.nodes if G.degree(n) <= 1]:
        best = None
        cx, cy = n[0] // 3, n[1] // 3
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for m in cell[(cx + dx, cy + dy)]:
                    if m == n or G.has_edge(n, m):
                        continue
                    d = math.hypot(m[0] - n[0], m[1] - n[1]) * GRID
                    if d <= 0.006 and (best is None or d < best[0]):
                        best = (d, m)
        if best:
            G.add_edge(n, best[1], w=best[0], pairs=set())
    comps_g = list(nx.connected_components(G))
    print(f"경계 그래프: 노드 {G.number_of_nodes()}, 연결 성분 {len(comps_g)}, 최대 {max(len(c) for c in comps_g)}")
    rivers = defaultdict(list)
    for t in terrain:
        if t["kind"] == "도하":
            rivers[t["name"]].append(t)
    known = {frozenset((t["a"], t["b"])) for t in terrain}
    added = {}
    links = []   # 경계가 아닌 시각적 연결선
    for river, segs in rivers.items():
        seg_nodes = set()
        H = nx.Graph()
        for t in segs:
            for ln in t["lines"]:
                ks = [key(x, y) for x, y in ln]
                for k in ks:
                    if k not in G:
                        # 가장 가까운 그래프 노드에 붙인다
                        near = min(G.nodes, key=lambda n: (n[0] - k[0]) ** 2 + (n[1] - k[1]) ** 2)
                        k = near
                    seg_nodes.add(k)
                    H.add_node(k)
                for k1, k2 in zip(ks, ks[1:]):
                    if k1 in G and k2 in G and k1 != k2:
                        H.add_edge(k1, k2)
        comps = [set(c) for c in nx.connected_components(H)]
        if len(comps) <= 1:
            continue

        def cdist(ca, cb):
            best = None
            for n1 in ca:
                for n2 in cb:
                    d = math.hypot(n1[0] - n2[0], n1[1] - n2[1]) * GRID
                    if best is None or d < best[0]:
                        best = (d, n1, n2)
            return best

        # 1) 2km 이내로 붙은 조각은 곧바로 잇는다
        merged_flag = True
        while merged_flag and len(comps) > 1:
            merged_flag = False
            for i in range(len(comps)):
                for j in range(i + 1, len(comps)):
                    d, n1, n2 = cdist(comps[i], comps[j])
                    if d <= 0.02:
                        links.append((river, [G.nodes[n1]["xy"], G.nodes[n2]["xy"]]))
                        comps[i] |= comps[j]
                        del comps[j]
                        merged_flag = True
                        break
                if merged_flag:
                    break
        if len(comps) <= 1:
            continue
        # 2) 남은 조각은 최소 신장 트리로: 경계선 경로가 자연스러우면(직선의 3배 이내) 경계를 따르고,
        #    아니면 직선으로 잇는다(시각적 연결만)
        C = nx.Graph()
        info = {}
        for i, ca in enumerate(comps):
            lengths, ps = nx.multi_source_dijkstra(G, ca, cutoff=1.0, weight="w")
            for j in range(i + 1, len(comps)):
                cb = comps[j]
                straight, s1, s2 = cdist(ca, cb)
                best = min(((lengths[n], n) for n in cb if n in lengths), default=None)
                if best is not None and best[0] <= straight * 3.0 + 0.01:
                    info[(i, j)] = ("path", ps[best[1]])
                    C.add_edge(i, j, w=best[0])
                else:
                    info[(i, j)] = ("line", [G.nodes[s1]["xy"], G.nodes[s2]["xy"]])
                    C.add_edge(i, j, w=straight * 1.3)
        for i, j in nx.minimum_spanning_edges(C, weight="w", data=False):
            kind, val = info[(min(i, j), max(i, j))]
            if kind == "line":
                links.append((river, val))
                continue
            for n1, n2 in zip(val, val[1:]):
                seg = [G.nodes[n1]["xy"], G.nodes[n2]["xy"]]
                owners = [pr for pr in G[n1][n2]["pairs"] if frozenset(pr) not in known]
                if not owners:
                    links.append((river, seg))
                for pair in owners:
                    added.setdefault((river, pair), []).append(seg)
    out = []
    from shapely.geometry import MultiLineString
    for (river, (a, b)), segs in added.items():
        used = sum(math.hypot(p2[0] - p1[0], p2[1] - p1[1]) for p1, p2 in segs)
        if used < 0.004 or frozenset((a, b)) in known:
            links.extend((river, sg) for sg in segs)   # 스치기만 한 경계는 도하로 치지 않는다
            continue
        known.add(frozenset((a, b)))
        merged = linemerge(MultiLineString(segs))
        lines = [[(round(x, 4), round(y, 4)) for x, y in ln.coords]
                 for ln in getattr(merged, "geoms", [merged])]
        out.append({"a": a, "b": b, "kind": "도하", "name": river, "note": "수계 연결(자동)", "mult": 0.9,
                    "connector": False, "auto": True, "lines": lines})
    print(f"수계 연결: 도하 경계 {len(out)}쌍 추가, 연결선 {len(links)}개")
    RIVER_LINKS.extend({"name": r, "line": [(round(x, 4), round(y, 4)) for x, y in ln]} for r, ln in links)
    return out


RIVER_LINKS = []


def build():
    regions = load_regions()
    by_name = {r["표기명"]: r for r in regions}

    sk_path = fetch(SK_URL, "HangJeongDong_ver20260701.geojson")
    nk_path = fetch(NK_URL, "geoBoundaries-PRK-ADM2_simplified.geojson")

    # ---- 남한
    parts = defaultdict(list)
    with open(sk_path, encoding="utf-8") as f:
        sk = json.load(f)
    for feat in sk["features"]:
        p = feat["properties"]
        parts[sk_display_name(p["sidonm"], p["sggnm"])].append(shape(feat["geometry"]).buffer(0))
    sk_geom = {k: unary_union(v) for k, v in parts.items()}

    # ---- 북한
    with open(nk_path, encoding="utf-8") as f:
        nk = json.load(f)
    nk_geom = {}
    unsan = []
    for feat in nk["features"]:
        n = feat["properties"]["shapeName"]
        g = shape(feat["geometry"]).buffer(0)
        if n == "Unsan":
            unsan.append(g)
            continue
        if n == "Pyongyang":
            nk_geom.update(voronoi_split(g, PYONGYANG_SEEDS))
            continue
        if n == "Rason City":
            nk_geom.update(voronoi_split(g, RASON_SEEDS))
            continue
        if n not in NK_NAMES:
            raise SystemExit(f"매칭 안 된 북한 구역: {n}")
        nk_geom[NK_NAMES[n]] = g
    unsan.sort(key=lambda g: g.centroid.y, reverse=True)
    nk_geom["평북 운산군"], nk_geom["평남 은산군"] = unsan  # 북쪽이 운산(평북)

    # ---- 병합: 남북 고성·철원, 황남 옹진 + 인천 옹진
    geom = {}
    adj_geom = {}  # 인접 계산용 (옹진은 북측 본토만)
    for name, r in by_name.items():
        if r["남북"] == "남북 병합":
            if name == "황남 옹진군":
                g = unary_union([nk_geom[name], sk_geom["인천 옹진군"]])
                adj_geom[name] = nk_geom[name]
            else:
                g = unary_union([nk_geom[name], sk_geom[name]])
                adj_geom[name] = g
            geom[name] = g
        elif r["남북"] == "남":
            geom[name] = sk_geom[name]
            adj_geom[name] = geom[name]
        else:
            geom[name] = nk_geom[name]
            adj_geom[name] = geom[name]

    missing = [n for n in by_name if n not in geom]
    extra = [n for n in list(sk_geom) + list(nk_geom)
             if n not in by_name and n != "인천 옹진군"]
    if missing or extra:
        report = os.path.join(ROOT, "tools", "match-report.md")
        with open(report, "w", encoding="utf-8") as f:
            f.write("# 이름 매칭 실패\n\n## 경계 없음\n")
            f.writelines(f"- {n}\n" for n in missing)
            f.write("\n## CSV에 없음\n")
            f.writelines(f"- {n}\n" for n in extra)
        raise SystemExit(f"매칭 실패: missing={missing} extra={extra} (see {report})")

    # ---- 인접
    names = list(by_name)
    src = {n: ("S" if by_name[n]["남북"] == "남" else "N") for n in names}
    for n in names:
        if by_name[n]["남북"] == "남북 병합":
            src[n] = "M"
    island = {n for n in names if by_name[n]["섬"]}
    boxes = {n: adj_geom[n].bounds for n in names}

    def near(a, b, pad):
        ax0, ay0, ax1, ay1 = boxes[a]
        bx0, by0, bx1, by1 = boxes[b]
        return not (ax1 + pad < bx0 or bx1 + pad < ax0 or ay1 + pad < by0 or by1 + pad < ay0)

    adjacency = set()
    for i, a in enumerate(names):
        if a in island:
            continue
        for b in names[i + 1:]:
            if b in island:
                continue
            cross = {src[a], src[b]} == {"S", "N"} or "M" in (src[a], src[b])
            tol = 0.02 if cross else 0.0008
            min_len = 0.02 if cross else 0.004
            if not near(a, b, tol):
                continue
            ga, gb = adj_geom[a], adj_geom[b]
            shared = ga.boundary.intersection(gb.buffer(tol))
            if shared.length >= min_len:
                adjacency.add(tuple(sorted((by_name[a]["ID"], by_name[b]["ID"]))))

    # ---- 렌더링용 단순화
    out_regions = {}
    for name, g in geom.items():
        rid = by_name[name]["ID"]
        polys = []
        for p in polygons_of(g):
            if p.area < 2e-5 and p.area < g.area * 0.02:
                continue  # 아주 작은 섬 조각 생략
            s = p.simplify(0.0015, preserve_topology=True)
            if s.is_empty:
                continue
            ring = [(round(x, 4), round(y, 4)) for x, y in s.exterior.coords]
            polys.append(ring)
        if not polys:  # 조각이 모두 작으면 가장 큰 것 하나는 유지
            p = max(polygons_of(g), key=lambda q: q.area)
            polys.append([(round(x, 4), round(y, 4)) for x, y in p.exterior.coords])
        main = max(polygons_of(g), key=lambda q: q.area)
        lp = main.representative_point() if not main.centroid.within(main) else main.centroid
        out_regions[rid] = {
            "polys": polys,
            "label": [round(lp.x, 4), round(lp.y, 4)],
            "area": round(g.area, 6),
        }

    # ---- 지형 경계(도하·산악 돌파) 선: terrain-borders.csv
    id2name = {r["ID"]: n for n, r in by_name.items()}
    terrain = []
    tpath = os.path.join(DATA, "terrain-borders.csv")
    if os.path.exists(tpath):
        from shapely.geometry import LineString, MultiLineString
        from shapely.ops import linemerge, nearest_points
        with open(tpath, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                a, b = row["구역A_ID"], row["구역B_ID"]
                if id2name.get(a) != row["구역A"] or id2name.get(b) != row["구역B"]:
                    raise SystemExit(f"지형 경계 ID·이름 불일치: {row}")
                ga, gb = geom[id2name[a]], geom[id2name[b]]
                cross = {src[id2name[a]], src[id2name[b]]} & {"N", "M"} and {src[id2name[a]], src[id2name[b]]} & {"S", "M"}
                lines = []
                for tol in ((0.02,) if cross else (0.0008, 0.004, 0.01)):
                    shared = ga.boundary.intersection(gb.buffer(tol))
                    if shared.length >= 0.003:
                        break
                parts = []
                if not shared.is_empty and shared.length >= 0.003:
                    merged = linemerge(shared) if shared.geom_type != "LineString" else shared
                    parts = list(getattr(merged, "geoms", [merged]))
                for ln in parts:
                    if ln.geom_type != "LineString" or ln.length < 0.002:
                        continue
                    ln = ln.simplify(0.0015)
                    lines.append([(round(x, 4), round(y, 4)) for x, y in ln.coords])
                connector = not lines
                if connector:  # 맞닿지 않은 경계(하구 등)는 가장 가까운 두 점을 잇는다
                    p1, p2 = nearest_points(ga, gb)
                    lines.append([(round(p1.x, 4), round(p1.y, 4)), (round(p2.x, 4), round(p2.y, 4))])
                terrain.append({"a": a, "b": b, "kind": row["구분"], "name": row["지형"],
                                "note": row["근거"], "mult": float(row["공격배수"]),
                                "connector": connector, "lines": lines})

    terrain += connect_rivers(terrain, adjacency, geom, id2name, src)

    # ---- 광역·조선 8도 외곽선 (경계선 그리기용)
    def outlines(key_fn, tol):
        groups = defaultdict(list)
        for name, g in geom.items():
            groups[key_fn(by_name[name])].append(g.buffer(0.001))
        out = {}
        for k, gs in groups.items():
            u = unary_union(gs).buffer(-0.001).simplify(tol, preserve_topology=True)
            rings = []
            for p in polygons_of(u):
                if p.area < 3e-4:
                    continue
                rings.append([(round(x, 4), round(y, 4)) for x, y in p.exterior.coords])
                for hole in p.interiors:
                    if Polygon(hole).area > 3e-4:
                        rings.append([(round(x, 4), round(y, 4)) for x, y in hole.coords])
            out[k] = rings
        return out

    provinces = outlines(lambda r: r["광역"] + ("·북" if r["남북"] == "북" and r["광역"] == "강원" else ""), 0.002)
    do8 = outlines(lambda r: r["조선8도"], 0.003)

    result = {
        "terrain": terrain,
        "river_links": RIVER_LINKS,
        "provinces": provinces,
        "do8": do8,
        "source": {
            "south": "vuski/admdongkor ver20260701 (CC BY 4.0, 통계청 SGIS)",
            "north": "geoBoundaries PRK ADM2 gbOpen (CC BY 4.0); 평양 구역·라선 2구역은 보로노이 근사",
        },
        "regions": out_regions,
        "adjacency": sorted(adjacency),
    }
    with open(os.path.join(DATA, "map_geometry.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    return result, by_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    result, by_name = build()
    npts = sum(len(r) for reg in result["regions"].values() for r in reg["polys"])
    print(f"regions={len(result['regions'])} land_adjacency={len(result['adjacency'])} points={npts}")
    if args.report:
        id2 = {r["ID"]: r for r in by_name.values()}
        deg = defaultdict(list)
        for a, b in result["adjacency"]:
            deg[a].append(b)
            deg[b].append(a)
        for rid, r in id2.items():
            if not deg[rid] and not r["섬"]:
                print("고립:", rid, r["표기명"])
        for a, b in result["adjacency"]:
            if (id2[a]["남북"] == "남") != (id2[b]["남북"] == "남"):
                print("남북 경계:", id2[a]["표기명"], "-", id2[b]["표기명"])


if __name__ == "__main__":
    sys.exit(main())
