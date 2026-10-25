import pytest
from collections import Counter, deque

from korciv.data import load_world


def test_region_counts():
    w = load_world()
    assert len(w.regions) == 427
    c = Counter(r.ns for r in w.regions.values())
    assert c == {"남": 228, "북": 197, "남북 병합": 2}
    assert round(sum(r.pop0 for r in w.regions.values()), 1) == 8611.1   # 옹진 분리로 반올림 0.1 차이


def test_geometry_for_every_region():
    w = load_world()
    assert set(w.geometry) == set(w.regions)
    assert all(g["polys"] for g in w.geometry.values())


def test_bridges_and_islands():
    w = load_world()
    assert len(w.bridges) == 18
    for a, b in (("인천 영종구", "인천 서해구"), ("경남 거제시", "부산 강서구"), ("전북 군산시", "전북 부안군")):
        ia, ib = w.name_to_id[a], w.name_to_id[b]
        assert ib in w.land_adj[ia]
    assert w.land_adj[w.name_to_id["경북 울릉군"]] == set()
    # 제주시–서귀포시는 같은 섬이라 서로만 육로로 잇는다
    j, sg = w.name_to_id["제주 제주시"], w.name_to_id["제주 서귀포시"]
    assert w.land_adj[j] == {sg} and w.land_adj[sg] == {j}


def test_every_mainland_region_has_neighbor_and_is_connected():
    w = load_world()
    mainland = [r for r in w.order if w.regions[r].island != "무연륙 섬"]
    assert all(w.land_adj[r] for r in mainland)
    seen = {mainland[0]}
    q = deque([mainland[0]])
    while q:
        u = q.popleft()
        for v in w.land_adj[u]:
            if v not in seen:
                seen.add(v)
                q.append(v)
    assert seen == set(mainland)


def test_sea_coasts():
    w = load_world()
    counts = {s.name: len(s.coast) for s in w.seas.values()}
    # v1.3.0: 지도와 맞춤 — 서한만 +은천·동림 −대안·룡강·안주·송화, 경기만 +판문·파주·검단 −미추홀,
    # 서해 남부 +서산(천수만), 동한만 +락원, 북동해 +명간. v1.3.24: 서한만 +박천(청천강 하구의 작은 해변)
    assert counts == {"서한만": 24, "경기만": 27, "서해 남부": 17, "남해 서부": 11, "남해 동부": 17,
                      "남동해": 8, "영동 해역": 7, "동한만": 15, "북동해": 9, "독도 해역": 1, "제주도 연안": 2}
    assert w.seas["SEA1"].adj == ["SEA2"]
    assert w.seas["SEA4"].adj == ["SEA3", "SEA5", "SEA11"]
    assert w.island_seas_of(w.name_to_id["제주 서귀포시"]) == ("SEA11",)
    n = w.name_to_id
    assert w.regions[n["충남 태안군"]].seas == ("SEA2", "SEA3")         # 경기만·서해 남부 경계
    assert w.regions[n["황남 옹진군"]].seas == ("SEA1", "SEA2")         # 서한만·경기만 경계
    assert w.regions[n["경북 울진군"]].seas == ("SEA7",) and w.regions[n["경북 영덕군"]].seas == ("SEA6",)
    assert w.regions[n["함남 단천시"]].seas == ("SEA8",) and w.regions[n["함북 성진시"]].seas == ("SEA9",)
    assert w.regions[w.name_to_id["경북 울릉군"]].specialties == ("독도새우", "명이")
    assert w.regions[w.name_to_id["경북 경산시"]].specialties == ("삽살개",)      # v1.3.26
    # 해안선에 맞춘 해역 모양이 저장되어 있다
    assert set(w.sea_shapes) == set(w.seas)
    assert w.regions[n["평북 박천군"]].seas == ("SEA1",)


def test_inland_regions_do_not_touch_sea_shapes():
    """지도와 데이터 일치(v1.3.24): '내륙' 지역 다각형이 해역 다각형과 맞닿지 않는다(박천 같은 불일치 방지)."""
    shapely = pytest.importorskip("shapely")
    import json
    import os
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    w = load_world()
    path = os.path.join(os.path.dirname(__file__), "..", "korciv", "data", "map_geometry.json")
    d = json.load(open(path, encoding="utf-8"))
    seas = unary_union([Polygon(p["ext"], p.get("holes", [])).buffer(0) for v in d["seas"].values() for p in v])
    near = seas.buffer(0.002)
    bad = []
    for rid, r in d["regions"].items():
        if w.regions[rid].coastal:
            continue
        poly = unary_union([Polygon(p).buffer(0) for p in r["polys"]])
        if poly.boundary.intersection(near).length > 0.002:
            bad.append(w.regions[rid].name)
    assert not bad


def test_cross_border_links():
    w = load_world()
    n = w.name_to_id
    assert n["개성 판문구역"] in w.land_adj[n["경기 파주시"]]
    assert n["강원 평강군"] in w.land_adj[n["강원 철원군"]]


def test_mountain_pass_not_adjacent_unless_touching():
    w = load_world()
    n = w.name_to_id
    assert n["량강 풍산군"] not in w.land_adj[n["함남 북청군"]]
    assert n["량강 백암군"] not in w.land_adj[n["함북 성진시"]]
    # 도하 하구 경로는 인접
    assert n["개성 개풍구역"] in w.land_adj[n["인천 강화군"]]
    assert w.terrain_between(n["경북 문경시"], n["충북 괴산군"])["kind"] == "돌파"


def test_jeju_sea_only_next_to_south_west_sea():
    w = load_world()
    assert w.seas["SEA11"].adj == ["SEA4"] and "SEA11" not in w.seas["SEA5"].adj


def test_ongjin_split():
    """황남 옹진(반도)과 인천 옹진(섬)은 따로. 인천 옹진은 영흥도–대부도(안산) 연륙교로 이어진 연륙 섬(섬 보너스 없음)."""
    w = load_world()
    n = w.name_to_id
    hw, ic = w.regions[n["황남 옹진군"]], w.regions[n["인천 옹진군"]]
    assert hw.ns == "북" and ic.ns == "남" and ic.province == "인천"
    assert ic.island == "연륙 섬" and not ic.start_port
    assert w.land_adj[ic.id] == {n["경기 안산시"]} and w.is_bridge(ic.id, n["경기 안산시"])
    assert w.land_adj[hw.id] and ic.seas == ("SEA2",) and hw.seas == ("SEA1", "SEA2")
    assert ic.power_site and "꽃게" in ic.specialties and ic.scenic == "두무진"


def test_no_adjacency_across_other_regions_land():
    """v1.3.4: 지도에서 맞닿지 않은 두 지역은 이웃이 아니다. 도하(강 건너기) 자료로 이어 주는 것은 하구처럼
    사이에 다른 지역 땅이 없는 물길뿐 — 남포 대안–황북 송림(사이에 평양 강남·남포 룡강), 평양 중구역–대동강구역,
    평천구역–선교구역은 다른 구역 땅을 사이에 두고 이어져 있었다."""
    import json
    import os
    from korciv.data import load_world
    w = load_world()
    path = os.path.join(os.path.dirname(__file__), "..", "korciv", "data", "map_geometry.json")
    with open(path, encoding="utf-8") as f:
        touch = {frozenset(p) for p in json.load(f)["adjacency"]}
    nm = {v.name: k for k, v in w.regions.items()}
    for a, b in (("남포 대안", "황북 송림"), ("평양 중구역", "평양 대동강"), ("평양 평천", "평양 선교")):
        assert nm[b] not in w.land_adj[nm[a]], (a, b)
        assert nm[a] in w.river_regions and nm[b] in w.river_regions       # 다른 도하 경계가 있어 하천 지역은 그대로
    extra = {frozenset((a, b)) for a in w.order for b in w.land_adj[a]} - touch - set(w.bridges)
    names = {tuple(sorted(w.regions[x].name for x in k)) for k in extra}
    # 맞닿지 않고 이웃인 쌍은 한강 하구(물길만 건넘)와 같은 섬 안의 육로뿐
    assert names <= {("개성 개풍", "인천 강화"), ("제주 서귀포", "제주 제주")}, names
