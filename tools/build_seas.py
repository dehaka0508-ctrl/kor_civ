"""해역 다각형을 해안선에 맞춰 자른다 (shapely 필요, 개발용).

korciv.data.SEA_POLYS의 원형 다각형에서 육지(모든 구역)를 빼고, 섬 전용 해역(독도 해역·
제주도 연안)은 주변 해역에서 잘라낸 뒤 korciv/data/map_geometry.json의 "seas"에 저장한다.
실행: python tools/build_seas.py
"""
import json
import os
import sys

from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from korciv.data import ISLAND_SEAS, SEA_POLYS  # noqa: E402

GEO = os.path.join(ROOT, "korciv", "data", "map_geometry.json")


def rings(geom, min_part=0.004, min_hole=0.0015):
    parts = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    out = []
    for p in sorted(parts, key=lambda p: -p.area):
        if p.area < min_part:
            continue
        p = p.simplify(0.002, preserve_topology=True)
        holes = [[[round(x, 4), round(y, 4)] for x, y in h.coords]
                 for h in p.interiors if Polygon(h).area >= min_hole]
        out.append({"ext": [[round(x, 4), round(y, 4)] for x, y in p.exterior.coords], "holes": holes})
    return out


def main():
    with open(GEO, encoding="utf-8") as f:
        geo = json.load(f)
    land = unary_union([Polygon(r).buffer(0) for g in geo["regions"].values() for r in g["polys"]
                        if len(r) >= 3]).buffer(0.001)
    island = {sid: Polygon(SEA_POLYS[sid]).buffer(0) for sid in ISLAND_SEAS}
    cut = unary_union(list(island.values()))
    seas = {}
    for sid, pts in SEA_POLYS.items():
        shape = Polygon(pts).buffer(0)
        if sid not in ISLAND_SEAS:
            shape = shape.difference(cut)
        seas[sid] = rings(shape.difference(land))
        print(sid, len(seas[sid]), "parts", sum(len(p["holes"]) for p in seas[sid]), "holes")
    geo["seas"] = seas
    with open(GEO, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
