"""지역 면적·상태·작업 대기열 표시."""
import pygame
from .. import config as C


def draw_area(app, x, y, w, rid):
    """면적·인구밀도·기본 슬롯 칸 수(v1.3.8: 면적은 밀도 성장과 슬롯 칸 수에만 쓴다)."""
    gui, g, t = app.gui, app.game, app.theme
    area = g.info(rid).area_km2
    dens = g.regions[rid].pop * 10000 / area
    base = len(g.regions[rid].b.slots.get("base", ()))
    gui.text((x, y), f'면적 {area:,.1f} km² · 밀도 {dens:,.0f}명/km² · 기본 슬롯 {base}칸', 12, t.muted, max_w=w)
    return y + 20


def draw_status(app, x, y, w, rid):
    for status in app.game.local_disaster_status(rid):
        app.gui.text((x, y), status, 11, app.theme.warn, max_w=w)
        y += 19
    return y


def draw_queue(app, x, y, w, rid):
    from .panels import project_name
    gui, g, t = app.gui, app.game, app.theme
    r = g.queue_region(rid)
    ps = g.local_projects(rid)
    if not ps:
        return y
    gui.text((x, y), f'작업 대기열 {len(ps)}건 · 끌기 또는 선택 후 ↑↓', 11, t.muted, max_w=w)
    y += 21
    row_h = 38
    area = pygame.Rect(x, y, w, min(2, len(ps)) * row_h)
    offset = gui.begin_scroll(f'queue:{r.id}', area, len(ps) * row_h)
    yy = y - offset
    drag = getattr(app, 'queue_drag', None)
    if drag and (drag[0] != r.id or drag[1] >= len(ps)):
        app.queue_drag = drag = None
    for i, p in enumerate(ps):
        row = pygame.Rect(x, yy + i * row_h, w, row_h - 3)
        delete = pygame.Rect(row.right - 28, row.y + 4, 24, 25)
        sel = getattr(app, 'queue_sel', None) == (r.id, i)
        gui.rect(t.panel_alt, row, radius=4)
        if sel:
            gui.rect(t.accent, row, 2, radius=4)
        gui.text((x + 5, row.y + 2), f'{i+1}. {project_name(app, p, rid)}', 11,
                 t.accent if i == 0 else t.text, 'semibold', max_w=w - 38)
        note = p.blocked_reason if p.stalled and p.blocked_reason else (
            f'{p.progress:g}/{p.turns}턴 · 납부 {p.paid:,.0f}' + (' · 최대' if p.chain else ''))
        gui.text((x + 5, row.y + 18), note, 10, t.bad if p.stalled else t.muted, max_w=w - 38)
        if gui.button(delete, '×', size=12, tooltip='이 작업 삭제(납부액 50% 환급)'):
            ok, msg = g.cancel_queued_project(g.player_id, rid, i)
            app.toast(msg, None if ok else t.bad)
            app.changed()
            app.queue_drag = None
            break
        if drag is None and gui.down and gui.drag_id is None and gui.hover(row) and not gui.hover(delete):
            drag = app.queue_drag = (r.id, i)
            gui.drag_id = 'region_queue'
    if drag and not gui.down:
        target = max(0, min(len(ps)-1, int((gui.mouse[1] - yy) // row_h)))
        app.queue_drag = None
        gui.clicked = False
        if target != drag[1]:
            ok, msg = g.move_queued_project(g.player_id, rid, drag[1], target)
            app.toast(msg, None if ok else t.bad)
            app.changed()
        app.queue_sel = (r.id, target)
    gui.end_scroll(f'queue:{r.id}', area, len(ps) * row_h)
    sel = getattr(app, 'queue_sel', None)
    if sel and sel[0] == r.id and sel[1] < len(ps):
        app.arrow_capture_v = True
        for event in list(gui.keys):
            if event.key in (pygame.K_UP, pygame.K_DOWN) and not gui.focus:
                gui.keys.remove(event)
                target = sel[1] + (-1 if event.key == pygame.K_UP else 1)
                if 0 <= target < len(ps):
                    ok, msg = g.move_queued_project(g.player_id, rid, sel[1], target)
                    if ok:
                        app.queue_sel = (r.id, target)
                        app.changed()
                    else:
                        app.toast(msg, t.bad)
            elif event.key == pygame.K_ESCAPE:
                gui.keys.remove(event)
                app.queue_sel = None
    return area.bottom + 8
