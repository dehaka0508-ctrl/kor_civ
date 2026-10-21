"""좌측 구역 정보 패널, 우측 행동·부대·국가 탭."""
from __future__ import annotations

import math

import pygame

from .. import config as C
from .. import diplomacy as D
from .. import metro as M
from .. import rules as R
from ..leaders import GOV_BY_KEY, LEADER_BY_KEY, gov_buff_scale
from ..state import BUILDING_NAMES, NEUTRAL
from ..flags import faction_flag
from .art import draw_flag, draw_portrait
from .theme import fmt_money, hex2rgb, measure, mix
from ..text import josa


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
    """소제목: 명조 쪽빛 글자 + 오른쪽으로 이어지는 금빛 선."""
    t = gui.t
    r = gui.text((x, y), title, 13, t.accent if not t.dark else t.gold_lt, "serif", max_w=w - 20)
    if r.right + 10 < x + w - 8:
        gui.line(mix(t.gold, t.panel, 0.25), (r.right + 10, y + 9), (x + w - 8, y + 9))
        gui.rect(t.gold, (x + w - 6, y + 6, 6, 6))
    return y + 26


def kv(gui, x, y, w, k, v, vcol=None):
    """이름 ······ 값 (장부식 점선)."""
    t = gui.t
    kr = gui.text((x, y), k, 13, t.muted)
    vr = gui.text((x + w, y), v, 13, vcol or t.text, "semibold", anchor="topright")
    x0, x1 = kr.right + 8, vr.x - 8
    if x1 - x0 > 12:
        col = mix(t.border, t.text, 0.12)
        yy = y + 13
        for dx in range(int(x0), int(x1), 6):
            gui.rect(col, (dx, yy, 1.5, 1.5))
    return y + 21


# ------------------------------------------------------------------ 좌측 패널
# 좌측 세로 탭(위에서부터): 키, 이름, 설명
SIDE_TABS = (("nation", "내정", "세율·자원 시장·특산물·지출 우선순위"), ("diplo", "외교", "세력별 관계·외교 창"),
             ("army", "군사", "전체 군사 유닛 수·유지비"), ("energy", "자원\n배정", "공장·발전소 연료 배정"),
             ("progression", "정책\n과학", "행정력·과학력·정책 트리·과학 기술·위인"),
             ("status", "국가\n현황", "국가 통계·재정·승리 조건 진행"))
RAIL_W = 44


def draw_side(app, rail, panel_rect):
    """좌측 끝 세로 탭(세로쓰기 책갈피) + 바로 옆 패널. 지역을 누르면 패널에 [행동]/[지역 정보]가 뜬다.
    같은 탭을 한 번 더 누르면 패널을 접는다."""
    gui = app.gui
    t = app.theme
    y = rail.y
    for i, (k, label, tip) in enumerate(SIDE_TABS):
        chars = label.replace("\n", "")
        r = pygame.Rect(rail.x, y, rail.w, 22 + len(chars) * 19)
        sel = app.left_open and app.left_tab == k
        hov = gui.hover(r)
        gui.shadow(r, 4, 4)
        bg = t.vermilion if sel else (mix(t.indigo, (255, 255, 255), 0.08) if hov else t.indigo)
        gui.rect(bg, r, radius=5)
        pygame.draw.rect(gui.screen, t.gold if sel else mix(t.gold, t.indigo, 0.45), gui.R(r), 1,
                         border_radius=int(5 * gui.u))
        for j, ch in enumerate(chars):
            gui.text((r.centerx, r.y + 20 + j * 19), ch, 14, (247, 241, 227) if sel else mix((247, 241, 227), t.indigo, 0.2),
                     "title", anchor="center")
        gui.block(r)
        if hov:
            gui.tooltip = tip
            if gui.clicked:
                gui.clicked = False
                if sel:
                    app.left_open = False
                else:
                    app.left_open, app.left_tab = True, k
                    if k == "diplo":
                        app.dip_view = None          # 외교 탭은 항상 세력 목록부터
        y = r.bottom + 7
    if not app.left_open:
        return
    gui.panel(panel_rect, ornament=True)
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
        gui.text((panel_rect.x + 18, panel_rect.y + 12), title, 19, weight="title")
        top = 46
    if gui.button((panel_rect.right - 40, panel_rect.y + 10, 30, 32), "‹", "ghost", size=16):
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
    elif k == "progression":
        from .progression import draw_progression_tab
        draw_progression_tab(app, body)
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
    mt = M.of(g, node) if visible else None
    gui.text((x, rect.y + 38), (f"{mt['name']} · 지역 {len(mt['members'])}곳" + (" · 중심" if mt["center"] == node else "")
                                + " · " if mt else "")
             + f"{info.rtype} · 조선 {info.do8}도 · {info.ns}" + (f" · {info.island}" if info.island else ""),
             12, t.accent if mt else t.muted, max_w=w)
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
    from .region_tools import draw_area, draw_status
    y = draw_area(app, x, y, w, node)
    if visible:
        y = draw_status(app, x, y, w, node)
    y = kv(gui, x, y, w, "인구", f"{r.pop:,.1f}만 명")
    y_out = r.output if r.owner != NEUTRAL else g.calc_output(node, full=True)
    y = kv(gui, x, y, w, "산출(GDP)", f"{y_out:,.0f} /턴")
    val, _ = g.region_value(node)
    vtxt = f"{val} / 10"
    if r.owner == NEUTRAL:
        vtxt += f" · 편입 {g.neutral_turns(pid, node)}턴 · 점령 {g.military_occupation_turns(pid, node)}턴"
    y = kv(gui, x, y, w, "지역 가치", vtxt, t.accent)
    if full:
        y = kv(gui, x, y, w, "세수", f"{y_out * of.tax:,.0f} /턴")
        y = kv(gui, x, y, w, "식량 생산", f"{r.food:,.1f} (소비 {r.pop:,.1f})")
        y = kv(gui, x, y, w, "행정력 생산", f"{g.admin_output(node):,.1f} /턴")
        y = kv(gui, x, y, w, "행정력 소비", f"{r.pop * (0.5 if g.resisting(r) else 1):,.1f} /턴")
        y = kv(gui, x, y, w, "과학력 생산", f"{g.science_output(node):,.1f} /턴")
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
            parts.append(f"전쟁 피로 −{ww:.1f}" + (f"(당한 전쟁 {josa(f'{wd:.1f}', '은/는')} 반란 판정 제외)" if wd >= 0.05 else ""))
        if r.conscript > 0:
            parts.append(f"징집 피로 −{r.conscript:.0f} (최근 {g.drafted_turns(node)}/{C.CONSCRIPT_WINDOW}턴 징집)")
        elif full and g.drafted_turns(node) >= min(C.CONSCRIPT_PENALTY) - 2:
            parts.append(f"최근 {g.drafted_turns(node)}/{C.CONSCRIPT_WINDOW}턴 징집")
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
        wf = getattr(r, "war_from", None)
        left = g.liberation_left(node)
        if wf is not None and 0 <= wf < len(g.factions) and g.factions[wf].alive and wf != owner and left > 0:
            # 해방 반환(v1.3.0): 직전 주인의 동맹·연합국이 빼앗긴 지 24턴 안에 되찾으면 직전 주인에게 돌아간다
            back = g.liberation_owner(pid, node) if owner != pid else None
            txt = (f"직전 주인: {g.seen_name(wf)} (전쟁으로 넘어감 — {left}턴 안에 그 동맹·연합국이 되찾으면 "
                   f"{g.seen_name(wf)}에게 돌아감)")
            if back is not None:
                txt = (f"직전 주인: {g.seen_name(wf)} — {left}턴 안에 우리가 되찾으면 동맹·연합국인 "
                       f"{g.seen_name(wf)}에게 돌려줍니다")
            y = gui.wrap((x, y), txt, w, 11, t.accent if back is not None else t.muted) + 4
    if full and r.focus:
        y = kv(gui, x, y, w, "생산 집중", f"적용 중 (인구 산출 +{C.FOCUS_POP_BONUS:.0%})" if g.focus_active(r) else "대기 (건설·생산 중)",
               t.good if g.focus_active(r) else t.muted)
    if visible:
        # 나라마다 점령·편입 가운데 빨리 끝나는 쪽 하나만(같은 나라의 점령과 편입은 서로 경쟁하지 않는다)
        best = {}
        for o in r.occs.values():
            left = max(0, o["need"] - o["progress"])
            best.setdefault(o["by"], []).append((left, f"점령 {o['progress']}/{o['need']}턴"))
        for rr2 in g.regions.values():
            if rr2.project and rr2.project.kind == "annex" and rr2.project.key == node:
                left = g.project_left(rr2.id)
                best.setdefault(rr2.owner, []).append((left, f"편입 {left}턴 남음"))
        claims = [f"{g.seen_name(fid)} {min(v)[1]}" for fid, v in best.items()]
        if claims:
            y = gui.wrap((x, y), ("점령·편입 경쟁: " if len(claims) > 1 else "점령·편입: ") + " / ".join(claims)
                         + (" — 먼저 채운 쪽이 차지(같은 턴이면 점령은 주둔 병력 체력 합, 편입은 맞닿은 지역 인구 합이 큰 쪽)"
                            if len(claims) > 1 else ""),
                         w, 12, t.warn) + 4
    # 건물
    y = section(gui, x, y + 6, w, "건물 단계")
    chips = []
    for k in ("admin", "edu", "farm", "fishery", "factory", "bank", "housing", "power", "hydro", "nuclear", "specialty", "extract", "shelter", "aa"):
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
    ld = getattr(r, "lost_def", None)
    if ld:
        parts = []
        if ld["lines"]:
            parts.append(f"방어선 {len(ld['lines'])}곳(최고 {max(ld['lines'].values())}단계)")
        for k, nm in (("shelter", "방공호"), ("aa", "대공포")):
            if ld[k]:
                parts.append(f"{nm} {ld[k]}단계")
        who = g.seen_name(ld["fid"]) if ld["fid"] != pid else "우리"
        y = gui.wrap((x, y + 2), f"점령으로 꺼진 방어 건물: {', '.join(parts)} — 저항·회복 동안 {josa(who, '이/가')} 되찾으면 그대로, "
                                 f"기간이 지나면 1단계씩 깎여 지금 주인 것이 됩니다.", w, 11, t.warn) + 4
    # 자원
    y = section(gui, x, y + 6, w, "자원·특산물")
    res = []
    if info.oil:
        res.append(f"정유 {info.oil}+{r.b['extract']}/턴")
    if info.coal:
        res.append(f"탄광 {info.coal}+{r.b['extract']}/턴")
    if info.power_source:
        res.append(power_text(info))
        if info.hydro or info.nuclear:
            res.append(f'자체 발전 가동 {g.self_power(node)}/턴' + (' · 직접 건설 필요' if not r.b['hydro'] and not r.b['nuclear'] else ''))
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
    if visible:
        from .progression import draw_region_people
        y = draw_region_people(app, x, y, w, node)
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
    if getattr(p, "metro", None) is not None and p.name:
        return p.name
    if getattr(p, "group", None):
        return f"{p.name} {p.group['target']}단계"
    if p.kind == "build":
        if p.key == "line":
            nm = "해안선" if p.border == "coast" else app.world.regions[p.border].short
            return f"방어선({nm}) {p.level}단계"
        if rid:
            return app.game.build_label(rid, p.key, p.level)
        return f"{BUILDING_NAMES[p.key]} {p.level}단계"
    if p.kind == "unit":
        more = int(getattr(p, "repeat", 0))
        owner = app.game.regions[rid].owner if rid else app.game.player_id
        return f"{app.game.unit_spec(owner, p.key)['name']} 생산" + (f" (뒤에 {more}개 더)" if more else "")
    if p.kind == "annex":
        return f"편입: {app.world.regions[p.key].name}"
    if p.kind == "science":
        k = C.SCIENCE_STEPS.index(p.key) + 1
        return f"과학 {k}단계: {C.SCIENCE[p.key]['name']}"
    if p.kind == "econ":
        return f"경제 {C.ECON_STEPS.index(p.key) + 2}단계: {C.ECON[p.key]['name']}"
    if p.kind == "repair":
        return "침수 복구"
    if p.kind == "capital":
        return "천도"
    return p.kind


def draw_project(app, x, y, w, rid, p, can_cancel=True, compact=False):
    gui = app.gui
    t = app.theme
    name = project_name(app, p, rid)
    if p.kind == "annex":
        n = app.game.joint_count(app.game.regions[rid].owner, p.key)
        if n > 1:
            name += f" (공동 {n}곳)"
    grp = app.game.group_regions(p) if getattr(p, "group", None) else []
    if grp:
        name += f" (지역 {len(grp)}곳)"
    mt = M.get(app.game, getattr(p, "metro", None))
    if mt:
        name = f"{mt['name']}: {name}"
    if compact:
        gui.text((x, y), name, 12, t.text, 'semibold', max_w=w-65)
        if gui.button((x+w-60, y, 60, 23), '취소', size=11):
            ok, msg = app.game.cancel_project(app.game.player_id, rid)
            app.toast(msg)
            app.changed()
        y += 25
        gui.progress((x, y, w, 6), min(1, p.progress / max(1, p.turns)), t.warn if p.stalled else t.accent)
        y += 10
        gui.text((x, y), p.blocked_reason if p.stalled and p.blocked_reason else
                 f'남은 {app.game.project_left(rid)}턴 · 턴당 {p.per_turn:,.0f}', 11,
                 t.bad if p.stalled else t.muted, max_w=w)
        return y + 22
    gui.text((x, y), name, 14, weight="semibold", max_w=w - 70)
    gui.text((x + w, y), f"남은 {app.game.project_left(rid)}턴", 12, t.muted, anchor="topright")
    y += 22
    gui.progress((x, y, w, 8), min(1.0, p.progress / max(1, p.turns)), t.warn if p.stalled else t.accent)
    y += 14
    gui.text((x, y), f"턴당 {p.per_turn:,.0f} · 낸 비용 {p.paid:,.0f}" + (" · 자금 부족으로 정지" if p.stalled else ""),
             12, t.bad if p.stalled else t.muted)
    y += 22
    if grp:
        names = [app.world.regions[r].short for r in grp]
        here = len(p.group["lines"].get(rid, []))
        txt = (f"이 지역 경계 {here}곳 포함 · 함께 짓는 지역: " + ", ".join(names[:6])
               + (f" 외 {len(names) - 6}곳" if len(names) > 6 else "") + " — 지출 우선순위에서 한 건, 비용은 묶음 전체로 냅니다.")
        y = gui.wrap((x, y), txt, w, 11, t.muted) + 6
    if not can_cancel:
        return y
    if app.game.can_chain(p.kind, p.key):
        on = gui.checkbox((x, y, w, 24), "최대 단계까지 이어서 건설", getattr(p, "chain", False), size=12)
        if on != getattr(p, "chain", False):
            p.chain = on
        y += 28
    lp = getattr(p, "line_plan", None)
    if p.key == "line" and lp:
        on = gui.checkbox((x, y, w, 24), f"{app.game.seen_name(lp['nation'])} 쪽 국경 방어선 {lp['target']}단계까지 이어서",
                          True, size=12)
        if not on:
            p.line_plan = None
        y += 28
    if p.kind == "unit":
        gui.text((x, y + 4), "이것 다음에 더 만들 수량", 12, t.muted)
        p.repeat = gui.stepper((x + w - 96, y, 96, 24), int(getattr(p, "repeat", 0)), 0, 50, size=12)
        y += 30
    if gui.button((x, y, 190 if grp else 150, 28), "묶음 전체 취소 (50% 환급)" if grp else "취소 (50% 환급)",
                  tooltip="대상 지역 모두에서 함께 취소됩니다." if grp else None):
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
    from .region_tools import draw_area, draw_status, draw_queue, area_effect
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    x, w = body.x + 14, body.w - 28
    rid = app.sel
    if (rid and rid in g.regions and g.regions[rid].owner == NEUTRAL
            and any(g.regions[n].owner == pid for n in app.world.land_adj[rid])):
        _neutral_annex_panel(app, x, body.y, w, rid)
        return
    if not rid or rid in app.world.seas or g.regions[rid].owner != pid:
        gui.text((x, body.y), "내 구역을 선택하면 슬롯을 지정할 수 있습니다.", 13, t.muted)
        idle = [r for r in g.regions_of(pid) if not r.project and not r.occ and not g.resisting(r)
                and M.center_of(g, r.id) == r.id]                   # 광역시는 중심 하나
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
    mt = M.of(g, rid)
    gui.text((x, y), app.world.regions[rid].name if not mt else mt["name"], 15, weight="bold")
    y += 26
    y = draw_area(app, x, y, w, rid)
    y = draw_status(app, x, y, w, rid)
    people = g.great_people_at(rid)
    if people:
        from ..progression import GREAT_PEOPLE
        label = " · ".join(f"{GREAT_PEOPLE[p['kind']]['name']} {p['name']}" for p in people)
        if gui.button((x, y, w, 26), label, size=11, tooltip="지역 정보에서 위인 이동·활성화"):
            app.tab = "info"
        y += 30
    if any(g.regions[s].flooded for s in M.members(g, rid)):
        if gui.button((x, y, w, 26), '침수 복구 · 1턴 / 무료', 'primary', size=12):
            flooded = next(s for s in M.members(g, rid) if g.regions[s].flooded)
            ok, msg = g.start_project(pid, flooded, 'repair', 'flood', site=flooded)
            if ok and len(g.local_projects(rid)) > 1:
                g.move_queued_project(pid, rid, len(g.local_projects(rid))-1, 0)
            app.toast(msg, None if ok else t.bad)
            app.changed()
        y += 31
    # 점령 저항 중에는 산출·생산이 없으니 다른 명령은 보이지 않는다
    phase, k = g.resist_phase(r)
    if phase == "resist":
        gui.wrap((x, y), f"점령 저항 중({r.resist['resist'] - k}턴 남음)", w, 14, t.bad)
        return
    if mt:
        y = _metro_header(app, x, y, w, mt)
    else:
        # 광역시를 만들 길이 없는 지역(조건을 못 채움·점령당하는 중)은 비활성으로 보이고 이유를 알려 준다(v1.3.0)
        ok_m, why_m = M.feasible(g, pid, rid)
        tip = (f"이 지역을 중심으로, 지도에서 육상 {C.METRO_RANGE}칸 안의 내 지역을 눌러 골라 하나의 지역(광역시)으로 묶습니다."
               if ok_m else "지정할 수 없습니다:\n" + "\n".join("· " + s_ for s_ in why_m))
        if gui.button((x, y, w, 28), "광역자치단체 지정", size=12, enabled=ok_m, tooltip=tip):
            app.start_metro_pick(rid)
        y += 34
    # 생산 집중: 건설·병력 생산을 하지 않는 동안 인구 산출 +15%
    on = gui.checkbox((x, y, w - 110, 26), f"생산 집중 (인구 산출 +{C.FOCUS_POP_BONUS:.0%})", r.focus, size=13)
    if on != r.focus:
        ok, msg = g.set_focus(pid, rid, on)
        app.toast(msg)
        app.changed()
    if r.focus:
        state = "적용 중" if g.focus_active(r) else "대기: 건설·생산 중"
        gui.text((x + w, y + 4), state, 11, t.good if g.focus_active(r) else t.muted, anchor="topright")
    y += 28
    # 인구 성장 집중: 건설·병력 생산을 하지 않고 실질 행복도 5 이상이면 성장률 +0.5%p
    pf = getattr(r, "pop_focus", False)
    can = pf or g.growth_happy(r) >= C.POP_FOCUS_MIN_H
    rate = f"{C.POP_FOCUS_GROWTH * g.growth_scale(rid) * 100:.2f}".rstrip("0").rstrip(".")   # 0.236361 → 0.24
    on = gui.checkbox((x, y, w - 110, 26), f"인구 성장 집중 (+{rate}%p/턴)", pf, size=13)
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
        y = draw_project(app, x, y, w, rid, r.project, compact=True)
    y = draw_queue(app, x, y, w, rid)
    if r.occ:
        gui.text((x, y), "점령당하는 중이라 슬롯을 쓸 수 없습니다.", 13, t.bad)
        return
    if r.b["factory"] or r.b["power"]:
        if gui.button((x, y, w, 28), "연료 배정 (자원 배정 탭)", size=12):
            app.left_open, app.left_tab = True, "energy"
        y += 36
    opts = g.options(pid, rid)
    # 생산 건물: 최대 단계까지 지은 건물은 '… 건설 완료'와 지금 턴당 산출을 남겨 둔다
    prod = []
    for key, spec in C.PROD_BUILDINGS.items():
        if mt:                               # 광역시: 통합 건물(탄광·정유 따로, 특산물 시설도 하나로)을 나열
            prod += [o for o in opts if o["kind"] == "build" and o["key"] == key]
            continue
        o = next((o for o in opts if o["kind"] == "build" and o["key"] == key), None)
        if o:
            prod.append(o)
        elif r.b.get(key, 0) >= spec["max"]:
            prod.append({"kind": "done", "key": key, "level": r.b[key], "ok": True})
    groups = [("편입", [o for o in opts if o["kind"] == "annex"]),
              ("생산 건물", prod),
              (f"유닛 생산 · 최근 {g.drafted_turns(rid)}/{C.CONSCRIPT_WINDOW}턴 징집",
               [o for o in opts if o["kind"] == "unit"]),
              ("방어·군사 건물", [o for o in opts if o["kind"] == "build" and o["key"] not in C.PROD_BUILDINGS]),
              ("특수", [o for o in opts if o["kind"] in ("science", "econ", "capital")]),
              ('시설 정리', [{'kind': 'demolish', 'key': key, 'level': r.b[key]} for key in C.PROD_BUILDINGS if r.b[key]])]
    area = pygame.Rect(body.x, y, body.w, body.bottom - y)
    content = sum(28 + sum(60 if o["kind"] in ("build", "science", "econ", "unit") else 44 for o in lst)
                  for _, lst in groups if lst)
    off = gui.begin_scroll("actions", area, content)
    yy = y - off
    money = g.player.money
    for title, lst in groups:
        if not lst:
            continue
        top = yy
        yy = section(gui, x, yy, w, title)
        if title.startswith("유닛 생산") and gui.hover((x, top - 4, w, yy - top + 4)):
            gui.tooltip = f"{min(C.CONSCRIPT_PENALTY)}/{C.CONSCRIPT_WINDOW}턴부터 지역 행복도 감소"
        for o in lst:
            if o['kind'] == 'demolish':
                key = o['key']
                label = C.PROD_BUILDINGS[key]['name']
                gui.text((x, yy+2), f'{label} {o["level"]} → {o["level"]-1}단계', 12, t.muted, max_w=w-70)
                tip = '광역시는 구성 지역 모두 1단계씩 철거합니다.' if mt else '이 건물을 1단계 철거합니다.'
                if key == 'housing':
                    tip += ' 주거 철거 시 인구 사용 면적이 늘어납니다.'
                if gui.button((x+w-62, yy+3, 62, 27), '철거', size=11, tooltip=tip):
                    ok, msg = g.demolish_building(pid, rid, key)
                    app.toast(msg, None if ok else t.bad)
                    app.changed()
                yy += 44
                continue
            if o["kind"] == "done":
                lv = o["level"]
                if o["key"] in C.PROD_LEVEL_NAMES:
                    label = f"{g.building_name(rid, o['key'], lv)} 건설 완료"
                elif o["key"] == "extract":
                    label = f"{'정유공장' if app.world.regions[rid].is_oil else '탄광'} {lv}단계 건설 완료"
                else:
                    label = f"{g.building_name(rid, o['key'])} {lv}단계 건설 완료"
                gui.text((x, yy + 2), label, 13, t.text, "semibold", max_w=w - 16)
                gui.text((x, yy + 21), g.building_total(pid, rid, o["key"]), 11, t.good, "semibold", max_w=w - 16)
                yy += 44
                continue
            row = pygame.Rect(x, yy, w, 40)
            label = o["name"] + (f" {o['level']}단계" if o["kind"] == "build" and o["key"] != "line"
                                 and o["key"] not in C.SINGLE_BUILDINGS else "")
            if o["kind"] == "build" and o["key"] in C.PROD_LEVEL_NAMES:
                label = g.build_label(rid, o["key"], o["level"])          # 예: '공업 단지 건설'
            if o["kind"] == "build" and o["key"] == "line":
                label = o["name"] + f" {o['level']}단계"
            if o.get("pool"):
                label = o["name"]                                            # 예: '광역 경작지 4단계
            gui.text((x, yy + 2), label, 13, t.text if o["ok"] else t.muted, "semibold", max_w=w - 70)
            eff = o.get("eff_turns", o["turns"])
            turns_txt = f"{eff}턴(기본 {o['turns']}턴)" if eff < o["turns"] else f"{o['turns']}턴"
            sub = f"총 {o['cost']:,.0f} · {turns_txt} · 턴당 {o['per_turn']:,.0f}"
            if o.get("oil"):
                sub += f" · 석유 {o['oil']}"
            if o['kind'] == 'build':
                sub += ' · ' + area_effect(g, rid, o)
            if not o["ok"]:
                sub = o["why"]
            gui.text((x, yy + 21), sub, 11, t.muted if o["ok"] else t.bad, max_w=w - 70)
            eff = g.building_effect(pid, rid, o) if o["kind"] == "build" else ""
            if o["kind"] == "science":
                eff = ("완료하면 유닛 1개 — 발사대 지역으로 옮긴다" if C.SCIENCE[o["key"]]["unit"]
                       else "완료하면 다음 과학 단계가 열린다")
                science_cost = g.science_per_turn_cost(C.SCIENCE_STEPS.index(o["key"]))
                eff = f"과학력 {science_cost:,}/턴 · " + eff
            if o["kind"] == "econ":
                eff = {"exchange": f"이 지역 시장 산출 +{C.EXCHANGE_BANK_BONUS:.0%}",
                       "sez": "완료하면 국제금융센터가 열린다(우호 관계 필요)",
                       "ifc": f"내 선물의 우호도 효과 +{C.IFC_GIFT_BONUS:.0%}",
                       "currency": "완료하면 경제승리"}[o["key"]]
            if eff:
                gui.text((x, yy + 38), eff, 11, t.good, "semibold", max_w=w - 70, tip=False)
            qty = 1
            if o["kind"] == "unit":
                # 연속 생산 수량: [지정] 아래에서 고른다(하나씩 차례로 만든다)
                qkey = (rid, o["key"])
                qty = app.unit_qty.get(qkey, 1) if hasattr(app, "unit_qty") else 1
                gui.text((x, yy + 38), f"수량 {qty}개" + (f" · 모두 {o['turns'] * qty}턴" if qty > 1 else ""),
                         11, t.muted, tip=False)
                qty = gui.stepper((x + w - 86, yy + 36, 86, 22), qty, 1, 50, size=11)
                if not hasattr(app, "unit_qty"):
                    app.unit_qty = {}
                app.unit_qty[qkey] = qty
            if gui.button((x + w - 62, yy + 6, 62, 28), "추가" if r.project else "지정", "primary" if o["ok"] else "default",
                          enabled=o["ok"], size=12,
                          tooltip=None if money >= o["per_turn"] else "현재 자금이 턴당 비용보다 적어 정지될 수 있습니다"):
                if o["kind"] == "unit":
                    ok, msg = g.start_units(pid, rid, o["key"], qty)
                else:
                    ok, msg = g.start_project(pid, rid, o["kind"], o["key"], border=o.get("border"),
                                              site=o.get("site"), pool=o.get("pool"))
                app.toast(msg, None if ok else t.bad)
                if ok:
                    app.changed()
            if g.can_chain(o["kind"], o["key"]) and gui.button(
                    (x + w - 62, yy + 36, 62, 22), "최대", "default", enabled=o["ok"], size=11,
                    tooltip="완공되면 바로 다음 단계를 이어서 짓습니다(마지막 단계까지)"):
                ok, msg = g.start_project_max(pid, rid, o["kind"], o["key"], site=o.get("site"), pool=o.get("pool"))
                app.toast(msg, None if ok else t.bad)
                if ok:
                    app.changed()
            yy += 60 if (o["kind"] in ("build", "science", "econ", "unit")) else 44
    gui.end_scroll("actions", area, content)


def _neutral_annex_panel(app, x, y, w, rid):
    """내 영토와 맞닿은 중립 지역의 행동 탭(v1.3.0): [편입]·[최대 편입], 편입 중이면 자동 해산."""
    gui, g, t = app.gui, app.game, app.theme
    pid = g.player_id
    f = g.player
    gui.text((x, y), app.world.regions[rid].name + " (중립)", 15, weight="bold")
    y += 26
    val = g.region_value(rid)[0]
    base = g.neutral_turns(pid, rid)
    y = kv(gui, x, y, w, "지역 가치", f"{val} / 10")
    y = kv(gui, x, y, w, "편입 기간(한 곳)", f"{base}턴 · 비용 {g.annex_cost(pid, rid):,.0f}")
    y = kv(gui, x, y, w, "무력 점령 기간", f"{g.military_occupation_turns(pid, rid)}턴")
    mine = [r for r in g.regions_of(pid) if r.project and r.project.kind == "annex" and r.project.key == rid]
    if mine:
        who = ", ".join(dict.fromkeys(M.label(g, r.id) if M.of(g, r.id) else app.world.regions[r.id].short
                                      for r in mine))
        y = gui.wrap((x, y + 2), f"편입 중: {who} · 공동 {g.joint_count(pid, rid)}곳 "
                                 f"−{g.joint_reduction_of(pid, rid):.0%} · 남은 {g.project_left(mine[0].id)}턴",
                     w, 12, t.accent) + 6
    srcs = g.annex_sources(pid, rid)
    bw = (w - 6) / 2
    one = app.world.regions[srcs[0]].short if srcs else ""
    if gui.button((x, y, bw, 30), f"편입 ({one})" if srcs else "편입", "primary", enabled=bool(srcs), size=12,
                  tooltip="생산이 지정되지 않은 내 이웃 지역 한 곳(인구가 가장 많은 곳)에서 편입을 착수합니다."
                  if srcs else "슬롯이 빈 이웃 지역이 없습니다."):
        n, msg = g.annex_from(pid, rid)
        app.toast(msg, None if n else t.bad)
        app.changed()
    if gui.button((x + bw + 6, y, bw, 30), f"최대 편입 ({len(srcs)}곳)", enabled=len(srcs) > 0, size=12,
                  tooltip="생산이 지정되지 않은 이웃 내 지역 모두에서 함께 편입합니다(공동 편입: 2곳 −33%, 3곳 −50% …)."):
        n, msg = g.annex_from(pid, rid, every=True)
        app.toast(msg, None if n else t.bad)
        app.changed()
    y += 38
    if mine:
        on = rid in getattr(f, "annex_disband", set())
        v = gui.checkbox((x, y, w, 24), "자동 해산", on, size=12)
        if v != on:
            (f.annex_disband.add if v else f.annex_disband.discard)(rid)
        y += 26
        y = gui.wrap((x + 26, y), f"편입이 끝나면 넘겨받는 보병을 바로 해산합니다(이 지역 행복도 "
                     f"+{C.UNIT_DISBAND_HAPPY['light']:g}).", w - 26, 11, t.muted, line_h=16, words=True) + 6
    elif rid in getattr(f, "annex_disband", set()):
        f.annex_disband.discard(rid)
    if pid in g.regions[rid].occs:
        gui.text((x, y), "내 군대가 무력 점령 중입니다.", 12, t.muted)
    return y


def _metro_header(app, x, y, w, mt):
    """광역시 행동 탭 머리: 구성 지역·통합 단계·해제(두 번 눌러 확인)."""
    gui, g, t = app.gui, app.game, app.theme
    names = [g.info(r).short for r in mt["members"]]
    y = gui.wrap((x, y), f"지역 {len(names)}곳 하나로 · 중심 {g.info(mt['center']).short} · " + ", ".join(names),
                 w, 11, t.muted) + 2
    lv = []
    for pool, key in M.POOLS:
        el = M.pool_members(g, mt, pool)
        if el and key in ("farm", "fishery", "factory", "bank", "power", "specialty"):
            lv.append(f"{M.POOL_NAMES[pool].replace('광역 ', '')} {M.pool_level(g, mt, pool)}")
    y = gui.wrap((x, y), "통합 단계: " + " · ".join(lv) + f" · 방어력 ×{M.def_mult(g, mt['center']):.2f}", w, 11,
                 t.text) + 4
    armed = getattr(app, "metro_dissolve", None) == mt["id"]
    if gui.button((x, y, w, 26), "광역시 해제 확정" if armed else "광역시 지정 해제", "danger" if armed else "default",
                  size=12, tooltip="해제하면 건물 단계 = 묶기 전 단계 + 묶은 뒤 올린 단계, 유일 건물은 중심(항구는 해안 지역), "
                                   "부대는 중심으로. 통합 건물 공사 중이면 50% 환급하고 취소."):
        if armed:
            app.metro_dissolve = None
            ok, msg = g.dissolve_metro(g.player_id, mt["center"])
            app.toast(msg)
            app.changed()
        else:
            app.metro_dissolve = mt["id"]
    return y + 32


def auto_slot_controls(app, x, y, w):
    gui = app.gui
    g = app.game
    f = g.player
    from .. import ai
    if gui.button((x, y, w, 30), "빈 슬롯 자동 지정 (AI 추천)", "primary", size=12,
                  ):
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
    y = _border_lines_section(app, x, y, w)
    y = _national_rally_section(app, x, y, w)
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
                          ):
                opened.symmetric_difference_update({k})
            gui.icon(k, (x + 10, yy + 9), t.text)
            gui.text((x + 26, yy), g.unit_spec(pid, k)["name"] + (" ▼" if k in opened else " ▶"), 13)
            gui.text((cols[0], yy), f"{counts[k]:,}", 13, anchor="topright")
            gui.text((cols[1], yy), f"{up.get(k, 0):,.0f}", 13, anchor="topright")
        else:
            k, a = v
            loc = app.world.node_name(a.loc)
            lab = f"{loc} · {a.spec(k)['name']} {a.units[k]}" + (f" (부대: {a.label()})" if len(a.units) > 1 else "")
            if a.order or a.goto:
                lab += " ▶"
            clicked = gui.button((x + 18, yy, w - 18, h - 2), "", "ghost")
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


def _national_rally_section(app, x, y, w):
    """[군사] 탭: 생산 집결지 일괄 지정(v1.3.0). 모든 지역의 생산 육군과 편입으로 받는 보병이 그리로."""
    gui, g, t = app.gui, app.game, app.theme
    pid = g.player_id
    y = section(gui, x, y + 8, w, "생산 집결지 일괄 지정")
    nat = getattr(g.player, "rally", None)
    gui.text((x, y), f"지금: {app.world.regions[nat].name}" if nat and nat in g.regions else "지금: 없음", 12,
             t.text if nat else t.muted, max_w=w)
    y += 22
    bw = (w - 6) / 2
    if gui.button((x, y, bw, 28), "일괄 지정", "primary", size=12,
                  tooltip="누른 뒤 지도에서 내 지역 하나를 누르면 모든 지역의 집결지가 그곳이 됩니다(지역별 지정은 지움). "
                          "중립 지역 편입으로 받는 보병도 그리로 갑니다."):
        app.start_rally_pick(None)
    if gui.button((x + bw + 6, y, bw, 28), "일괄 해제", size=12, enabled=bool(nat)):
        ok, msg = g.set_rally(pid, None, None)
        app.toast(msg)
    return y + 36


def _border_lines_section(app, x, y, w):
    """[군사] 탭: 맞닿은 나라를 고르면 그 나라 쪽 국경 방어선을 목표 단계까지 한꺼번에 짓는다(v1.3.0)."""
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    y = section(gui, x, y + 8, w, "국경 방어선 일괄 건설")
    nbrs = g.border_nations(pid)
    if not nbrs:
        gui.text((x, y), "맞닿은 나라가 없습니다.", 12, t.muted)
        return y + 22
    sel = getattr(app, "border_nation", None)
    ids = [o for o, *_ in nbrs]
    if sel not in ids:
        sel = app.border_nation = None
    bw = (w - 6) / 2
    for i, (o, n, lo, avg) in enumerate(nbrs):
        cx, cy = x + (i % 2) * (bw + 6), y + (i // 2) * 30
        war = D.at_war(g, pid, o)
        if gui.button((cx, cy, bw, 26), ("⚔ " if war else "") + g.seen_name(o), "primary" if o == sel else "default",
                      size=12, tooltip=f"맞닿은 경계 {n}곳 · 최저 {lo}단계 · 평균 {avg:.1f}단계"):
            app.border_nation = sel = None if o == sel else o
            app.border_target = None
    y += ((len(nbrs) + 1) // 2) * 30 + 2
    if sel is None:
        gui.text((x, y), "나라를 고르면 그쪽 국경 방어선을 한꺼번에 짓습니다.", 11, t.muted, max_w=w)
        return y + 20
    _, n, lo, avg = next(v for v in nbrs if v[0] == sel)
    tgt = getattr(app, "border_target", None) or min(C.DEF_BUILDINGS["line"]["max"], lo + 1)
    gui.text((x, y + 4), f"경계 {n}곳 · 최저 {lo} · 평균 {avg:.1f}단계", 12, t.text, max_w=w - 130)
    gui.text((x + w - 128, y + 4), "목표", 12, t.muted)
    app.border_target = tgt = gui.stepper((x + w - 92, y, 92, 24), int(tgt), 1, C.DEF_BUILDINGS["line"]["max"], size=12)
    y += 30
    plan = g.border_line_plan(pid, sel, tgt)
    regs = plan["lines"]
    if regs:
        txt = (f"{g.seen_name(sel)} 방어선: 대상 {len(regs)}곳 (방어선 {plan['steps']}단계분) · "
               f"{plan['turns']}턴 소요 · 총 {plan['total']:,.0f} (턴당 {plan['per_turn']:,.0f})")
        y0 = y
        y = gui.wrap((x, y), txt, w, 11, t.text) + 4
        if gui.hover((x, y0, w, y - y0)):
            gui.tooltip = (f"소요 턴 = 모든 방어선 단계의 건설 턴 합({plan['turns_sum']}) ÷ "
                           f"작업 슬롯 수({plan.get('slots', len(regs))}곳), 올림")
    stop, seen = [], set()
    for r in plan["interrupt"]:                  # 광역시처럼 한 작업을 함께 하는 지역은 한 건
        if id(g.regions[r].project) not in seen:
            seen.add(id(g.regions[r].project))
            stop.append(r)
    if stop:
        what = ", ".join(f"{app.world.regions[r].short}({project_name(app, g.regions[r].project, r)})" for r in stop[:4])
        y = gui.wrap((x, y), f"착수하면 진행 중인 작업 {len(stop)}건을 중단합니다(낸 비용 50% 환급): {what}"
                     + (f" 외 {len(stop) - 4}건" if len(stop) > 4 else ""), w, 11, t.warn) + 4
    key = (sel, tgt, tuple(stop))
    armed = stop and getattr(app, "border_confirm", None) == key
    label = (f"작업 {len(stop)}건 중단 후 착수" if armed
             else f"착수: 대상 {len(regs)}곳 · {plan['turns']}턴 (턴당 {plan['per_turn']:,.0f})")
    if gui.button((x, y, w, 30), label, "danger" if armed else "primary", enabled=bool(regs) and not plan["why"],
                  size=12, tooltip=plan["why"] or (
                      ("한 번 더 누르면 진행 중인 작업을 중단하고 착수합니다.\n" if armed else "")
                      + "대상 지역 모두에 '나라 방어선' 묶음 공사 한 건을 착수합니다. 지출 우선순위에서 한 건으로 다루고, "
                        "비용은 묶음 전체로 매 턴 한꺼번에 냅니다. 다 지으면 대상 경계가 모두 목표 단계가 됩니다.\n"
                      + f"소요 턴 = 건설 턴 합({plan['turns_sum']}) ÷ 작업 슬롯 수({plan.get('slots', len(regs))}곳)")):
        if stop and not armed:
            app.border_confirm = key
        else:
            app.border_confirm = None
            ok, msg = g.build_border_lines(pid, sel, tgt)
            app.toast(msg)
            app.changed()
    y += 34
    note = []
    if plan["skipped"]:
        note.append(f"점령당하는 중·저항 중인 지역 {plan['skipped']}곳 제외")
    if plan["done"]:
        note.append(f"이미 목표에 닿은 지역 {plan['done']}곳")
    if note:
        gui.text((x, y), " · ".join(note), 11, t.muted, max_w=w)
        y += 18
    return y


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
        main = g.army_icon_unit(a)
        if a.units.get("lst", 0) > 0:
            main = "lst"
        picked = merge is not None and a.id in merge
        selected = a.id == app.sel_army and merge is None
        if gui.button(rect, "", "ghost", selected=selected or picked,
                      tooltip=a.label() + (" (이동 명령 있음)" if a.order or a.goto else "")):
            if merge is not None:
                if not g.army_acted(a.id):          # 이번 턴 행동(이동·전투)한 부대는 합칠 수 없다
                    merge.symmetric_difference_update({a.id})
            else:
                app.sel_army = a.id
                app.split = {}
        lit = selected or picked
        acted = g.army_acted(a.id)
        fg = (255, 255, 255) if lit else (t.muted if acted else t.text)
        gui.icon(main, (cx + size / 2, cy + size * 0.30), fg, 1.8)
        if acted:
            gui.text((cx + 6, cy + 4), "전투 완료" if g.army_fought(a.id) else "행동 완료", 9,
                     (235, 240, 255) if lit else t.bad, "semibold")
        kinds = len([k for k in a.units if a.units[k] > 0])
        name = a.spec(main)["name"] + (f" 외 {kinds - 1}" if kinds > 1 else "")
        if a.units.get("lst", 0) > 0:
            name = a.spec("lst")["name"]
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
    """지역 패널 [부대]: 선택한 지역에 있는 내 부대만 고르고 조종한다(내용이 길면 휠로 넘긴다)."""
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    x, w = body.x + 14, body.w - 28
    area = pygame.Rect(body.x, body.y, body.w, body.h)
    off = gui.begin_scroll("army_tab", area, getattr(app, "_army_tab_h", 900))
    y = body.y - off
    y0 = y
    y = _army_tab_body(app, x, y, w, pid)
    app._army_tab_h = y - y0 + 10
    gui.end_scroll("army_tab", area, app._army_tab_h)


def _army_tab_body(app, x, y, w, pid):
    gui = app.gui
    g = app.game
    t = app.theme
    node = app.sel
    here = sorted([a for a in g.armies_at(node, pid)], key=g.army_sort_key) if node else []   # 병종 순서(v1.3.0)
    if here and (app.sel_army not in {a.id for a in here}):
        app.sel_army = min(here, key=g.army_pick_key).id
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
    if not army:
        gui.text((x, y), "이 지역에 내 부대가 없습니다.", 13, t.muted)
        return draw_rally(app, x, y + 32, w, node)
    loc = app.world.node_name(army.loc)
    gui.text((x, y), f"부대 #{army.id} · {loc}", 15, weight="bold")
    y += 24
    dom = {"land": "육군", "naval": "해군", "air": "공군"}[army.domain()]
    gui.text((x, y), f"{dom} · 전력 {g.army_power(army):,.0f}", 12, t.muted)
    y += 22
    fought = g.army_fought(army.id)
    acted = g.army_acted(army.id)
    if acted:
        gui.rect(t.panel_alt, (x, y, w, 26), radius=6)
        msg = ("이번 턴 전투 완료 — 합치기·분리·이동·공격 불가" if fought
               else "이번 턴 행동 완료 — 이동·공격·합치기는 다음 턴")
        gui.text((x + 8, y + 13), msg, 12, t.bad, "semibold", anchor="midleft", max_w=w - 16)
        if not fought and gui.hover((x, y, w, 26)):
            gui.tooltip = "이미 움직인 부대도 분리·해산·하선은 할 수 있습니다(합치기는 다음 턴)."
        y += 32
    naval = army.domain() == "naval"
    # 유닛 목록 + 분리 수량(함대에 실린 육군·공군은 아래 화물칸에서 다룬다)
    for k in C.UNIT_ORDER:
        n = army.units.get(k, 0)
        if not n or (naval and C.UNITS[k]["kind"] in ("land", "air")):
            continue
        gui.icon(k, (x + 8, y + 11), t.text)
        u = army.spec(k)
        inline = n <= 5
        tw = w - (138 if inline else 22)
        gui.text((x + 22, y + 2), f"{u['name']} {n}", 13, weight="semibold", max_w=tw)
        left, full = army.hp_left(k), army.hp_max(k)
        stat = f"공{u['atk']:g} 방{u['df']:g}" + (f" 폭{u['bomb']:g}" if u.get("bomb") else "")
        gui.text((x + 22, y + 20), f"{stat} 체 {left:.0f}/{full:g}", 11,
                 t.bad if left < full * 0.5 else t.muted, max_w=tw)
        app.split[k], y = _qty_stepper(gui, x, y, w, min(app.split.get(k, 0), n), n)   # 해산 수량에도 쓴다
    app.split = {k: v for k, v in app.split.items() if not (naval and C.UNITS[k]["kind"] in ("land", "air"))}
    merge, y, gone = _army_buttons(app, x, y, w, army, here, merge, fought, node)
    if gone:
        return y
    if naval and (army.units.get("lst") or army.units.get("cv") or g.cargo_of(army)):
        y = draw_cargo_panel(app, x, y, w, army)
    elif army.domain() in ("land", "air"):
        y = _boarding_buttons(app, x, y, w, army, acted)
    if g.solo_army(army):
        # 포병·폭격기 부대(v1.3.0): 우클릭한 곳에 적 병력이 있으면 폭격 확인 창, 없으면 이동
        what = "포병" if army.units.get("art") else "폭격기"
        rng = (f"육상 {C.ART_RANGE}칸" if army.units.get("art")
               else f"공항이 있는 지역에서 {C.BOMB_RANGE}칸, 육지↔바다는 2칸으로 셈")
        y = gui.wrap((x, y + 2), f"{what} 부대 — 우클릭: 적 병력이 있으면 폭격 확인 창({rng}), 없으면 이동. "
                                 f"Shift+우클릭: 병력 없는 곳의 건물 폭격", w, 12, t.muted) + 8
    else:
        gui.text((x, y + 6), "공격 방식", 12, t.muted)
        if g.mods(pid).value("no_surprise"):
            app.attack_mode = "assault"
            gui.text((x + 70, y + 6), f"돌격만 가능 — {g.fx_source(pid, 'no_surprise')}", 12, t.muted)
        else:
            modes = ["assault", "surprise"]
            idx = gui.segmented((x + 70, y, w - 70, 28), ["돌격", "기습"], modes.index(app.attack_mode))
            app.attack_mode = modes[idx]
        y += 34
        if army.units.get("dd") or (army.units.get("bmb") and army.units.get("cv")):
            y = gui.wrap((x, y), "함포·함재기 폭격: 폭격 대상 우클릭 → 폭격 확인 창 (상륙 대상이면 Shift+우클릭)",
                         w, 12, t.muted) + 6
    if army.goto:
        gui.text((x, y), f"자동 이동 → {app.world.node_name(army.goto)}", 13, t.accent, "semibold",
                 max_w=w - 80)
        if gui.button((x + w - 70, y - 4, 70, 26), "취소", size=12):
            army.goto, army.order = None, None
            app.changed()
        y += 26
        y = gui.wrap((x, y), "다음 턴부터 턴이 시작될 때 한 구간씩 바로 갑니다.", w, 11, t.muted)
    elif acted:
        y = gui.wrap((x, y), "다음 턴에 다시 명령할 수 있습니다. 해산은 가능합니다.", w, 12, t.muted)
    else:
        y0 = y
        y = gui.wrap((x, y), "우클릭: 이동·공격·폭격 · Shift+우클릭: 건물 폭격 (멀면 자동 이동)", w, 12, t.muted)
        if gui.hover((x, y0, w, y - y0)):
            gui.tooltip = ("지도에서 우클릭하면 바로 이동·폭격·점령합니다(한 부대는 한 턴에 한 번).\n"
                           "적 병력이 있는 곳은 확인 창에서 싸웁니다.\n"
                           "이동 범위: 진한 색은 자국 영토 2칸, 옅은 색은 1칸, 점선은 연륙교입니다.\n"
                           "범위 밖을 우클릭하면 첫 구간을 바로 가고, 다음 턴부터 턴 시작마다 이어서 자동 이동합니다.\n"
                           "Shift+우클릭: 병력이 없는 곳의 건물 폭격(포병·폭격기·구축함).")
    return draw_rally(app, x, y + 6, w, node)


def _army_buttons(app, x, y, w, army, here, merge, fought, node):
    """[분리]·[합치기]·[해산]. 반환 (merge, y, 부대가 사라졌는가)."""
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    nb = 4 if merge is not None else 3
    bw = (w - 4 * (nb - 1)) / nb
    sel_n = sum(app.split.values())
    if gui.button((x, y, bw, 28), "분리", enabled=sel_n > 0 and not fought):
        b, msg = g.split_army(army.id, app.split)
        if b:
            app.sel_army = b.id
            app.split = {}
        else:
            app.toast(msg, t.bad)
    others = [a for a in g.armies_at(army.loc, pid) if g.mergeable(army, a)]   # 이 부대와 합칠 수 있는 부대만
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
                  enabled=bool(others) and not g.army_acted(army.id),
                  tooltip="같은 병종 계열끼리 합칩니다. 포병·폭격기는 같은 병종끼리만(함대에 싣는 것은 [승선]·[탑재])"):
        if merge is None and len(others) == 1:
            app.merge_pick = merge = {army.id, others[0].id}   # 부대가 둘뿐이면 고를 것 없이 바로 합친다
            go = True
        elif merge is None:
            app.merge_pick, app.merge_node = {army.id}, node
            merge = app.merge_pick
        else:
            go = True
    if merge is not None and gui.button((x + 2 * bw + 8, y, bw, 28), "모두 합치기", size=12):
        app.merge_pick = merge = {army.id} | {a.id for a in here if g.mergeable(army, a)}
        go = True
    if go and merge is not None:
        ids = [a.id for a in here if a.id in merge]
        if len(ids) < 2:
            app.toast("합칠 부대를 두 개 이상 고르세요.", t.bad)
        else:
            base = army.id if army.id in ids else ids[0]
            n_ok = 1
            for o in ids:
                if o != base:
                    ok, msg = g.merge_player(base, o)
                    if ok:
                        n_ok += 1
                    else:
                        app.toast(msg, t.bad)
            app.sel_army = base
            if n_ok > 1:
                app.toast(f"부대 {n_ok}개를 합쳤습니다.")
        app.merge_pick = merge = None
    if gui.button((x + (nb - 1) * (bw + 4), y, bw, 28), "해산", "danger", enabled=sel_n > 0,
                  tooltip="선택한 수량 해산 (자국 영토면 행복도 +)"):
        g.disband(army.id, app.split)
        app.split = {}
        if army.id not in g.armies:
            app.sel_army = None
            return merge, y + 38, True
    return merge, y + 38, False


def _boarding_buttons(app, x, y, w, army, acted):
    """육군·공군 쪽 [승선]·[탑재]: 같은 항구의 상륙함·항공모함 함대에 싣는다(분리 수량을 고르면 그만큼)."""
    gui = app.gui
    g = app.game
    t = app.theme
    fleets = g.cargo_fleets(army.id)
    if not fleets:
        return y
    verb = "승선" if army.domain() == "land" else "탑재"
    for fl in fleets[:3]:
        room = (f"빈 칸 {fl.cargo_cap() - fl.cargo_used()}" if verb == "승선"
                else f"빈 자리 {fl.air_cap() - fl.air_used()}")
        pick = {k: v for k, v in app.split.items() if v > 0}
        what = "고른 유닛" if pick else "전부"
        if gui.button((x, y - 4, w, 30), f"{verb} → {'상륙함' if verb == '승선' else '항공모함'} 부대 #{fl.id} "
                                         f"({room}) · {what}", "primary", size=12, enabled=not acted,
                      tooltip=None if not acted else "이번 턴에 이미 행동한 부대는 다음 턴에 실을 수 있습니다"):
            took, msg = g.load_cargo(fl.id, army.id, pick or None)
            app.toast(msg, None if took else t.bad)
            if took:
                app.split = {}
                app.sel_army = fl.id
                app.changed()
                return y + 34
        y += 34
    return y


def _cargo_slots(gui, t, x, y, w, cap, items, per_key, label):
    """드랍쉽 화물칸: cap 칸을 그리고, 실린 유닛 하나가 차지하는 칸들을 한 덩어리 상자(아이콘)로 채운다. 다음 y."""
    if cap <= 0:
        return y
    gui.text((x, y), label, 12, t.muted, "semibold")
    y += 18
    per_row = min(cap, 16)
    gap = 2
    cell = min(22, (w - (per_row - 1) * gap) / per_row)
    rows = (cap + per_row - 1) // per_row
    for i in range(cap):                         # 빈 칸
        cx = x + (i % per_row) * (cell + gap)
        cy = y + (i // per_row) * (cell + gap)
        gui.rect(t.panel_alt, (cx, cy, cell, cell), radius=3)
        gui.rect(mix(t.border, t.panel, 0.3), (cx, cy, cell, cell), 1, radius=3)
    shade = {"tank": 0.0, "art": 0.18, "inf": 0.32, "bmb": 0.0, "ftr": 0.25}
    i = 0
    for k, n in items:
        size = per_key(k)
        col = mix(t.accent, (255, 255, 255), shade.get(k, 0.1))
        for _ in range(n):
            if i + size > cap:
                break
            j = 0
            while j < size:                          # 줄이 바뀌면 줄마다 한 덩어리
                c0, row = (i + j) % per_row, (i + j) // per_row
                span = min(size - j, per_row - c0)
                bx, by = x + c0 * (cell + gap), y + row * (cell + gap)
                bw = span * cell + (span - 1) * gap
                gui.rect(col, (bx, by, bw, cell), radius=4)
                pygame.draw.rect(gui.screen, mix(col, (0, 0, 0), 0.35), gui.R((bx, by, bw, cell)), 1,
                                 border_radius=int(4 * gui.u))
                if j == 0:
                    gui.icon(k, (bx + bw / 2, by + cell / 2), (255, 255, 255), 1.0 if cell >= 18 else 0.8)
                j += span
            i += size
    return y + rows * (cell + gap) + 6


def _qty_stepper(gui, x, y, w, value, n):
    """유닛 한 줄의 수량 조절(v1.3.0). 5개 이하면 같은 줄 오른쪽에 [−] 값 [+],
    더 많으면 아랫줄에 [−10][−5][−] 값 [+][+5][+10](10개 이하면 ±10 은 뺀다). (새 값, 다음 y)."""
    if n <= 5:
        return gui.stepper_multi((x + w - 116, y + 6, 116, 26), value, 0, n, steps=(1,)), y + 40
    steps = (10, 5, 1) if n > 10 else (5, 1)
    v = gui.stepper_multi((x + 22, y + 38, w - 22, 26), value, 0, n, steps=steps)
    return v, y + 72


def draw_cargo_panel(app, x, y, w, fl):
    """상륙함·항공모함 화물칸(스타크래프트 수송선처럼): 빈 칸과 실린 유닛을 칸으로 보여 주고,
    항구에서는 같은 지역 부대를 [승선]·[탑재], 실린 유닛을 [하선]·[이함]. 바다에서는 맞닿은 해안을 골라 [하선](상륙)."""
    gui = app.gui
    g = app.game
    t = app.theme
    w_ = app.world
    pid = g.player_id
    cargo = g.cargo_of(fl)
    y = section(gui, x, y + 2, w, "화물칸")
    land = [(k, cargo[k]) for k in ("tank", "art", "inf", "booster", "module", "propellant") if cargo.get(k)]
    air = [(k, cargo[k]) for k in ("bmb", "ftr") if cargo.get(k)]
    if fl.units.get("lst"):
        y = _cargo_slots(gui, t, x, y, w, fl.cargo_cap(), land, lambda k: C.UNITS[k].get("cargo", 1),
                         f"상륙함 수송 칸 {fl.cargo_used()}/{fl.cargo_cap()} (보병 1·포병 2·전차 4칸)")
    if fl.units.get("cv"):
        y = _cargo_slots(gui, t, x, y, w, fl.air_cap(), air, lambda k: 1,
                         f"항공모함 탑재 {fl.air_used()}/{fl.air_cap()}대")
    # 내릴 수량(기본 전부)
    pick = getattr(app, "cargo_pick", None)
    if not pick or pick.get("fid") != fl.id:
        pick = app.cargo_pick = {"fid": fl.id, "units": dict(cargo)}
    sel = pick["units"]
    for k in list(sel):
        if k not in cargo:
            sel.pop(k)
    for k, n in land + air:
        sel.setdefault(k, n)
        gui.icon(k, (x + 8, y + 11), t.text)
        left, full = fl.hp_left(k), fl.hp_max(k)
        tw = w - (138 if n <= 5 else 22)
        gui.text((x + 22, y + 2), f"{fl.spec(k)['name']} {n}", 13, weight="semibold", max_w=tw)
        gui.text((x + 22, y + 20), f"체 {left:.0f}/{full:g}", 11, t.bad if left < full * 0.5 else t.muted, max_w=tw)
        sel[k], y = _qty_stepper(gui, x, y, w, min(sel.get(k, n), n), n)
    at_sea = w_.is_sea(fl.loc)
    fought = g.army_fought(fl.id)
    want_land = {k: v for k, v in sel.items() if v > 0 and C.UNITS[k]["kind"] == "land"}
    want_air = {k: v for k, v in sel.items() if v > 0 and C.UNITS[k]["kind"] == "air"}
    if cargo and not at_sea:
        bw = (w - 4) / 2
        if gui.button((x, y, bw, 30), f"하선 ({sum(want_land.values())})", "primary", size=12,
                      enabled=bool(want_land) and not fought, tooltip="고른 육군을 이 항구에 내립니다"):
            made, msg = g.unload_cargo(fl.id, want_land)
            app.toast(msg, None if made else t.bad)
            app.cargo_pick = None
            app.changed()
        if gui.button((x + bw + 4, y, bw, 30), f"이함 ({sum(want_air.values())})", "primary", size=12,
                      enabled=bool(want_air) and not fought, tooltip="고른 함재기를 이 항구 지역(육상)에 내립니다"):
            made, msg = g.unload_cargo(fl.id, want_air)
            app.toast(msg, None if made else t.bad)
            app.cargo_pick = None
            app.changed()
        y += 36
    elif cargo and at_sea:
        targets = g.landing_targets(fl) if want_land else {}
        if want_land:
            gui.text((x, y), "하선(상륙)할 해안", 12, t.muted, "semibold")
            y += 20
        for v, kind in sorted(targets.items(), key=lambda p: (p[1] != "land", w_.node_name(p[0]))):
            label = f"하선 → {w_.node_name(v)}" + (" (빈 적 땅 점령)" if kind == "capture" else "")
            blocked = fought or (kind == "capture" and g.army_acted(fl.id))
            if gui.button((x, y, w, 28), label, "primary" if kind == "land" else "danger", size=12,
                          enabled=not blocked,
                          tooltip="이번 턴에 움직인 함대는 빈 적 땅에 상륙할 수 없습니다" if blocked else None):
                made, msg = g.unload_cargo(fl.id, want_land, v)
                app.toast(msg, None if made else t.bad)
                app.cargo_pick = None
                app.changed()
            y += 32
        if want_land and not targets:
            y = gui.wrap((x, y), "맞닿은 해안 가운데 내릴 수 있는 곳이 없습니다. 적 병력이 있는 해안은 우클릭으로 상륙 공격합니다.",
                         w, 11, t.muted)
        if air:
            y = gui.wrap((x, y), "함재기는 항구에 정박했을 때만 내릴 수 있습니다.", w, 11, t.muted)
    # 같은 항구의 부대 싣기
    if not at_sea:
        cands = [a for a in g.armies_at(fl.loc, pid) if a.id != fl.id and (
            (fl.units.get("lst") and a.domain() == "land") or (fl.units.get("cv") and a.domain() == "air"))]
        for a in cands[:6]:
            verb = "승선" if a.domain() == "land" else "탑재"
            acted = g.army_acted(a.id)
            if gui.button((x, y, w, 28), f"{verb}: 부대 #{a.id} {a.label()}", size=12, enabled=not acted,
                          tooltip="이번 턴에 이미 행동한 부대는 다음 턴에 실을 수 있습니다" if acted
                          else "칸이 모자라면 들어가는 만큼(무거운 유닛부터) 싣습니다"):
                took, msg = g.load_cargo(fl.id, a.id)
                app.toast(msg, None if took else t.bad)
                app.cargo_pick = None
                app.changed()
            y += 32
        if not cargo and not cands:
            y = gui.wrap((x, y), "이 항구에 실을 부대가 없습니다. 육군·공군을 이 항구로 옮긴 뒤 [승선]·[탑재]하세요.",
                         w, 11, t.muted)
    return y + 4


def draw_rally(app, x, y, w, node):
    """n칸 이내 병력 집결: 이 지역에서 육상 n칸 안의 내 육군을 이리로 모은다(멀면 여러 턴 자동 이동)."""
    gui = app.gui
    g = app.game
    t = app.theme
    pid = g.player_id
    if not node or node not in g.regions or not g.friendly_territory(pid, node):
        return y
    y = section(gui, x, y, w, "병력 집결")
    n = getattr(app, "rally_n", 2)
    gui.text((x, y + 4), "이 지역에서", 12, t.muted)
    n = gui.stepper((x + 76, y, 86, 26), n, 1, 15, size=12)
    gui.text((x + 168, y + 4), "칸 이내", 12, t.muted)
    app.rally_n = n
    cands = g.rally_candidates(pid, node, n)
    units = sum(a.count() for a in cands)
    y += 32
    if gui.button((x, y, w, 30), f"{n}칸 이내 병력 집결 (부대 {len(cands)}개 · 유닛 {units})", "primary",
                  size=12, enabled=bool(cands),
                  tooltip="육상 n칸 안의 내 육군을 이 지역으로 부릅니다. 한 턴에 못 오는 부대는 여러 턴에 걸쳐 자동 이동합니다.\n"
                          "이번 턴 이미 행동한 부대(이동·전투·폭격·상륙)와 과학 유닛은 빠집니다. 부른 부대는 바로 움직입니다."):
        k, u = g.rally(pid, node, n)
        app.toast(f"{josa(app.world.node_name(node), '으로/로')} 부대 {k}개(유닛 {u}) 집결")
        app.changed()
    y += 38
    if g.regions[node].owner == pid:
        y = draw_prod_rally(app, x, y, w, node)
    return y


def draw_prod_rally(app, x, y, w, node):
    """생산 집결지(v1.3.0): 이 지역(광역시면 광역시)에서 만든 육군이 자동으로 가는 곳."""
    gui, g, t = app.gui, app.game, app.theme
    pid = g.player_id
    y = section(gui, x, y, w, "생산 집결지")
    own = getattr(g.regions[node], "rally", None)
    nat = getattr(g.player, "rally", None)
    cur = g.rally_of(pid, node)
    txt = (f"{app.world.regions[cur].name}" + (" (일괄 지정)" if not own else "")) if cur else "없음 — 만든 자리에 남음"
    gui.text((x, y), f"지금: {txt}", 12, t.text if cur else t.muted, max_w=w)
    y += 22
    bw = (w - 6) / 2
    if gui.button((x, y, bw, 28), "생산 집결지 지정", "primary", size=12,
                  tooltip="누른 뒤 지도에서 내 지역 하나를 누르면, 이 지역에서 만든 육군이 다음 턴부터 그곳으로 자동 이동합니다."):
        app.start_rally_pick(node)
    if gui.button((x + bw + 6, y, bw, 28), "해제", size=12, enabled=bool(own),
                  tooltip="이 지역만의 집결지를 지웁니다(일괄 지정이 있으면 그곳으로)." if nat else None):
        ok, msg = g.set_rally(pid, node, None)
        app.toast(msg)
    return y + 36


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
    if gui.button((x, y, 28, 28), "−", size=14, enabled=not locked and cur > 0, tooltip=None):
        new_val = cur - 1
    val, released = gui.slider((x + 40, y + 4, w - 122, 20), cur, 0, tmax * 100, 1, "tax", enabled=not locked)
    if gui.button((x + w - 74, y, 28, 28), "+", size=14, enabled=not locked and cur < tmax * 100,
                  ):
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
    # 잉여 식량: 비축 / 판매 / 배급 중 하나
    last = f.last
    surplus = max(0.0, last.get("food_prod", 0) - last.get("food_cons", 0))
    y = section(gui, x, y + 4, w, f"잉여 식량 (지난 턴 +{surplus:,.0f} · 비축 {f.res.get('food', 0):,.0f})")
    mode = getattr(f, "food_mode", "store")
    bw3 = (w - 8) / 3
    for i, (key, lab) in enumerate((("store", "잉여 식량 비축"), ("sell", "잉여 식량 판매"), ("ration", "잉여 식량 배급"))):
        if gui.button((x + i * (bw3 + 4), y, bw3, 30), lab, "primary" if mode == key else "default", size=11):
            g.set_food_mode(pid, key)
            app.changed()
    y += 36
    cons = max(1.0, last.get("food_cons", 1))
    desc = {"store": "잉여분을 비축합니다.",
            "sell": f"잉여분을 모두 개당 {g.sell_price(pid, 'food'):,.0f}에 팝니다 (약 +{surplus * g.sell_price(pid, 'food'):,.0f}/턴).",
            "ration": f"밀도 400명/km² 기준 +{min(C.FOOD_RATION_MAX, surplus / cons) * C.POP_FOCUS_GROWTH * 100:.2f}%p/턴 "
                      f"· 지역 밀도에 따라 최대 10배."}[mode]
    gui.text((x, y), desc, 11, t.muted, max_w=w)
    y += 20
    # 비축 식량 판매: 슬라이더로 양을 정해 시장 판매가로 판다
    stock_f = int(f.res.get("food", 0))
    amt = max(0, min(int(getattr(app, "food_sell_amt", 0)), stock_f))
    price = g.sell_price(pid, "food")
    gui.text((x, y + 2), "비축 식량 판매", 12, t.text, "semibold")
    sx = x + int(measure("비축 식량 판매", 12, "semibold")[0]) + 16      # 손잡이(반지름 10)가 글자를 덮지 않게
    amt, _ = gui.slider((sx, y + 2, x + w - 80 - sx, 20), amt, 0, max(1, stock_f), 1, "food_sell",
                        enabled=stock_f > 0)
    amt = int(min(amt, stock_f))
    app.food_sell_amt = amt
    if gui.button((x + w - 72, y - 2, 72, 26), "판매", "primary" if amt else "default", size=12, enabled=amt > 0,
                  tooltip=f"비축 식량 {josa(f'{amt:,}', '을/를')} 개당 {price:,.0f}에 팝니다"):
        q, gain = g.market_sell(pid, "food", amt)
        app.food_sell_amt = 0
        app.toast(f"비축 식량 {q:,} 판매: +{gain:,.0f}")
        app.changed()
    y += 24
    gui.text((x, y), f"{amt:,} / {stock_f:,} · 판매액 {amt * price:,.0f}", 11, t.muted)
    y += 20
    f.auto_food = gui.checkbox((x, y, w, 24), "식량 부족 시 자동 구매", f.auto_food)
    y += 26
    y += 4
    # 특산물
    stock = {k: v for k, v in f.specialty.items() if v > 0}
    supplied = sum(len(r.supplied) for r in g.regions_of(pid))
    y = section(gui, x, y, w, f"특산물 (이번 턴 {sum(stock.values())}개 · 공급 {supplied}건, 남는 것은 사라짐)")
    f.auto_specialty = gui.checkbox((x, y, w - 110, 24), "행복도 낮은 지역부터 자동", f.auto_specialty, size=12)
    if gui.button((x + w - 100, y - 2, 100, 26), "배분 수정", size=12):
        app.spec_sel = app.sel if app.sel in g.regions and g.regions[app.sel].owner == pid else None
        app.modal = ("specialty", None)
    y += 30
    # 지출 우선순위 (드래그)
    items = g.projects_by_priority(pid)
    y = section(gui, x, y + 6, w, "지출 우선순위 (드래그, 또는 클릭 후 ↑↓)")
    bw2 = (w - 4) / 2
    cur = getattr(f, "prio_mode", None)
    for i, (mode, lab) in enumerate(g.PRIORITY_SORTS.items()):
        if gui.button((x + (i % 2) * (bw2 + 4), y + (i // 2) * 32, bw2, 28), lab, size=11, selected=mode == cur,
                      tooltip="누르면 해제할 때까지 계속 이 규칙대로 정렬합니다(새 작업·남은 턴이 바뀌어도). "
                              "다시 누르거나 직접 끌어서 옮기면 해제됩니다." if mode != cur else "다시 누르면 자동 정렬 해제"):
            now = g.set_priority_mode(pid, mode)
            items = g.projects_by_priority(pid)
            app.toast(f"지출 우선순위 자동 정렬: {lab} (해제할 때까지 유지)" if now else "지출 우선순위 자동 정렬 해제")
    y += 68
    cur = getattr(f, "prio_mode", None)
    gui.text((x, y - 2), f"자동 정렬 유지 중: {g.PRIORITY_SORTS[cur]} (다시 누르면 해제)" if cur
             else "자금이 모자라면 위에서부터 비용을 내고 아래 작업이 정지됩니다.", 11, t.accent if cur else t.muted, max_w=w)
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
    off = gui.begin_scroll("diplo", area, len(others) * 50 + 130)
    y = body.y - off
    y0 = y
    for o in others:
        st = D.stage(g, o.id, pid)
        op = D.opinion(g, o.id, pid)
        if gui.button((x - 4, y, w + 8, 46), "", "ghost"):
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
        y += 24
    y = max(y + 6, y0 + body.h - TRADE_REJECT_H)      # 목록이 짧으면 탭 맨 아래에 붙인다
    y = _trade_reject_section(app, x, y, w)
    gui.end_scroll("diplo", area, y - y0)


TRADE_REJECT_H = 132


def _trade_reject_section(app, x, y, w):
    """외교 탭 하단: AI 의 거래 제의를 통째로 거절하는 설정(v1.3.0)."""
    gui, t = app.gui, app.theme
    ai = app.game.player.ai
    gui.line(t.border, (x, y), (x + w, y))
    y += 8
    gui.text((x, y), "AI 거래 제의", 13, weight="bold")
    y += 22
    for key, label, hint in (("reject_buy", "모든 구매 제의 거절", "상대가 내 자원·특산물을 사겠다는 제의"),
                             ("reject_sell", "모든 판매 제의 거절", "상대가 자원·특산물을 팔겠다는 제의")):
        v = gui.checkbox((x, y, w, 24), label, bool(ai.get(key)), size=12)
        if v != bool(ai.get(key)):
            ai[key] = v
        gui.text((x + 26, y + 24), hint, 11, t.muted, max_w=w - 26)
        y += 46
    return y + 4


def _reject_from(app):
    """이 국가의 거래 제의 거절 목록(set). 없으면 만든다."""
    ai = app.game.player.ai
    s = ai.get("reject_from")
    if not isinstance(s, set):
        s = ai["reject_from"] = set(s or ())
    return s


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
               f"상대 우호도 -100,\n전쟁광 평판: {D.warmonger_text(g, pid)}\n"
               "한 번 더 눌러야 선포됩니다.")
    confirm = getattr(app, "war_confirm", None) == fid and can_war
    if gui.button((x + bw + 8, y, bw, 40), "선전포고 확정" if confirm else "선전포고", "danger", size=14,
                  enabled=can_war, tooltip=tip):
        if confirm:
            app.war_confirm = None
            ok, msg = D.declare_war(g, pid, fid)
            app.toast(msg or f"{o.name}에 선전포고했습니다.", t.bad)
            app.changed()
        else:
            app.war_confirm = fid
    y += 52
    if known:
        rej = _reject_from(app)
        v = gui.checkbox((x, y, w, 24), "이 국가의 거래 제의 거절", fid in rej, size=12)
        if v != (fid in rej):
            (rej.add if v else rej.discard)(fid)
        y += 32
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
        return f"{head} · 복합 무역 센터 {len(g.finance_cluster(pid))}/{C.ECON_CLUSTER}곳"
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
        if cs["met"] and cs["wars"]:
            txt += f" · 전쟁 {cs['wars']}곳 — 모두 강화하면 승리"
        y = kv(gui, x, y, w, "정복승리(2/3 + 반란 없음 + 전쟁 없음)", txt,
               t.good if cs["ok"] else (t.warn if cs["met"] else None))
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


# 국가 현황 추이(Game.stat_hist 한 줄 = (턴, GDP, 지역 수, 인구)): 키 → 열 번호·이름·단위
STAT_COL = {"gdp": 1, "regions": 2, "pop": 3}
STAT_NAME = {"gdp": "GDP", "regions": "영토", "pop": "인구"}
STAT_UNIT = {"gdp": "만원 / 턴", "regions": "지역 수", "pop": "만 명"}


def stat_color(t, key):
    """추이 선 색(어두운 모드는 바탕과 구분되게 밝힌다)."""
    c = {"gdp": t.indigo_lt, "regions": t.jade, "pop": (138, 106, 58)}[key]
    return mix(c, (255, 255, 255), 0.45) if t.dark else c


def stat_text(key, v, detail=False, sign=False):
    """추이 값 글자. detail=True 면 인구를 소수 한 자리까지, sign=True 면 +/− 부호."""
    if key == "regions":
        return f"{v:+,.0f}곳" if sign else f"{v:,.0f}곳"
    if key == "pop":
        d = 1 if detail else 0
        return f"{v:+,.{d}f}만" if sign else f"{v:,.{d}f}만"
    return f"{v:+,.0f}" if sign else f"{v:,.0f}"


def _magnifier(gui, center, col):
    """작은 돋보기(크게 보기 표시)."""
    cx, cy = center
    gui.circle(col, (cx - 1.5, cy - 1.5), 4, 1.5)
    gui.line(col, (cx + 1.5, cy + 1.5), (cx + 5, cy + 5), 2)


def sparkline(gui, rect, vals, col):
    """작은 꺾은선(최근 추이). 값이 둘 미만이면 가로선만."""
    r = pygame.Rect(rect)
    pr = gui.R(r)
    if len(vals) < 2:
        pygame.draw.line(gui.screen, mix(col, gui.t.panel, 0.5), (pr.x, pr.bottom - 1), (pr.right, pr.bottom - 1), 1)
        return
    lo, hi = min(vals), max(vals)
    hi = hi if hi > lo else lo + 1
    n = len(vals)
    pts = [(pr.x + i / (n - 1) * pr.w, pr.bottom - (v - lo) / (hi - lo) * pr.h) for i, v in enumerate(vals)]
    fill = pygame.Surface(pr.size, pygame.SRCALPHA)
    pygame.draw.polygon(fill, (*col, 40), [(px - pr.x, py - pr.y) for px, py in pts] + [(pr.w, pr.h), (0, pr.h)])
    gui.screen.blit(fill, pr.topleft)
    pygame.draw.lines(gui.screen, col, False, pts, max(1, int(2 * gui.u)))
    pygame.draw.circle(gui.screen, col, (int(pts[-1][0]), int(pts[-1][1])), max(2, int(3 * gui.u)))


def draw_victory_bars(app, x, y, w, pid):
    """승리 조건별 진행 막대(국가 현황): 이름 · 다음 할 일 · 진행값."""
    g, gui, t = app.game, app.gui, app.theme
    vs = g.settings.victories
    f = g.factions[pid]
    rows = []
    if "conquest" in vs:
        cs = g.conquest_status(pid)
        desc = "2/3 영토 · 반란 없음 · 전쟁 없음" + (f" · 반란 가능 {cs['risky']}곳" if cs["risky"] is not None else "")
        if cs["met"] and cs["wars"]:
            desc = f"조건 충족 — 전쟁 {cs['wars']}곳을 모두 강화하면 승리"
        rows.append(("정복", desc, f"{cs['have']} / {cs['need']}곳", cs["have"] / max(1, cs["need"]), t.vermilion))
    if "science" in vs:
        txt = science_progress_text(g, pid)
        head, _, rest = txt.partition(" · ")
        total = len(C.SCIENCE_STEPS) + 1
        done = sum(1 for st in C.SCIENCE_STEPS if st in f.science)
        rows.append(("과학", "다음: " + rest, head, done / total, t.indigo_lt))
    if "economic" in vs:
        txt = econ_progress_text(g, pid)
        head, _, rest = txt.partition(" · ")
        rows.append(("경제", rest, head, g.econ_stage(pid) / max(1, C.ECON_STAGES), (160, 122, 44)))
    if "diplomatic" in vs:
        alive = g.alive_ids()
        cid = D.coalition_of(g, pid)
        n = len(g.dip.coalitions[cid]["members"] & set(alive)) if cid is not None else 1
        rows.append(("외교", "모두 한 연합", f"{n} / {len(alive)}개국", n / max(1, len(alive)), t.jade))
    if "time" in vs:
        sc = g.time_scores()
        rank = sorted(sc, key=lambda k: -sc[k]).index(pid) + 1 if pid in sc else "-"
        mt = getattr(g.settings, "max_turns", C.TIME_VICTORY_TURNS)
        left = max(0, mt - g.turn)
        rows.append(("시간", f"{left}턴 남음", f"{sc.get(pid, 0):.1f}점 · {rank}위", 1 - left / max(1, mt), t.muted))
    for name, desc, val, frac, col in rows:
        nr = gui.text((x, y), name, 13, t.text, "serif")
        vr = gui.text((x + w, y + 1), val, 11, t.text, "semibold", anchor="topright")
        gui.text((nr.right + 8, y + 2), desc, 10, t.muted, "semibold", max_w=max(20, vr.x - nr.right - 14))
        br = pygame.Rect(x, y + 19, w, 6)
        gui.rect(mix(t.border, t.panel, 0.45), br, radius=3)
        gui.rect(col, (br.x, br.y, max(6, int(br.w * min(1.0, frac))), br.h), radius=3)
        y += 31
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
    # 국력 타일(최근 추이) — 누르면 턴별 추이를 크게 본다(modals.draw_stat_chart)
    hist = getattr(g, "stat_hist", {}).get(pid, [])[-52:]
    tiles = [("gdp", "GDP / 턴", f"{last.get('gdp', 0):,.0f}"),
             ("regions", "영토", f"{len(regs)}곳"),
             ("pop", "인구", f"{g.total_pop(pid):,.0f}만")]
    tw = (w - 12) / 3
    for i, (key, lab, val) in enumerate(tiles):
        r = pygame.Rect(int(x + i * (tw + 6)), y, int(tw), 72)
        hov = gui.hover(r)
        gui.rect(mix(t.panel, t.panel_alt, 0.6), r, radius=4)
        pygame.draw.rect(gui.screen, t.gold if hov else t.border, gui.R(r), gui.W(2) if hov else 1,
                         border_radius=int(4 * gui.u))
        gui.text((r.x + 7, r.y + 5), lab, 10, t.muted, "semibold")
        gui.text((r.x + 7, r.y + 18), val, 14, t.text, "bold", max_w=r.w - 10)
        _magnifier(gui, (r.right - 11, r.y + 11), t.gold if hov else mix(t.muted, t.panel, 0.3))
        col = stat_color(t, key)
        sparkline(gui, (r.x + 7, r.y + 44, r.w - 14, 22), [h[STAT_COL[key]] for h in hist], col)
        if hov:
            gui.tooltip = "누르면 턴별 추이를 크게 봅니다"
            if gui.clicked:
                gui.clicked = False
                app.modal = ("stat_chart", key)
    y += 82
    # 핵심 지표: 행복도(명목·실질), 군 전력(사기), 국력(패권), 전쟁 피로(턴당 변화)
    ww = f.war_weary
    if D.enemies(g, pid):
        rec, rec_col = f"턴당 +{D.war_weary_rate(g, pid):.1f}", t.bad
    else:
        rec, rec_col = (f"턴당 −{C.WAR_WEARY_RECOVERY:.0f}" if ww > 0 else "평시"), t.muted
    morale = g.morale(pid)
    eff = g.avg_happiness(pid)
    cells = [("행복도", f"{g.avg_happiness(pid, effective=False):+.1f}", f"실질 {eff:+.1f}", t.bad if eff < 0 else t.good,
              "평균 행복도(실질: 전쟁 피로·점령 저항 반영). 산출·반란·인구·사기는 실질로 판정"),
             ("군 전력", f"{g.mil_power(pid):,.0f}", f"사기 ×{morale:.2f}", t.bad if morale < 1 else t.muted,
              "군 사기: 실질 평균 행복도 −10 이하이면 전투력이 줄어듭니다"),
             ("국력", f"{g.power.get(pid, 0):.2f}", "패권" if g.hegemon == pid else "패권 아님", t.muted, None),
             ("전쟁 피로", f"{ww:.1f}", rec, rec_col,
              f"전쟁 피로도 {ww:.1f} / {C.WAR_WEARY_MAX:.0f}"
              + (f"\n그중 당한 전쟁 {f.war_weary_def:.1f} (반란 판정에서는 빼지 않음)" if f.war_weary_def >= 0.05 else ""))]
    cw = (w - 9) / 4
    for i, (k, v, sub, sc, tip) in enumerate(cells):
        r = pygame.Rect(int(x + i * (cw + 3)), y, int(cw), 48)
        if i:
            gui.line(t.border, (r.x - 2, r.y + 6), (r.x - 2, r.bottom - 6))
        gui.text((r.centerx, r.y + 1), k, 10, t.muted, "semibold", anchor="midtop")
        gui.text((r.centerx, r.y + 14), v, 14, t.text, "bold", anchor="midtop", max_w=r.w - 4)
        gui.text((r.centerx, r.y + 33), sub, 10, sc, "semibold", anchor="midtop", max_w=r.w - 4)
        if tip and gui.hover(r):
            gui.tooltip = tip
    y += 56
    # 재정
    items = g.projects_by_priority(pid)
    spend = {}
    for rr in items:
        k = rr.project.kind
        n, s = spend.get(k, (0, 0.0))
        spend[k] = (n + 1, s + rr.project.per_turn)
    total_spend = sum(s for _, s in spend.values())
    y = section(gui, x, y + 6, w, "재정 (지난 턴 실제 수입·지출)")
    from .progression import draw_balances
    y = draw_balances(app, x, y, w)
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
    # 승리의 길
    y = section(gui, x, y + 6, w, "승리의 길")
    y = draw_victory_bars(app, x, y, w, pid)
    # 자원
    y = section(gui, x, y + 6, w, "자원")
    y = kv(gui, x, y, w, "식량", f"{f.res.get('food', 0):,.0f} (생산 {last.get('food_prod', 0):,.0f} / 소비 "
           f"{last.get('food_cons', 0):,.0f})")
    y = kv(gui, x, y, w, "이번 턴 석유 / 석탄 / 전기",
           f"{f.res.get('oil', 0):,.0f} / {f.res.get('coal', 0):,.0f} / {f.res.get('elec', 0):,.0f}")
    # 특산물 재고
    stock = {k: v for k, v in f.specialty.items() if v > 0}
    kinds = sorted(set(stock) | set(g.specialty_kinds(pid)))
    y = section(gui, x, y + 6, w, f"이번 턴 특산물 {sum(stock.values())}개 · {len(kinds)}종 (눌러서 생산지 열기)")
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
        info = f"이번 턴 {stock.get(k, 0)} · 공급 {supplied.get(k, 0)}곳"
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
    # 지도자·체제
    lead = LEADER_BY_KEY[f.leader]
    gov = GOV_BY_KEY.get(f.gov, {})
    y = section(gui, x, y + 6, w, "지도자·체제")
    from .modals import no_effect

    def eff(nm, desc, none):
        if no_effect(nm, desc):
            return none
        return f"{nm}({desc})" if nm else desc
    y = gui.wrap((x, y), f"지도자 {lead['name']}: {eff(*lead['buff'], '버프 없음')} / "
                 f"{eff(*lead['debuff'], '디버프 없음')}", w, 11, t.muted)
    if gov:
        from ..progression import POLICIES, POLICY_COMPLETION
        names = [p["name"] for p in POLICIES.get(f.gov, [])[:f.policy_level]]
        y = gui.wrap((x, y), f"체제 {gov['name']}: 정책 {f.policy_level}/5 · " + (", ".join(names) or "미해금"),
                     w, 11, t.muted)
        if f.policy_level == 5 and f.gov in POLICY_COMPLETION:
            y = gui.wrap((x, y), "★ " + POLICY_COMPLETION[f.gov]["name"], w, 11, t.good)
        if gui.button((x, y + 5, w, 28), "정책·과학·위인 관리", size=12):
            app.left_tab, app.progression_tab = "progression", "policy"
        y += 38
    app._nation_h = y - y0 + 20
    gui.end_scroll("nation_status", area, app._nation_h)


PRIO_HOLD_MS = 1000     # 우선순위 ↑↓를 이만큼 누르고 있으면
PRIO_REPEAT_MS = 70     # 이 간격으로 빠르게 이어서 움직인다


def draw_priority_list(app, x, y, w, items):
    """자금 지출 우선순위 목록. 행을 끌어 순서를 바꾼다."""
    gui = app.gui
    g = app.game
    t = app.theme
    row_h = 44
    # 같은 중립 지역을 함께 편입하는 작업은 한 줄(v1.3.0): 줄 = 맨 앞 지역 ID
    rows, first_of = {}, {}
    for rr in items:
        k = g._row_key(rr)
        if k in first_of:
            rows[first_of[k]].append(rr)
        else:
            first_of[k] = rr.id
            rows[rr.id] = [rr]

    def expand(order):
        return [r.id for rid in order for r in rows[rid]]
    n = len(rows)
    if not n:
        gui.text((x, y), "진행 중인 작업이 없습니다.", 13, t.muted)
        return y + 26
    top = y
    drag = getattr(app, "prio_drag", None)
    ids = list(rows)
    if drag not in ids:
        drag = app.prio_drag = None
    pinned = {rid for rid, lst in rows.items() if any(getattr(r.project, "pinned", False) for r in lst)}

    def pin_rect(i):
        return pygame.Rect(x + w - 64, top + i * row_h + 6, 36, row_h - 16)
    # 고정 단추: 누르면 맨 위에 고정/해제(끌기보다 먼저)
    if drag is None:
        for i, rid in enumerate(ids):
            if gui.hover(pin_rect(i)):
                if gui.clicked:
                    gui.clicked = False
                    on = g.toggle_pin(g.player_id, rid)
                    app.toast(f"{app.world.regions[rid].short}: " + ("우선순위 맨 위에 고정" if on else "고정 해제"))
                    return draw_priority_list(app, x, y, w, g.projects_by_priority(g.player_id))
                break
    # 끌기 시작
    if drag is None and gui.down and gui.drag_id is None:
        for i, rid in enumerate(ids):
            if gui.hover(pin_rect(i)):
                break
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
        order.sort(key=lambda r: r not in pinned)      # 고정한 작업은 고정하지 않은 작업보다 늘 위
    for i, rid in enumerate(order):
        rr = g.regions[rid]
        p = rr.project
        row = pygame.Rect(x, top + i * row_h, w, row_h - 4)
        dragged = rid == drag
        gui.rect(t.accent if dragged else t.panel_alt, row, radius=8)
        fg = (255, 255, 255) if dragged else t.text
        sub = (235, 240, 255) if dragged else t.muted
        mt = M.get(app.game, getattr(p, "metro", None))
        lst = rows[rid]
        if p.kind == "annex" and len(lst) > 1:
            who = ", ".join(M.label(g, r.id) if M.of(g, r.id) else app.world.regions[r.id].short for r in lst)
            label = f"{who} · 편입: {app.world.regions[p.key].short}"
        else:
            label = (f"{project_name(app, p, rid)} · 지역 {len(app.game.group_regions(p))}곳" if getattr(p, "group", None)
                     else f"{mt['name']} · {project_name(app, p, rid)}" if mt
                     else f"{app.world.regions[rid].short} · {project_name(app, p, rid)}")
        gui.text((row.x + 8, row.y + 3), f"{i + 1}. {label}", 12, fg, "semibold", max_w=w - 80)
        stalled = any(r.project.stalled for r in lst)
        state = "정지" if stalled else f"남은 {app.game.project_left(rid)}턴"
        if p.kind == "annex":
            jn = app.game.joint_count(rr.owner, p.key)
            if jn > 1:
                state += f" · 공동 {jn}곳 −{app.game.joint_reduction_of(rr.owner, p.key):.0%}"
        gui.text((row.x + 8, row.y + 21), f"턴당 {sum(r.project.per_turn for r in lst):,.0f} · {state}", 11,
                 (t.bad if stalled and not dragged else sub))
        pr = pin_rect(i)
        on = rid in pinned
        gui.rect(t.gold if on else (t.panel if not dragged else t.accent), pr, radius=5)
        gui.rect(t.border, pr, 1, radius=5)
        gui.text(pr.center, "고정", 11, (40, 30, 10) if on else sub, "semibold", anchor="center")
        if gui.hover(pr):
            gui.tooltip = ("이 작업을 지출 우선순위 맨 위에 고정합니다(정렬·끌기로 바뀌지 않음). 다시 누르면 해제." if not on
                           else "고정 해제")
        gui.text((row.right - 8, row.centery), "≡", 16, sub, anchor="midright")
    # 놓기: 움직였으면 순서 변경, 제자리면 그 행을 고른다(↑↓로 이동)
    if drag is not None and not gui.down:
        app.prio_drag = None
        if order != ids:
            was = getattr(g.player, "prio_mode", None)
            g.set_priority_order(g.player_id, expand(order), manual=True)
            gui.clicked = False
            app.toast(f"우선순위 변경: {app.world.regions[drag].short} → {order.index(drag) + 1}번"
                      + (" · 자동 정렬 해제" if was else ""))
        else:
            app.prio_sel = None if app.prio_sel == drag else drag
    sel = getattr(app, "prio_sel", None)
    if sel in ids and drag is None:
        i = ids.index(sel)
        gui.rect(t.accent, pygame.Rect(x, top + i * row_h, w, row_h - 4), 2, radius=8)
        app.arrow_capture_v = True                # ↑↓를 누르고 있어도 지도는 위아래로 움직이지 않는다

        def step(d):
            nonlocal ids, i
            j = i + d
            if 0 <= j < n:
                new = ids[:]
                new[i], new[j] = new[j], new[i]
                if getattr(g.player, "prio_mode", None):
                    app.toast("직접 옮겨서 자동 정렬을 해제했습니다.")
                g.set_priority_order(g.player_id, expand(new), manual=True)
                ids, i = new, j
        now = pygame.time.get_ticks()
        for k in list(gui.keys):
            if k.key in (pygame.K_UP, pygame.K_DOWN) and not gui.focus:
                gui.keys.remove(k)                 # 지도 이동 대신 순서 이동
                d = -1 if k.key == pygame.K_UP else 1
                step(d)
                app.prio_hold = [d, now, now]      # 1초 넘게 누르고 있으면 빠르게 이어서 움직인다
            elif k.key == pygame.K_ESCAPE:
                gui.keys.remove(k)
                app.prio_sel = None
        hold = getattr(app, "prio_hold", None)
        if hold and not gui.focus:
            pressed = pygame.key.get_pressed()
            if not pressed[pygame.K_UP if hold[0] < 0 else pygame.K_DOWN]:
                app.prio_hold = None
            elif now - hold[1] >= PRIO_HOLD_MS and now - hold[2] >= PRIO_REPEAT_MS:
                hold[2] = now
                step(hold[0])
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
    if gui.button((x, y - 2, 120, 28), "자동 배정", "primary", size=12):
        units, cap = g.assign_energy(pid)
        app.toast(f"자원 자동 배정: 공장 연료 {units}/{cap}")
        app.changed()
    each = getattr(f, "energy_each_turn", True)
    cb = (x + 132, y - 2, min(220, w - 132), 28)
    nv = gui.checkbox(cb, "매 턴 자동 배정", each, size=12)
    if gui.hover(cb):
        gui.tooltip = ("켜 두면 턴이 시작될 때마다 [자동 배정]을 다시 실행합니다(새 공장·발전소에도 바로 연료). "
                       "끄면 직접 정한 배정을 그대로 쓰고, 새 공장·발전소가 생기면 알려 줍니다.")
    if nv != each:
        f.energy_each_turn = nv
        if nv:
            g.assign_energy(pid)
        app.changed()
    y += 30
    plan = g.energy_plan(pid)
    plants, facts = g.energy_sites(pid)
    # 에너지 흐름 표의 앞부분(어디서 들어오고 나갔는가): 채굴 · 타국 계약 구매·판매 · 병력 생산 · 시장 등(v1.3.0)
    pl0 = g.energy_plan(pid)
    st0, mi0 = pl0["stock"], pl0["mined"]
    recv = getattr(f, "recv", {}) or {}
    sent = getattr(f, "sent", {}) or {}
    ufuel = getattr(f, "unit_fuel", {}) or {}
    keys3 = ("coal", "oil", "elec")
    src_rows = [("채굴·자체 발전", tuple(mi0[k] for k in keys3), False)]
    if any(recv.get(k) for k in keys3):
        src_rows.append(("타국에서 구매(계약)", tuple(recv.get(k, 0) for k in keys3), True))
    if any(sent.get(k) for k in keys3):
        src_rows.append(("타국에 판매(계약)", tuple(-sent.get(k, 0) for k in keys3), True))
    if any(ufuel.get(k) for k in keys3):
        src_rows.append(("병력 생산", tuple(-ufuel.get(k, 0) for k in keys3), True))
    other = tuple(st0[k] - mi0[k] - recv.get(k, 0) + sent.get(k, 0) + ufuel.get(k, 0) for k in keys3)
    if any(abs(v) >= 0.5 for v in other):
        src_rows.append(("시장 거래 등", other, True))
    flow_h = 236 + 20 * len(src_rows)
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
                 f"(석탄 1→전기 {g.power_elec(pid, 'coal', 1):g}~{g.power_elec(pid, 'coal', 5):g}, 석유는 두 배 · 단계별)")
    for r in plants:
        u = plan["plants"].get(r.id, {})
        gui.text((x, yy), f"{app.world.regions[r.id].name} · {r.b['power']}단계", 12, weight="semibold", max_w=w - 90)
        gui.text((x + w, yy), f"전기 +{u.get('elec_out', 0):.1f}", 12, t.good if u.get("elec_out") else t.muted,
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
        per = R.factory_unit(lv)
        gui.text((x, yy), f"{app.world.regions[r.id].name} · {lv}단계 · 1개당 {per:,.0f}", 12, weight="semibold",
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
    p_elec = plan.get("elec_gen_int", 0)          # 전국 발전량 합계의 정수 부분
    fu = {k: sum(a[k] for a in plan["factories"].values()) for k in ("coal", "oil", "elec")}
    st, mi, af = plan["stock"], plan["mined"], plan["after"]
    rows = src_rows + [("① 이번 턴 확보", (st["coal"], st["oil"], st["elec"]), False),
            ("② 발전소 투입", (-p_coal, -p_oil, 0), True),
            ("③ 발전", (0, 0, p_elec), True),
            ("④ 공장 투입", (-fu["coal"], -fu["oil"], -fu["elec"]), True),
            ("남는 양 → 판매", (af["coal"], af["oil"], af["elec"]), False)]
    for label, vals, signed in rows:
        bold = not signed and label != "채굴·자체 발전"
        gui.text((x, fy), label, 12, t.text if bold else t.muted, "semibold" if bold else "regular")
        for cx, v in zip(cols, vals):
            if signed and not v:
                txt, col = "·", t.muted
            else:
                txt = f"{v:+,.0f}" if signed else f"{v:,.0f}"
                col = (t.good if v > 0 else t.bad) if signed else t.text
            gui.text((cx + 40, fy), txt, 12, col, "semibold" if bold else "regular", anchor="topright")
        fy += 20
        if label in ("① 이번 턴 확보", "④ 공장 투입"):
            gui.line(t.border, (x, fy - 2), (x + w, fy - 2))
    sold = sum(max(0, int(af[k])) * g.sell_price(pid, k) for k in C.ENERGY)
    short = {k: -int(math.floor(af[k] + 1e-9)) for k in C.ENERGY if af[k] < -1e-9}
    if short:                                       # 판매 계약으로 먼저 보낸 몫이 이번 턴 확보·발전보다 많다
        cost = sum(n * C.MARKET_BUY[k] * C.MONEY_SCALE for k, n in short.items())
        gui.text((x, fy + 2), "계약 부족분 " + ", ".join(f"{C.RESOURCE_NAMES[k]} {n}" for k, n in short.items())
                 + f" → 턴 끝에 시장가로 구매(−{cost:,.0f})", 11, t.bad, "semibold", max_w=w)
        fy += 18
    gui.text((x, fy + 2), f"판매 계약분은 공장보다 먼저 보내고, 남는 양은 턴 종료 때 시장 판매(+{sold:,.0f})", 11, t.muted,
             max_w=w)
    fy += 20
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
