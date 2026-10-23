"""지역 정보 탭의 '건물 슬롯 및 부존 자원'(v1.3.8): 슬롯 카드 그리드와 슬롯 밖 시설·자원 칩."""
from __future__ import annotations

import pygame

from .. import config as C
from .. import slots as S
from ..state import NEUTRAL
from .theme import measure, mix

# 슬롯 색: (강조·테두리·상단 바, 카드 본문, 빈 슬롯 바탕, 빈 슬롯 테두리)
SLOT_PALETTE = {
    "base": ((201, 42, 42), (255, 245, 245), (250, 232, 232), (224, 140, 140)),
    "river": ((51, 154, 240), (240, 248, 255), (227, 242, 253), (130, 195, 248)),
    "coast": ((24, 100, 171), (235, 243, 252), (218, 232, 248), (100, 150, 205)),
}
CARD_H = 62
GAP = 8


def slot_colors(t, stype) -> dict:
    """테마에 맞춘 슬롯 색. 어두운 테마는 밝은 바탕을 패널 색에 섞어(반투명처럼) 눈부시지 않게."""
    accent, body, empty, empty_line = SLOT_PALETTE[stype]
    if t.dark:
        body = mix(t.panel, accent, 0.18)
        empty = mix(t.panel, accent, 0.10)
        empty_line = mix(t.panel, accent, 0.55)
    return {"accent": accent, "body": body, "empty": empty, "empty_line": empty_line,
            "title": (245, 236, 236) if t.dark else mix(t.text, accent, 0.25)}


def columns(w) -> int:
    return 4 if w >= 440 else 3


def _dashed_rect(gui, color, r, dash=5, gap=4):
    """빈 슬롯의 점선 테두리."""
    x0, y0, x1, y1 = r.x, r.y, r.right - 1, r.bottom - 1
    for x in range(int(x0) + 6, int(x1) - 6, dash + gap):
        gui.line(color, (x, y0), (min(x + dash, x1 - 6), y0))
        gui.line(color, (x, y1), (min(x + dash, x1 - 6), y1))
    for y in range(int(y0) + 6, int(y1) - 6, dash + gap):
        gui.line(color, (x0, y), (x0, min(y + dash, y1 - 6)))
        gui.line(color, (x1, y), (x1, min(y + dash, y1 - 6)))


def _project_badge(app, gui, t, r, rid, p, col):
    """카드 아래 진행률 바와 '공사 중 (n턴)'·'대기 중' 배지."""
    g = app.game
    active = g.queue_region(rid).project is p
    frac = p.progress / max(1, p.turns) if active else 0.0
    bar = pygame.Rect(r.x + 6, r.bottom - 7, r.w - 12, 4)
    gui.rect(mix(col["empty_line"], t.panel, 0.4), bar, radius=2)
    if frac > 0:
        gui.rect(col["accent"], (bar.x, bar.y, max(2, bar.w * frac), bar.h), radius=2)
    txt = (f"공사 중 ({max(0, p.turns - p.progress)}턴)" if active and not p.stalled
           else "정지" if active else "대기 중")
    bw = measure(txt, 9, "semibold")[0] + 10
    badge = pygame.Rect(r.right - bw - 4, r.bottom - 22, bw, 14)
    gui.rect(t.warn if active and p.stalled else col["accent"], badge, radius=7)
    gui.text(badge.center, txt, 9, (255, 255, 255), "semibold", anchor="center")


def draw_slot_grid(app, x, y, w, rid, mine=False):
    """슬롯 카드 그리드(기본 → 하천 → 해안). 다음 y 를 돌려준다."""
    gui, g, t = app.gui, app.game, app.theme
    r = g.regions[rid]
    b = r.b
    cells = g.slot_summary(rid)
    if not cells:
        gui.text((x, y), "건물 슬롯 없음", 12, t.muted)
        return y + 22
    n = columns(w)
    cw = (w - GAP * (n - 1)) / n
    hover_tip = None
    for k, (stype, idx, card) in enumerate(cells):
        cx = x + (k % n) * (cw + GAP)
        cy = y + (k // n) * (CARD_H + GAP)
        rect = pygame.Rect(int(cx), int(cy), int(cw), CARD_H)
        col = slot_colors(t, stype)
        p = g.slot_project(rid, (stype, idx)) if r.owner != NEUTRAL else None
        hov = gui.hover(rect)
        if card is None:
            gui.rect(col["empty"], rect, radius=6)
            if hov and mine:
                gui.rect(col["accent"], rect, 2, radius=6)
            else:
                _dashed_rect(gui, col["empty_line"], rect)
            gui.text((rect.x + 7, rect.y + 5), f"{S.SLOT_NAMES[stype]} 슬롯", 10, col["accent"], "semibold")
            if p is not None:
                name = g.card_title(rid, p.key, 1, stype)
                gui.text((rect.centerx, rect.y + 25), f"{name} 신축", 11, t.text, "semibold", anchor="center",
                         max_w=rect.w - 10)
                _project_badge(app, gui, t, rect, rid, p, col)
            else:
                gui.text((rect.centerx, rect.y + 31), "+ 빈 슬롯", 12, col["accent"] if mine else t.muted, "semibold",
                         anchor="center")
            if hov:
                hover_tip = (f"{S.slot_label((stype, idx))}: 비어 있음\n"
                             f"지을 수 있는 건물: {', '.join(_kinds(g, rid, stype))}"
                             + ("\n누르면 [행동] 탭에서 이 슬롯에 지을 건물만 보여 줍니다." if mine else ""))
                if mine and gui.clicked:
                    gui.clicked = False
                    app.slot_filter = (rid, stype)
                    app.left_open, app.left_tab, app.tab = True, "region", "action"
            continue
        key, lv = card["key"], card["level"]
        gui.rect(col["body"], rect, radius=6)
        gui.rect(col["accent"], rect, 2, radius=6)
        head = pygame.Rect(rect.x, rect.y, rect.w, 16)
        gui.rect(col["accent"], head, radius=6)
        gui.rect(col["accent"], (head.x, head.y + 8, head.w, 8))
        gui.text((head.x + 6, head.y + 1), S.SLOT_NAMES[stype], 10, (255, 255, 255), "semibold")
        lv_txt = f"Lv.{lv}→{p.level}" if p is not None and p.level > lv else f"Lv.{lv}"
        gui.text((head.right - 6, head.y + 1), lv_txt, 10, (255, 255, 255), "semibold", anchor="topright")
        title = g.card_title(rid, key, lv, stype)
        gui.text((rect.centerx, rect.y + 20), title, 12, col["title"], "bold", anchor="midtop", max_w=rect.w - 8, tip=False)
        eff = g.card_effect(r.owner if r.owner != NEUTRAL else None, rid, card, stype)
        if p is not None:                     # 공사 중: 상단 바에 목표 단계(Lv.1→2), 아래에 진행 막대·배지
            _project_badge(app, gui, t, rect, rid, p, col)
        else:
            gui.text((rect.centerx, rect.y + 40), eff, 9, t.muted, anchor="midtop", max_w=rect.w - 6, tip=False)
        if hov:
            kind = g.slot_kind_name(rid, key, stype)
            hover_tip = (f"{S.slot_label((stype, idx))}: {title} ({kind} {lv}단계)\n"
                         f"{g.card_effect(r.owner if r.owner != NEUTRAL else None, rid, card, stype)}"
                         + (f"\n공사: {p.name}" if p is not None and p.name else "")
                         + ("\n[행동] 탭에서 증축·철거" if mine else ""))
            if mine and gui.clicked:
                gui.clicked = False
                app.slot_filter = (rid, stype)
                app.left_open, app.left_tab, app.tab = True, "region", "action"
    if hover_tip:
        gui.tooltip = hover_tip
    rows = (len(cells) + n - 1) // n
    return y + rows * (CARD_H + GAP) + 2


def _kinds(g, rid, stype) -> list:
    out = []
    for key in S.SLOT_KEYS[stype]:
        if g.slot_key_ok(rid, key, stype):
            out.append(g.slot_kind_name(rid, key, stype))
    return out


def resource_chips(app, rid) -> list:
    """부존 자원·특산물·경관."""
    g = app.game
    info = app.world.regions[rid]
    r = g.regions[rid]
    out = []
    if info.is_oil:
        out.append(f"유전(원유 {info.oil + r.b.cap('extract'):g})")
    if info.is_coal:
        out.append(f"탄전{info.coal_field}(석탄 {r.b.cap('extract'):g})")
    if info.power_source:
        src = info.power_source
        kind = "수력" if info.hydro else "원전" if info.nuclear else "화력"
        out.append(f"발전원({kind})" + (f" · 자체 발전 {g.self_power(rid)}/턴" if (info.hydro or info.nuclear) else ""))
    for sp in info.specialties:
        lv = r.b.get("specialty", 0)
        out.append(f"특산물: {sp}" + (f"(시설 {lv}단계)" if lv else "(시설 없음)"))
    if info.scenic:
        out.append(f"자연경관: {info.scenic}")
    if info.coastal:
        out.append("인접 해역: " + ", ".join(app.world.seas[s].name for s in info.seas))
    return out


def facility_chips(app, rid) -> list:
    """슬롯을 쓰지 않는 특수·방어·승리 시설."""
    g = app.game
    r = g.regions[rid]
    out = []
    if r.b.get("airport"):
        out.append("공항")
    if r.b.get("shelter"):
        out.append(f"방공호 {r.b['shelter']}")
    if r.b.get("aa"):
        out.append(f"대공포 {r.b['aa']}")
    lines = [(bk, lv) for bk, lv in sorted(r.lines.items()) if lv]
    if len(lines) <= 2:
        for bk, lv in lines:
            nm = "해안" if bk == "coast" else app.world.regions[bk].short
            out.append(f"방어선({nm}) {lv}")
    else:                                   # 경계가 많으면 한 칩으로(2줄 이내)
        lo, hi = min(lv for _, lv in lines), max(lv for _, lv in lines)
        out.append(f"방어선 {len(lines)}곳 " + (f"{lo}" if lo == hi else f"{lo}~{hi}") + "단계")
    for k in C.SCIENCE_STEPS:
        if k in r.sci:
            out.append(f"★ {C.SCIENCE[k]['name']}")
    for k in C.ECON_STEPS:
        if k in r.econ:
            out.append(f"★ {C.ECON[k]['name']}")
    return out


def draw_slot_section(app, x, y, w, rid, mine=False):
    """'건물 슬롯 및 부존 자원' 섹션 전체. 다음 y 를 돌려준다."""
    from .panels import draw_chips, section
    gui, g, t = app.gui, app.game, app.theme
    b = g.regions[rid].b
    used = b.used()
    y = section(gui, x, y + 6, w, f"건물 슬롯 및 부존 자원 · {used}/{b.total()}칸")
    y = draw_slot_grid(app, x, y, w, rid, mine)
    res = resource_chips(app, rid)
    fac = facility_chips(app, rid)
    if res:
        y = draw_chips(gui, x, y, w, res)
    if fac:
        y = draw_chips(gui, x, y - 2, w, fac)
    return y
