"""광역·조선 8도 경계선을 게임이 그리는 지역 다각형(map_geometry.json "regions")에서 다시 만든다.

예전에는 원자료 경계를 따로 합치고 단순화해서, 휴전선처럼 남북 자료가 만나는 곳에서
지역 경계와 어긋난 선이 하나 더 보였다. 지역 다각형 자체를 합치면 경계선이 지역 경계 위에 정확히 겹친다.

  python tools/build_outlines.py      (shapely 필요)
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict

from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "korciv", "data")
EPS = 0.0004      # 이웃 지역 사이 미세한 틈만 메운다(휴전선 폭보다 훨씬 작다)


def polygons_of(g):
    return list(g.geoms) if hasattr(g, "geoms") else [g]


def main():
    path = os.path.join(DATA, "map_geometry.json")
    geo = json.load(open(path, encoding="utf-8"))
    rows = {r["ID"]: r for r in csv.DictReader(open(os.path.join(DATA, "regions.csv"), encoding="utf-8-sig"))}
    shapes = {}
    for rid, reg in geo["regions"].items():
        polys = [Polygon(ring).buffer(0) for ring in reg["polys"] if len(ring) >= 3]
        shapes[rid] = unary_union(polys)

    def outlines(key_fn):
        groups = defaultdict(list)
        for rid, g in shapes.items():
            groups[key_fn(rows[rid])].append(g.buffer(EPS, join_style="mitre", quad_segs=1))
        out = {}
        for k, gs in groups.items():
            # 지역 다각형 꼭짓점을 그대로 쓰도록 아주 작게만 단순화(버퍼가 만든 잔 꼭짓점 정리)
            u = unary_union(gs).buffer(-EPS, join_style="mitre", quad_segs=1).simplify(0.0002)
            rings = []
            for p in polygons_of(u):
                if p.area < 3e-5:
                    continue
                rings.append([(round(x, 4), round(y, 4)) for x, y in p.exterior.coords])
                for hole in p.interiors:
                    if Polygon(hole).area > 3e-5:
                        rings.append([(round(x, 4), round(y, 4)) for x, y in hole.coords])
            out[k] = rings
        return out

    geo["provinces"] = outlines(lambda r: r["광역"] + ("·북" if r["남북"] == "북" and r["광역"] == "강원" else ""))
    geo["do8"] = outlines(lambda r: r["조선8도"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))
    print("provinces", len(geo["provinces"]), "do8", len(geo["do8"]))


if __name__ == "__main__":
    main()
