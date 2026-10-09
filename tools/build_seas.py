"""해역 다각형을 해안선에 맞춰 자른다 (shapely 필요, 개발용).

- 남해 서부·남해 동부와 섬 전용 해역(독도 해역·제주도 연안)은 korciv.data.SEA_POLYS 의 원형 다각형에서
  육지를 빼서 만든다(섬 전용 해역은 주변 해역에서 잘라낸다).
- 서해(서한만·경기만·서해 남부)와 동해(남동해·영동 해역·동한만·북동해)는 korciv.data.SEA_GROUPS 의 묶음
  다각형에서 육지를 뺀 바다를, 해안 지역의 해역 배정(regions.csv '인접해역')에 따라 '가장 가까운 해안'
  기준으로 나눈다(해안선 위 점들의 보로노이 분할). 두 해역에 걸친 경계 지역은 SEA_SPLIT 위도로 해안을 나눈다.
결과는 korciv/data/map_geometry.json 의 "seas"(모양)와 "sea_labels"(이름 위치)에 저장한다.
실행: python tools/build_seas.py
"""
import csv
import json
import os
import sys

from shapely.geometry import MultiPoint, Point, Polygon
from shapely.ops import unary_union, voronoi_diagram

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from korciv.data import (ISLAND_SEAS, SEA_BY_NAME, SEA_GROUPS, SEA_LABELS, SEA_POLYS,  # noqa: E402
                         SEA_SPLIT)

GEO = os.path.join(ROOT, "korciv", "data", "map_geometry.json")
CSV = os.path.join(ROOT, "korciv", "data", "regions.csv")
# 해안선에 붙도록: 육지는 지역 사이 미세한 틈만 메울 만큼(약 30m)만 넓히고, 해역 경계도 약 50m 이내로만 단순화한다.
LAND_PAD = 0.0003
SIMPLIFY = 0.0005
STEP = 0.01            # 해안선 표본 간격(도)


def rings(geom, min_part=0.004, min_hole=0.0015):
    parts = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
    out = []
    for p in sorted(parts, key=lambda p: -p.area):
        if p.geom_type != "Polygon" or p.area < min_part:
            continue
        p = p.simplify(SIMPLIFY, preserve_topology=True)
        holes = [[[round(x, 4), round(y, 4)] for x, y in h.coords]
                 for h in p.interiors if Polygon(h).area >= min_hole]
        out.append({"ext": [[round(x, 4), round(y, 4)] for x, y in p.exterior.coords], "holes": holes})
    return out


def region_seas():
    with open(CSV, encoding="utf-8-sig") as f:
        return {r["ID"]: [SEA_BY_NAME[s.strip()] for s in r["인접해역"].split(",") if s.strip()]
                for r in csv.DictReader(f)}


def coast_points(geo, rid, area, label_of):
    """rid 의 해안선(바다 area 와 맞닿은 경계) 위에 STEP 간격으로 점을 찍고 해역을 붙인다."""
    shape = unary_union([Polygon(r).buffer(0) for r in geo["regions"][rid]["polys"] if len(r) >= 3])
    near = area.buffer(0.01)
    out = []
    for poly in ([shape] if shape.geom_type == "Polygon" else list(shape.geoms)):
        line = poly.exterior
        n = max(2, int(line.length / STEP))
        for i in range(n):
            pt = line.interpolate(i / n, normalized=True)
            if near.contains(pt):
                sid = label_of(pt)
                if sid:
                    out.append((pt, sid))
    return out


def split_group(geo, land, cut, group, seas_of):
    area = Polygon(group["poly"]).buffer(0).difference(cut).difference(land)
    sids = set(group["seas"])
    pts = []
    for rid, ss in seas_of.items():
        mine = [s for s in ss if s in sids]
        if not mine:
            continue
        if rid in SEA_SPLIT and set(SEA_SPLIT[rid][1:]) <= set(mine):
            lat, north, south = SEA_SPLIT[rid]
            label = (lambda p, lat=lat, north=north, south=south: north if p.y >= lat else south)
        elif len(mine) == 1:
            label = (lambda p, s=mine[0]: s)
        else:
            continue                                   # 묶음 밖 해역과의 경계 지역은 이 묶음 쪽 해역만
        pts += coast_points(geo, rid, area, label)
    # 먼바다 경계선: 선 양쪽에 점을 촘촘히 찍어 먼바다에서는 경계가 이 선을 따르게 한다
    for (x0, y0), (x1, y1), left, right in group.get("lines", ()):
        dx, dy = x1 - x0, y1 - y0
        length = (dx * dx + dy * dy) ** 0.5
        nx, ny = -dy / length * 0.03, dx / length * 0.03          # 진행 방향 왼쪽
        n = max(2, int(length / 0.05))
        for i in range(1, n + 1):
            x, y = x0 + dx * i / n, y0 + dy * i / n
            pts.append((Point(x + nx, y + ny), left))
            pts.append((Point(x - nx, y - ny), right))
    cells = voronoi_diagram(MultiPoint([p for p, _ in pts]), envelope=area.envelope.buffer(1.0))
    by_sid = {s: [] for s in sids}
    # 각 보로노이 칸을 그 칸을 만든 해안 점의 해역에 붙인다
    from shapely.strtree import STRtree
    tree = STRtree([p for p, _ in pts])
    for cell in cells.geoms:
        idx = tree.query(cell, predicate="contains")
        if len(idx):
            by_sid[pts[int(idx[0])][1]].append(cell)
    return {s: unary_union(cs).intersection(area) for s, cs in by_sid.items()}


def main():
    with open(GEO, encoding="utf-8") as f:
        geo = json.load(f)
    land = unary_union([Polygon(r).buffer(0) for g in geo["regions"].values() for r in g["polys"]
                        if len(r) >= 3]).buffer(LAND_PAD, join_style="mitre")
    island = {sid: Polygon(SEA_POLYS[sid]).buffer(0) for sid in ISLAND_SEAS}
    cut = unary_union(list(island.values()))
    shapes = {}
    for sid, pts in SEA_POLYS.items():
        shape = Polygon(pts).buffer(0)
        if sid not in ISLAND_SEAS:
            shape = shape.difference(cut)
        shapes[sid] = shape.difference(land)
    seas_of = region_seas()
    for group in SEA_GROUPS.values():
        shapes.update(split_group(geo, land, cut, group, seas_of))
    seas, labels = {}, {}
    for sid in sorted(shapes, key=lambda s: int(s[3:])):
        seas[sid] = rings(shapes[sid])
        labels[sid] = list(SEA_LABELS[sid])
        print(sid, len(seas[sid]), "parts", sum(len(p["holes"]) for p in seas[sid]), "holes",
              round(shapes[sid].area, 3), "area")
    geo["seas"] = seas
    geo["sea_labels"] = labels
    with open(GEO, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
