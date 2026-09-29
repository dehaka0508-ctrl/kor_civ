from collections import Counter, deque

from korciv.data import load_world


def test_region_counts():
    w = load_world()
    assert len(w.regions) == 424
    c = Counter(r.ns for r in w.regions.values())
    assert c == {"남": 227, "북": 194, "남북 병합": 3}
    assert round(sum(r.pop0 for r in w.regions.values()), 1) == 8611.2


def test_geometry_for_every_region():
    w = load_world()
    assert set(w.geometry) == set(w.regions)
    assert all(g["polys"] for g in w.geometry.values())


def test_bridges_and_islands():
    w = load_world()
    assert len(w.bridges) == 17
    for a, b in (("인천 영종구", "인천 서해구"), ("경남 거제시", "부산 강서구"), ("전북 군산시", "전북 부안군")):
        ia, ib = w.name_to_id[a], w.name_to_id[b]
        assert ib in w.land_adj[ia]
    for name in ("경북 울릉군", "제주 제주시", "제주 서귀포시"):
        assert w.land_adj[w.name_to_id[name]] == set()


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
    assert counts == {"서북해": 33, "서남해": 32, "남서해": 13, "남동해": 19, "동남해": 16, "동북해": 24}
    assert w.seas["SEA1"].adj == ["SEA2"]
    assert w.seas["SEA3"].adj == ["SEA2", "SEA4"]


def test_cross_border_links():
    w = load_world()
    n = w.name_to_id
    assert n["황북 개성시"] in w.land_adj[n["경기 파주시"]]
    assert n["강원 평강군"] in w.land_adj[n["강원 철원군"]]


def test_mountain_pass_not_adjacent_unless_touching():
    w = load_world()
    n = w.name_to_id
    assert n["양강 김형권군"] not in w.land_adj[n["함남 북청군"]]
    assert n["양강 백암군"] not in w.land_adj[n["함북 김책시"]]
    # 도하 하구 경로는 인접
    assert n["황북 개성시"] in w.land_adj[n["인천 강화군"]]
    assert w.terrain_between(n["경북 문경시"], n["충북 괴산군"])["kind"] == "돌파"
