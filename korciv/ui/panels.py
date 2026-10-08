"""좌측 구역 정보 패널, 우측 행동·부대·국가 탭."""
from __future__ import annotations

import math

import pygame

from .. import config as C
from .. import diplomacy as D
from .. import rules as R
from ..leaders import GOV_BY_KEY, LEADER_BY_KEY, gov_buff_scale
from ..state import BUILDING_NAMES, NEUTRAL
from ..flags import faction_flag
from .art import draw_flag, draw_portrait
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
    elif key in ("ftr", "bmb"):
        wing = {"ftr": 5, "bmb": 7}[key] * k
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
# 좌측 세로 탭(위에서부터): 키, 이름, 설명
SIDE_TABS = (("nation", "내정", "세율·자원 시장·특산물·지출 우선순위"), ("diplo", "외교", "세력별 관계·외교 창"),
             ("army", "군사", "전체 군사 유닛 수·유지비"), ("energy", "자원\n배정", "공장·발전소 연료 배정"),
             ("status", "국가\n현황", "국가 통계·재정·승리 조건 진행"))
RAIL_W = 64


def draw_side(app, rail, panel_rect):
    """좌측 끝 세로 탭 + 바로 옆 패널. 지역을 누르면 패널에 [행동]/[지역 정보]가 뜬다.
    같은 탭을 한 번 더 누르면 패널을 접는다."""
    gui = app.gui
    t = app.theme
    gui.panel(rail)
    bh = 58
    for i, (k, label, tip) in enumerate(SIDE_TABS):
        r = pygame.Rect(rail.x + 6, rail.y + 8 + i * (bh + 6), rail.w - 12, bh)
        sel = app.left_open and app.left_tab == k
        if gui.button(r, "", selected=sel, tooltip=tip):
            if sel:
                app.left_open = False
            else:
                app.left_open, app.left_tab = True, k
                if k == "diplo":
                    app.dip_view = None          # 외교 탭은 항상 세력 목록부터
        lines = label.split("\n")
        for j, ln in enumerate(lines):
            gui.text((r.centerx, r.centery + (j - (len(lines) - 1) / 2) * 17), ln, 13,
                     (255, 255, 255) if sel else t.text, "semibold", anchor="center")
    if not app.left_open:
        return
    gui.panel(panel_rect)
    k = app.left_tab
    if k == "region":
        tabs = (("action", "행동"), ("army", "부대"), ("info", "지역 정보"))
        tw = (panel_rect.w - 24 - 36 - 8) / 3
        for i, (tk, label) in enumerate(tabs):
            if gui.button((panel_rect.x + 12 + i * (tw + 4), panel_rect.y + 10, tw, 32), label,
                          selected=app.tab == tk, size=14):
                app.tab = tk
        top = 48
    else:
        title = next(lb for kk, lb, _ in SIDE_TABS if kk == k).replace("\n", " ")
        gui.text((panel_rect.x + 16, panel_rect.y + 14), title, 17, weight="bold")
        top = 46
    if gui.button((panel_rect.right - 40, panel_rect.y + 10, 30, 32), "‹", "ghost", size=16, tooltip="접기"):
        app.left_open = False
        return
    body = pygame.Rect(panel_rect.x, panel_rect.y + top, panel_rect.w, panel_rect.h - top - 6)
    if k == "nation":
        draw_nation_tab(app, body)
    elif k == "diplo":
        draw_diplo_tab(app, body)
    elif k == "army":
        draw_military_tab(app, body)
    elif k == "energy":
        draw_energy_tab(app, body)
    elif k == "status":
        draw_nation_status(app, body)
    elif app.tab == "action":
        draw_action_tab(app, body)
    elif app.tab == "army":
        draw_army_tab(app, body)
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
    oname = g.seen_name(owner)
    if owner not in (NEUTRAL,) and owner != pid:
        st = D.stage(g, owner, pid)
        oname += f" · {D.STAGE_NAMES[st]}"
    if owner == pid and g.player.capital == node:
        oname += " · ★수도"
    gui.text((x + 18, y), oname, 13, weight="semibold")
    if not visible:
        gui.text((x + w, y), "시야 밖(마지막 정보)", 11, t.muted, anchor="topright")
    # 내 지역과 시야 안의 타국 지역은 같은 현황을 보여 준다(중립·시야 밖은 기본 정보만)
    full = owner == pid or (visible and owner != NEUTRAL)
    of = g.factions[owner] if full else None
    y += 24
    scroll_rect = pygame.Rect(rect.x, y, rect.w, rect.bottom - y - 8)
    content_h = 1100
    off = gui.begin_scroll("left", scroll_rect, content_h)
    y0 = y
    y -= off
    y = kv(gui, x, y, w, "인구", f"{r.pop:,.1f}만 명")
    y_out = r.output if r.owner != NEUTRAL else g.calc_output(node, full=True)
    y = kv(gui, x, y, w, "산출(GDP)", f"{y_out:,.0f} /턴")
    val, _ = g.region_value(node)
    vtxt = f"{val} / 10"
    if r.owner == NEUTRAL:
        vtxt += f" · 편입·점령 {g.neutral_turns(pid, node)}턴"
    y = kv(gui, x, y, w, "지역 가치", vtxt, t.accent)
    if full:
        y = kv(gui, x, y, w, "세수", f"{y_out * of.tax:,.0f} /턴")
        y = kv(gui, x, y, w, "식량 생산", f"{r.food:,.1f} (소비 {r.pop:,.1f})")
        if r.b["factory"]:
            y = kv(gui, x, y, w, "공장 연료", f"{getattr(r, 'fuel_used', 0)}/{r.b['factory']}개 투입")
    # 행복도 막대
    if owner != NEUTRAL and visible:
        eh = g.eff_happy(r)
        gui.text((x, y), "실질 행복도", 13, t.muted)
        gui.text((x + w, y), f"{eh:+.1f}", 13, t.good if eh >= 0 else t.bad, "semibold", anchor="topright")
        y += 20
        bar = pygame.Rect(x, y, w, 8)
        gui.rect(t.panel_alt, bar, radius=4)
        mid = bar.centerx
        hw = int(abs(eh) / 100 * w / 2)
        if eh >= 0:
            gui.rect(t.happy_pos, (mid, bar.y, hw, 8), radius=4)
        else:
            gui.rect(t.happy_neg, (mid - hw, bar.y, hw, 8), radius=4)
        gui.line(t.muted, (mid, bar.y - 2), (mid, bar.bottom + 1))
        y += 16
        parts = [f"행복도 {r.happy:+.1f}"]
        ww = g.factions[owner].war_weary
        if ww >= 0.05:
            wd = getattr(g.factions[owner], "war_weary_def", 0.0)
            parts.append(f"전쟁 피로 −{ww:.1f}" + (f"(당한 전쟁 {wd:.1f}은 반란 판정 제외)" if wd >= 0.05 else ""))
        if r.conscript > 0:
            parts.append(f"징집 피로 −{r.conscript:.0f} (최근 10턴 중 {g.drafted_turns(node)}턴 징집)")
        elif full and g.drafted_turns(node) >= min(C.CONSCRIPT_PENALTY) - 2:
            parts.append(f"최근 10턴 중 {g.drafted_turns(node)}턴 징집({min(C.CONSCRIPT_PENALTY)}턴부터 징집 피로)")
        y = gui.wrap((x, y - 2), " · ".join(parts), w, 11, t.muted) + 2
        phase, k = g.resist_phase(r)
        if phase:
            rs = r.resist
            if phase == "resist":
                txt = f"저항 {rs['resist'] - k}턴 남음: 산출·생산 없음, 행복도 −100"
            elif phase == "recover":
                txt = f"저항 후 회복 중 ({k - rs['resist'] + 1}/{rs['recover']}턴)"
            else:
                txt = "점령 직후 안정기"
            txt += f" · 반란 없음 {C.RESIST_NO_REBEL_TURNS - k}턴"
            y = gui.wrap((x, y), "점령 저항: " + txt, w, 12, t.warn if phase == "resist" else t.muted) + 4
        if g.rebel_happy(r) <= C.REBEL_THRESHOLD and full and not phase:
            y = kv(gui, x, y, w, "반란 확률", f"{g.rebellion_chance(owner, node)*100:.1f}%/턴", t.bad)
    if full and r.focus:
        y = kv(gui, x, y, w, "생산 집중", f"적용 중 (인구 산출 +{C.FOCUS_POP_BONUS:.0%})" if g.focus_active(r) else "대기 (건설·생산 중)",
               t.good if g.focus_active(r) else t.muted)
    if visible:
        claims = [f"{g.seen_name(o['by'])} 점령 {o['progress']}/{o['need']}턴" for o in r.occs.values()]
        claims += [f"{g.seen_name(rr2.owner)} 편입 {g.project_left(rr2.id)}턴 남음" for rr2 in g.regions.values()
                   if rr2.project and rr2.project.kind == "annex" and rr2.project.key == node]
        claims = list(dict.fromkeys(claims))
        if claims:
            y = gui.wrap((x, y), ("점령·편입 경쟁: " if len(claims) > 1 else "점령·편입: ") + " / ".join(claims)
                         + (" — 먼저 채운 쪽이 차지(같은 턴이면 맞닿은 지역 인구 합이 많은 쪽)" if len(claims) > 1 else ""),
                         w, 12, t.warn) + 4
    # 건물
    y = section(gui, x, y + 6, w, "건물 단계")
    chips = []
    for k in ("farm", "fishery", "factory", "bank", "power", "specialty", "extract", "shelter", "aa"):
        if r.b[k]:
            if k in C.PROD_LEVEL_NAMES:
                chips.append(f"{g.building_name(node, k, r.b[k])}({r.b[k]})")   # 예: 공업 단지(5)
                continue
            nm = ("정유공장" if app.world.regions[node].is_oil else "탄광") if k == "extract" else BUILDING_NAMES[k]
            chips.append(f"{nm} {r.b[k]}")
    for k in ("academy", "airport", "port"):
        if r.b[k]:
            chips.append(BUILDING_NAMES[k])
    for k in C.SCIENCE_STEPS:
        if k in r.sci:
            chips.append(f"★ {C.SCIENCE[k]['name']}")
    for k in C.ECON_STEPS:
        if k in r.econ:
            chips.append(f"★ {C.ECON[k]['name']}")
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
    if info.power_source:
        res.append(power_text(info))
    if info.specialty:
        res += [f"특산물: {sp}" for sp in info.specialties]   # 두 종류면 따로 표기
    if info.scenic:
        res.append(f"자연경관: {info.scenic}")
    if info.coastal:
        res.append("해안: " + ", ".join(app.world.seas[s].name for s in info.seas))
    y = draw_chips(gui, x, y, w, res or ["없음"])
    if full:
        cp = g.crowd_penalty(r)
        t1, t2 = g.crowd_thresholds(node)
        y = section(gui, x, y + 6, w, f"과밀 행복도 {cp:+g}" if cp else "과밀 없음")
        y = draw_chips(gui, x, y, w, [f"인구 {r.pop:.1f} · −2 문턱 {t1:.1f} · −4 문턱 {t2:.1f}"])
        sb = g.scenic_bonus(r)
        if sb:
            src = [app.world.regions[n].scenic for n in app.world.scenic_near[node] if g.regions[n].owner == owner]
            y = section(gui, x, y + 6, w, f"자연경관 행복도 +{sb:g}")
            y = draw_chips(gui, x, y, w, src)
        y = section(gui, x, y + 6, w, f"특산물 공급 {len(r.supplied)}/{C.SPECIALTY_MAX_TYPES}종"
                    + (f" (행복도 턴당 +{C.SPECIALTY_HAPPY_TURN * len(r.supplied):g})" if r.supplied else ""))
        sup = [k + (" (고정)" if k in r.spec_pin else "") for k in sorted(r.supplied)]
        y = draw_chips(gui, x, y, w, sup or ["없음"])
        if owner == pid:
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
        gui.text((x + 20, y + 3), f"{g.seen_name(a.owner)} · {a.label()}", 13, max_w=w - 24)
        if a.owner == pid and gui.hover(rr) and gui.clicked:
            gui.clicked = False
            app.sel_army = a.id
            app.left_open, app.left_tab, app.tab = True, "region", "army"
        y += 26
    # 슬롯
    if full:
        y = section(gui, x, y + 6, w, "진행 중 슬롯")
        p = r.project
        if not p:
            gui.text((x, y), "비어 있음 — [행동] 탭에서 지정" if owner == pid else "비어 있음", 13,
                     t.warn if owner == pid else t.muted)
            y += 22
        else:
            y = draw_project(app, x, y, w, node, p, can_cancel=owner == pid)
    if owner not in (NEUTRAL, pid):
        y += 8
        if gui.button((x, y, w, 32), "외교", "primary", enabled=g.has_met(pid, owner),
                      tooltip=None if g.has_met(pid, owner) else "조우한 적 없는 국가와는 외교할 수 없습니다."):
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


def project_name(app, p, rid=None):
    if p.kind == "build":
        if p.key == "line":
            nm = "해안선" if p.border == "coast" else app.world.regions[p.border].short
            return f"방어선({nm}) {p.level}단계"
        if rid:
            return app.game.build_label(rid, p.key, p.level)
        return f"{BUILDING_NAMES[p.key]} {p.level}단계"
    if p.kind == "unit":
        return f"{C.UNITS[p.key]['name']} 생산"
    if p.kind == "annex":
        return f"편입: {app.world.regions[p.key].name}"
    if p.kind == "science":
        k = C.SCIENCE_STEPS.index(p.key) + 1
        return f"과학 {k}단계: {C.SCIENCE[p.key]['name']}"
    if p.kind == "econ":
        return f"경제 {C.ECON_STEPS.index(p.key) + 2}단계: {C.ECON[p.key]['name']}"
    if p.kind == "capital":
        return "천도"
    return p.kind


def draw_project(app, x, y, w, rid, p, can_cancel=True):
    gui = app.gui
    t = app.theme
    name = project_name(app, p, rid)
    if p.kind == "annex":
        n = app.game.joint_count(app.game.regions[rid].owner, p.key)
        if n > 1:
            name += f" (공동 {n}곳)"
    gui.text((x, y), name, 14, weight="semibold", max_w=w - 70)
    gui.text((x + w, y), f"남은 {app.game.project_left(rid)}턴", 12, t.muted, anchor="topright")
    y += 22
    gui.progress((x, y, w, 8), min(1.0, p.progress / max(1, p.turns)), t.warn if p.stalled else t.accent)
    y += 14
    gui.text((x, y), f"턴당 {p.per_turn:,.0f} · 낸 비용 {p.paid:,.0f}" + (" · 자금 부족으로 정지" if p.stalled else ""),
             12, t.bad if p.stalled else t.muted)
    y += 22
    if not can_cancel:
        return y
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
    y = kv(gui, x, y, w, "해안선 점유", g.seen_name(ctrl) if ctrl is not None else "없음")
    gui.wrap((x, y), "점유 효과: 해안 어장 식량·산출 +25%, 이 해역 해전 방어 +25%", w, 12, t.muted)
    y += 40
    y = kv(gui, x, y, w, "인접 해역", ", ".join(app.world.seas[s].name for s in sea.adj))
    y = section(gui, x, y + 6, w, "해역의 함대")
    for a in g.armies_at(sid):
        if a.owner == g.player_id or g.is_visible(g.player_id, sid) or app.fog_reveal:
            gui.rect(app.faction_rgb(a.owner), (x, y + 5, 10, 12), radius=3)
            r = pygame.Rect(x, y, w, 24)
            gui.text((x + 16, y + 2), f"{g.seen_name(a.owner)} · {a.label()}", 13, max_w=w - 20)
            if a.owner == g.player_id and gui.hover(r) and gui.clicked:
                gui.clicked = False
                app.sel_army = a.id
                app.left_open, app.left_tab, app.tab = True, "region", "army"
            y += 24


# ------------------------------------------------------------------ 우측 패널
def draw_action_tab(app, body):
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    x, w = body.x + 14, body.w - 28
    rid = app.sel
    if not rid or rid in app.world.seas or g.regions[rid].owner != pid:
        gui.text((x, body.y), "내 구역을 선택하면 슬롯을 지정할 수 있습니다.", 13, t.muted)
        idle = [r for r in g.regions_of(pid) if not r.project and not r.occ and not g.resisting(r)]
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
    # 점령 저항 중에는 산출·생산이 없으니 다른 명령은 보이지 않는다
    phase, k = g.resist_phase(r)
    if phase == "resist":
        gui.wrap((x, y), f"점령 저항 중({r.resist['resist'] - k}턴 남음)", w, 14, t.bad)
        return
    # 생산 집중: 건설·병력 생산을 하지 않는 동안 인구 산출 +15%
    on = gui.checkbox((x, y, w, 26), f"생산 집중 (인구 산출 +{C.FOCUS_POP_BONUS:.0%})", r.focus, size=13)
    if on != r.focus:
        ok, msg = g.set_focus(pid, rid, on)
        app.toast(msg)
        app.changed()
    if r.focus:
        state = "적용 중" if g.focus_active(r) else "대기: 건설·생산 중에는 효과 없음"
        gui.text((x + w, y + 4), state, 11, t.good if g.focus_active(r) else t.muted, anchor="topright")
    y += 28
    # 인구 성장 집중: 건설·병력 생산을 하지 않고 실질 행복도 5 이상이면 성장률 +0.5%p
    pf = getattr(r, "pop_focus", False)
    can = pf or g.growth_happy(r) >= C.POP_FOCUS_MIN_H
    on = gui.checkbox((x, y, w - 110, 26), f"인구 성장 집중 (+{C.POP_FOCUS_GROWTH * 100:g}%p/턴)", pf, size=13)
    if on != pf:
        ok, msg = g.set_pop_focus(pid, rid, on)
        app.toast(msg, None if ok else t.bad)
        app.changed()
    if pf:
        state = ("적용 중" if g.pop_focus_active(r) else
                 ("대기: 행복도 5 미만" if g.growth_happy(r) < C.POP_FOCUS_MIN_H else "대기: 건설·생산 중에는 효과 없음"))
        gui.text((x + w, y + 4), state, 11, t.good if g.pop_focus_active(r) else t.muted, anchor="topright")
    elif not can:
        gui.text((x + w, y + 4), "행복도 5 이상 필요", 11, t.muted, anchor="topright")
    y += 32
    if r.project:
        y = draw_project(app, x, y, w, rid, r.project)
        y = section(gui, x, y, w, "슬롯 사용 중 — 완료 후 새 작업 지정")
    if r.occ:
        gui.text((x, y), "점령당하는 중이라 슬롯을 쓸 수 없습니다.", 13, t.bad)
        return
    if r.b["factory"] or r.b["power"]:
        if gui.button((x, y, w, 28), "연료 배정 (국가 현황 › 자원 배정)", size=12):
            app.left_open, app.left_tab = True, "energy"
        y += 36
    if r.project:
        return
    opts = g.options(pid, rid)
    groups = [("편입", [o for o in opts if o["kind"] == "annex"]),
              ("생산 건물", [o for o in opts if o["kind"] == "build" and o["key"] in C.PROD_BUILDINGS]),
              (f"유닛 생산 · 최근 10턴 중 {g.drafted_turns(rid)}턴 징집 ({min(C.CONSCRIPT_PENALTY)}턴부터 징집 피로)",
               [o for o in opts if o["kind"] == "unit"]),
              ("방어·군사 건물", [o for o in opts if o["kind"] == "build" and o["key"] not in C.PROD_BUILDINGS]),
              ("특수", [o for o in opts if o["kind"] in ("science", "econ", "capital")])]
    area = pygame.Rect(body.x, y, body.w, body.bottom - y)
    content = sum(28 + sum(60 if o["kind"] in ("build", "science", "econ") else 44 for o in lst) for _, lst in groups if lst)
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
            if o["kind"] == "build" and o["key"] in C.PROD_LEVEL_NAMES:
                label = g.build_label(rid, o["key"], o["level"])          # 예: '공업 단지 건설'
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
            if o["kind"] == "science":
                eff = ("완료하면 유닛 1개 — 발사대 지역으로 옮긴다" if C.SCIENCE[o["key"]]["unit"]
                       else "완료하면 다음 과학 단계가 열린다")
            if o["kind"] == "econ":
                eff = {"exchange": f"이 지역 은행 산출 +{C.EXCHANGE_BANK_BONUS:.0%}",
                       "sez": "완료하면 국제금융센터가 열린다(우호 관계 필요)",
                       "ifc": f"내 선물의 우호도 효과 +{C.IFC_GIFT_BONUS:.0%}",
                       "currency": "완료하면 경제승리"}[o["key"]]
            if eff:
                gui.text((x, yy + 38), eff, 11, t.good, "semibold", max_w=w - 70, tip=False)
            if gui.button((x + w - 62, yy + 6, 62, 28), "지정", "primary" if o["ok"] else "default",
                          enabled=o["ok"], size=12,
                          tooltip=None if money >= o["per_turn"] else "현재 자금이 턴당 비용보다 적어 정지될 수 있습니다"):
                ok, msg = g.start_project(pid, rid, o["kind"], o["key"], border=o.get("border"))
                app.toast(msg, None if ok else t.bad)
                if ok:
                    app.changed()
            yy += 60 if (o["kind"] in ("build", "science", "econ")) else 44
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


def draw_military_tab(app, body):
    """세로 탭 [군사]: 전체 군사 유닛 수와 유지비 지출만."""
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    x, w = body.x + 14, body.w - 28
    y = body.y + 4
    counts = {}
    for a in g.armies.values():
        if a.owner == pid:
            for k, n in a.units.items():
                counts[k] = counts.get(k, 0) + n
    up = g.upkeep_breakdown(pid)
    total = sum(up.values())
    n_all = sum(counts.values())
    n_army = sum(1 for a in g.armies.values() if a.owner == pid)
    y = kv(gui, x, y, w, "전체 유닛", f"{n_all:,}개 (부대 {n_army}개)")
    y = kv(gui, x, y, w, "유지비 지출", f"{total:,.0f} /턴", t.bad if total else None)
    last = g.player.last
    if last.get("tax"):
        y = kv(gui, x, y, w, "세수 대비", f"{total / last['tax'] * 100:.0f}%")
    y = section(gui, x, y + 10, w, "유닛 종류별 (누르면 부대 목록)")
    cols = (x + w - 150, x + w)
    gui.text((cols[0], y), "수", 11, t.muted, anchor="topright")
    gui.text((cols[1], y), "유지비/턴", 11, t.muted, anchor="topright")
    y += 18
    opened = app.__dict__.setdefault("mil_open", set())
    armies_of = {}
    for a in g.armies.values():
        if a.owner == pid:
            for k in a.units:
                if a.units[k] > 0:
                    armies_of.setdefault(k, []).append(a)
    # 펼친 목록이 길어질 수 있어 아래는 스크롤한다
    rows = []
    for kind, title in (("land", "육군"), ("naval", "해군"), ("air", "공군")):
        keys = [k for k in C.UNIT_ORDER if C.UNITS[k]["kind"] == kind and counts.get(k)]
        if not keys:
            continue
        rows.append(("title", title, 20))
        for k in keys:
            rows.append(("unit", k, 26))
            if k in opened:
                for a in sorted(armies_of.get(k, []), key=lambda a: (-a.units[k], a.id)):
                    rows.append(("army", (k, a), 24))
    area = pygame.Rect(body.x, y, body.w, body.bottom - y - 30)
    content = sum(h for _, _, h in rows) + 8
    off = gui.begin_scroll("military_tab", area, content)
    yy = y - off
    for typ, v, h in rows:
        if typ == "title":
            gui.text((x, yy), v, 12, t.muted, "semibold")
        elif typ == "unit":
            k = v
            row = pygame.Rect(x, yy - 2, w, h - 2)
            if gui.button(row, "", "ghost", selected=k in opened,
                          tooltip="이 병종이 있는 부대 목록 펼치기/접기"):
                opened.symmetric_difference_update({k})
            gui.icon(k, (x + 10, yy + 9), t.text)
            gui.text((x + 26, yy), C.UNITS[k]["name"] + (" ▼" if k in opened else " ▶"), 13)
            gui.text((cols[0], yy), f"{counts[k]:,}", 13, anchor="topright")
            gui.text((cols[1], yy), f"{up.get(k, 0):,.0f}", 13, anchor="topright")
        else:
            k, a = v
            loc = app.world.node_name(a.loc)
            lab = f"{loc} · {C.UNITS[k]['name']} {a.units[k]}" + (f" (부대: {a.label()})" if len(a.units) > 1 else "")
            if a.order or a.goto:
                lab += " ▶"
            clicked = gui.button((x + 18, yy, w - 18, h - 2), "", "ghost",
                                 tooltip="이 부대가 있는 지역의 [부대] 메뉴로 이동")
            gui.text((x + 26, yy + (h - 2) / 2), lab, 11, t.text, anchor="midleft", max_w=w - 30)
            if clicked:
                app.select(a.loc)
                app.sel_army = a.id
                app.left_open, app.left_tab, app.tab = True, "region", "army"
                app.map.center_on(a.loc)
        yy += h
    if not n_all:
        gui.text((x, yy), "군사 유닛이 없습니다.", 13, t.muted)
    gui.end_scroll("military_tab", area, content)
    gui.text((x, body.bottom - 24), "부대 조종: 지도에서 지역을 눌러 [부대] 탭", 11, t.muted)


def draw_army_tiles(app, x, y, w, here, merge):
    """같은 지역 내 부대 목록: 한 줄에 4개까지 정사각형 칸(대표 병종 아이콘·병종·유닛 수).
    합치기 고르기 중이면 칸을 눌러 체크를 켜고 끈다."""
    gui = app.gui
    g = app.game
    t = app.theme
    cols, gap = 4, 6
    size = (w - gap * (cols - 1)) / cols
    for i, a in enumerate(here):
        cx = x + (i % cols) * (size + gap)
        cy = y + (i // cols) * (size + gap)
        rect = pygame.Rect(cx, cy, size, size)
        main = max(a.units, key=lambda k: (C.unit_weight(k) * a.units[k], k)) if a.units else "inf"
        picked = merge is not None and a.id in merge
        selected = a.id == app.sel_army and merge is None
        if gui.button(rect, "", "ghost", selected=selected or picked,
                      tooltip=a.label() + (" (이동 명령 있음)" if a.order or a.goto else "")):
            if merge is not None:
                merge.symmetric_difference_update({a.id})
            else:
                app.sel_army = a.id
                app.split = {}
        lit = selected or picked
        fg = (255, 255, 255) if lit else t.text
        gui.icon(main, (cx + size / 2, cy + size * 0.30), fg, 1.8)
        kinds = len([k for k in a.units if a.units[k] > 0])
        name = C.UNITS[main]["name"] + (f" 외 {kinds - 1}" if kinds > 1 else "")
        gui.text((cx + size / 2, cy + size * 0.58), name, 11, (235, 240, 255) if lit else t.muted, anchor="center",
                 max_w=size - 6)
        gui.text((cx + size / 2, cy + size * 0.80), f"{a.count()}", 16, fg, "bold", anchor="center")
        if a.order or a.goto:
            gui.text((cx + size - 6, cy + 4), "▶", 11, fg if lit else t.accent, anchor="topright")
        if merge is not None:
            box = pygame.Rect(cx + 5, cy + 5, 16, 16)
            gui.rect(t.panel, box, radius=3)
            gui.rect(t.accent if picked else t.border, box, 2, radius=3)
            if picked:
                gui.rect(t.accent, box.inflate(-6, -6), radius=2)
    rows = (len(here) + cols - 1) // cols
    return y + rows * (size + gap)


def draw_army_tab(app, body):
    """지역 패널 [부대]: 선택한 지역에 있는 내 부대만 고르고 조종한다."""
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    x, w = body.x + 14, body.w - 28
    y = body.y
    node = app.sel
    here = sorted([a for a in g.armies_at(node, pid)], key=lambda a: (-g.army_power(a), a.id)) if node else []
    if here and (app.sel_army not in {a.id for a in here}):
        app.sel_army = here[0].id
    # 합치기 고르기 모드: 같은 지역에서만 유지
    merge = getattr(app, "merge_pick", None)
    if merge is not None and (getattr(app, "merge_node", None) != node or len(here) < 2):
        merge = app.merge_pick = None
    if here:
        y = draw_army_tiles(app, x, y, w, here, merge)
        y += 6
    army = g.armies.get(app.sel_army) if app.sel_army else None
    if army and (army.owner != pid or army.loc != node):
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
            left, full = army.hp_left(k), army.hp_max(k)
            stat = f"공{u['atk']:g} 방{u['df']:g}" + (f" 폭{u['bomb']:g}" if u.get("bomb") else "")
            gui.text((x + 22, y + 20), f"{stat} 체 {left:.0f}/{full:g}", 11,
                     t.bad if left < full * 0.5 else t.muted)
            app.split[k] = gui.stepper((x + w - 96, y + 6, 96, 26), min(app.split.get(k, 0), n), 0, n)
            y += 40
        if army.domain() == "naval":
            gui.text((x, y), f"수송 {army.cargo_used()}/{army.cargo_cap()}칸 · 탑재 {army.air_used()}/{army.air_cap()}대",
                     12, t.muted)
            y += 20
        nb = 4 if merge is not None else 3
        bw = (w - 4 * (nb - 1)) / nb
        sel_n = sum(app.split.values())
        if gui.button((x, y, bw, 28), "분리", enabled=sel_n > 0,
                      tooltip="선택한 수량을 새 부대로(남은 체력은 수에 비례해 정수로 나눔)\n"
                              "한 턴 동안 아무것도 하지 않은 부대는 다음 턴 체력 10% 회복"):
            b, msg = g.split_army(army.id, app.split)
            if b:
                app.sel_army = b.id
                app.split = {}
            else:
                app.toast(msg, t.bad)
        others = [a for a in g.armies_at(army.loc, pid) if a.id != army.id]
        go = False
        if merge is not None:
            for k in list(gui.keys):
                if k.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and not gui.focus:
                    gui.keys.remove(k)            # Enter: 고른 부대 합치기(턴 종료로 넘어가지 않게)
                    go = True
                elif k.key == pygame.K_ESCAPE and not gui.focus:
                    gui.keys.remove(k)
                    app.merge_pick = merge = None
        label = "합치기" if merge is None else f"합치기 ({len(merge)})"
        if gui.button((x + bw + 4, y, bw, 28), label, "primary" if merge is not None else "default",
                      enabled=bool(others),
                      tooltip="누르면 부대 칸에 체크 상자가 생깁니다. 합칠 부대를 고른 뒤 Enter나 [합치기]를 한 번 더\n"
                              "누르면 고른 부대만 하나로 합칩니다(같은 유닛끼리 남은 체력 합산). Esc: 취소"):
            if merge is None:
                app.merge_pick, app.merge_node = {army.id}, node
                merge = app.merge_pick
            else:
                go = True
        if merge is not None and gui.button((x + 2 * bw + 8, y, bw, 28), "모두 합치기", size=12,
                                            tooltip="이 지역의 내 부대를 모두 하나로 합칩니다"):
            app.merge_pick = merge = {a.id for a in here}
            go = True
        if go and merge is not None:
            ids = [a.id for a in here if a.id in merge]
            if len(ids) < 2:
                app.toast("합칠 부대를 두 개 이상 고르세요.", t.bad)
            else:
                base = army.id if army.id in ids else ids[0]
                for o in ids:
                    if o != base:
                        ok, msg = g.merge_armies(base, o)
                        if not ok:
                            app.toast(msg, t.bad)
                app.sel_army = base
                app.toast(f"부대 {len(ids)}개를 합쳤습니다.")
            app.merge_pick = None
        if gui.button((x + (nb - 1) * (bw + 4), y, bw, 28), "해산", "danger", enabled=sel_n > 0,
                      tooltip="선택한 수량 해산 (자국 영토면 행복도 +)"):
            g.disband(army.id, app.split)
            app.split = {}
            if army.id not in g.armies:
                app.sel_army = None
                return
        y += 38
        ship = g.boarding_target(army.id)
        if ship is not None:
            what = "상륙함" if army.domain() == "land" else "항공모함"
            if gui.button((x, y - 4, w, 30), f"탑승 ({what} 부대 #{ship.id})", "primary",
                          tooltip=f"이 부대를 같은 지역에 주둔한 {what}에 태웁니다(수송·탑재 칸 안에서)"):
                ok, msg, fleet = g.board(army.id)
                app.toast(msg, None if ok else t.bad)
                if ok:
                    app.sel_army = fleet.id
                    app.split = {}
                    return
            y += 34
        gui.text((x, y + 6), "공격 방식", 12, t.muted)
        if g.mods(pid).value("no_surprise"):
            app.attack_mode = "assault"
            gui.text((x + 70, y + 6), f"돌격만 가능 — {g.fx_source(pid, 'no_surprise')}", 12, t.muted)
        else:
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
                gui.text((x, y), f"최종 목적지: {app.world.node_name(army.goto)}", 12, t.muted)
                y += 22
        else:
            gui.wrap((x, y), "지도에서 우클릭으로 이동·공격 대상을 지정하세요. 진한 색은 자국 영토 2칸, 옅은 색은 1칸, 점선은 연륙교입니다. "
                             "범위 밖을 우클릭하면 최단 경로로 여러 턴에 걸쳐 자동 이동합니다.",
                     w, 12, t.muted)
            y += 78
    else:
        gui.text((x, y), "이 지역에 내 부대가 없습니다.", 13, t.muted)


def draw_nation_tab(app, body):
    gui = app.gui
    g = app.game
    t = app.theme
    f = g.player
    pid = f.id
    x, w = body.x + 14, body.w - 28
    area = pygame.Rect(body.x, body.y, body.w, body.h)
    content = getattr(app, "_nation_tab_h", 1500)
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
    eff = g.tax_happy(pid, val)
    gui.text((x, y), f"예상 세수 {gdp * val / 100:,.0f}/턴 · 행복도 {eff:+.1f}/턴" + (" · 잠김" if locked else ""), 12, t.muted)
    y += 24
    # 자원 시장
    y = section(gui, x, y + 4, w, "자원 시장 (구매/판매가, 같은 턴 추가 구매 +10%)")
    for res in C.RESOURCES:
        gui.text((x, y + 5), C.RESOURCE_NAMES[res], 13, weight="semibold")
        gui.text((x + 40, y + 5), f"{f.res.get(res, 0):,.0f}", 13)
        bp, sp = g.buy_price(pid, res), g.sell_price(pid, res)
        gui.text((x + 96, y + 5), f"{bp:,.0f}/{sp:,.0f}", 11, t.muted)
        bx = x + w - 112
        name = C.RESOURCE_NAMES[res]
        from . import modals

        def do_buy(n, res=res, name=name):
            k, s_ = g.market_buy(pid, res, n)
            app.toast(f"{name} {k}개 구매 ({s_:,.0f})")

        def do_sell(n, res=res, name=name):
            k, s_ = g.market_sell(pid, res, n)
            app.toast(f"{name} {k}개 판매 (+{s_:,.0f})")
        energy = res in C.UNBUYABLE
        if gui.button((bx, y, 54, 24), "구매", size=11, enabled=not energy,
                      tooltip="석유·석탄은 돈으로 살 수 없습니다(판매만)" if energy
                      else f"최대 {g.max_buyable(pid, res):,}개까지"):
            modals.open_qty(app, f"{name} 구매", g.max_buyable(pid, res), 0, do_buy,
                            preview=lambda n, res=res: f"비용 {g.buy_cost(pid, res, n):,.0f} (자금 {f.money:,.0f})",
                            ok_label="구매")
        if gui.button((bx + 58, y, 54, 24), "판매", size=11, tooltip=f"보유 {int(f.res.get(res, 0)):,}개"):
            modals.open_qty(app, f"{name} 판매", int(f.res.get(res, 0)), 0, do_sell,
                            preview=lambda n, sp=sp: f"수입 +{n * sp:,.0f}", ok_label="판매")
        y += 30
    f.auto_food = gui.checkbox((x, y, w, 24), "식량 부족 시 자동 구매", f.auto_food)
    y += 26
    y += 4
    # 특산물
    stock = {k: v for k, v in f.specialty.items() if v > 0}
    supplied = sum(len(r.supplied) for r in g.regions_of(pid))
    y = section(gui, x, y, w, f"특산물 (재고 {sum(stock.values())}개 · 공급 {supplied}건, 자동 배분)")
    f.auto_specialty = gui.checkbox((x, y, w - 110, 24), "행복도 낮은 지역부터 자동", f.auto_specialty, size=12)
    if gui.button((x + w - 100, y - 2, 100, 26), "배분 수정", size=12):
        app.spec_sel = app.sel if app.sel in g.regions and g.regions[app.sel].owner == pid else None
        app.modal = ("specialty", None)
    y += 30
    # 지출 우선순위 (드래그)
    items = g.projects_by_priority(pid)
    y = section(gui, x, y + 6, w, "지출 우선순위 (드래그, 또는 클릭 후 ↑↓)")
    bw2 = (w - 4) / 2
    for i, (mode, lab) in enumerate(g.PRIORITY_SORTS.items()):
        if gui.button((x + (i % 2) * (bw2 + 4), y + (i // 2) * 32, bw2, 28), lab, size=11, enabled=bool(items),
                      tooltip=f"{lab}으로 자동 정렬"):
            g.sort_priority(pid, mode)
            items = g.projects_by_priority(pid)
            app.toast(f"지출 우선순위: {lab}")
    y += 68
    gui.text((x, y - 2), "자금이 모자라면 위에서부터 비용을 내고 아래 작업이 정지됩니다.", 11, t.muted)
    y += 20
    y = draw_priority_list(app, x, y, w, items)
    gui.text((x, y + 6), "국가 통계·재정·특산물 재고는 [국가 현황] 탭에 있습니다.", 11, t.muted)
    y += 34
    app._nation_tab_h = y - y0
    gui.end_scroll("nation", area, y - y0)


def draw_diplo_tab(app, body):
    """세력 목록. 세력을 누르면 국기·초상화·관계가 담긴 상세 화면."""
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    view = getattr(app, "dip_view", None)
    if view is not None and 0 <= view < len(g.factions) and g.factions[view].alive and view != pid:
        draw_diplo_detail(app, body, view)
        return
    app.dip_view = None
    x, w = body.x + 14, body.w - 28
    others = [o for o in g.factions if o.id != pid and o.alive]
    area = pygame.Rect(body.x, body.y, body.w, body.h)
    off = gui.begin_scroll("diplo", area, len(others) * 50 + 10)
    y = body.y - off
    y0 = y
    for o in others:
        st = D.stage(g, o.id, pid)
        op = D.opinion(g, o.id, pid)
        if gui.button((x - 4, y, w + 8, 46), "", "ghost", tooltip="눌러서 상세 보기"):
            app.dip_view = o.id
            app.war_confirm = None
        draw_flag(gui, (x, y + 9, 42, 28), faction_flag(o))
        if not g.has_met(pid, o.id):            # 조우하지 않은 국가: 국기(지도 공개면 국가명까지)만
            gui.text((x + 52, y + 5), g.seen_name(o.id), 13, t.muted, "semibold", max_w=w - 60)
            gui.text((x + 52, y + 24), g.UNKNOWN_LEADER + " · 조우한 적 없음", 11, t.muted, max_w=w - 60)
            y += 50
            continue
        gui.text((x + 52, y + 5), o.name, 13, weight="semibold", max_w=w - 60)
        origin = f" · {g.seen_name(o.rebel_of)}에서 독립" if o.rebel_of is not None else ""
        decl = " · 우호 선언" if D.declared_friends(g, pid, o.id) and st < 2 else ""
        gui.text((x + 52, y + 24), f"{o.leader_name} · {D.STAGE_NAMES[st]}{decl} · 우호 {op:+.0f}{origin}", 11,
                 t.bad if st == -1 else t.muted, max_w=w - 60)
        y += 50
    if not others:
        gui.text((x, y), "다른 세력이 없습니다.", 13, t.muted)
    gui.end_scroll("diplo", area, y - y0)


def stage_color(t, st):
    return {-1: t.bad, 3: t.good, 4: t.good}.get(st, t.text if st > 0 else t.muted)


def draw_diplo_detail(app, body, fid):
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    o = g.factions[fid]
    x, w = body.x + 14, body.w - 28
    area = pygame.Rect(body.x, body.y, body.w, body.h)
    others = [f for f in g.factions if f.alive and f.id != fid]
    known = g.has_met(pid, fid)                  # 조우하지 않았으면 국기 말고는 가린다
    off = gui.begin_scroll("diplo_detail", area, getattr(app, "_dip_h", 600))
    y = body.y - off
    y0 = y
    if gui.button((x - 4, y, 72, 26), "‹ 목록", "ghost", size=12):
        app.dip_view = None
        gui.end_scroll("diplo_detail", area, 0)
        return
    y += 32
    # 상단: 국기 + 국가명
    draw_flag(gui, (x, y, 60, 40), faction_flag(o))
    gui.text((x + 72, y), g.seen_name(fid), 19, weight="bold", max_w=w - 72)
    sub = f"{o.leader_name} · {GOV_BY_KEY.get(o.gov, {}).get('name', '체제 미정')}" if known else g.UNKNOWN_LEADER
    gui.text((x + 72, y + 25), sub, 12, t.muted, max_w=w - 72)
    y += 52
    # 좌: 초상화(3:4), 우: 수도·관계·우호도
    pw, ph = 120, 160
    draw_portrait(gui, (x, y, pw, ph), o.leader if known else "__unknown__", t)
    rx, rw = x + pw + 14, w - pw - 14
    st = D.stage(g, fid, pid)
    op = D.opinion(g, fid, pid)
    rel = D.STAGE_NAMES[st]
    if st == -1:
        rel += f" (전쟁 점수 {D.war_score(g, pid, fid):+.1f})"
    pl = D.peace_left(g, pid, fid)
    cap = app.world.regions[o.capital].name if o.capital in app.world.regions else "없음"
    rows = [("수도", cap, None), ("관계", rel, stage_color(t, st)),
            ("우호도 (상대 → 나)", f"{op:+.1f}", t.good if op >= 0 else t.bad)]
    if not known:
        cap_txt = cap if g.knows_name(pid, fid) else "알 수 없음"     # 지도 공개: 국가명·수도만 공개
        rows = [("수도", cap_txt, None if g.knows_name(pid, fid) else t.muted), ("관계", "조우한 적 없음", t.muted),
                ("우호도 (상대 → 나)", "?", t.muted)]
    if pl:
        rows.append(("강화 불가침", f"{pl}턴 남음", None))
    ry = y + 2
    for k, v, vc in rows:
        gui.text((rx, ry), k, 11, t.muted)
        gui.text((rx, ry + 15), v, 14, vc or t.text, "semibold", max_w=rw)
        ry += 40
    y += ph + 14
    # 통계
    cw = (w - 16) / 3
    stats = (("인구", f"{g.total_pop(fid):,.0f}만"), ("지역 수", f"{g.region_count(fid)}곳"),
             ("GDP", f"{o.last.get('gdp', g.gdp(fid)):,.0f}"))
    if not known:
        stats = (("인구", "?"), ("지역 수", "?"), ("GDP", "?"))
    for i, (k, v) in enumerate(stats):
        cell = pygame.Rect(x + i * (cw + 8), y, cw, 48)
        gui.rect(t.panel_alt, cell, radius=6)
        gui.text((cell.centerx, cell.y + 6), k, 11, t.muted, anchor="midtop")
        gui.text((cell.centerx, cell.y + 23), v, 14, weight="bold", anchor="midtop", max_w=cell.w - 6)
    y += 60
    # 타국과의 관계
    gui.text((x, y), "타국과의 관계", 13, weight="bold")
    y += 22
    if not known:
        gui.text((x, y), "조우한 적이 없어 알려진 정보가 없습니다.", 12, t.muted)
        y += 22
        others = []
    for f in others:
        s2 = D.stage(g, fid, f.id)
        draw_flag(gui, (x, y + 2, 24, 16), faction_flag(f))
        gui.text((x + 32, y + 1), g.seen_name(f.id) + (" (나)" if f.id == pid else ""), 12, max_w=w - 140)
        gui.text((x + w, y + 1), D.STAGE_NAMES[s2], 12, stage_color(t, s2), "semibold", anchor="topright")
        y += 22
    y += 12
    # 외교 / 선전포고
    bw = (w - 8) / 2
    unmet_tip = "조우한 적 없는 국가와는 외교할 수 없습니다." if not known else None
    if gui.button((x, y, bw, 40), "외교", "primary", size=14, enabled=known, tooltip=unmet_tip):
        app.war_confirm = None
        app.open_diplomacy(fid)
    can_war = st != -1 and not D.has_nonaggr(g, pid, fid) and known
    if not known:
        tip = unmet_tip
    elif st == -1:
        tip = "이미 전쟁 중입니다."
    elif not can_war:
        tip = "불가침·동맹 중에는 먼저 외교 창에서 파기해야 합니다."
    else:
        tip = (f"전쟁 피로도 +{C.WAR_WEARY_START['aggressor']:.0f}(전쟁 중 턴당 +{C.WAR_WEARY_TURN['aggressor']:g}), "
               f"상대 우호도 -100,\n전쟁광 평판: 다른 모든 세력 우호도 {D.warmonger_penalty(g, pid):+.0f}\n"
               "한 번 더 눌러야 선포됩니다.")
    confirm = getattr(app, "war_confirm", None) == fid and can_war
    if gui.button((x + bw + 8, y, bw, 40), "정말 선전포고?" if confirm else "선전포고", "danger", size=14,
                  enabled=can_war, tooltip=tip):
        if confirm:
            app.war_confirm = None
            ok, msg = D.declare_war(g, pid, fid)
            app.toast(msg or f"{o.name}에 선전포고했습니다.", t.bad)
            app.changed()
        else:
            app.war_confirm = fid
    y += 52
    app._dip_h = y - y0
    gui.end_scroll("diplo_detail", area, y - y0)


# ------------------------------------------------------------------ 좌측 [국가 현황]
PROJECT_KIND_NAMES = {"build": "건설", "unit": "병력 생산", "annex": "편입", "science": "과학", "econ": "경제",
                      "capital": "천도"}


def power_text(info) -> str:
    """'수력(충주댐) 1/턴', '원자력(고리) 3/턴', '화력(당진)'(화력발전소 소재지는 발전소 1단계로 시작)."""
    if info.power_self:
        return f"{info.power_source} {info.power_self}/턴"
    return info.power_source


def econ_progress_text(g, pid) -> str:
    """'1/5 · 증권거래소 1/3곳(수도 포함)' 형식: 지금 단계와 다음에 필요한 것."""
    st = g.econ_stage(pid)
    head = f"{st}/{C.ECON_STAGES}"
    if st == 0:
        return f"{head} · 금융 단지 {len(g.finance_cluster(pid))}/{C.ECON_CLUSTER}곳"
    if st == 1:
        return f"{head} · {g.econ_ready(pid, 'sez')[1]}"
    if st >= C.ECON_STAGES:
        return f"{head} · 기축통화 지정 완료"
    step = C.ECON_STEPS[st - 1]                 # 2 → 경제특구, 3 → 국제금융센터, 4 → 기축통화
    busy = g.econ_busy(pid, step)
    if busy is not None:
        return f"{head} · {C.ECON[step]['name']} 건설 중({g.project_left(busy)}턴 남음)"
    ok, why = g.econ_ready(pid, step)
    return f"{head} · {C.ECON[step]['name']}" + (" 건설 가능" if ok else f" — {why}")


def science_progress_text(g, pid) -> str:
    """'0/8 · 항공우주연구소 건설(수도)' 형식. 8단계는 발사대에 부품 3종(추진체·탑승 모듈·연료) 집결."""
    f = g.factions[pid]
    total = len(C.SCIENCE_STEPS) + 1
    done = sum(1 for st in C.SCIENCE_STEPS if st in f.science)
    nxt = next((st for st in C.SCIENCE_STEPS if st not in f.science), None)
    if nxt is not None:
        spec = C.SCIENCE[nxt]
        return f"{done}/{total} · {spec['name']} {spec.get('verb') or ('생산' if spec['unit'] else '건설')}({spec['where']})"
    lost = [C.SCIENCE[k]["name"] for k in C.SCIENCE_UNITS if not g.science_units_alive(pid).get(k)]
    if lost:
        return f"{done}/{total} · 잃은 부품 다시 생산: " + ", ".join(lost)
    return f"{done}/{total} · 발사대에 부품 3종(추진체·탑승 모듈·연료) 집결"


def draw_victory_progress(app, x, y, w, pid):
    """승리 조건별 진행 상황(국가 현황)."""
    g, gui, t = app.game, app.gui, app.theme
    vs = g.settings.victories
    f = g.factions[pid]
    if "conquest" in vs:
        cs = g.conquest_status(pid)
        txt = f"{cs['have']} / {cs['need']}곳"
        if cs["risky"] is not None:
            txt += f" · 반란 가능 지역 {cs['risky']}곳"
        y = kv(gui, x, y, w, "정복승리(2/3 + 반란 없음)", txt, t.good if cs["ok"] else None)
    if "science" in vs:
        y = kv(gui, x, y, w, "과학승리", science_progress_text(g, pid))
    if "economic" in vs:
        y = kv(gui, x, y, w, "경제승리", econ_progress_text(g, pid))
    if "diplomatic" in vs:
        alive = g.alive_ids()
        cid = D.coalition_of(g, pid)
        n = len(g.dip.coalitions[cid]["members"] & set(alive)) if cid is not None else 1
        y = kv(gui, x, y, w, "외교승리(모두 한 연합)", f"내 연합 {n} / 생존 {len(alive)}개국")
    if "time" in vs:
        sc = g.time_scores()
        rank = sorted(sc, key=lambda k: -sc[k]).index(pid) + 1 if pid in sc else "-"
        left = max(0, getattr(g.settings, "max_turns", C.TIME_VICTORY_TURNS) - g.turn)
        y = kv(gui, x, y, w, "시간 종료 점수", f"{sc.get(pid, 0):.1f}점 · {rank}위 · {left}턴 남음")
    return y


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
    y = kv(gui, x, y, w, "평균 행복도", f"{g.avg_happiness(pid, effective=False):+.1f} "
                                        f"(실질 {g.avg_happiness(pid):+.1f})")
    ww = f.war_weary
    if D.enemies(g, pid):
        rec = f"전쟁 중 턴당 +{D.war_weary_rate(g, pid):.1f}"
    else:
        rec = f"평시 턴당 {C.WAR_WEARY_RECOVERY:.0f} 회복" if ww > 0 else "평시"
    y = kv(gui, x, y, w, "전쟁 피로도", f"{ww:.1f} / {C.WAR_WEARY_MAX:.0f} ({rec})", t.bad if ww >= 1 else None)
    if f.war_weary_def >= 0.05:
        y = kv(gui, x, y, w, "  그중 당한 전쟁", f"{f.war_weary_def:.1f} (반란 판정에서는 빼지 않음)")
    morale = g.morale(pid)
    if morale < 1:
        y = kv(gui, x, y, w, "군 사기", f"전투력 ×{morale:.2f} (실질 평균 행복도 −10 이하)", t.bad)
    y = kv(gui, x, y, w, "군 전력", f"{g.mil_power(pid):,.0f}")
    y = draw_victory_progress(app, x, y, w, pid)
    lead = LEADER_BY_KEY[f.leader]
    gov = GOV_BY_KEY.get(f.gov, {})
    y = gui.wrap((x, y + 2), f"지도자 {lead['name']}: {lead['buff'][0]}({lead['buff'][1]}) / "
                 f"{lead['debuff'][0]}({lead['debuff'][1]})", w, 11, t.muted)
    if gov:
        buff = gov['buff'][1]
        if gov_buff_scale(f.leader) != 1.0 and gov.get("buff_keys"):
            buff = f"{buff} ({lead['debuff'][0]}: 효과 {gov_buff_scale(f.leader):.0%})"
        y = gui.wrap((x, y), f"체제 {gov['name']}: {buff} / {gov['debuff'][1]}", w, 11, t.muted)
    # 재정
    items = g.projects_by_priority(pid)
    spend = {}
    for rr in items:
        k = rr.project.kind
        n, s = spend.get(k, (0, 0.0))
        spend[k] = (n + 1, s + rr.project.per_turn)
    total_spend = sum(s for _, s in spend.values())
    y = section(gui, x, y + 6, w, "재정 (지난 턴 실제 수입·지출)")
    y = kv(gui, x, y, w, "자금", f"{f.money:,.0f}", t.bad if f.money < 0 else None)
    spent = last.get("spend", {})
    income = last.get("tax", 0) + last.get("sell", 0) + last.get("refund", 0)
    outgo = last.get("upkeep", 0) + last.get("buy", 0) + sum(spent.values())
    y = kv(gui, x, y, w, "수입 합계", f"+{income:,.0f}", t.good)
    y = kv(gui, x, y, w, "  세수", f"+{last.get('tax', 0):,.0f} (세율 {f.tax*100:.0f}%)")
    if last.get("sell", 0):
        y = kv(gui, x, y, w, "  시장 판매", f"+{last.get('sell', 0):,.0f}")
    if last.get("refund", 0):
        y = kv(gui, x, y, w, "  환급", f"+{last.get('refund', 0):,.0f}")
    y = kv(gui, x, y, w, "지출 합계", f"−{outgo:,.0f}", t.bad)
    y = kv(gui, x, y, w, "  군 유지비", f"−{last.get('upkeep', 0):,.0f}")
    if last.get("buy", 0):
        y = kv(gui, x, y, w, "  시장 구매(식량 자동 구매 포함)", f"−{last.get('buy', 0):,.0f}")
    for k in ("build", "unit", "annex", "science", "econ", "capital"):
        if spent.get(k):
            y = kv(gui, x, y, w, f"  {PROJECT_KIND_NAMES[k]}", f"−{spent[k]:,.0f}")
    y = kv(gui, x, y, w, "턴당 순수익", f"{last.get('net', 0):+,.0f}", t.good if last.get("net", 0) >= 0 else t.bad)
    y = section(gui, x, y + 6, w, "이번 턴 예정 작업 지출")
    for k in ("build", "unit", "annex", "science", "econ", "capital"):
        if k in spend:
            n, s_ = spend[k]
            y = kv(gui, x, y, w, f"{PROJECT_KIND_NAMES[k]} {n}건", f"−{s_:,.0f}")
    y = kv(gui, x, y, w, "합계", f"−{total_spend:,.0f}" if total_spend else "0", t.bad if total_spend > f.money else None)
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
                app.left_open = True
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
        gui.text((row.x + 8, row.y + 3), f"{i + 1}. {app.world.regions[rid].short} · {project_name(app, p, rid)}", 12, fg,
                 "semibold", max_w=w - 16)
        state = "정지" if p.stalled else f"남은 {app.game.project_left(rid)}턴"
        if p.kind == "annex":
            jn = app.game.joint_count(rr.owner, p.key)
            if jn > 1:
                state += f" · 공동 {jn}곳 −{R.joint_reduction(jn):.0%}"
        gui.text((row.x + 8, row.y + 21), f"턴당 {p.per_turn:,.0f} · {state}", 11,
                 (t.bad if p.stalled and not dragged else sub))
        gui.text((row.right - 8, row.centery), "≡", 16, sub, anchor="midright")
    # 놓기: 움직였으면 순서 변경, 제자리면 그 행을 고른다(↑↓로 이동)
    if drag is not None and not gui.down:
        app.prio_drag = None
        if order != ids:
            g.set_priority_order(g.player_id, order)
            gui.clicked = False
            app.toast(f"우선순위 변경: {app.world.regions[drag].short} → {order.index(drag) + 1}번")
        else:
            app.prio_sel = None if app.prio_sel == drag else drag
    sel = getattr(app, "prio_sel", None)
    if sel in ids and drag is None:
        i = ids.index(sel)
        gui.rect(t.accent, pygame.Rect(x, top + i * row_h, w, row_h - 4), 2, radius=8)
        app.arrow_capture_v = True                # ↑↓를 누르고 있어도 지도는 위아래로 움직이지 않는다
        for k in list(gui.keys):
            if k.key in (pygame.K_UP, pygame.K_DOWN) and not gui.focus:
                gui.keys.remove(k)                 # 지도 이동 대신 순서 이동
                j = i + (-1 if k.key == pygame.K_UP else 1)
                if 0 <= j < n:
                    new = ids[:]
                    new[i], new[j] = new[j], new[i]
                    g.set_priority_order(g.player_id, new)
                    ids, i = new, j
            elif k.key == pygame.K_ESCAPE:
                gui.keys.remove(k)
                app.prio_sel = None
    elif sel is not None and sel not in ids:
        app.prio_sel = None
    return top + n * row_h + 4


# ------------------------------------------------------------------ 자원 배정
def draw_energy_tab(app, body):
    """공장·발전소 연료 배정과 이번 턴 에너지 흐름(채굴 → 발전소 → 전기 → 공장)."""
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    f = g.player
    x, w = body.x + 14, body.w - 28
    y = body.y + 4
    if f.auto_energy:
        g.set_auto_energy(pid, False)        # 예전 세이브: 지금 자동안을 수동 배정으로 옮긴다
    if gui.button((x, y - 2, 120, 28), "자동 배정", "primary", size=12,
                  tooltip="턴마다 생산되는 양(채굴·자체 발전) 기준으로 배정합니다(다음에 누를 때까지 유지).\n"
                          "우선순위: ① 발전소에 석유 → ② 발전소에 석탄 → ③ 공장에 전기 → ④ 공장에 석탄 → "
                          "⑤ 공장에 석유\n발전소·공장 모두 단계가 높은 곳부터 채웁니다."):
        units, cap = g.assign_energy(pid)
        app.toast(f"자원 자동 배정: 공장 연료 {units}/{cap}")
        app.changed()
    gui.text((x + 130, y + 12), "배정은 아래에서 직접 고칠 수 있습니다", 11, t.muted, anchor="midleft", max_w=w - 130)
    y += 30
    plan = g.energy_plan(pid)
    plants, facts = g.energy_sites(pid)
    flow_h = 236
    area = pygame.Rect(body.x, y, body.w, body.bottom - y - flow_h)
    row_h = 54
    content = 30 + len(plants) * row_h + 30 + len(facts) * row_h + 10
    off = gui.begin_scroll("energy", area, content)
    yy = y - off

    def steppers(r, site, keys, cap, used):
        nonlocal yy
        cur = (r.energy or {}).get(site, {}) if not f.auto_energy else {}
        sw = (w - 8 * (len(keys) - 1)) / len(keys)
        for i, (key, label) in enumerate(keys):
            bx = x + i * (sw + 8)
            gui.text((bx, yy + 22), label, 11, t.muted)
            if f.auto_energy:
                gui.text((bx + 34, yy + 22), f"{used.get(key, 0)}", 12, t.text, "semibold")
                continue
            v = cur.get(key, 0)
            others = sum(cur.get(k, 0) for k, _ in keys if k != key)
            nv = gui.stepper((bx + 30, yy + 20, sw - 30, 24), v, 0, max(0, cap - others), size=11)
            if nv != v:
                g.set_energy(pid, r.id, site, key, nv)
                app.changed()

    yy = section(gui, x, yy, w, f"발전소 {len(plants)}곳 · 연료 최대 {sum(r.b['power'] for r in plants)}/턴 "
                 f"(석탄→전기 {C.POWER_ELEC['coal']}, 석유→{C.POWER_ELEC['oil']})")
    for r in plants:
        u = plan["plants"].get(r.id, {})
        gui.text((x, yy), f"{app.world.regions[r.id].name} · {r.b['power']}단계", 12, weight="semibold", max_w=w - 90)
        gui.text((x + w, yy), f"전기 +{u.get('elec_out', 0)}", 12, t.good if u.get("elec_out") else t.muted,
                 anchor="topright")
        steppers(r, "p", (("coal", "석탄"), ("oil", "석유")), r.b["power"], u)
        yy += row_h
    if not plants:
        gui.text((x, yy), "발전소가 없습니다.", 12, t.muted)
        yy += 24
    yy = section(gui, x, yy + 6, w, f"공장 {len(facts)}곳 · 연료 최대 {sum(r.b['factory'] for r in facts)}/턴 (종류 무관)")
    for r in facts:
        u = plan["factories"].get(r.id, {})
        lv = r.b["factory"]
        per = C.FACTORY_UNIT_OUTPUT[min(lv, 5) - 1]
        gui.text((x, yy), f"{app.world.regions[r.id].name} · {lv}단계 · 1개당 {per:,}", 12, weight="semibold",
                 max_w=w - 70)
        gui.text((x + w, yy), f"{u.get('units', 0)}/{lv}", 12, t.good if u.get("units") == lv else t.warn,
                 anchor="topright")
        steppers(r, "f", (("elec", "전기"), ("coal", "석탄"), ("oil", "석유")), lv, u)
        yy += row_h
    if not facts:
        gui.text((x, yy), "공장이 없습니다.", 12, t.muted)
    gui.end_scroll("energy", area, content)
    # ---- 에너지 흐름표 (이번 턴 예상, 실제 처리와 같은 순서)
    fy = body.bottom - flow_h + 6
    gui.line(t.border, (x, fy - 4), (x + w, fy - 4))
    cols = [x + w - 150, x + w - 95, x + w - 40]
    gui.text((x, fy), "에너지 흐름 (이번 턴)", 13, weight="bold")
    for cx, nm in zip(cols, ("석탄", "석유", "전기")):
        gui.text((cx + 40, fy + 2), nm, 11, t.muted, anchor="topright")
    fy += 22
    p_coal = sum(a["coal"] for a in plan["plants"].values())
    p_oil = sum(a["oil"] for a in plan["plants"].values())
    p_elec = sum(a["elec_out"] for a in plan["plants"].values())
    fu = {k: sum(a[k] for a in plan["factories"].values()) for k in ("coal", "oil", "elec")}
    st, mi, af = plan["stock"], plan["mined"], plan["after"]
    rows = [("재고", (st["coal"], st["oil"], st["elec"]), False),
            ("① 채굴·자체 발전", (mi["coal"], mi["oil"], mi["elec"]), True),
            ("② 발전소 투입", (-p_coal, -p_oil, 0), True),
            ("③ 발전", (0, 0, p_elec), True),
            ("④ 공장 투입", (-fu["coal"], -fu["oil"], -fu["elec"]), True),
            ("턴 뒤 재고", (af["coal"], af["oil"], af["elec"]), False)]
    for label, vals, signed in rows:
        bold = not signed
        gui.text((x, fy), label, 12, t.text if bold else t.muted, "semibold" if bold else "regular")
        for cx, v in zip(cols, vals):
            if signed and not v:
                txt, col = "·", t.muted
            else:
                txt = f"{v:+,.0f}" if signed else f"{v:,.0f}"
                col = (t.good if v > 0 else t.bad) if signed else t.text
            gui.text((cx + 40, fy), txt, 12, col, "semibold" if bold else "regular", anchor="topright")
        fy += 20
        if label in ("재고", "④ 공장 투입"):
            gui.line(t.border, (x, fy - 2), (x + w, fy - 2))
    units = sum(a["units"] for a in plan["factories"].values())
    cap = sum(r.b["factory"] for r in facts)
    m = g.mods(pid)
    out = sum(R.factory_output(r.b["factory"], plan["factories"][r.id]["units"]) for r in facts)
    full = sum(R.factory_output(r.b["factory"]) for r in facts)
    mult = m.mult("output_factory") * m.mult("output_prod")
    gui.text((x, fy + 4), f"공장 연료 {units}/{cap} → 산출 {out * mult:,.0f}/턴", 12,
             t.good if units >= cap else t.warn, "semibold", max_w=w)
    if units < cap:
        gui.text((x, fy + 22), f"연료가 차면 {full * mult:,.0f}/턴", 11, t.muted)
