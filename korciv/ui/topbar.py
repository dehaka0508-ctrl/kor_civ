"""상단 우측: 잔고와 턴당 변화를 한 항목에, 세 자원을 항상 함께 표시한다."""
from __future__ import annotations

import pygame

from .. import config as C, diplomacy as D
from ..text import fmt_points
from .theme import measure, mix


def resource_items(g, snap):
    f, last = g.player, g.player.last
    return [
        ("science", "과학력", f"{fmt_points(snap['science'])}(+{fmt_points(snap['science_prod'])}/턴)",
         f"과학력 생산 {fmt_points(snap['science_prod'])}/턴\n연구·위인·과학승리 공사에 사용합니다."),
        ("admin", "행정력", f"{fmt_points(snap['admin'])}({fmt_points(snap['admin_net'], signed=True)}/턴)",
         f"생산 {fmt_points(snap['admin_prod'])} / 소비 {fmt_points(snap['admin_cons'])}\n정책·위인에 사용합니다."),
        ("money", "자금(만원)", f"{snap['money']:,.0f}({snap['net']:+,.0f}/턴)",
         f"세수 {last.get('tax', 0):,.0f} / 유지비 −{last.get('upkeep', 0):,.0f}\n"
         f"구매 −{last.get('buy', 0):,.0f} / 판매 +{last.get('sell', 0):,.0f}\n"
         f"지난 턴 순수익 {snap['net']:+,.0f} · 진행 중 작업 {sum(p.per_turn for p in g.unique_projects(g.regions_of(f.id))):,.0f}/턴"),
    ]


def draw_resources(app, sw, paper, dim, good, bad):
    gui, g, t = app.gui, app.game, app.theme
    f, snap = g.player, app.snapshot()
    items = resource_items(g, snap)
    available = sw - 14 - 650
    aux_w, gap = 174, 10
    size = 14
    while size > 9 and sum(max(measure(val, size, 'semibold')[0], 44) + 8 for _, _, val, _ in items) + aux_w + 3 * gap > available:
        size -= 1
    widths = [max(measure(val, size, 'semibold')[0], 44) + 8 for _, _, val, _ in items]
    x = sw - 14 - sum(widths) - 2 * gap
    highlight = pygame.time.get_ticks() - app.prev_t < 600
    for (key, label, val, tip), width in zip(items, widths):
        box = pygame.Rect(x, 5, width, 44)
        previous = app.prev_values.get(key)
        if highlight and previous is not None and app._differs(previous, snap[key]):
            gui.rect(mix(t.gold, t.indigo, .35), box, radius=4)
        negative = (key == 'money' and snap['money'] < 0) or (key == 'admin' and snap['admin_net'] < 0)
        gui.text((x + 4, 7), val, size, bad if negative else paper, 'semibold')
        gui.text((x + 4, 34), label, 10, dim, 'semibold')
        if gui.hover(box):
            gui.tooltip = tip
        x += width + gap
    # 자금의 별도 순수익 항목을 없애고, 보조 통계 네 개는 두 줄로 배치한다.
    aux_x = sw - 14 - sum(widths) - 3 * gap - aux_w
    auxiliary = [
        ('happy', '행복도', f"{snap['happy']:+d}", f"실질 평균 행복도 {g.avg_happiness(f.id):+.1f}"),
        ('weary', '전쟁 피로', f"{snap['weary']:d}", f"전쟁 피로 {f.war_weary:.1f}/{C.WAR_WEARY_MAX:.0f}\n"
         + (f"전쟁 중 턴당 +{D.war_weary_rate(g, f.id):.1f}" if D.enemies(g, f.id) else f"평시 턴당 {C.WAR_WEARY_RECOVERY:.0f} 회복")),
        ('tax', '세율', f"{snap['tax']}%", f"세율 효과 행복도 {g.tax_happy(f.id, f.tax * 100):+.1f}/턴"),
        ('food', '식량', f"{snap['food']:,.0f}", f"생산 {f.last.get('food_prod', 0):,.0f} / 소비 {f.last.get('food_cons', 0):,.0f}"),
    ]
    for i, (key, label, value, tip) in enumerate(auxiliary):
        box = pygame.Rect(aux_x + (i % 2) * (aux_w // 2), 5 + (i // 2) * 23, aux_w // 2, 22)
        text = label + ' ' + value
        font = 11
        while font > 8 and measure(text, font, 'semibold')[0] > box.w - 3:
            font -= 1
        gui.text((box.x, box.y + 2), text, font, bad if key == 'happy' and snap[key] < 0 else dim,
                 'semibold', max_w=box.w - 3)
        if gui.hover(box):
            gui.tooltip = tip
