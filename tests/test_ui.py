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
    app.tab = "nation"
    app.left_open = False
    gui = app.gui
    orig = pygame.mouse.get_pos
    try:
        # 슬라이더 위치: 우측 패널 국가 탭 첫 줄 (논리 좌표 → 실제 픽셀)
        sw, sh = app.lsize()
        x0 = sw - 320 - 12 + 14 + 40
        wdt = 320 - 28 - 122
        y = 56 + 12 + 52 + 26 + 4 + 10
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
