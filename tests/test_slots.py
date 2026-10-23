"""건물 슬롯(v1.3.8): 기본·하천·해안 슬롯, 현실 모드 시작 카드, 카드별 산출 합산, 신축·증축·철거, 슬롯 카드 화면."""
import os
import pickle

import pytest

from korciv import config as C, rules as R, slots as S
from korciv.data import load_world
from korciv.game import Game
from korciv.state import NEUTRAL, Settings


@pytest.fixture(autouse=True)
def strict_slots(monkeypatch):
    """이 파일은 슬롯 규칙 자체를 본다: 빈 칸이 없으면 억지로 늘리지 않는다."""
    monkeypatch.setattr(S, "GROW_WHEN_FULL", False)


@pytest.fixture(scope="module")
def world():
    return load_world()


def game(mode="standard", start="S002", **kw):
    g = Game(Settings(mode=mode, n_enemies=1, player_start=start, seed=8, **kw))
    g.set_player_government("philosopher")
    g.player.money = 10 ** 8
    return g


def own(g, rid):
    if g.regions[rid].owner != 0:
        g.transfer_region(rid, 0, reason="편입")
    rr = g.regions[rid]
    rr.resist, rr.happy = None, 20
    return rr


def cards(b):
    return {t: [(c["key"], c["level"]) if c else None for c in v] for t, v in b.slots.items()}


# ------------------------------------------------------------------ 칸 수
def test_base_slot_count_by_area_and_water_slots(world):
    assert [S.base_slot_count(a) for a in (3, 100, 100.1, 300, 300.1, 600, 600.1, 1000, 1000.1, 1800)] == \
        [2, 2, 3, 3, 4, 4, 5, 5, 6, 6]
    for rid, info in world.regions.items():
        cap = S.capacity(world, rid)
        assert 2 <= cap["base"] <= 6
        assert cap["coast"] == int(info.coastal)
        assert cap["river"] == int(rid in world.river_regions or bool(info.hydro)
                                   or (info.fishery > 0 and not info.coastal))
    # 댐(수력) 소재지는 하천과 닿아 있지 않아도 하천 슬롯이 있다(장진강 등)
    jangjin = world.name_to_id["함남 장진군"]
    assert jangjin not in world.river_regions and S.capacity(world, jangjin)["river"] == 1


def test_slot_kinds_allowed_per_slot_type():
    assert set(S.SLOT_KEYS["base"]) == {"farm", "factory", "bank", "admin", "edu", "academy", "extract"}
    assert set(S.SLOT_KEYS["river"]) == {"fishery", "power", "hydro"}
    assert set(S.SLOT_KEYS["coast"]) == {"port", "fishery", "power", "nuclear"}
    for k in ("specialty", "shelter", "aa", "airport"):
        assert k not in S.CARD_KEYS                         # 슬롯을 쓰지 않는 건물
    assert {"admin", "edu", "academy", "port"} <= S.UNIQUE_KEYS
    assert set(S.STACK_KEYS) == {"farm", "fishery", "factory", "bank", "power", "extract"}


# ------------------------------------------------------------------ 현실 모드 시작 카드
def test_standard_start_cards_follow_spec(world):
    for rid, info in world.regions.items():
        b = S.initial(world, rid)
        assert {t: len(v) for t, v in b.slots.items()} == S.capacity(world, rid)
        assert b.used() <= b.total()
        for key in S.UNIQUE_KEYS:
            assert b.count(key) <= 1
        assert all(c["level"] <= 3 for _, _, c in b.cards())
        assert b["admin"] == S.admin_start_level(info.pop0) or b.count("admin") == 0
        coast = b.slots["coast"][0] if b.slots["coast"] else None
        if coast is not None and coast["key"] in ("power", "nuclear"):
            assert info.power_source and not info.hydro
        if info.coastal and info.power_source and not info.hydro:
            assert coast["key"] in ("power", "nuclear")
            assert coast["level"] == max(1, min(2, info.power_self)) or coast["key"] == "nuclear"
        elif info.coastal and info.start_port:
            assert coast == {"key": "port", "level": 1}
        if info.hydro:
            assert b.slots["river"][0] == {"key": "hydro", "level": info.hydro}
        # 시장·공장·농장은 칸이 모자라면 도심은 시장 > 공장 > 농장, 농촌은 농장 > 공장 > 시장 순으로만 남는다
        order = ("bank", "factory", "farm") if info.rtype != "군" else ("farm", "factory", "bank")
        want = [k for k in order if getattr(info, k) > 0]
        placed = [k for k in want if b.count(k)]
        assert placed == want[:len(placed)], (rid, info.name, cards(b))
        if len(placed) < len(want):
            assert not b.empty("base")


def test_start_card_examples(world):
    n = world.name_to_id
    # 부산 기장(원전 고리, 자체 발전 2): 해안 슬롯에 원자력발전소 2단계
    assert S.initial(world, n["부산 기장군"]).slots["coast"] == [{"key": "nuclear", "level": 2}]
    # 충남 태안(화력): 해안 슬롯에 발전소 1단계, 평양 평천(내륙 화력): 하천 슬롯에 발전소
    assert S.initial(world, n["충남 태안군"]).slots["coast"] == [{"key": "power", "level": 1}]
    assert S.initial(world, "N021").slots["river"] == [{"key": "power", "level": 1}]
    # 대전 대덕(대청댐): 하천 슬롯에 수력발전소
    assert S.initial(world, n["대전 대덕구"]).slots["river"] == [{"key": "hydro", "level": 1}]
    # 서울 송파(인구 64.9만, 기본 2칸): 구청 + 시장 3단계(시장 2단계·인구 50만 이상)
    assert cards(S.initial(world, "S001"))["base"] == [("admin", 2), ("bank", 3)]
    # 서울 관악(거점대학): 행정 → 연구 2단계가 먼저 칸을 차지한다
    assert cards(S.initial(world, "S006"))["base"] == [("admin", 1), ("edu", 2)]
    # 경북 울진(기본 5칸, 농촌): 농장 카드를 한 장 더
    assert cards(S.initial(world, n["경북 울진군"]))["base"][:2] == [("farm", 1), ("farm", 1)]
    # 행정 단계: 20만 미만 0, 20~50만 1, 50~100만 2, 100만 이상 3
    assert [S.admin_start_level(p) for p in (19.9, 20, 49.9, 50, 99.9, 100)] == [0, 1, 1, 2, 2, 3]


def test_level_rescale_rules():
    f = S._scaled
    assert f(0, 80) == 0
    assert f(2, 50) == 3 and f(2, 49) == 2
    assert f(1, 30) == 2 and f(1, 29) == 1
    assert f(2, 10, area=600, farm=True) == 3 and f(2, 99, area=599, farm=True) == 2


def test_frontier_and_chaos_start_with_empty_slots():
    for mode in ("frontier", "chaos"):
        g = game(mode)
        caps = {f.capital for f in g.factions}
        for rid, r in g.regions.items():
            keys = {c["key"] for _, _, c in r.b.cards()}
            allowed = {"admin"} if rid in caps else set()
            if g.info(rid).island == "무연륙 섬":
                allowed.add("port")
            assert keys <= allowed, (mode, rid, cards(r.b))


def test_start_capital_admin(world):
    g = game(start="S001")                                 # 송파: 구청(2) → 시청(3)
    assert g.regions["S001"].b["admin"] == 3
    g = game(start="S041")                                 # 부산 중구(인구 3.6만): 빈 칸에 주민센터
    b = g.regions["S041"].b
    assert b["admin"] == 1 and b.count("bank") == 1
    full = next(rid for rid in world.order if not S.initial(world, rid).empty("base")
                and not S.initial(world, rid).count("admin"))
    g = game(start=full)                                   # 빈 칸이 없으면 마지막 기본 슬롯을 바꾼다
    b = g.regions[full].b
    assert b.slots["base"][-1] == {"key": "admin", "level": 1}


# ------------------------------------------------------------------ 산출
def test_duplicate_cards_sum_output_and_conditions_use_max():
    g = game()
    rid = "S192"                                           # 경북 안동(기본 6칸)
    rr = own(g, rid)
    rr.b.reset({})
    rr.b.place("bank", 3, ("base", 0))
    rr.b.place("bank", 3, ("base", 1))
    rr.b.place("farm", 2, ("base", 2))
    rr.b.place("farm", 1, ("base", 3))
    rr.happy = 50
    assert rr.b["bank"] == 3 and rr.b.cap("bank") == 6 and rr.b.levels("farm") == [2, 1]
    base = R.region_output(rr.pop, 0, 0, 0, 0)
    out = R.region_output(rr.pop, rr.b.cap("farm"), 0, 0, rr.b.levels("bank"))
    assert out - base == pytest.approx(2 * C.BANK_OUTPUT * R.g(3) + C.FARM_OUTPUT * 3)
    assert g.food_prod(0, rr) == pytest.approx(C.FARM_FOOD * 3 * g.farm_mult(0, rid))
    # 공장 카드 2장: 연료는 높은 단계부터(3단계 3개, 그다음 1단계 1개)
    assert R.factory_output([3, 1], 4) == pytest.approx(R.factory_unit(3) * 3 + R.factory_unit(1) * 1)
    assert R.factory_output([3, 1]) == pytest.approx(R.factory_output(3) + R.factory_output(1))
    # 조건 판정은 가장 높은 카드: 시장 5단계 1장이면 '시장 5단계 지역'
    g.player.techs.add("aerospace")
    assert not g.science_site_ok(0, rid, "budget")
    rr.b.place("bank", 5, ("base", 4))
    assert rr.b["bank"] == 5 and rr.b.count("bank") == 3
    assert g.science_site_ok(0, rid, "budget")               # 과학 3단계 '예산 편성': 시장 5단계 지역


def test_power_cards_capacity_and_elec():
    g = game()
    rr = own(g, "S192")
    rr.b.reset({})
    rr.b.place("power", 2, ("river", 0))
    assert rr.b.cap("power") == 2
    e = g.plant_elec(0, rr.b.levels("power"), 1, 1)
    assert e == pytest.approx(g.power_elec(0, "oil", 2) + g.power_elec(0, "coal", 2))


def test_fishery_slot_multiplier():
    g = game()
    rid = next(r for r in g.world.order if g.info(r).coastal and r in g.world.river_regions
               and g.regions[r].owner == NEUTRAL)
    rr = own(g, rid)
    rr.b.reset({})
    rr.b.place("fishery", 2, ("river", 0))
    rr.b.place("fishery", 1, ("coast", 0))
    w = g.weather_fish_mult
    eff = 2 * C.RIVER_FISH_MULT * w(rid, river=True) + 1 * g.fish_slot_mult(0, rid, "coast")
    assert g.fishery_eff(0, rid) == pytest.approx(eff)
    assert C.FISH_FOOD * C.RIVER_FISH_MULT == pytest.approx(12) and C.FISH_OUTPUT * C.RIVER_FISH_MULT == pytest.approx(120)
    assert (C.FARM_FOOD, C.FARM_OUTPUT, C.RIVER_FARM_MULT) == (15, 150, 1.0)


# ------------------------------------------------------------------ 선택지·공사
def test_slot_options_new_upgrade_and_unique():
    g = game()
    rr = own(g, "S192")
    rr.b.reset({})
    rr.b.place("admin", 2, ("base", 0))
    rr.b.place("farm", 1, ("base", 1))
    opts = [o for o in g.options(0, "S192") if o.get("slot")]
    new = {(o["key"], o["slot"]) for o in opts if o["level"] == 1}
    # 빈 기본 슬롯(첫 빈 칸 = 2번 칸)에 1단계 신축. 행정은 이미 있어 신축 없음, 하천 칸에는 어장·발전소·수력
    assert ("bank", ("base", 2)) in new and ("farm", ("base", 2)) in new and ("academy", ("base", 2)) in new
    assert not any(k == "admin" for k, _ in new)
    assert {k for k, s in new if s[0] == "river"} == {"fishery", "power", "hydro"}
    up = {(o["key"], o["slot"], o["level"]) for o in opts if o["level"] > 1}
    assert ("admin", ("base", 0), 3) in up and ("farm", ("base", 1), 2) in up
    # 슬롯을 정해 신축 → 그 칸에 카드
    ok, msg = g.start_project(0, "S192", "build", "farm", slot=("base", 2))
    assert ok and msg.startswith("[기본 슬롯 3]")
    p = rr.project
    p.progress = p.turns - 1
    g._fund_projects()
    g._phase_projects(("build",))
    assert rr.b.card(("base", 2)) == {"key": "farm", "level": 1} and rr.b.count("farm") == 2
    # 증축: 같은 칸 단계만 오른다
    ok, msg = g.start_project(0, "S192", "build", "farm", slot=("base", 1))
    assert ok and "농장 1→2단계 증축" in msg
    rr.project.progress = rr.project.turns - 1
    g._fund_projects()
    g._phase_projects(("build",))
    assert rr.b.levels("farm") == [2, 1]


def test_demolish_empties_slot_and_respects_projects():
    g = game()
    rr = own(g, "S192")
    rr.b.reset({})
    rr.b.place("bank", 2, ("base", 0))
    rr.b.place("farm", 1, ("base", 1))
    assert g.start_project(0, "S192", "build", "bank", slot=("base", 0))[0]
    ok, msg = g.demolish_card(0, "S192", ("base", 0))
    assert not ok and "공사" in msg
    ok, msg = g.demolish_card(0, "S192", ("base", 1))
    assert ok and rr.b.card(("base", 1)) is None and rr.b["farm"] == 0
    assert not g.demolish_card(0, "S192", ("base", 1))[0]


def test_slot_change_while_queued_refunds_in_full():
    g = game()
    rr = own(g, "S192")
    rr.b.reset({})
    assert g.start_project(0, "S192", "build", "farm", slot=("base", 0))[0]
    p = rr.project
    g._fund_projects()
    paid = p.paid
    assert paid > 0
    rr.b.place("bank", 1, ("base", 0))                     # 그사이 다른 건물이 그 칸을 차지
    assert not g.project_ready("S192", p) and "다른 건물" in p.blocked_reason
    money = g.player.money
    p.progress = p.turns
    rr.project = None
    g._complete_project(g.player, rr, p)
    assert g.player.money == pytest.approx(money + paid)


def test_buildings_pickle_and_copy_keep_slots():
    g = game()
    b = g.regions["S192"].b
    g2 = pickle.loads(pickle.dumps(g))
    b2 = g2.regions["S192"].b
    assert isinstance(b2, S.Buildings) and b2.slots == b.slots and dict(b2) == dict(b)
    import copy
    b3 = copy.deepcopy(b)
    assert b3.slots == b.slots and b3.slots is not b.slots


def test_no_free_slot_means_no_silent_growth():
    g = game()
    b = g.regions["S001"].b                                # 송파: 기본 2칸 꽉 참
    assert not b.empty("base")
    b["factory"] = 3
    assert b["factory"] == 0 and len(b.slots["base"]) == 2


def test_ai_turns_keep_slot_invariants():
    g = Game(Settings(mode="standard", n_enemies=3, seed=11, all_ai=True))
    for _ in range(12):
        g.end_turn()
    for rid, r in g.regions.items():
        assert {t: len(v) for t, v in r.b.slots.items()} == S.capacity(g.world, rid)
        for key in S.UNIQUE_KEYS:
            assert r.b.count(key) <= 1
        for key in S.CARD_KEYS:
            assert r.b[key] == max(r.b.levels(key), default=0)


# ------------------------------------------------------------------ 화면
def test_slot_cards_render_and_empty_slot_opens_filtered_action_tab(monkeypatch, tmp_path):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from korciv.ui import app as appmod, slot_cards as SC, theme
    monkeypatch.setattr(appmod, "PREFS_PATH", str(tmp_path / "prefs.json"))
    theme._fonts.clear()
    theme._text_cache.clear()
    app = appmod.App(width=1280, height=800)
    try:
        app.start_game(Settings(seed=4, n_enemies=1, mode="standard", player_start="S192"))
        app.game.set_player_government("presidential")
        app.scene = "main"
        g = app.game
        rid = g.player.capital
        rr = g.regions[rid]
        first_empty = next(k for k, (t, i, c) in enumerate(g.slot_summary(rid)) if c is None)
        assert rr.b.empty("base")
        app.select(rid)
        app.left_open, app.left_tab, app.tab = True, "region", "info"
        app.gui.begin([])
        app.frame()
        # 빈 슬롯 카드를 누르면 행동 탭으로 가고 그 슬롯 종류 건물만
        x, y, w = 20, 120, 330
        n = SC.columns(w)
        cw = (w - SC.GAP * (n - 1)) / n
        cx = x + (first_empty % n) * (cw + SC.GAP) + cw / 2
        cy = y + (first_empty // n) * (SC.CARD_H + SC.GAP) + SC.CARD_H / 2
        app.gui.begin([])
        app.gui.mouse = (int(cx), int(cy))
        app.gui.clicked = True
        SC.draw_slot_grid(app, x, y, w, rid, mine=True)
        assert app.tab == "action" and app.slot_filter == (rid, "base")
        app.gui.begin([])
        app.frame()
        chips = SC.resource_chips(app, rid) + SC.facility_chips(app, rid)
        assert any(c.startswith("발전원(수력)") for c in chips)
        assert any(c.startswith("특산물: ") and "시설" in c for c in chips)
        assert any(c.startswith("방어선") for c in chips)
        for dark in (True, False):
            app.theme.set_dark(dark)
            assert SC.slot_colors(app.theme, "base")["accent"] == (201, 42, 42)
            app.tab = "info"
            app.gui.begin([])
            app.frame()
    finally:
        theme._fonts.clear()
        theme._text_cache.clear()
        pygame.quit()
