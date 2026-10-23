"""정책·기술·위인 화면의 실제 클릭과 네 가지 지도 배지 검증."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from korciv.state import Settings
from korciv.ui.app import App
from korciv.ui.progression import great_person_badge


def test_progression_panel_clicks_spend_and_unlock(monkeypatch, tmp_path):
    from korciv.ui import app as appmod
    monkeypatch.setattr(appmod, "PREFS_PATH", str(tmp_path / "prefs.json"))
    app = App(width=1280, height=800)
    try:
        app.start_game(Settings(seed=41, player_start="S002", n_enemies=1, player_leader="cus"))
        g = app.game
        g.set_player_government("presidential")
        g.player.admin = g.player.sci_points = 10000
        g.regions[g.player.capital].b.update(admin=4, edu=4, academy=1, specialty=3)
        app.select(g.player.capital)
        app.scene, app.modal = "main", None
        app.left_open, app.left_tab = True, "policy"
        buttons = []
        real_button = app.gui.button

        def collect(rect, label, *args, **kwargs):
            if kwargs.get("enabled", True):
                buttons.append((label, pygame.Rect(rect)))
            return real_button(rect, label, *args, **kwargs)

        monkeypatch.setattr(app.gui, "button", collect)

        def click(tab, label):
            buttons.clear()
            app.left_tab = "science" if tab == "military" else "policy"
            app.science_tab = "military"
            app.progression_tab = tab
            app.gui.begin([])
            app.frame()
            rect = next(rect for text, rect in buttons if text == label)
            pos = tuple(int(v * app.gui.u) for v in rect.center)
            monkeypatch.setattr(pygame.mouse, "get_pos", lambda: pos)
            app.gui.begin([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
            app.frame()

        click("policy", "해금")
        assert g.player.policy_level == 1 and g.player.admin == 9900
        click("military", "해금")
        assert "inf" in g.player.techs and g.player.sci_points == 9200
        click("people", "초빙")
        assert g.great_people[0]["kind"] == "scientist"
        assert g.player.sci_points == 8600
        assert not app.gui._clip_stack
    finally:
        pygame.quit()


def test_four_badges_have_distinct_vector_icons():
    images = set()
    for kind in ("scientist", "chancellor", "general", "artist"):
        surface = pygame.Surface((40, 40))
        surface.fill((0, 0, 0))
        rect = great_person_badge(surface, kind, (20, 20), (30, 60, 120), u=1.5)
        assert rect.width == 2 * int(9 * 1.5) + 1
        images.add(pygame.image.tobytes(surface, "RGB"))
    assert len(images) == 4
