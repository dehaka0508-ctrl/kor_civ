"""pygame 화면을 창 없이(dummy 드라이버) 그려 보는 스모크 테스트."""
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from korciv.state import Settings  # noqa: E402
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
