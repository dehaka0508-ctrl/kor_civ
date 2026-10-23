"""상단 우측 자원 표시(v1.3.14): 왼쪽부터 자금·식량·행정력·과학력·세율·전쟁 피로·행복도.
항목마다 아이콘 하나 + 값(위) + 이름(아래). 자금·행정력·과학력은 잔고와 턴당 변화를 한 값으로 보인다."""
from __future__ import annotations

import pygame

from .. import config as C, diplomacy as D
from ..text import fmt_points
from .theme import measure, mix

LEFT_X = 650          # 날짜·절기 오른쪽부터 쓴다
ICON_W = 22           # 아이콘 칸 폭(값·이름은 그 오른쪽)
GAP = 10


def happy_face(v) -> str:
    """행복도 아이콘: +10 초과 웃음, −10 미만 슬픔, 그 사이 무표정."""
    return "face_happy" if v > 10 else "face_sad" if v < -10 else "face_neutral"


def resource_items(g, snap, good, bad):
    """(키, 아이콘, 이름, 값, 값 색 또는 None, 툴팁) — 왼쪽부터 놓을 순서."""
    f, last = g.player, g.player.last
    return [
        ("money", "coin", "자금(만원)", f"{snap['money']:,.0f}({snap['net']:+,.0f}/턴)",
         bad if snap["money"] < 0 else None,
         f"세수 {last.get('tax', 0):,.0f} / 유지비 −{last.get('upkeep', 0):,.0f}\n"
         f"구매 −{last.get('buy', 0):,.0f} / 판매 +{last.get('sell', 0):,.0f}\n"
         f"지난 턴 순수익 {snap['net']:+,.0f} · 진행 중 작업 {sum(p.per_turn for p in g.unique_projects(g.regions_of(f.id))):,.0f}/턴"),
        ("food", "rice", "식량", f"{snap['food']:,.0f}", None,
         f"생산 {last.get('food_prod', 0):,.0f} / 소비 {last.get('food_cons', 0):,.0f}"
         + (f"\n기근 {last.get('famine', 0) * 100:.0f}%" if last.get("famine") else "")),
        ("admin", "seal", "행정력", f"{fmt_points(snap['admin'])}({fmt_points(snap['admin_net'], signed=True)}/턴)",
         bad if snap["admin_net"] < 0 else None,
         f"생산 {fmt_points(snap['admin_prod'])} / 소비 {fmt_points(snap['admin_cons'])}\n정책·위인에 사용합니다."),
        ("science", "flask", "과학력", f"{fmt_points(snap['science'])}(+{fmt_points(snap['science_prod'])}/턴)", None,
         f"과학력 생산 {fmt_points(snap['science_prod'])}/턴\n연구·위인·과학승리 공사에 사용합니다."),
        ("tax", "tax", "세율", f"{snap['tax']}%", None,
         f"세율 {f.tax * 100:.0f}% · 세수 {last.get('tax', 0):,.0f}/턴\n"
         f"세율 효과 행복도 {g.tax_happy(f.id, f.tax * 100):+.1f}/턴"),
        ("weary", "swords", "전쟁 피로", f"{snap['weary']:d}", bad if f.war_weary >= 1 else None,
         f"전쟁 피로 {f.war_weary:.1f}/{C.WAR_WEARY_MAX:.0f}: 모든 지역 실질 행복도에서 빠집니다.\n"
         + (f"전쟁 중 턴당 +{D.war_weary_rate(g, f.id):.1f}" if D.enemies(g, f.id)
            else f"평시 턴당 {C.WAR_WEARY_RECOVERY:.0f} 회복")),
        ("happy", happy_face(snap["happy"]), "행복도", f"{snap['happy']:+d}", bad if snap["happy"] < 0 else None,
         f"실질 평균 행복도 {g.avg_happiness(f.id):+.1f} "
         f"(피로·저항 반영 전 {g.avg_happiness(f.id, effective=False):+.1f})"),
    ]


def _widths(items, size, label_size, icon_w):
    return [icon_w + max(measure(val, size, "semibold")[0], measure(label, label_size, "semibold")[0]) + 4
            for _, _, label, val, _, _ in items]


def _layouts():
    """넓은 것부터: (값 글자, 이름 글자, 아이콘 칸, 간격). 큰 숫자·좁은 창이면 차례로 줄인다."""
    for size in range(15, 8, -1):
        yield size, 10, ICON_W, GAP
    for gap in range(GAP - 2, 3, -2):
        yield 9, 10, ICON_W, gap
    yield 9, 9, 17, 4
    yield 8, 9, 16, 4


def draw_resources(app, sw, paper, dim, good, bad):
    from .art import ui_icon
    gui, g, t = app.gui, app.game, app.theme
    u = gui.u
    snap = app.snapshot()
    items = resource_items(g, snap, good, bad)
    available = sw - 14 - LEFT_X
    for size, label_size, icon_w, gap in _layouts():
        widths = _widths(items, size, label_size, icon_w)
        if sum(widths) + gap * (len(items) - 1) <= available:
            break
    x = sw - 14 - sum(widths) - gap * (len(items) - 1)
    highlight = pygame.time.get_ticks() - app.prev_t < 600
    ik = 0.85 * u * min(1.0, (size + 3) / 18, icon_w / ICON_W)
    for (key, icon, label, val, col, tip), width in zip(items, widths):
        box = pygame.Rect(int(x), 6, int(width), 42)
        previous = app.prev_values.get(key)
        if highlight and previous is not None and app._differs(previous, snap[key]):
            gui.rect(mix(t.gold, t.indigo, .35), box, radius=4)
        ui_icon(app.screen, icon, gui.P(box.x + icon_w / 2 - 1, box.y + 14), t.gold_lt, ik)
        gui.text((box.x + icon_w, box.y + 2), val, size, col or paper, "semibold")
        gui.text((box.x + icon_w, box.bottom - 2), label, label_size, dim, "semibold", anchor="bottomleft")
        if gui.hover(box):
            gui.tooltip = tip
        x += width + gap
