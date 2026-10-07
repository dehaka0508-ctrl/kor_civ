"""pygame 화면을 창 없이(dummy 드라이버) 그려 보는 스모크 테스트."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from korciv.state import NEUTRAL, Settings  # noqa: E402
from korciv.ui.app import MAP_MODES, App  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = App()
    yield a
    pygame.quit()


def frame(app):
    app.gui.begin([])
    app.frame()


def test_screens_render(app):
    frame(app)  # 설정 화면
    app.scene = "pick_start"
    frame(app)
    app.start_game(Settings(seed=4, n_enemies=3))
    frame(app)  # 정치체제
    app.game.set_player_government("presidential")
    app.scene = "main"
    g = app.game
    for _ in range(5):
        g.pending_rebellions.clear()
        g.pending_proposals.clear()
        app.end_turn()
    g.pending_proposals.clear()
    app.modal = None
    app.select(g.player.capital)
    for tab in ("action", "army", "nation"):
        app.tab = tab
        frame(app)
    for key, _ in MAP_MODES:
        app.mode = key
        app.changed()
        frame(app)
    other = next(f.id for f in g.factions if f.id != g.player_id)
    app.open_diplomacy(other)
    frame(app)
    for m in (("help", None), ("log", None), ("gameover", None)):
        app.modal = m
        frame(app)
    app.modal = None
    g.pending_rebellions.append(g.player.capital)
    frame(app)
    g.pending_rebellions.clear()
    g.pending_proposals.append({"from": other, "kind": "nonaggr"})
    frame(app)
    g.pending_proposals.clear()
    app.select("SEA2")
    frame(app)


def test_map_pick(app):
    mv = app.map
    mv.z = 3
    mv.center_on("S002")
    x, y = mv.label_screen("S002")
    assert mv.pick((int(x), int(y))) == "S002"


def test_tax_slider_release_commits(app):
    from korciv.state import Settings
    app.start_game(Settings(seed=5, n_enemies=1))
    app.game.set_player_government("presidential")
    app.scene = "main"
    from korciv.ui import panels
    from korciv.ui.app import LEFT_W
    app.left_open, app.left_tab = True, "nation"
    gui = app.gui
    orig = pygame.mouse.get_pos
    try:
        # 슬라이더 위치: 좌측 세로 탭 옆 [국가] 패널 첫 줄 (논리 좌표 → 실제 픽셀)
        x0 = 8 + panels.RAIL_W + 6 + 14 + 40
        wdt = LEFT_W - 28 - 122
        y = 56 + 12 + 46 + 26 + 4 + 10
        u = gui.u
        def at(lx):
            p = (int(lx * u), int(y * u))
            pygame.mouse.get_pos = lambda: p
            return p
        at(x0 + wdt * 0.1)
        gui.begin([]); app.frame()
        p = at(x0 + wdt * 0.1)
        gui.begin([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=p)]); app.frame()
        p = at(x0 + wdt * 0.6)
        gui.begin([]); app.frame()
        gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=p)]); app.frame()
        assert app.game.player.tax == pytest.approx(0.30, abs=0.02)
    finally:
        pygame.mouse.get_pos = orig


def test_enter_ends_turn_after_setup_text_focus(app):
    """시작 화면 입력칸에 포커스가 남은 채 게임을 시작해도 Enter로 턴이 넘어간다."""
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r", scancode=40)
    app.game = None
    app.scene = "setup"
    frame(app)
    app.gui.focus = "name"
    frame(app)
    assert app.gui.focus == "name"               # 그려지는 동안은 유지
    app.start_game(Settings(seed=4, n_enemies=3))
    frame(app)
    app.game.set_player_government("presidential")
    app.scene = "main"
    t0 = app.game.turn
    for _ in range(6):
        app.game.pending_proposals.clear()
        app.game.pending_rebellions.clear()
        app.modal = None
        app.gui.begin([enter])
        app.frame()
    assert app.gui.focus is None
    assert app.game.turn > t0


def test_priority_arrow_keys_reorder(app):
    """지출 우선순위에서 고른 행을 ↓로 옮긴다(시작 화면 입력칸 포커스가 남아 있어도)."""
    down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, mod=0, unicode="", scancode=81)
    app.start_game(Settings(seed=4, n_enemies=3))
    frame(app)
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    pid = g.player_id
    near = sorted(g.world.land_adj[g.player.capital])[:2]
    for r in near:
        g.transfer_region(r, pid)
    for r in [g.player.capital] + near:
        assert g.start_project(pid, r, "build", "farm")[0]
    app.left_open, app.left_tab = True, "nation"           # 지출 우선순위는 [내정] 탭
    frame(app)
    ids = [r.id for r in g.projects_by_priority(pid)]
    app.prio_sel = ids[0]
    app.gui.focus = "name"                       # 시작 화면에서 남은 포커스
    app.gui.begin([down])
    app.frame()
    assert [r.id for r in g.projects_by_priority(pid)] == [ids[1], ids[0]] + ids[2:]


def test_reselect_region_closes_panel(app):
    g = app.game
    cap = g.player.capital
    app.left_open = False
    app.select(cap)
    assert app.left_open and app.left_tab == "region"
    sel = app.sel_army
    app.select(cap)                       # 같은 지역 다시 클릭 → 닫힘, 부대 선택은 그대로
    assert not app.left_open and app.sel_army == sel
    app.left_tab, app.tab, app.left_open = "army", "action", True
    frame(app)                            # 군사 요약
    app.left_tab, app.tab = "region", "army"
    frame(app)                            # 지역 부대 탭


def test_flags_and_diplo_detail(app):
    from korciv import flags as FL
    from korciv.ui import modals
    from korciv.ui.art import render_flag
    for bg in FL.BG_KEYS:                 # 모든 배경·문양 조합이 그려진다
        for em in FL.EMBLEM_KEYS:
            surf = render_flag({"bg": bg, "em": em, "c1": (10, 20, 30), "c2": (200, 0, 0), "ec": (255, 255, 0)}, 30, 20)
            assert surf.get_size() == (30, 20)
    assert len(FL.EMBLEMS) == 24 and len(FL.BACKGROUNDS) == 10
    for pk in FL.PRESET_KEYS:             # 역사 국기(이미지·그림)
        assert render_flag({"preset": pk}, 30, 20).get_size() == (30, 20)
    assert FL.normalize({"bg": "nordic", "em": "star6"}) ["bg"] == "cross"   # 예전 저장 키
    assert FL.normalize({"em": "bolt"})["em"] == "cloud"
    # 단색 배경은 배경 색 2, 한 색 문양은 문양 색 2를 쓰지 않는다
    assert not FL.uses_c2({"bg": "solid"}) and FL.uses_c2({"bg": "h2"})
    assert FL.uses_ec2({"em": "taegeuk"}) and FL.uses_ec2({"em": "flower"}) and not FL.uses_ec2({"em": "star5"})
    a = render_flag({"em": "taegeuk", "ec": (255, 0, 0), "ec2": (0, 0, 255)}, 60, 40)
    b = render_flag({"em": "taegeuk", "ec": (255, 0, 0), "ec2": (0, 255, 0)}, 60, 40)
    assert a.get_at((30, 26)) != b.get_at((30, 26))   # 문양 색 2가 태극 아래쪽 색
    a = FL.default_flag("#3366cc", "1:x")
    assert a == FL.default_flag("#3366cc", "1:x")   # 기본 국기는 결정적
    s = app.setup
    s.flag_draft = dict(s.flag)
    app.scene = "setup"
    frame(app)                            # 국기 편집 창
    s.flag_draft["em"] = "taegeuk"
    s.flag = FL.normalize(s.flag_draft)
    s.flag_draft = None
    modals.start_from_setup(app)
    assert app.game.player.flag["em"] == "taegeuk"
    app.game.set_player_government("presidential")
    app.scene = "main"
    app.game.pending_proposals.clear()
    app.left_open, app.left_tab = True, "diplo"
    frame(app)
    other = next(f.id for f in app.game.factions if f.id != app.game.player_id)
    app.dip_view = other
    frame(app)
    app.dip_view = None


def test_click_foreign_region_by_visibility(app):
    app.start_game(Settings(seed=5, n_enemies=3, fog=1))
    g = app.game
    g.set_player_government("presidential")
    app.scene = "main"
    app.modal = None
    g.pending_proposals.clear()
    pid = g.player_id
    other = next(f for f in g.factions if f.id != pid)
    cap = other.capital
    assert not g.is_visible(pid, cap) and g.is_explored(pid, cap)
    app.sel, app.left_open = None, False
    app.select(cap)                       # 시야 밖 타국 영토 → 외교 탭 세력 상세
    assert app.left_open and app.left_tab == "diplo" and app.dip_view == other.id
    frame(app)
    app.select(cap)                       # 다시 누르면 닫힘
    assert not app.left_open
    g.new_army(pid, cap, {"inf": 1})      # 시야 확보 → 지역 현황
    g._visible = {}
    assert g.is_visible(pid, cap)
    app.sel = None
    app.select(cap)
    assert app.left_tab == "region" and app.tab == "info"
    frame(app)
    neutral = next(rid for rid, r in g.regions.items() if r.owner == NEUTRAL and not g.is_visible(pid, rid))
    app.select(neutral)                   # 중립은 현행대로 지역 정보
    assert app.left_tab == "region" and app.tab == "info"
    frame(app)


def test_arrow_key_hold_pans(app, monkeypatch):
    """방향키를 누르고 있으면 프레임마다 지도가 계속 움직인다."""
    app.start_game(Settings(seed=4, n_enemies=3))
    app.game.set_player_government("presidential")
    app.scene, app.modal = "main", None
    app.game.pending_proposals.clear()
    app.gui.focus = None
    held = {pygame.K_RIGHT}

    class Pressed:
        def __getitem__(self, k):
            return k in held
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: Pressed())
    t = [1000]
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: t[0])
    app.arrow_pan()
    x0 = app.map.cx
    for _ in range(5):
        t[0] += 16
        app.arrow_pan()
    assert app.map.cx > x0                 # 오른쪽 키: 지도 중심이 오른쪽(동쪽)으로
    held.clear()
    x1 = app.map.cx
    t[0] += 16
    app.arrow_pan()
    assert app.map.cx == x1                # 떼면 멈춘다


def test_ai_flag_rules():
    from korciv import flags as FL
    for i in range(500):
        f = FL.default_flag("#c0392b", i)
        assert "preset" not in f                       # 역사 국기는 플레이어 전용
        if f["bg"] in ("solid", "border"):
            assert f["em"] != "none" and f["ec"] == (255, 255, 255)
            if f["em"] == "flower":
                assert f["ec2"] == f["c1"]
            if f["em"] == "yinyang":
                assert f["ec2"] == (0, 0, 0)
        else:
            assert f["em"] == "none"
        if f["bg"] != "solid":
            assert f["c2"] == (255, 255, 255)


def test_random_flag_follows_ai_rules():
    import random as _r
    from korciv import flags as FL
    rng = _r.Random(1)
    for _ in range(200):
        f = FL.random_flag(rng)
        assert "preset" not in f and f["c2"] == (255, 255, 255)
        assert (f["em"] != "none") == (f["bg"] in ("solid", "border"))


def test_save_version_and_slot_visibility(app, tmp_path, monkeypatch):
    """세이브에는 버전이 적히고, 버전이 없거나 주·부 버전이 다른 세이브는 [이어하기]에 보이지 않는다."""
    import pickle
    from korciv import version as V
    from korciv.ui import app as appmod
    monkeypatch.setattr(appmod, "SAVE_DIR", str(tmp_path))
    app.start_game(Settings(seed=4, n_enemies=1))
    assert app.save("slot1")
    with open(tmp_path / "slot1.sav", "rb") as f:
        assert pickle.load(f)["version"] == V.VERSION
    assert app.slot_info(1) is not None
    with open(tmp_path / "slot2.sav", "wb") as f:          # 버전 표기 없는 예전 형식
        pickle.dump(app.game, f)
    assert app.slot_info(2) is None
    major, minor, patch = V.parse(V.VERSION)
    with open(tmp_path / "slot3.sav", "wb") as f:          # 내용 패치(부 버전)가 다름
        pickle.dump({"version": f"{major}.{minor + 1}.0", "game": app.game}, f)
    assert app.slot_info(3) is None
    with open(tmp_path / "slot3.sav", "wb") as f:          # 수 버전만 다르면 이어서 가능
        pickle.dump({"version": f"{major}.{minor}.{patch + 5}", "game": app.game}, f)
    assert app.slot_info(3) is not None
    app.game = None
    app.load("slot2")
    assert app.game is None                                 # 불러오기도 거부
    app.load("slot1")
    assert app.game is not None
    app.game, app.scene = None, "title"
    frame(app)                                              # 시작 화면 버전 표시


def test_random_flag_ec2_not_white():
    """무작위 국기의 문양 색 2는 흰색으로 고정되지 않는다(두 색 문양으로 바꿔도 보이게)."""
    import random as _r
    from korciv import flags as FL
    rng = _r.Random(5)
    for _ in range(200):
        f = FL.random_flag(rng)
        assert f["ec2"] != (255, 255, 255)


def test_unmet_factions_hidden_under_fog(app):
    """안개 '미탐색'에서 조우하지 않은 국가는 '미지의 국가'·'수수께끼의 지도자'로만 보인다."""
    app.start_game(Settings(seed=7, n_enemies=6, fog=2))
    g = app.game
    g.set_player_government("presidential")
    app.scene, app.modal = "main", None
    g.pending_proposals.clear()
    pid = g.player_id
    unmet = [f for f in g.factions if f.id != pid and not g.has_met(pid, f.id)]
    assert unmet, "시작하자마자 모두 만난 상태면 안 된다"
    o = unmet[0]
    assert g.seen_name(o.id) == "미지의 국가" and g.seen_leader(o.id) == "수수께끼의 지도자"
    # 조우 판정: 그 세력 영토가 시야에 들어오면 만난 것
    g.new_army(pid, o.capital, {"inf": 1})
    g._update_fog()
    assert g.has_met(pid, o.id) and g.seen_name(o.id) == o.name
    # 이벤트 문장 가리기
    other = next(f for f in unmet[1:] if not g.has_met(pid, f.id))
    e = {"turn": 1, "kind": "war", "text": f"{other.name}이(가) {g.player.name}에 선전포고", "fids": (other.id, pid)}
    assert other.name not in g.event_for_player(e) and "미지의 국가" in g.event_for_player(e)
    e2 = {"turn": 1, "kind": "war", "text": "x", "fids": (other.id, o.id)}
    assert g.event_for_player(e2) is None
    app.left_open, app.left_tab, app.dip_view = True, "diplo", None
    frame(app)
    app.dip_view = other.id
    frame(app)
    app.modal = ("log", None)
    frame(app)
    app.modal = None
    # 안개가 없으면 모두 안다
    app.start_game(Settings(seed=7, n_enemies=3, fog=0))
    assert all(app.game.has_met(app.game.player_id, f.id) for f in app.game.factions)


def test_ai_leader_picker_and_fog_name_rules(app):
    from korciv.ui import modals
    s = modals.SetupState()
    s.leader, s.n_enemies, s.ai_leaders = "sej", 3, ["yis", None, None]
    app.setup, app.scene, app.game = s, "setup", None
    s.ai_pick = 1
    frame(app)                                   # 고르기 창
    assert s.ai_pick == 1
    s.ai_pick = None
    frame(app)
    # 안개 '지도 공개'는 국가명·수도는 알고 지도자는 모른다, '미탐색'은 둘 다 모른다
    for fog, name_known in ((1, True), (2, False)):
        app.start_game(Settings(seed=7, n_enemies=6, fog=fog))
        g = app.game
        o = next(f for f in g.factions if f.id != g.player_id and not g.has_met(g.player_id, f.id))
        assert (g.seen_name(o.id) == o.name) == name_known
        assert g.seen_leader(o.id) == "수수께끼의 지도자"


def test_portrait_codes():
    """지도자 키는 서로 다른 3글자이고, 올려 둔 이미지가 그 이름으로 불린다."""
    from korciv.leaders import LEADERS
    from korciv.ui.art import portrait_path
    keys = [l["key"] for l in LEADERS]
    assert len(keys) == len(set(keys)) and all(len(k) == 3 and k.islower() for k in keys)
    for key in ("dan", "jum", "onz"):
        p = portrait_path(key)
        assert p and os.path.basename(p).startswith(key + ".")
