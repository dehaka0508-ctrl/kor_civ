"""시작 정책 카드, 분리된 기술·군사 탭, 상단 잔고, 클릭한 슬롯 아래 메뉴의 실제 화면 검증."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from korciv.state import Settings
from korciv.ui.app import App
from korciv.ui import slot_cards as SC
from korciv.ui.panels import SIDE_TABS


@pytest.fixture
def app(monkeypatch, tmp_path):
    from korciv.ui import app as appmod
    monkeypatch.setattr(appmod, "PREFS_PATH", str(tmp_path / "prefs.json"))
    instance = App(width=1280, height=800)
    instance.start_game(Settings(seed=81, mode="frontier", n_enemies=1,
                                 player_start="S002", player_leader="cus"))
    yield instance
    pygame.quit()


def frame(app, events=()):
    app.gui.begin(list(events))
    app.frame()


def labels(app, monkeypatch):
    texts, buttons = [], []
    real_text, real_button = app.gui.text, app.gui.button

    def text(pos, value, *args, **kw):
        rect = real_text(pos, value, *args, **kw)
        texts.append((value, rect))
        return rect

    def button(rect, label, *args, **kw):
        buttons.append((label, pygame.Rect(rect), kw.get("enabled", True)))
        return real_button(rect, label, *args, **kw)

    monkeypatch.setattr(app.gui, "text", text)
    monkeypatch.setattr(app.gui, "button", button)
    return texts, buttons


def test_start_policy_cards_select_without_popup_or_resource_reset(app, monkeypatch):
    assert app.scene == "main" and app.left_tab == "policy" and app.progression_tab == "policy"
    assert {key for key, _, _ in SIDE_TABS} >= {"policy", "science"}
    assert "progression" not in {key for key, _, _ in SIDE_TABS}
    texts, buttons = labels(app, monkeypatch)
    frame(app)
    assert any(text == "정치체제를 고르세요" for text, _ in texts)
    assert not any("철인" in text for text, _ in texts)
    assert sum(label == "채택" for label, _, _ in buttons) == 6
    money, pop = app.game.player.money, app.game.regions[app.game.player.capital].pop
    rect = next(rect for label, rect, enabled in buttons if label == "채택" and enabled)
    pos = tuple(round(v * app.gui.u) for v in rect.center)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: pos)
    frame(app, [pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
    assert app.game.player.gov == "absolute" and app.scene == "main" and app.left_tab == "policy"
    assert app.game.player.money == money and app.game.regions[app.game.player.capital].pop == pop
    texts.clear()
    frame(app)
    assert any(text == "1. 왕실 직할령" for text, _ in texts)


def test_science_and_military_show_separate_research_lists(app, monkeypatch):
    texts, _ = labels(app, monkeypatch)
    app.left_tab, app.science_tab = "science", "tech"
    frame(app)
    assert any(text == "현대 농업" for text, _ in texts)
    assert not any(text == "기계화보병 편제" for text, _ in texts)
    texts.clear()
    app.science_tab = "military"
    frame(app)
    assert any(text == "기계화보병 편제" for text, _ in texts)
    assert not any(text == "현대 농업" for text, _ in texts)
    assert not app.gui._clip_stack


@pytest.mark.parametrize("size", [(800, 500), (1024, 768), (1280, 800), (1920, 1080)])
def test_topbar_combines_balance_and_rate_with_science_precision(app, monkeypatch, size):
    app.window = pygame.display.set_mode(size, pygame.RESIZABLE)
    app._update_scale()
    g = app.game
    g.player.money, g.player.admin, g.player.sci_points = 123456789, 12345.6789, 98765.4321
    g.player.last["net"] = -123456
    texts, _ = labels(app, monkeypatch)
    app.gui.begin([])
    app.draw_topbar()
    shown = dict(texts)
    assert "123,456,789(-123,456/턴)" in shown
    assert any(text.startswith("12,345.68(") for text in shown)
    assert any(text.startswith("98,765.43(+") for text in shown)
    assert "턴당 순수익" not in shown
    for text, rect in texts:
        if "/턴)" in text:
            assert rect.left >= 650 and rect.right <= app.lsize()[0] - 14 and rect.bottom <= 50
        if text.startswith(("행복도 ", "전쟁 피로 ", "세율 ", "식량 ")):
            assert rect.left >= 650
    assert g.player.sci_points == 98765.4321


def test_slot_menu_opens_immediately_below_clicked_row(app, monkeypatch):
    g = app.game
    rid = g.player.capital
    app.select(rid)
    boxes, menus = [], []
    real_grid, real_menu = SC.draw_slot_grid, SC.draw_slot_panel

    def grid(instance, x, y, w, region, **kw):
        _, _, cells = SC._cells(instance, region)
        layout, _ = SC.grid_layout(cells, x, y, w)
        boxes[:] = layout
        return real_grid(instance, x, y, w, region, **kw)

    def menu(instance, x, y, w, region, slot, opts):
        menus.append(pygame.Rect(x, y, w, SC.slot_panel_height(instance, region, slot, opts)))
        return real_menu(instance, x, y, w, region, slot, opts)

    monkeypatch.setattr(SC, "draw_slot_grid", grid)
    monkeypatch.setattr(SC, "draw_slot_panel", menu)
    frame(app)
    rect = next(rect for slot, rect in boxes if slot == ("base", 0))
    pos = tuple(round(v * app.gui.u) for v in rect.center)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: pos)
    frame(app, [pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)])
    frame(app)
    picked = next(rect for slot, rect in boxes if slot == ("base", 0))
    assert app.slot_sel == (rid, "base", 0)
    assert menus[-1].top == picked.bottom + SC.GAP
    assert menus[-1].top < 500
    assert not app.gui._clip_stack


def test_expansion_moves_only_rows_after_selected_slot():
    cells = [("base", i) for i in range(6)] + [("river", 0), ("coast", 0)]
    before, end_before = SC.grid_layout(cells, 0, 0, 360)
    after, end_after, menu = SC.expanded_layout(cells, 0, 0, 360, ("base", 1), 300)
    assert menu.top == SC.CARD_H + SC.GAP
    old = dict(before)
    for key, rect in after:
        assert rect.y == old[key].y + (300 + SC.GAP if old[key].y > 0 else 0)
    assert end_after == end_before + 300 + SC.GAP
