"""국왕 진상은 화면에 표시되고 수동 배분으로 해제할 수 없다."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from korciv.state import Settings
from korciv.ui import app as appmod


def test_long_great_person_label_renders_once_and_preserves_tooltip(monkeypatch):
    from korciv.ui import gui as G, theme
    pygame.font.init()
    theme._fonts.clear()
    theme._text_cache.clear()
    try:
        gui = G.Gui(pygame.Surface((800, 600)), theme.Theme())
        gui.mouse = (12, 12)
        label = " · ".join(["위대한 장군 을지문덕", "위대한 과학자 장영실", "위대한 재상 서희"] * 20)
        calls = []
        original = G.render_text

        def render(text, *args):
            calls.append(text)
            return original(text, *args)

        monkeypatch.setattr(G, "render_text", render)
        rect = gui.text((10, 10), label, max_w=240)
        assert len(calls) == 1 and calls[0].endswith("…")
        assert rect.w <= 240 and gui.tooltip == label
    finally:
        theme._fonts.clear()
        theme._text_cache.clear()
        pygame.quit()


def test_royal_tithe_is_visible_and_read_only(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "PREFS_PATH", str(tmp_path / "prefs.json"))
    app = appmod.App(width=1280, height=800)
    try:
        app.start_game(Settings(seed=61, player_start="S002", n_enemies=1, player_leader="sej"))
        g = app.game
        g.set_player_government("philosopher")
        sites = [r for r in g.world.order if g.info(r).specialties and g.regions[r].owner == -1][:3]
        for rid in sites:
            g.transfer_region(rid, 0, reason="편입")
            g.regions[rid].b["specialty"] = 5
        g.player.specialty = g.specialty_made(g.player)
        texts = []
        original = app.gui.text

        def text(pos, value, *args, **kwargs):
            texts.append(str(value))
            return original(pos, value, *args, **kwargs)

        monkeypatch.setattr(app.gui, "text", text)
        app.scene, app.modal, app.spec_sel = "main", ("specialty", None), sites[0]
        app.gui.begin([])
        app.frame()
        assert any("국왕 진상" in t and "수정 불가" in t for t in texts)
        assert g.player.last["specialty_tithe"] > 0
        before = dict(g.specialty_made(g.player))
        assert not g.set_specialty(0, sites[0], "국왕 진상", "block")[0]
        assert g.specialty_made(g.player) == before
        assert not app.gui._clip_stack
    finally:
        from korciv.ui import theme
        theme._fonts.clear()
        theme._text_cache.clear()
        pygame.quit()
