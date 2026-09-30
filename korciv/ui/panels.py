"""좌측 구역 정보 패널, 우측 행동·부대·국가 탭."""
from __future__ import annotations

import math

import pygame

from .. import config as C
from .. import diplomacy as D
from ..leaders import GOV_BY_KEY, LEADER_BY_KEY
from ..state import BUILDING_NAMES, NEUTRAL
from .theme import fmt_money, hex2rgb, measure, mix


# ------------------------------------------------------------------ 유닛 아이콘 (단색 실루엣)
def unit_icon(surf, key, center, color, s=1.0):
    x, y = center
    k = s
    if key == "inf":
        pygame.draw.circle(surf, color, (x, y - 4 * k), 2.5 * k)
        pygame.draw.polygon(surf, color, [(x - 3 * k, y - 1 * k), (x + 3 * k, y - 1 * k), (x + 2 * k, y + 5 * k),
                                          (x - 2 * k, y + 5 * k)])
    elif key == "art":
        pygame.draw.circle(surf, color, (x - 2 * k, y + 3 * k), 2.5 * k)
        pygame.draw.line(surf, color, (x - 2 * k, y + 2 * k), (x + 5 * k, y - 4 * k), max(1, int(2 * k)))
    elif key == "tank":
        pygame.draw.rect(surf, color, (x - 5 * k, y - 1 * k, 10 * k, 5 * k), border_radius=2)
        pygame.draw.rect(surf, color, (x - 2 * k, y - 4 * k, 5 * k, 3 * k))
        pygame.draw.line(surf, color, (x + 2 * k, y - 3 * k), (x + 6 * k, y - 3 * k), 1)
    elif key in ("lst", "dd", "cv"):
        w = {"lst": 5, "dd": 6, "cv": 7}[key] * k
        pygame.draw.polygon(surf, color, [(x - w, y), (x + w, y), (x + w - 2 * k, y + 4 * k), (x - w + 2 * k, y + 4 * k)])
        if key == "dd":
            pygame.draw.rect(surf, color, (x - 1 * k, y - 3 * k, 3 * k, 3 * k))
        if key == "cv":
            pygame.draw.rect(surf, color, (x - w, y - 2 * k, 2 * w, 2 * k))
        if key == "lst":
            pygame.draw.rect(surf, color, (x - 3 * k, y - 3 * k, 6 * k, 3 * k), 1)
    elif key in ("ftr", "bmb", "stl"):
        wing = {"ftr": 5, "bmb": 7, "stl": 7}[key] * k
        if key == "stl":
            pygame.draw.polygon(surf, color, [(x, y - 5 * k), (x + wing, y + 4 * k), (x, y + 2 * k), (x - wing, y + 4 * k)])
        else:
            pygame.draw.line(surf, color, (x, y - 5 * k), (x, y + 5 * k), max(1, int(2 * k)))
            pygame.draw.line(surf, color, (x - wing, y), (x + wing, y), max(1, int(2 * k)))
            pygame.draw.line(surf, color, (x - 3 * k, y + 4 * k), (x + 3 * k, y + 4 * k), 1)


def section(gui, x, y, w, title):
    gui.text((x, y), title, 12, gui.t.muted, "semibold")
    gui.line(gui.t.border, (x, y + 20), (x + w, y + 20))
    return y + 26


def kv(gui, x, y, w, k, v, vcol=None):
    gui.text((x, y), k, 13, gui.t.muted)
    gui.text((x + w, y), v, 13, vcol or gui.t.text, "semibold", anchor="topright")
    return y + 21


# ------------------------------------------------------------------ 좌측 패널
def draw_left(app, rect):
    """좌측 패널: [국가 현황] / [지역 정보] 탭, 접기 가능."""
    gui = app.gui
    t = app.theme
    gui.panel(rect)
    tw = (rect.w - 60) / 2
    for i, (k, label) in enumerate((("nation", "국가 현황"), ("region", "지역 정보"))):
        if gui.button((rect.x + 12 + i * (tw + 4), rect.y + 10, tw, 32), label, selected=app.left_tab == k, size=14):
            app.left_tab = k
    if gui.button((rect.right - 40, rect.y + 10, 30, 32), "‹", "ghost", size=16, tooltip="접기"):
        app.left_open = False
        return
    body = pygame.Rect(rect.x, rect.y + 48, rect.w, rect.h - 48)
    if app.left_tab == "nation":
        draw_nation_status(app, body)
    elif not app.sel:
        gui.text((body.x + 16, body.y + 10), "지도에서 지역을 선택하세요.", 13, t.muted)
    else:
        draw_region_info(app, body)


def draw_region_info(app, rect):
    gui = app.gui
    g = app.game
    t = app.theme
    node = app.sel
    x, w = rect.x + 16, rect.w - 32
    pid = g.player_id
    if node in app.world.seas:
        draw_sea_info(app, rect, node)
        return
    info = app.world.regions[node]
    r = g.regions[node]
    explored = g.is_explored(pid, node) or app.fog_reveal
    visible = g.is_visible(pid, node) or app.fog_reveal
    gui.text((x, rect.y + 12), info.name, 18, weight="bold", max_w=w - 30)
    gui.text((x, rect.y + 38), f"{info.rtype} · 조선 {info.do8}도 · {info.ns}" + (f" · {info.island}" if info.island else ""),
             12, t.muted)
    y = rect.y + 62
    owner = r.owner if visible else g.player.last_seen.get(node, r.owner)
    if not explored:
        gui.text((x, y), "미탐색 지역입니다.", 13, t.muted)
        return
    col = app.faction_rgb(owner)
    gui.rect(col, (x, y + 2, 12, 12), radius=3)
    oname = g.fname(owner)
    if owner not in (NEUTRAL,) and owner != pid:
        st = D.stage(g, owner, pid)
        oname += f" · {D.STAGE_NAMES[st]}"
    if owner == pid and g.player.capital == node:
        oname += " · ★수도"
    gui.text((x + 18, y), oname, 13, weight="semibold")
    if not visible:
        gui.text((x + w, y), "시야 밖(마지막 정보)", 11, t.muted, anchor="topright")
    y += 24
    scroll_rect = pygame.Rect(rect.x, y, rect.w, rect.bottom - y - 8)
    content_h = 1100
    off = gui.begin_scroll("left", scroll_rect, content_h)
    y0 = y
    y -= off
    y = kv(gui, x, y, w, "인구", f"{r.pop:,.1f}만 명 (시작 {info.pop0:.1f})")
    y_out = r.output if r.owner != NEUTRAL else g.calc_output(node, phi=1.0)
    y = kv(gui, x, y, w, "산출(GDP)", f"{y_out:,.0f} /턴")
    if r.owner == pid:
        y = kv(gui, x, y, w, "세수", f"{y_out * g.player.tax:,.0f} /턴")
        y = kv(gui, x, y, w, "식량 생산", f"{r.food:,.1f} (소비 {r.pop:,.1f})")
        if r.b["factory"]:
            fuel = {1.0: "석탄", 1.1: "석유", 1.25: "전기", 0.25: "연료 없음"}.get(round(r.phi, 2), "-")
            y = kv(gui, x, y, w, "공장 연료", f"{fuel} (φ {r.phi:.2f})")
    # 행복도 막대
    if owner != NEUTRAL and visible:
        gui.text((x, y), "행복도", 13, t.muted)
        gui.text((x + w, y), f"{r.happy:+.1f}", 13, t.good if r.happy >= 0 else t.bad, "semibold", anchor="topright")
        y += 20
        bar = pygame.Rect(x, y, w, 8)
        gui.rect(t.panel_alt, bar, radius=4)
        mid = bar.centerx
        hw = int(abs(r.happy) / 100 * w / 2)
        if r.happy >= 0:
            gui.rect(t.happy_pos, (mid, bar.y, hw, 8), radius=4)
        else:
            gui.rect(t.happy_neg, (mid - hw, bar.y, hw, 8), radius=4)
        gui.line(t.muted, (mid, bar.y - 2), (mid, bar.bottom + 1))
        y += 16
        if r.happy <= C.REBEL_THRESHOLD and owner == pid:
            y = kv(gui, x, y, w, "반란 확률", f"{g.rebellion_chance(pid, node)*100:.1f}%/턴", t.bad)
    if owner == pid and r.focus:
        y = kv(gui, x, y, w, "생산 집중", f"적용 중 (인구 산출 +{C.FOCUS_POP_BONUS:.0%})" if g.focus_active(r) else "대기 (건설·생산 중)",
               t.good if g.focus_active(r) else t.muted)
    if r.occ and visible:
        y = kv(gui, x, y, w, "점령 진행", f"{g.fname(r.occ['by'])} {r.occ['progress']}/{r.occ['need']}턴", t.warn)
    # 건물
    y = section(gui, x, y + 6, w, "건물 단계")
    chips = []
    for k in ("farm", "fishery", "factory", "bank", "power", "liquefy", "specialty", "extract", "shelter", "aa"):
        if r.b[k]:
            chips.append(f"{BUILDING_NAMES[k]} {r.b[k]}")
    for k in ("academy", "airport", "port"):
        if r.b[k]:
            chips.append(BUILDING_NAMES[k])
    if r.landmark:
        chips.append(f"★ {r.landmark_name or g.default_landmark_name(node)}")
    for bk, lv in sorted(r.lines.items()):
        if lv:
            nm = "해안" if bk == "coast" else app.world.regions[bk].short
            chips.append(f"방어선({nm}) {lv}")
    y = draw_chips(gui, x, y, w, chips or ["없음"])
    # 자원
    y = section(gui, x, y + 6, w, "자원·특산물")
    res = []
    if info.oil:
        res.append(f"정유 {info.oil}+{r.b['extract']}/턴")
    if info.coal:
        res.append(f"탄광 {info.coal}+{r.b['extract']}/턴")
    if info.power_self:
        res.append(f"자체 발전 {info.power_self}/턴")
    if info.power_source:
        res.append(info.power_source)
    if info.specialty:
        res.append(f"특산물: {info.specialty}")
    if info.coastal:
        res.append("해안: " + ", ".join(app.world.seas[s].name for s in info.seas))
    y = draw_chips(gui, x, y, w, res or ["없음"])
    if owner == pid:
        y = section(gui, x, y + 6, w, f"특산물 공급 {len(r.supplied)}/{C.SPECIALTY_MAX_TYPES}종")
        sup = [k + (" (고정)" if k in r.spec_pin else "") for k in sorted(r.supplied)]
        y = draw_chips(gui, x, y, w, sup or ["없음"])
        if gui.button((x, y - 2, 120, 26), "배분 수정", size=12):
            app.spec_sel = node
            app.modal = ("specialty", None)
        y += 30
    terr = [(n, app.world.terrain_between(node, n)) for n in sorted(app.world.land_adj[node])]
    terr = [(n, tr) for n, tr in terr if tr]
    if terr:
        y = section(gui, x, y + 6, w, "지형 경계 (넘는 공격 ×0.9)")
        from .mapview import TERRAIN_COLORS
        for n, tr in terr:
            gui.line(TERRAIN_COLORS[tr["kind"]], (x, y + 9), (x + 14, y + 9), 4)
            gui.text((x + 20, y), f"{app.world.regions[n].short} · {tr['label']}({tr['name']})", 12, max_w=w - 24)
            y += 20
        y += 4
    # 주둔 부대
    y = section(gui, x, y + 6, w, "주둔 부대")
    arms = g.armies_at(node) if visible else []
    if not arms:
        gui.text((x, y), "없음" if visible else "보이지 않음", 13, t.muted)
        y += 22
    for a in arms:
        col = (130, 130, 130) if a.owner == NEUTRAL else app.faction_rgb(a.owner)
        rr = pygame.Rect(x, y, w, 24)
        if a.id == app.sel_army:
            gui.rect(t.panel_alt, rr, radius=6)
        gui.rect(col, (x + 4, y + 6, 10, 12), radius=3)
        gui.text((x + 20, y + 3), f"{g.fname(a.owner)} · {a.label()}", 13, max_w=w - 24)
        if a.owner == pid and gui.hover(rr) and gui.clicked:
            gui.clicked = False
            app.sel_army = a.id
            app.tab = "army"
        y += 26
    # 슬롯
    if owner == pid:
        y = section(gui, x, y + 6, w, "진행 중 슬롯")
        p = r.project
        if not p:
            gui.text((x, y), "비어 있음 — 우측 행동 탭에서 지정", 13, t.warn)
            y += 22
        else:
            y = draw_project(app, x, y, w, node, p)
    elif owner not in (NEUTRAL,):
        y += 8
        if gui.button((x, y, w, 32), "외교", "primary"):
            app.open_diplomacy(owner)
        y += 40
    gui.end_scroll("left", scroll_rect, y - y0 + off + 10)


def draw_chips(gui, x, y, w, chips):
    cx = x
    for c in chips:
        cw = measure(c, 12)[0] + 16
        if cx + cw > x + w and cx > x:
            cx = x
            y += 26
        r = pygame.Rect(cx, y, cw, 22)
        gui.rect(gui.t.panel_alt, r, radius=11)
        gui.text(r.center, c, 12, anchor="center")
        cx += cw + 6
    return y + 28


def project_name(app, p):
    if p.kind == "build":
        if p.key == "line":
            nm = "해안선" if p.border == "coast" else app.world.regions[p.border].short
            return f"방어선({nm}) {p.level}단계"
        return f"{BUILDING_NAMES[p.key]} {p.level}단계"
    if p.kind == "unit":
        return f"{C.UNITS[p.key]['name']} 생산"
    if p.kind == "annex":
        return f"편입: {app.world.regions[p.key].name}"
    if p.kind == "landmark":
        return f"랜드마크 「{p.name}」" if p.name else "랜드마크 건설"
    if p.kind == "capital":
        return "천도"
    return p.kind


def draw_project(app, x, y, w, rid, p):
    gui = app.gui
    t = app.theme
    gui.text((x, y), project_name(app, p), 14, weight="semibold")
    gui.text((x + w, y), f"남은 {p.remaining}턴", 12, t.muted, anchor="topright")
    y += 22
    gui.progress((x, y, w, 8), p.progress / max(1, p.turns), t.warn if p.stalled else t.accent)
    y += 14
    gui.text((x, y), f"턴당 {p.per_turn:,.0f} · 낸 비용 {p.paid:,.0f}" + (" · 자금 부족으로 정지" if p.stalled else ""),
             12, t.bad if p.stalled else t.muted)
    y += 22
    if gui.button((x, y, 150, 28), "취소 (50% 환급)"):
        ok, msg = app.game.cancel_project(app.game.player_id, rid)
        app.toast(msg)
    return y + 36


def draw_sea_info(app, rect, sid):
    gui = app.gui
    g = app.game
    t = app.theme
    sea = app.world.seas[sid]
    x, w = rect.x + 16, rect.w - 32
    gui.text((x, rect.y + 12), sea.name, 18, weight="bold")
    gui.text((x, rect.y + 38), sea.desc, 12, t.muted)
    y = rect.y + 66
    mine = sum(1 for r in sea.coast if g.regions[r].owner == g.player_id)
    y = kv(gui, x, y, w, "해안 타일 보유", f"{mine}/{len(sea.coast)}")
    ctrl = g.coast_controller(sid)
    y = kv(gui, x, y, w, "해안선 점유", g.fname(ctrl) if ctrl is not None else "없음")
    gui.wrap((x, y), "점유 효과: 해안 어장 식량·산출 +25%, 이 해역 해전 방어 +25%", w, 12, t.muted)
    y += 40
    y = kv(gui, x, y, w, "인접 해역", ", ".join(app.world.seas[s].name for s in sea.adj))
    y = section(gui, x, y + 6, w, "해역의 함대")
    for a in g.armies_at(sid):
        if a.owner == g.player_id or g.is_visible(g.player_id, sid) or app.fog_reveal:
            gui.rect(app.faction_rgb(a.owner), (x, y + 5, 10, 12), radius=3)
            r = pygame.Rect(x, y, w, 24)
            gui.text((x + 16, y + 2), f"{g.fname(a.owner)} · {a.label()}", 13, max_w=w - 20)
            if a.owner == g.player_id and gui.hover(r) and gui.clicked:
                gui.clicked = False
                app.sel_army = a.id
                app.tab = "army"
            y += 24


# ------------------------------------------------------------------ 우측 패널
def draw_right(app, rect):
    gui = app.gui
    gui.panel(rect)
    tabs = [("action", "행동"), ("army", "부대"), ("nation", "국가")]
    tw = (rect.w - 24) / 3
    for i, (k, label) in enumerate(tabs):
        if gui.button((rect.x + 12 + i * tw, rect.y + 10, tw - 4, 32), label, selected=app.tab == k, size=14):
            app.tab = k
    body = pygame.Rect(rect.x, rect.y + 52, rect.w, rect.h - 60)
    if app.tab == "action":
        draw_action_tab(app, body)
    elif app.tab == "army":
        draw_army_tab(app, body)
    else:
        draw_nation_tab(app, body)


def draw_action_tab(app, body):
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    x, w = body.x + 14, body.w - 28
    rid = app.sel
    if not rid or rid in app.world.seas or g.regions[rid].owner != pid:
        gui.text((x, body.y), "내 구역을 선택하면 슬롯을 지정할 수 있습니다.", 13, t.muted)
        idle = [r for r in g.regions_of(pid) if not r.project and not r.occ]
        yb = auto_slot_controls(app, x, body.y + 26, w)
        y = section(gui, x, yb, w, f"빈 슬롯 {len(idle)}곳")
        area = pygame.Rect(body.x, y, body.w, body.bottom - y)
        off = gui.begin_scroll("idle", area, len(idle) * 30)
        yy = y - off
        for r in sorted(idle, key=lambda r: -r.pop):
            if gui.button((x, yy, w, 26), f"{app.world.regions[r.id].name} · 인구 {r.pop:.1f}", "ghost", weight="regular"):
                app.select(r.id)
                app.map.center_on(r.id)
            yy += 30
        gui.end_scroll("idle", area, len(idle) * 30)
        return
    r = g.regions[rid]
    y = body.y
    gui.text((x, y), app.world.regions[rid].name, 15, weight="bold")
    y += 26
    # 생산 집중: 건설·병력 생산을 하지 않는 동안 인구 산출 +15%
    on = gui.checkbox((x, y, w, 26), f"생산 집중 (인구 산출 +{C.FOCUS_POP_BONUS:.0%})", r.focus, size=13)
    if on != r.focus:
        ok, msg = g.set_focus(pid, rid, on)
        app.toast(msg)
        app.changed()
    if r.focus:
        state = "적용 중" if g.focus_active(r) else "대기: 건설·생산 중에는 효과 없음"
        gui.text((x + w, y + 4), state, 11, t.good if g.focus_active(r) else t.muted, anchor="topright")
    y += 32
    if r.project:
        y = draw_project(app, x, y, w, rid, r.project)
        y = section(gui, x, y, w, "슬롯 사용 중 — 완료 후 새 작업 지정")
    if r.occ:
        gui.text((x, y), "점령당하는 중이라 슬롯을 쓸 수 없습니다.", 13, t.bad)
        return
    if r.b["factory"]:
        gui.text((x, y + 6), "공장 연료", 12, t.muted)
        opts = ["auto", "coal", "oil", "elec"]
        idx = gui.segmented((x + 70, y, w - 70, 28), ["자동", "석탄", "석유", "전기"], opts.index(r.fuel))
        if opts[idx] != r.fuel:
            g.set_fuel(pid, rid, opts[idx])
        y += 36
    if r.project:
        return
    opts = g.options(pid, rid)
    groups = [("편입", [o for o in opts if o["kind"] == "annex"]),
              ("생산 건물", [o for o in opts if o["kind"] == "build" and o["key"] in C.PROD_BUILDINGS]),
              ("유닛 생산", [o for o in opts if o["kind"] == "unit"]),
              ("방어·군사 건물", [o for o in opts if o["kind"] == "build" and o["key"] not in C.PROD_BUILDINGS]),
              ("특수", [o for o in opts if o["kind"] in ("landmark", "capital")])]
    area = pygame.Rect(body.x, y, body.w, body.bottom - y)
    content = sum(28 + sum(60 if o["kind"] == "build" else 44 for o in lst) for _, lst in groups if lst)
    off = gui.begin_scroll("actions", area, content)
    yy = y - off
    money = g.player.money
    for title, lst in groups:
        if not lst:
            continue
        yy = section(gui, x, yy, w, title)
        for o in lst:
            row = pygame.Rect(x, yy, w, 40)
            label = o["name"] + (f" {o['level']}단계" if o["kind"] == "build" and o["key"] != "line"
                                 and o["key"] not in C.SINGLE_BUILDINGS else "")
            if o["kind"] == "build" and o["key"] == "line":
                label = o["name"] + f" {o['level']}단계"
            gui.text((x, yy + 2), label, 13, t.text if o["ok"] else t.muted, "semibold", max_w=w - 70)
            sub = f"총 {o['cost']:,.0f} · {o['turns']}턴 · 턴당 {o['per_turn']:,.0f}"
            if o.get("oil"):
                sub += f" · 석유 {o['oil']}"
            if not o["ok"]:
                sub = o["why"]
            gui.text((x, yy + 21), sub, 11, t.muted if o["ok"] else t.bad, max_w=w - 70)
            eff = g.building_effect(pid, rid, o) if o["kind"] == "build" else ""
            if eff:
                gui.text((x, yy + 38), eff, 11, t.good, "semibold", max_w=w - 70)
            if gui.button((x + w - 62, yy + 6, 62, 28), "지정", "primary" if o["ok"] else "default",
                          enabled=o["ok"], size=12,
                          tooltip=None if money >= o["per_turn"] else "현재 자금이 턴당 비용보다 적어 정지될 수 있습니다"):
                if o["kind"] == "landmark":
                    app.lm_name = g.default_landmark_name(rid)
                    app.modal = ("landmark_name", rid)
                else:
                    ok, msg = g.start_project(pid, rid, o["kind"], o["key"], border=o.get("border"))
                    app.toast(msg, None if ok else t.bad)
                    if ok:
                        app.changed()
            yy += 60 if (o["kind"] == "build") else 44
    gui.end_scroll("actions", area, content)


def auto_slot_controls(app, x, y, w):
    gui = app.gui
    g = app.game
    f = g.player
    from .. import ai
    if gui.button((x, y, w, 30), "빈 슬롯 자동 지정 (AI 추천)", "primary", size=12,
                  tooltip="AI 유틸리티 판단으로 편입·건설을 지정합니다 (단축키 A)"):
        n = ai.auto_slots(g, f.id, military=f.ai.get("auto_military", False))
        app.toast(f"슬롯 {n}곳을 지정했습니다.")
    y += 36
    f.ai["auto_slots"] = gui.checkbox((x, y, w, 22), "매 턴 빈 슬롯 자동 지정", f.ai.get("auto_slots", False), size=12)
    y += 24
    f.ai["auto_military"] = gui.checkbox((x, y, w, 22), "자동 지정에 군 생산 포함", f.ai.get("auto_military", False), size=12)
    return y + 30


def draw_army_tab(app, body):
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    x, w = body.x + 14, body.w - 28
    y = body.y
    army = g.armies.get(app.sel_army) if app.sel_army else None
    if army and army.owner != pid:
        army = None
    if army:
        loc = app.world.node_name(army.loc)
        gui.text((x, y), f"부대 #{army.id} · {loc}", 15, weight="bold")
        y += 24
        dom = {"land": "육군", "naval": "해군", "air": "공군"}[army.domain()]
        gui.text((x, y), f"{dom} · 전력 {g.army_power(army):,.0f}", 12, t.muted)
        y += 22
        # 유닛 목록 + 분리 수량
        for k in C.UNIT_ORDER:
            n = army.units.get(k, 0)
            if not n:
                continue
            gui.icon(k, (x + 8, y + 11), t.text)
            u = C.UNITS[k]
            gui.text((x + 22, y + 2), f"{u['name']} {n}", 13, weight="semibold")
            dmg = army.dmg.get(k, 0)
            gui.text((x + 22, y + 20), f"공{u['atk'] or u.get('naval', 0) or u.get('air', 0)} 방{u['df']} 체{u['hp']}"
                     + (f" · 누적피해 {dmg:.1f}" if dmg else ""), 11, t.muted)
            app.split[k] = gui.stepper((x + w - 96, y + 6, 96, 26), min(app.split.get(k, 0), n), 0, n)
            y += 40
        if army.domain() == "naval":
            gui.text((x, y), f"수송 {army.cargo_used()}/{army.cargo_cap()}칸 · 탑재 {army.air_used()}/{army.air_cap()}대",
                     12, t.muted)
            y += 20
        bw = (w - 8) / 3
        sel_n = sum(app.split.values())
        if gui.button((x, y, bw, 28), "분리", enabled=sel_n > 0, tooltip="선택한 수량을 새 부대로"):
            b, msg = g.split_army(army.id, app.split)
            if b:
                app.sel_army = b.id
                app.split = {}
            else:
                app.toast(msg, t.bad)
        others = [a for a in g.armies_at(army.loc, pid) if a.id != army.id]
        if gui.button((x + bw + 4, y, bw, 28), "합치기", enabled=bool(others), tooltip="같은 위치의 내 부대를 모두 합침"):
            for o in others:
                ok, msg = g.merge_armies(army.id, o.id)
                if not ok:
                    app.toast(msg, t.bad)
        if gui.button((x + 2 * bw + 8, y, bw, 28), "해산", "danger", enabled=sel_n > 0,
                      tooltip="선택한 수량 해산 (자국 영토면 행복도 +)"):
            g.disband(army.id, app.split)
            app.split = {}
            if army.id not in g.armies:
                app.sel_army = None
                return
        y += 38
        gui.text((x, y + 6), "공격 방식", 12, t.muted)
        modes = ["assault", "surprise"]
        idx = gui.segmented((x + 70, y, w - 70, 28), ["돌격", "기습"], modes.index(app.attack_mode))
        app.attack_mode = modes[idx]
        y += 34
        app.bombard_mode = gui.checkbox((x, y, w, 24), "폭격 모드 (우클릭 대상 폭격)", app.bombard_mode)
        y += 30
        o = army.order
        if o:
            desc = {"move": "이동", "attack": "공격", "land": "상륙", "bombard": "폭격"}[o["type"]]
            tgt = o.get("target") or (o.get("path") or [army.loc])[-1]
            gui.text((x, y), f"명령: {desc} → {app.world.node_name(tgt)}", 13, t.accent, "semibold")
            if gui.button((x + w - 70, y - 4, 70, 26), "취소", size=12):
                g.order_army(army.id, None)
            y += 26
            if army.goto:
                gui.text((x, y), f"최종 목적지: {app.world.node_name(army.goto)} (매 턴 자동 이동)", 12, t.muted)
                y += 22
        else:
            gui.wrap((x, y), "지도에서 우클릭으로 이동·공격 대상을 지정하세요. 진한 색은 자국 영토 2칸, 옅은 색은 1칸, 점선은 연륙교입니다. "
                             "범위 밖을 우클릭하면 최단 경로로 여러 턴에 걸쳐 자동 이동합니다.",
                     w, 12, t.muted)
            y += 78
    else:
        gui.text((x, y), "부대를 선택하세요.", 13, t.muted)
        y += 26
    # 내 모든 부대
    mine = sorted([a for a in g.armies.values() if a.owner == pid], key=lambda a: (-g.army_power(a), a.id))
    y = section(gui, x, y + 4, w, f"내 부대 {len(mine)}개 · 유지비 {g.upkeep(pid):,.0f}/턴")
    area = pygame.Rect(body.x, y, body.w, body.bottom - y)
    off = gui.begin_scroll("armies", area, len(mine) * 28)
    yy = y - off
    for a in mine:
        lab = f"{app.world.node_name(a.loc)} · {a.label()}" + (" ▶" if a.order or a.goto else "")
        if gui.button((x, yy, w, 26), lab, "ghost", selected=a.id == app.sel_army, weight="regular", size=12):
            app.sel_army = a.id
            app.sel = a.loc
            app.map.center_on(a.loc)
            app.split = {}
        yy += 28
    gui.end_scroll("armies", area, len(mine) * 28)


def draw_nation_tab(app, body):
    gui = app.gui
    g = app.game
    t = app.theme
    f = g.player
    pid = f.id
    x, w = body.x + 14, body.w - 28
    area = pygame.Rect(body.x, body.y, body.w, body.h)
    content = 1500
    off = gui.begin_scroll("nation", area, content)
    y = body.y - off
    y0 = y
    # 세율
    y = section(gui, x, y, w, "세율")
    tmax = g.tax_max(pid)
    locked = f.tax_locked_until > g.turn
    cur = round(f.tax * 100)
    new_val = None
    if gui.button((x, y, 28, 28), "−", size=14, enabled=not locked and cur > 0, tooltip="세율 1%p 내리기"):
        new_val = cur - 1
    val, released = gui.slider((x + 40, y + 4, w - 122, 20), cur, 0, tmax * 100, 1, "tax", enabled=not locked)
    if gui.button((x + w - 74, y, 28, 28), "+", size=14, enabled=not locked and cur < tmax * 100,
                  tooltip="세율 1%p 올리기"):
        new_val = cur + 1
    gui.text((x + w, y + 4), f"{val:.0f}%", 15, weight="semibold", anchor="topright")
    if released:
        new_val = val
    if new_val is not None and abs(new_val / 100 - f.tax) > 1e-6:
        ok, msg = g.set_tax(pid, new_val / 100)
        app.toast(msg if ok else msg, None if ok else t.bad)
    y += 34
    gdp = sum(g.region_output_estimate(r.id) for r in g.regions_of(pid))
    eff = 0.1 * (10 - val)
    gui.text((x, y), f"예상 세수 {gdp * val / 100:,.0f}/턴 · 행복도 {eff:+.1f}/턴" + (" · 잠김" if locked else ""), 12, t.muted)
    y += 24
    # 자원 시장
    y = section(gui, x, y + 4, w, "자원 시장 (구매/판매가, 같은 턴 추가 구매 +10%)")
    for res in C.RESOURCES:
        gui.text((x, y + 5), C.RESOURCE_NAMES[res], 13, weight="semibold")
        gui.text((x + 40, y + 5), f"{f.res.get(res, 0):,.0f}", 13)
        bp, sp = g.buy_price(pid, res), g.sell_price(pid, res)
        gui.text((x + 96, y + 5), f"{bp:,.0f}/{sp:,.0f}", 11, t.muted)
        bx = x + w - 150
        q1, q2 = (10, 100) if res == "food" else (1, 10)   # 식량은 10·100 단위
        bs = 9 if res == "food" else 11
        if gui.button((bx, y, 36, 24), f"+{q1}", size=bs, tooltip=f"{q1}개 구매 ({bp * q1:,.0f})"):
            n, s_ = g.market_buy(pid, res, q1)
            app.toast(f"{C.RESOURCE_NAMES[res]} {n}개 구매 ({s_:,.0f})")
        if gui.button((bx + 38, y, 36, 24), f"+{q2}", size=bs, tooltip=f"{q2}개 구매"):
            n, s_ = g.market_buy(pid, res, q2)
            app.toast(f"{C.RESOURCE_NAMES[res]} {n}개 구매 ({s_:,.0f})")
        if gui.button((bx + 76, y, 36, 24), f"−{q1}", size=bs, tooltip=f"{q1}개 판매 ({sp * q1:,.0f})"):
            g.market_sell(pid, res, q1)
        if gui.button((bx + 114, y, 36, 24), f"−{q2}", size=bs, tooltip=f"{q2}개 판매"):
            g.market_sell(pid, res, q2)
        y += 30
    f.auto_food = gui.checkbox((x, y, w, 24), "식량 부족 시 자동 구매", f.auto_food)
    y += 26
    f.liquefy = gui.checkbox((x, y, w, 24), f"석유 비축 {C.OIL_RESERVE_FOR_LIQUEFY} 미만이면 석탄액화", f.liquefy)
    y += 30
    # 특산물
    stock = {k: v for k, v in f.specialty.items() if v > 0}
    supplied = sum(len(r.supplied) for r in g.regions_of(pid))
    y = section(gui, x, y, w, f"특산물 (재고 {sum(stock.values())}개 · 공급 {supplied}건, 자동 배분)")
    f.auto_specialty = gui.checkbox((x, y, w - 110, 24), "행복도 낮은 지역부터 자동", f.auto_specialty, size=12)
    if gui.button((x + w - 100, y - 2, 100, 26), "배분 수정", size=12):
        app.spec_sel = app.sel if app.sel in g.regions and g.regions[app.sel].owner == pid else None
        app.modal = ("specialty", None)
    y += 30
    gui.text((x, y), "국가 통계·재정·특산물 재고는 좌측 [국가 현황] 탭에 있습니다.", 11, t.muted)
    y += 18
    # 외교
    y = section(gui, x, y + 8, w, "외교")
    for o in g.factions:
        if o.id == pid or not o.alive:
            continue
        gui.rect(hex2rgb(o.color), (x, y + 6, 10, 14), radius=3)
        st = D.stage(g, o.id, pid)
        op = D.opinion(g, o.id, pid)
        gui.text((x + 16, y + 2), o.name, 13, weight="semibold", max_w=110)
        origin = f" · {g.fname(o.rebel_of)}에서 독립" if o.rebel_of is not None else ""
        gui.text((x + 16, y + 20), f"{o.leader_name} · {D.STAGE_NAMES[st]} · 우호 {op:+.0f}{origin}", 11,
                 t.bad if st == -1 else t.muted, max_w=w - 80)
        if gui.button((x + w - 58, y + 6, 58, 26), "외교", size=12):
            app.open_diplomacy(o.id)
        y += 42
    # 기타
    y = section(gui, x, y + 6, w, "게임")
    bw = (w - 8) / 3
    if gui.button((x, y, bw, 28), "저장 F5", size=12):
        app.save()
    if gui.button((x + bw + 4, y, bw, 28), "불러오기 F9", size=12):
        app.load()
    if gui.button((x + 2 * bw + 8, y, bw, 28), "도움말 F1", size=12):
        app.modal = ("help", None)
    y += 34
    if gui.button((x, y, (w - 4) / 2, 28), "이벤트 로그", size=12):
        app.modal = ("log", None)
    if gui.button((x + (w + 4) / 2, y, (w - 4) / 2, 28), "연말 랭킹", size=12, enabled=bool(g.rankings)):
        app.modal = ("ranking", max(g.rankings))
    y += 40
    gui.end_scroll("nation", area, y - y0)


# ------------------------------------------------------------------ 좌측 [국가 현황]
PROJECT_KIND_NAMES = {"build": "건설", "unit": "병력 생산", "annex": "편입", "landmark": "랜드마크", "capital": "천도"}


def draw_nation_status(app, body):
    gui = app.gui
    g = app.game
    t = app.theme
    f = g.player
    pid = f.id
    x, w = body.x + 16, body.w - 32
    area = pygame.Rect(body.x, body.y, body.w, body.h - 6)
    content = getattr(app, "_nation_h", 1600)
    off = gui.begin_scroll("nation_status", area, content)
    y = body.y + 4 - off
    y0 = y
    regs = g.regions_of(pid)
    last = f.last
    # 국가 통계
    y = section(gui, x, y, w, "국가 통계")
    y = kv(gui, x, y, w, "GDP", f"{last.get('gdp', 0):,.0f} /턴")
    y = kv(gui, x, y, w, "국력", f"{g.power.get(pid, 0):.2f}" + (" (패권)" if g.hegemon == pid else ""))
    y = kv(gui, x, y, w, "지역 / 인구", f"{len(regs)}곳 / {g.total_pop(pid):,.0f}만")
    y = kv(gui, x, y, w, "평균 행복도", f"{g.avg_happiness(pid):+.1f}")
    y = kv(gui, x, y, w, "군 전력", f"{g.mil_power(pid):,.0f}")
    lm = [app.world.regions[r.id].do8 for r in regs if r.landmark]
    y = kv(gui, x, y, w, "랜드마크(8도)", f"{len(lm)}개 · {len(set(lm))}/8도")
    lead = LEADER_BY_KEY[f.leader]
    gov = GOV_BY_KEY.get(f.gov, {})
    y = gui.wrap((x, y + 2), f"지도자 {lead['name']}: {lead['buff'][0]}({lead['buff'][1]}) / "
                 f"{lead['debuff'][0]}({lead['debuff'][1]})", w, 11, t.muted)
    if gov:
        y = gui.wrap((x, y), f"체제 {gov['name']}: {gov['buff'][1]} / {gov['debuff'][1]}", w, 11, t.muted)
    # 재정
    items = g.projects_by_priority(pid)
    spend = {}
    for rr in items:
        k = rr.project.kind
        n, s = spend.get(k, (0, 0.0))
        spend[k] = (n + 1, s + rr.project.per_turn)
    total_spend = sum(s for _, s in spend.values())
    y = section(gui, x, y + 6, w, "재정 (턴당)")
    y = kv(gui, x, y, w, "자금", f"{f.money:,.0f}", t.bad if f.money < 0 else None)
    y = kv(gui, x, y, w, "세수", f"+{last.get('tax', 0):,.0f} (세율 {f.tax*100:.0f}%)", t.good)
    y = kv(gui, x, y, w, "군 유지비", f"−{g.upkeep(pid):,.0f}", t.bad)
    y = kv(gui, x, y, w, "시장 구매 / 판매", f"−{last.get('buy', 0):,.0f} / +{last.get('sell', 0):,.0f}")
    y = kv(gui, x, y, w, "순수익", f"{last.get('net', 0):+,.0f}", t.good if last.get("net", 0) >= 0 else t.bad)
    for k in ("build", "unit", "annex", "landmark", "capital"):
        if k in spend:
            n, s = spend[k]
            y = kv(gui, x, y, w, f"{PROJECT_KIND_NAMES[k]} {n}건", f"−{s:,.0f}")
    y = kv(gui, x, y, w, "진행 중 작업 지출 합", f"−{total_spend:,.0f}", t.bad if total_spend > f.money else None)
    stalled = sum(1 for rr in items if rr.project.stalled)
    if stalled:
        y = kv(gui, x, y, w, "자금 부족으로 정지", f"{stalled}건", t.bad)
    focus = [r for r in regs if g.focus_active(r)]
    bonus = sum(C.POP_OUTPUT * r.pop * C.FOCUS_POP_BONUS for r in focus)
    y = kv(gui, x, y, w, "생산 집중 지역", f"{len(focus)}곳 (+{bonus:,.0f})")
    # 자원
    y = section(gui, x, y + 6, w, "자원 비축")
    y = kv(gui, x, y, w, "식량", f"{f.res.get('food', 0):,.0f} (생산 {last.get('food_prod', 0):,.0f} / 소비 "
           f"{last.get('food_cons', 0):,.0f})")
    y = kv(gui, x, y, w, "석유 / 석탄 / 전기",
           f"{f.res.get('oil', 0):,.0f} / {f.res.get('coal', 0):,.0f} / {f.res.get('elec', 0):,.0f}")
    # 지출 우선순위 (드래그)
    y = section(gui, x, y + 6, w, "지출 우선순위 (드래그로 순서 변경)")
    gui.text((x, y - 2), "자금이 모자라면 위에서부터 비용을 내고 아래 작업이 정지됩니다.", 11, t.muted)
    y += 20
    y = draw_priority_list(app, x, y, w, items)
    # 특산물 재고
    stock = {k: v for k, v in f.specialty.items() if v > 0}
    kinds = sorted(set(stock) | set(g.specialty_kinds(pid)))
    y = section(gui, x, y + 6, w, f"특산물 재고 {sum(stock.values())}개 · {len(kinds)}종 (눌러서 생산지 열기)")
    producer = {sp: r.id for r in regs for sp in app.world.regions[r.id].specialties}
    supplied = {}
    for r in regs:
        for k in r.supplied:
            supplied[k] = supplied.get(k, 0) + 1
    for k in kinds:
        row = pygame.Rect(x, y, w, 26)
        src = producer.get(k)
        hov = src and gui.hover(row)
        if hov:
            gui.rect(t.panel_alt, row, radius=6)
        gui.text((x + 6, y + 4), k, 13, t.accent if src else t.text, "semibold" if src else "regular", max_w=w * 0.55)
        info = f"재고 {stock.get(k, 0)} · 공급 {supplied.get(k, 0)}곳"
        gui.text((x + w - 4, y + 5), info, 11, t.muted, anchor="topright")
        if hov:
            gui.tooltip = f"생산지: {app.world.regions[src].name} (클릭하면 지역 정보·행동 메뉴)"
            if gui.clicked:
                gui.clicked = False
                app.select(src)
                app.tab = "action"
                app.left_tab = "region"
                app.map.center_on(src)
        y += 28
    if not kinds:
        gui.text((x, y), "없음", 13, t.muted)
        y += 24
    app._nation_h = y - y0 + 20
    gui.end_scroll("nation_status", area, app._nation_h)


def draw_priority_list(app, x, y, w, items):
    """자금 지출 우선순위 목록. 행을 끌어 순서를 바꾼다."""
    gui = app.gui
    g = app.game
    t = app.theme
    row_h = 44
    n = len(items)
    if not n:
        gui.text((x, y), "진행 중인 작업이 없습니다.", 13, t.muted)
        return y + 26
    top = y
    drag = getattr(app, "prio_drag", None)
    ids = [rr.id for rr in items]
    if drag not in ids:
        drag = app.prio_drag = None
    # 끌기 시작
    if drag is None and gui.down and gui.drag_id is None:
        for i, rid in enumerate(ids):
            if gui.hover(pygame.Rect(x, top + i * row_h, w, row_h - 4)):
                app.prio_drag = drag = rid
                gui.drag_id = "prio"
                break
    target = None
    if drag is not None:
        target = max(0, min(n - 1, int((gui.mouse[1] - top) // row_h)))
    order = ids
    if drag is not None:
        order = [r for r in ids if r != drag]
        order.insert(target, drag)
    for i, rid in enumerate(order):
        rr = g.regions[rid]
        p = rr.project
        row = pygame.Rect(x, top + i * row_h, w, row_h - 4)
        dragged = rid == drag
        gui.rect(t.accent if dragged else t.panel_alt, row, radius=8)
        fg = (255, 255, 255) if dragged else t.text
        sub = (235, 240, 255) if dragged else t.muted
        gui.text((row.x + 8, row.y + 3), f"{i + 1}. {app.world.regions[rid].short} · {project_name(app, p)}", 12, fg,
                 "semibold", max_w=w - 16)
        state = "정지" if p.stalled else f"남은 {p.remaining}턴"
        gui.text((row.x + 8, row.y + 21), f"턴당 {p.per_turn:,.0f} · {state}", 11,
                 (t.bad if p.stalled and not dragged else sub))
        gui.text((row.right - 8, row.centery), "≡", 16, sub, anchor="midright")
    # 놓기
    if drag is not None and not gui.down:
        app.prio_drag = None
        if order != ids:
            g.set_priority_order(g.player_id, order)
            gui.clicked = False
            app.toast(f"우선순위 변경: {app.world.regions[drag].short} → {order.index(drag) + 1}번")
    return top + n * row_h + 4
