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
OUT_D = 0.002     # 이 거리 안의 이웃 변은 같은 경계로 본다(지역마다 따로 단순화해 생긴 어긋남 흡수)


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
        """광역(도) 경계를 지역 다각형의 변 그대로 열린 선으로: 같은 광역 안쪽 경계는 빼고, 두 광역이 맞닿은 경계는
        키가 작은 쪽 지역의 변 하나만 남긴다(양쪽 변이 미세하게 달라 두 줄로 보이지 않게)."""
        from shapely.ops import linemerge
        group = {rid: key_fn(rows[rid]) for rid in shapes}
        keys = sorted(set(group.values()))
        by_key = {k: [rid for rid in shapes if group[rid] == k] for k in keys}
        done = None                         # 이미 그린 광역들의 합집합(경계 중복 제거용)
        out = {}
        for k in keys:
            mine = unary_union([shapes[rid] for rid in by_key[k]])
            parts = []
            for rid in by_key[k]:
                ln = shapes[rid].boundary
                others = [shapes[o] for o in by_key[k] if o != rid and shapes[o].distance(shapes[rid]) < OUT_D]
                if others:
                    ln = ln.difference(unary_union(others).buffer(OUT_D))
                if done is not None:
                    ln = ln.difference(done.buffer(OUT_D))
                parts.extend(g for g in getattr(ln, "geoms", [ln]) if not g.is_empty)
            merged = linemerge(unary_union(parts)) if parts else None
            lines = []
            for g in (getattr(merged, "geoms", [merged]) if merged is not None else []):
                if g.is_empty or g.length < 0.003:
                    continue
                lines.append([(round(x, 4), round(y, 4)) for x, y in g.coords])
            out[k] = lines
            done = mine if done is None else unary_union([done, mine])
        return out

    geo["provinces"] = outlines(lambda r: r["광역"] + ("·북" if r["남북"] == "북" and r["광역"] == "강원" else ""))
    geo["do8"] = outlines(lambda r: r["조선8도"])
    geo["outline_open"] = True             # 광역·8도 경계는 닫힌 고리가 아니라 열린 선 목록
    with open(path, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))
    print("provinces", len(geo["provinces"]), "do8", len(geo["do8"]))


if __name__ == "__main__":
    main()
