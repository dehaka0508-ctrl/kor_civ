"""지도 배경용 주변국 땅(중국·러시아·일본)을 만든다(v1.2.13). 게임 실행에는 필요 없고,
korciv/data/foreign_land.json 을 다시 만들 때만 쓴다.

원자료: Natural Earth 1:10m Admin 0 – Countries (public domain)
https://github.com/nvkelso/natural-earth-vector (geojson/ne_10m_admin_0_countries.geojson)
플레이할 수 없는 땅이라 가장 멀리 축소·이동했을 때 보이는 범위(경도 100~156, 위도 18~56)만 잘라
한반도 가까이(NEAR)는 곱게, 그 바깥은 거칠게 따로 단순화해 둔다. 두 조각은 NEAR 사각형 가장자리에서 만나므로
조금 겹치게 자르고, 지도는 테두리 없이 칠하기만 한다(테두리를 그으면 이음매가 보인다).
"""
from __future__ import annotations

import json
import os
import urllib.request

from shapely.geometry import box, mapping, shape

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


def main():
    if not os.path.exists(SRC):
        os.makedirs(CACHE, exist_ok=True)
        urllib.request.urlretrieve(URL, SRC)
    data = json.load(open(SRC, encoding="utf-8"))
    clip = box(*BBOX)
    lands = []
    for ft in data["features"]:
        a3 = ft["properties"].get("ADM0_A3")
        if a3 not in NAMES:
            continue
        full = shape(ft["geometry"]).intersection(clip)
        near = full.intersection(box(*NEAR)).simplify(TOL, preserve_topology=True)
        inner = box(NEAR[0] + 0.05, NEAR[1] + 0.05, NEAR[2] - 0.05, NEAR[3] - 0.05)   # 조금 겹쳐 틈이 안 보이게
        far = full.difference(inner).simplify(TOL_FAR, preserve_topology=True)
        polys = []
        for geom, min_area in ((near, MIN_AREA), (far, MIN_AREA_FAR)):
            for p in getattr(geom, "geoms", [geom]):
                if p.geom_type != "Polygon" or p.area < min_area:
                    continue
                ring = [[round(x, 4), round(y, 4)] for x, y in mapping(p)["coordinates"][0]]
                polys.append(ring[:-1])
        lands.append({"name": NAMES[a3], "polys": polys})
        print(NAMES[a3], len(polys), "다각형", sum(len(r) for r in polys), "꼭짓점")
    out = {"source": "Natural Earth 1:10m Admin 0 Countries (public domain)", "bbox": BBOX,
           "lands": lands, "labels": {k: list(v) for k, v in LABELS.items() if k in LABELED}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("저장:", OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
