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
    app.left_open, app.left_tab = True, "status"
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
