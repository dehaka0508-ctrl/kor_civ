"""지역 정보 탭의 '건물 슬롯 및 부존 자원'(v1.3.8): 슬롯 카드 그리드(기타 슬롯·과학/경제 금빛 카드 v1.3.9)와 자원·시설 칩."""
from __future__ import annotations

import pygame

from .. import config as C
from .. import slots as S
from ..state import NEUTRAL
from ..text import fmt_points
from .theme import measure, mix

# 슬롯 색: (강조·테두리·상단 바, 카드 본문, 빈 슬롯 바탕, 빈 슬롯 테두리)
SLOT_PALETTE = {
    "base": ((201, 42, 42), (255, 245, 245), (250, 232, 232), (224, 140, 140)),
    "river": ((51, 154, 240), (240, 248, 255), (227, 242, 253), (130, 195, 248)),
    "coast": ((24, 100, 171), (235, 243, 252), (218, 232, 248), (100, 150, 205)),
    "etc": ((73, 80, 87), (241, 243, 245), (233, 236, 239), (150, 156, 163)),       # 기타: 진한 회색(v1.3.9)
    "gold": ((222, 168, 20), (255, 248, 222), (252, 240, 200), (232, 196, 110)),    # 과학·경제: 금빛 노랑
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
    gold = stype == "gold"
    return {"accent": accent, "body": body, "empty": empty, "empty_line": empty_line,
            "head_text": (70, 45, 0) if gold else (255, 255, 255),
            "title": (245, 236, 236) if t.dark else mix(t.text, accent, 0.25 if not gold else 0.15)}


def columns(w) -> int:
    return 4 if w >= 440 else 3


def grid_layout(cells, x, y, w):
    """카드 자리: 슬롯 종류마다 새 줄에서 시작한다(v1.3.9). ([((종류, 칸), Rect)], 다음 y)."""
    n = columns(w)
    cw = (w - GAP * (n - 1)) / n
    out = []
    col, row_y, last = 0, y, None
    for stype, idx in cells:
        if last is not None and (stype != last or col >= n):
            col = 0
            row_y += CARD_H + GAP
        last = stype
        out.append(((stype, idx), pygame.Rect(int(x + col * (cw + GAP)), int(row_y), int(cw), CARD_H)))
        col += 1
    return out, (row_y + CARD_H + GAP if out else y)


def expanded_layout(cells, x, y, w, selected=None, panel_h=0):
    """선택한 카드가 있는 줄 바로 아래에 메뉴 공간을 두고 뒷줄만 내린다."""
    layout, bottom = grid_layout(cells, x, y, w)
    picked = next((rect for cell, rect in layout if cell == selected), None)
    if picked is None or not panel_h:
        return layout, bottom, None
    box = pygame.Rect(x, picked.bottom + GAP, w, panel_h)
    offset = panel_h + GAP
    layout = [(cell, rect.move(0, offset) if rect.y > picked.y else rect) for cell, rect in layout]
    return layout, bottom + offset, box


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
    gui.text(badge.center, txt, 9, col["head_text"], "semibold", anchor="center")


def _card_frame(gui, rect, col, left, right):
    """채운 카드: 테두리 2px·상단 바(왼쪽 종류, 오른쪽 단계)."""
    gui.rect(col["body"], rect, radius=6)
    gui.rect(col["accent"], rect, 2, radius=6)
    head = pygame.Rect(rect.x, rect.y, rect.w, 16)
    gui.rect(col["accent"], head, radius=6)
    gui.rect(col["accent"], (head.x, head.y + 8, head.w, 8))
    gui.text((head.x + 6, head.y + 1), left, 10, col["head_text"], "semibold")
    if right:
        gui.text((head.right - 6, head.y + 1), right, 10, col["head_text"], "semibold", anchor="topright")


def special_cards(app, rid) -> list:
    """기타 슬롯 아래 금빛 카드: 이 지역의 과학·경제승리 시설과 짓는 중인 과학·경제 공사.
    [(머리, 이름, 효과, 공사 또는 None)]"""
    g = app.game
    r = g.regions[rid]
    out = []
    office = g.office_building(rid)
    if office:
        out.append(("집무실", office["name"], f"행정력 +{fmt_points(office['output'])}/턴", None))
    paused = r.owner != NEUTRAL and g.facility_paused(rid)
    for k in C.SCIENCE_STEPS:
        if k in r.sci:
            out.append(("과학", C.SCIENCE[k]["name"], f"과학 {C.SCIENCE_STEPS.index(k) + 1}단계"
                        + (" · 정지" if paused else ""), None))
    for k in C.ECON_STEPS:
        if k in r.econ:
            out.append(("경제", C.ECON[k]["name"], f"경제 {C.ECON_STEPS.index(k) + 2}단계"
                        + (" · 정지" if paused else ""), None))
    if r.owner != NEUTRAL:
        for p in g.local_projects(rid):
            if p.kind in ("science", "econ") and (p.site or rid) == rid:
                spec = C.SCIENCE[p.key] if p.kind == "science" else C.ECON[p.key]
                k = (C.SCIENCE_STEPS.index(p.key) + 1) if p.kind == "science" else (C.ECON_STEPS.index(p.key) + 2)
                out.append(("과학" if p.kind == "science" else "경제", spec["name"],
                            f"{'과학' if p.kind == 'science' else '경제'} {k}단계", p))
    return out


def _cells(app, rid):
    g = app.game
    summary = g.slot_summary(rid)
    specials = special_cards(app, rid)
    return summary, specials, [(st, i) for st, i, _ in summary] + [("gold", k) for k in range(len(specials))]


def slot_grid_height(app, rid, w, opts=None) -> int:
    _, _, cells = _cells(app, rid)
    picked = getattr(app, "slot_sel", None)
    selected = tuple(picked[1:]) if picked and picked[0] == rid and opts is not None else None
    height = slot_panel_height(app, rid, selected, opts) if selected else 0
    _, y_end, _ = expanded_layout(cells, 0, 0, w, selected, height)
    return max(22, y_end + 2)


def _select(app, rid, stype, idx):
    """행동 탭: 카드를 누르면 그 칸을 고르고(다시 누르면 접는다) 아래에 건설·증축 선택지를 펼친다."""
    cur = getattr(app, "slot_sel", None)
    app.slot_sel = None if cur == (rid, stype, idx) else (rid, stype, idx)
    app._slot_reveal = app.slot_sel


def draw_slot_grid(app, x, y, w, rid, mine=False, select=False, opts=None):
    """슬롯 카드 그리드(기본 → 하천 → 해안 → 기타, 종류마다 새 줄)와 그 아래 과학·경제 금빛 카드. 다음 y.
    select=True(행동 탭): 카드를 누르면 그 칸의 건설·증축 선택지를 펼친다."""
    gui, g, t = app.gui, app.game, app.theme
    r = g.regions[rid]
    summary, specials, cells_list = _cells(app, rid)
    cards = {(st, i): c for st, i, c in summary}
    picked = getattr(app, "slot_sel", None)
    selected = tuple(picked[1:]) if select and picked and picked[0] == rid else None
    if selected and not g.regions[g.slot_site(rid, selected[0])].b.valid(selected):
        selected = None                         # (광역시 기본·하천·해안 칸은 중심의 광역 슬롯에서 확인)
    opts = g.options(g.player_id, rid) if select and opts is None else opts
    height = slot_panel_height(app, rid, selected, opts) if selected else 0
    layout, y_end, menu = expanded_layout(cells_list, x, y, w, selected, height)
    if not layout:
        gui.text((x, y), "건물 슬롯 없음", 12, t.muted)
        return y + 22
    holes = g.etc_placeholders(rid)
    hover_tip = None
    for (stype, idx), rect in layout:
        col = slot_colors(t, stype)
        hov = gui.hover(rect)
        if stype == "gold":
            head, name, eff, p = specials[idx]
            _card_frame(gui, rect, col, "★ " + head, "")
            gui.text((rect.centerx, rect.y + 20), name, 12, col["title"], "bold", anchor="midtop", max_w=rect.w - 8,
                     tip=False)
            if p is not None:
                _project_badge(app, gui, t, rect, rid, p, col)
            else:
                gui.text((rect.centerx, rect.y + 40), eff, 9, t.muted, anchor="midtop", max_w=rect.w - 6, tip=False)
            if hov:
                hover_tip = (f"{name}\n{eff}\n슬롯을 차지하지 않으며 증축할 수 없습니다. 수도를 따라 이전합니다."
                             if head == "집무실" else f"{head}승리 시설: {name}\n{eff}"
                             + (f"\n공사: {p.name or name}" if p is not None else ""))
            continue
        card = cards[(stype, idx)]
        site = g.slot_site(rid, stype)          # 광역시 기본·하천·해안 슬롯은 중심의 광역 슬롯(v1.3.16)
        mult = g.regions[site].b.mult_of(stype)
        p = g.slot_project(site, (stype, idx)) if r.owner != NEUTRAL else None
        if select and picked == (rid, stype, idx):
            gui.rect(t.gold, rect.inflate(6, 6), 3, radius=8)     # 고른 칸
        if card is None:
            gui.rect(col["empty"], rect, radius=6)
            if hov and mine:
                gui.rect(col["accent"], rect, 2, radius=6)
            else:
                _dashed_rect(gui, col["empty_line"], rect)
            gui.text((rect.x + 7, rect.y + 5), f"{S.SLOT_NAMES[stype]} 슬롯" + (f" ×{mult}" if mult > 1 else ""), 10,
                     col["accent"], "semibold")
            hole = holes.get(idx) if stype == "etc" else None
            if p is not None:
                name = g.card_title(site, p.key, 1, stype)
                gui.text((rect.centerx, rect.y + 25), f"{name} 신축", 11, t.text, "semibold", anchor="center",
                         max_w=rect.w - 10)
                _project_badge(app, gui, t, rect, rid, p, col)
            else:
                label = f"+ {g.slot_kind_name(site, hole, stype)}" if hole else "+ 빈 슬롯"
                gui.text((rect.centerx, rect.y + 31), label, 12 if not hole else 11, col["accent"] if mine else t.muted,
                         "semibold", anchor="center", max_w=rect.w - 8)
            if hov:
                kinds = [g.slot_kind_name(site, hole, stype)] if hole else _kinds(g, site, stype)
                hover_tip = (f"{S.slot_label((stype, idx))}: 비어 있음\n"
                             f"지을 수 있는 건물: {', '.join(kinds) or '없음'}"
                             + (f"\n광역 슬롯: 지으면 구성 지역 {mult}곳만큼 산출(비용도 {mult}배)" if mult > 1 else "")
                             + ("\n누르면 지을 수 있는 건물 목록을 펼칩니다." if mine and select else ""))
                if mine and select and gui.clicked:
                    gui.clicked = False
                    _select(app, rid, stype, idx)
            continue
        key, lv = card["key"], card["level"]
        lv_txt = f"Lv.{lv}→{p.level}" if p is not None and p.level > lv else f"Lv.{lv}"
        _card_frame(gui, rect, col, S.SLOT_NAMES[stype] + (f" ×{mult}" if mult > 1 else ""), lv_txt)
        title = g.card_title(site, key, lv, stype)
        gui.text((rect.centerx, rect.y + 20), title, 12, col["title"], "bold", anchor="midtop", max_w=rect.w - 8, tip=False)
        eff = g.card_effect(r.owner if r.owner != NEUTRAL else None, site, card, stype)
        if p is not None:                     # 공사 중: 상단 바에 목표 단계(Lv.1→2), 아래에 진행 막대·배지
            _project_badge(app, gui, t, rect, rid, p, col)
        else:
            gui.text((rect.centerx, rect.y + 40), eff, 9, t.muted, anchor="midtop", max_w=rect.w - 6, tip=False)
        if hov:
            kind = g.slot_kind_name(site, key, stype)
            hover_tip = (f"{S.slot_label((stype, idx))}: {title} ({kind} {lv}단계)\n{eff}"
                         + (f"\n광역 슬롯: 구성 지역 {mult}곳만큼 산출" if mult > 1 else "")
                         + ("\n장보고 '청해진 해상왕' 무료 항구 — 다른 슬롯을 차지하지 않음" if card.get("free") else "")
                         + (f"\n공사: {p.name}" if p is not None and p.name else "")
                         + ("\n누르면 다음 단계 건설·최대 건설·철거" if mine and select else ""))
            if mine and select and gui.clicked:
                gui.clicked = False
                _select(app, rid, stype, idx)
    if hover_tip:
        gui.tooltip = hover_tip
    if menu is not None:
        draw_slot_panel(app, menu.x, menu.y, menu.w, rid, selected, opts)
    return y_end + 2


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
    for sp in info.specialties:                 # 특산물 시설은 기타 슬롯 카드(v1.3.9)
        out.append(f"특산물: {sp}")
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
    office = g.office_building(rid)
    if office:
        out.append(f"{office['name']}(행정력 +{fmt_points(office['output'])}/턴)")
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
    return out                              # 과학·경제 시설은 기타 슬롯 아래 금빛 카드(v1.3.9)


def draw_slot_section(app, x, y, w, rid, mine=False):
    """지역 정보 탭(v1.3.9): 내 지역은 부존 자원·슬롯 밖 시설 칩만(건물 슬롯 카드는 [행동] 탭),
    다른 나라·중립 지역은 슬롯 카드를 읽기 전용으로 함께 보여 준다. 다음 y 를 돌려준다."""
    from .panels import draw_chips, section
    gui, g, t = app.gui, app.game, app.theme
    used, total = g.slot_counts(rid)
    if mine:
        y = section(gui, x, y + 6, w, "부존 자원·슬롯 밖 시설")
        if gui.button((x, y - 2, w, 26), f"건물 슬롯 {used}/{total}칸 — [행동] 탭에서 건설·증축", size=11):
            app.left_open, app.left_tab, app.tab = True, "region", "action"
        y += 30
    else:
        y = section(gui, x, y + 6, w, f"건물 슬롯 및 부존 자원 · {used}/{total}칸")
        y = draw_slot_grid(app, x, y, w, rid)
    res = resource_chips(app, rid)
    fac = facility_chips(app, rid)
    if res:
        y = draw_chips(gui, x, y, w, res)
    if fac:
        y = draw_chips(gui, x, y - 2, w, fac)
    return y


PANEL_ROW = 58


def slot_panel_height(app, rid, slot, opts) -> int:
    g = app.game
    rid = g.slot_site(rid, slot[0])
    n = len(g.slot_choices(g.player_id, rid, slot, opts))
    card = g.regions[rid].b.card(tuple(slot))
    return 34 + max(1, n) * PANEL_ROW + (34 if card is not None else 0) + 10


def _choice_label(g, rid, o, stype):
    key, lv = o["key"], o["level"]
    kind = g.slot_kind_name(rid, key, stype)
    if lv <= 1 or key in C.SITE_POWER:
        first = g.building_name(rid, key, 1) if key in C.PROD_LEVEL_NAMES else kind
        return f"{kind} 건설" + (f" · {first}" if first != kind else "")
    return f"{kind} {lv - 1}→{lv}단계 · {g.card_title(rid, key, lv, stype)}"


def draw_slot_panel(app, x, y, w, rid, slot, opts):
    """고른 칸의 선택지: 빈 칸은 지을 수 있는 건물마다 [건설]·[최대 건설], 지은 칸은 [다음 단계]·[최대 건설]과 [철거]."""
    gui, g, t = app.gui, app.game, app.theme
    pid = g.player_id
    slot = tuple(slot)
    stype, idx = slot
    col = slot_colors(t, stype)
    home = rid
    rid = g.slot_site(rid, stype)          # 광역 슬롯 카드는 중심 지역에 있다
    r = g.regions[rid]
    card = r.b.card(slot)
    mult = r.b.mult_of(stype)
    choices = g.slot_choices(pid, rid, slot, opts)
    h = slot_panel_height(app, rid, slot, opts)
    box = pygame.Rect(x, y, w, h)
    gui.rect(mix(t.panel, col["empty"], 0.6), box, radius=6)
    gui.rect(col["accent"], box, 2, radius=6)
    tag = f"광역 {S.slot_label(slot)} ×{mult}" if mult > 1 else S.slot_label(slot)
    if card is None:
        head = f"{tag} · 빈 슬롯 — 지을 건물을 고르세요"
    else:
        head = f"{tag} · {g.card_title(rid, card['key'], card['level'], stype)} {card['level']}단계"
    gui.text((x + 10, y + 8), head, 12, col["accent"] if not t.dark else t.text, "semibold", max_w=w - 46)
    if gui.button((x + w - 32, y + 5, 26, 22), "×", "ghost", size=12, tooltip="접기"):
        app.slot_sel = None
        return y + h + 8
    yy = y + 32
    if not choices:
        if card is not None and card["level"] >= g.card_max(rid, card["key"]):
            msg = "최대 단계입니다 · " + g.card_effect(pid, rid, card, stype)
        elif g.slot_project(rid, slot) is not None:
            msg = "이 칸에 공사가 잡혀 있습니다(작업 대기열)."
        else:
            msg = "지금 지을 수 있는 건물이 없습니다."
        gui.text((x + 10, yy + 6), msg, 11, t.muted, max_w=w - 20)
        yy += PANEL_ROW
    busy = g.queue_region(home).project is not None
    for o in choices:
        label = _choice_label(g, rid, o, stype)
        bx = x + w - 140
        gui.text((x + 10, yy), label, 12, t.text if o["ok"] else t.muted, "semibold", max_w=bx - x - 14)
        sub = (f"총 {o['cost']:,.0f} · {o['turns']}턴 · 턴당 {o['per_turn']:,.0f}" if o["ok"] else o["why"])
        gui.text((x + 10, yy + 18), sub, 10, t.muted if o["ok"] else t.bad, max_w=bx - x - 14)
        eff = g.building_effect(pid, rid, o)
        if eff:
            gui.text((x + 10, yy + 34), eff, 10, t.good, "semibold", max_w=bx - x - 14, tip=False)
        first = o["level"] <= 1 or o["key"] in C.SITE_POWER
        lab1 = ("추가" if busy else "건설") if first else ("다음 단계" if not busy else "추가")
        if gui.button((bx, yy + 2, 64, 26), lab1, "primary" if o["ok"] else "default", enabled=o["ok"], size=11,
                      tooltip=("작업 대기열에 추가" if busy else None)):
            ok, msg = g.start_project(pid, home, "build", o["key"], site=o.get("site") or rid, slot=slot)
            app.toast(msg, None if ok else t.bad)
            if ok:
                app.changed()
        if g.can_chain("build", o["key"]) and o["level"] < g.card_max(rid, o["key"]):
            if gui.button((bx + 70, yy + 2, 64, 26), "최대 건설", enabled=o["ok"], size=10,
                          tooltip="완공되면 같은 칸에서 다음 단계를 이어서 짓습니다(마지막 단계까지)"):
                ok, msg = g.start_project_max(pid, home, "build", o["key"], site=o.get("site") or rid, slot=slot)
                app.toast(msg, None if ok else t.bad)
                if ok:
                    app.changed()
        yy += PANEL_ROW
    if card is not None:
        locked = g.slot_project(rid, slot) is not None
        gui.text((x + 10, yy + 6), ("슬롯 비우기(비용 환급 없음)" + (f" · 광역 카드라 구성 지역 {mult}곳분" if mult > 1 else ""))
                 if not locked else "공사가 잡힌 칸은 철거할 수 없습니다", 10, t.muted, max_w=w - 100)
        if gui.button((x + w - 74, yy + 1, 64, 26), "철거", size=11, enabled=not locked,
                      tooltip="이 건물을 통째로 철거해 슬롯을 비웁니다."):
            ok, msg = g.demolish_card(pid, rid, slot)
            app.toast(msg, None if ok else t.bad)
            app.changed()
    return y + h + 8

