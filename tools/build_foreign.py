"""지도 배경용 주변국 땅(중국·러시아·일본)을 만든다(v1.2.13). 게임 실행에는 필요 없고,
korciv/data/foreign_land.json 을 다시 만들 때만 쓴다.

원자료: Natural Earth 1:10m Admin 0 – Countries (public domain)
https://github.com/nvkelso/natural-earth-vector (geojson/ne_10m_admin_0_countries.geojson)
플레이할 수 없는 땅이라 가장 멀리 축소·이동했을 때 보이는 범위(경도 100~156, 위도 18~56)만 잘라
한반도 가까이(NEAR)는 곱게, 그 바깥은 거칠게 따로 단순화해 둔다. 두 조각은 NEAR 사각형 가장자리에서 만나므로
조금 겹치게 자르고, 지도는 테두리 없이 칠하기만 한다(테두리를 그으면 이음매가 보인다).

v1.2.22: 북한과 맞닿은 중국·러시아 땅은 Natural Earth 국경과 게임 지역 경계(map_geometry.json)가 어긋나
사이로 바다색 틈이 보였다. 두 나라 땅을 Natural Earth 북한 땅 쪽으로 GROW 만큼 넓힌 뒤 게임의 한반도 땅과
해역을 빼서(넓힌 조각만), 우리 지역 경계에 꼭 맞붙게 한다. 맞붙은 경계선(국경)은 "borders" 로 따로 저장해 지도에 국경 기호로 긋는다.
"""
from __future__ import annotations

import json
import os
import urllib.request

from shapely.geometry import LineString, Polygon, box, mapping, shape
from shapely.ops import linemerge, unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tools", "_cache")
SRC = os.path.join(CACHE, "ne_10m_admin_0_countries.geojson")
URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
       "ne_10m_admin_0_countries.geojson")
OUT = os.path.join(ROOT, "korciv", "data", "foreign_land.json")
BBOX = (100.0, 18.0, 156.0, 56.0)
NEAR = (116.0, 28.0, 140.0, 48.0)
NAMES = {"CHN": "중국", "RUS": "러시아", "JPN": "일본", "MNG": "몽골", "TWN": "대만"}
LABELED = ("중국", "러시아", "일본")
# 이름표 자리(경도, 위도): 지도에서 보이는 땅 위
LABELS = {"중국": (125.2, 42.45), "러시아": (131.1, 43.0), "일본": (130.75, 33.55)}
TOL = 0.006           # 한반도 가까이 단순화(도) ≈ 600m
TOL_FAR = 0.04        # 먼 곳
MIN_AREA = 0.0004     # 이보다 작은 섬은 뺀다(도²)
MIN_AREA_FAR = 0.01
GROW = 0.1            # 북한 쪽으로 넓히는 폭(도): 이 안의 틈을 메운다
NEIGHBORS = ("CHN", "RUS")      # 한반도와 맞닿은 나라
GEO = os.path.join(ROOT, "korciv", "data", "map_geometry.json")


def korea_shapes():
    """게임의 한반도 땅(모든 지역 합)과 해역(해안선에 맞춘 모양)."""
    geo = json.load(open(GEO, encoding="utf-8"))
    land = unary_union([Polygon(ring).buffer(0) for r in geo["regions"].values() for ring in r["polys"]])
    # 지역 사이의 작은 틈(구멍)은 메운다: 넓힌 주변국 땅이 한반도 안쪽 틈에 끼어들지 않게
    land = unary_union([Polygon(p.exterior) for p in getattr(land, "geoms", [land])])
    sea = unary_union([Polygon(p["ext"], p["holes"]).buffer(0) for parts in geo["seas"].values() for p in parts])
    return land, sea


def rings(geom, min_area):
    out = []
    for p in getattr(geom, "geoms", [geom]):
        if p.geom_type != "Polygon" or p.area < min_area:
            continue
        ring = [[round(x, 4), round(y, 4)] for x, y in mapping(p)["coordinates"][0]]
        out.append(ring[:-1])
    return out


def lines_of(geom):
    if geom.is_empty:
        return []
    geom = linemerge(geom) if geom.geom_type in ("MultiLineString", "GeometryCollection") else geom
    out = []
    for ln in getattr(geom, "geoms", [geom]):
        if ln.geom_type != "LineString" or ln.length < 0.005:
            continue
        out.append([[round(x, 4), round(y, 4)] for x, y in ln.coords])
    return out


def main():
    if not os.path.exists(SRC):
        os.makedirs(CACHE, exist_ok=True)
        urllib.request.urlretrieve(URL, SRC)
    data = json.load(open(SRC, encoding="utf-8"))
    clip = box(*BBOX)
    korea, sea = korea_shapes()
    shapes = {ft["properties"].get("ADM0_A3"): shape(ft["geometry"]) for ft in data["features"]
              if ft["properties"].get("ADM0_A3") in set(NAMES) | {"PRK"}}
    prk = shapes["PRK"].intersection(box(*NEAR))
    lands, touching = [], []
    for a3, geom in shapes.items():
        if a3 not in NAMES:
            continue
        full = geom.intersection(clip)
        near = full.intersection(box(*NEAR)).simplify(TOL, preserve_topology=True)
        if a3 in NEIGHBORS:
            # 북한 쪽 틈 메우기: 넓힌 만큼(북한 땅 안에서만) 더한 뒤, 게임의 한반도 땅·해역을 빼서 경계에 맞붙인다
            # (넓힌 조각만 게임 해역을 뺀다: 원래 땅을 해역 모양대로 깎으면 해안이 직선으로 잘린다)
            # (단순화로 원래 국경에서 물러난 틈도 메우도록 단순화 전 땅도 넣는다)
            grow = near.buffer(GROW).intersection(prk.union(full.intersection(box(*NEAR)))).difference(sea)
            near = near.union(grow).simplify(TOL, preserve_topology=True).difference(korea)
            touching.append(near)
        inner = box(NEAR[0] + 0.05, NEAR[1] + 0.05, NEAR[2] - 0.05, NEAR[3] - 0.05)   # 조금 겹쳐 틈이 안 보이게
        far = full.difference(inner).simplify(TOL_FAR, preserve_topology=True)
        polys = rings(near, MIN_AREA) + rings(far, MIN_AREA_FAR)
        lands.append({"name": NAMES[a3], "polys": polys})
        print(NAMES[a3], len(polys), "다각형", sum(len(r) for r in polys), "꼭짓점")
    # 국경: 한반도 땅 테두리 가운데 중국·러시아 땅과 맞붙은 부분(한 줄로 이어 둔다)
    # (바다와 맞닿은 해안은 국경이 아니다: 하구 근처에서 원자료 땅이 해안에 걸친 곳은 뺀다, v1.2.26)
    borders = lines_of(korea.boundary.intersection(unary_union(touching).buffer(0.0005)).difference(sea.buffer(0.003)))
    print("국경", len(borders), "줄", round(sum(LineString(l).length for l in borders), 2), "도")
    out = {"source": "Natural Earth 1:10m Admin 0 Countries (public domain)", "bbox": BBOX,
           "lands": lands, "borders": borders,
           "labels": {k: list(v) for k, v in LABELS.items() if k in LABELED}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("저장:", OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
