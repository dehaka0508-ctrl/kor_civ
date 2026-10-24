"""행정·과학 현황, 정책·기술 해금과 위인 운용 화면."""
from __future__ import annotations

import pygame

from .. import config as C
from .. import metro as M
from ..leaders import GOV_BY_KEY
from ..text import fmt_points
from .theme import mix


def great_person_icon(surface, kind, center, color, u=1.0):
    """작은 배지에서도 구분되는 네 가지 벡터 문양."""
    x, y = center
    width = max(1, int(1.4 * u))

    def p(dx, dy):
        return round(x + dx * u), round(y + dy * u)

    if kind == "scientist":
        pygame.draw.lines(surface, color, True,
                          [p(-2, -5), p(2, -5), p(2, -1), p(5, 5), p(-5, 5), p(-2, -1)], width)
        pygame.draw.line(surface, color, p(-3, 2), p(3, 2), width)
        pygame.draw.line(surface, color, p(-3, -5), p(3, -5), width)
    elif kind == "chancellor":
        pygame.draw.rect(surface, color, pygame.Rect(p(-5, 1), (round(10 * u), max(2, round(4 * u)))))
        pygame.draw.lines(surface, color, False, [p(-3, 0), p(-3, -3), p(0, -5), p(3, -3), p(3, 0)], width)
        pygame.draw.line(surface, color, p(-6, 5), p(6, 5), width)
    elif kind == "general":
        pygame.draw.polygon(surface, color, [p(-2, 1), p(4, -6), p(5, -3), p(0, 3)])
        pygame.draw.line(surface, color, p(-4, 0), p(2, 5), width)
        pygame.draw.line(surface, color, p(-2, 3), p(-5, 6), max(2, width))
    elif kind == "artist":
        pygame.draw.ellipse(surface, color, pygame.Rect(p(-5, 2), (round(6 * u), max(2, round(4 * u)))))
        pygame.draw.line(surface, color, p(0, 4), p(0, -6), width)
        pygame.draw.lines(surface, color, False, [p(0, -6), p(5, -3), p(4, 0)], width)


def great_person_badge(surface, kind, center, color, u=1.0, selected=False):
    radius = max(1, int(9 * u))
    center = tuple(round(v) for v in center)
    pygame.draw.circle(surface, (31, 26, 22), center, radius + max(1, int(u)))
    pygame.draw.circle(surface, color, center, radius)
    pygame.draw.circle(surface, (255, 255, 255) if selected else (231, 198, 108), center, radius,
                       max(1, int(1.5 * u)))
    great_person_icon(surface, kind, center, (255, 255, 255), u)
    return pygame.Rect(center[0] - radius, center[1] - radius, radius * 2 + 1, radius * 2 + 1)


def draw_balances(app, x, y, w, detailed=True):
    from .panels import kv
    g, gui, t, f = app.game, app.gui, app.theme, app.game.player
    prod, cons = g.admin_balance(f.id)
    y = kv(gui, x, y, w, "비축 행정력", f"{f.admin:,.0f}  ({prod-cons:+,.1f}/턴)",
           t.bad if f.lawless else t.text)
    if detailed:
        y = kv(gui, x, y, w, "행정력 생산 / 소비", f"{prod:,.1f} / {cons:,.1f}")
    y = kv(gui, x, y, w, "비축 과학력", f"{fmt_points(f.sci_points)}  (+{fmt_points(g.science_production(f.id))}/턴)")
    if f.lawless:
        y = gui.wrap((x, y), f"무법 상태 · 매 턴 전 지역 행복도 −{abs(C.LAWLESS_HAPPY):g}. 행정력을 흑자로 전환하세요.", w, 12, t.bad) + 5
    elif f.admin_deficit_turns:
        y = gui.wrap((x, y), f"행정력 고갈·적자 {f.admin_deficit_turns}턴 연속 · 행정 건물을 증축하세요.",
                     w, 11, t.warn) + 5
    return y


def _result(app, result):
    ok, message = result
    app.toast(message, None if ok else app.theme.bad)
    if ok:
        app.changed()


def draw_progression_tab(app, body, science=False):
    gui, g, t = app.gui, app.game, app.theme
    x, w = body.x + 14, body.w - 28
    y = draw_balances(app, x, body.y, w, detailed=False) + 5
    tabs = ("tech", "military") if science else ("policy", "people")
    attr = "science_tab" if science else "progression_tab"
    current = getattr(app, attr, tabs[0])
    current = current if current in tabs else tabs[0]
    index = gui.segmented((x, y, w, 30), ["기술", "군사"] if science else ["정책 트리", "위인"],
                          tabs.index(current), size=12)
    current = tabs[index]
    setattr(app, attr, current)
    y += 40
    area = pygame.Rect(body.x, y, body.w, max(1, body.bottom - y))
    scroll_key = "progression:" + current
    heights = app.__dict__.setdefault("_progression_h", {})
    off = gui.begin_scroll(scroll_key, area, heights.get(current, 1400))
    y0 = y - off
    if current == "policy":
        bottom = draw_policies(app, x, y0, w)
    elif current in ("tech", "military"):
        bottom = draw_technologies(app, x, y0, w, military=current == "military")
    else:
        bottom = draw_great_people(app, x, y0, w)
    heights[current] = bottom - y0 + 8
    gui.end_scroll(scroll_key, area, heights[current])


def draw_policies(app, x, y, w):
    from ..progression import POLICIES, POLICY_COMPLETION
    from .panels import section
    gui, g, t, f = app.gui, app.game, app.theme, app.game.player
    if f.gov not in GOV_BY_KEY:
        return draw_government_cards(app, x, y, w)
    policies = POLICIES.get(f.gov, [])
    y = section(gui, x, y, w, GOV_BY_KEY.get(f.gov, {}).get("name", "체제 미정"))
    y = gui.wrap((x, y), "잉여 행정력으로 순서대로 해금합니다. 해금한 정책의 효과는 모두 누적됩니다.", w, 12, t.muted) + 12
    for index, policy in enumerate(policies, 1):
        done = f.policy_level >= index
        next_policy = f.policy_level + 1 == index
        color = t.good if done else (t.text if next_policy else t.muted)
        gui.text((x, y), f"{index}. {policy['name']}", 14, color, "semibold", max_w=w - 76)
        gui.text((x, y + 23), "시행 중" if done else f"행정력 {policy['cost']:,}", 11, color)
        label = "시행 중" if done else ("해금" if next_policy else "잠김")
        if gui.button((x + w - 70, y, 70, 29), label, "primary" if next_policy else "default",
                      enabled=next_policy and f.admin >= policy["cost"], size=12,
                      tooltip="앞 단계 정책을 먼저 해금하세요." if not done and not next_policy else
                      (f"행정력 {policy['cost']:,} 필요" if not done else "효과가 적용 중입니다.")):
            _result(app, g.unlock_policy(f.id))
        y = gui.wrap((x, y + 42), policy["description"], w, 12, color) + 15
        gui.line(t.border, (x, y - 6), (x + w, y - 6))
    completion = POLICY_COMPLETION.get(f.gov)
    if completion:
        y = section(gui, x, y + 5, w, "★ 체제 완성 · " + completion["name"])
        y = gui.wrap((x, y), completion["description"], w, 12, t.good if f.policy_level == 5 else t.muted) + 5
        y = gui.wrap((x, y), "완성 보너스 적용 중" if f.policy_level == 5 else "5단계를 해금하면 함께 활성화됩니다.",
                     w, 11, t.good if f.policy_level == 5 else t.muted) + 12
    if not policies:
        y = gui.wrap((x, y), "이 체제에는 해금할 정책이 없습니다.", w, 12, t.muted) + 10
    return y


def draw_government_cards(app, x, y, w):
    from ..leaders import GOVERNMENTS, GOV_DESCRIPTIONS, GOV_OFFICES, banned_govs
    from ..progression import POLICIES, POLICY_COMPLETION
    from .panels import section
    gui, g, t, f = app.gui, app.game, app.theme, app.game.player
    y = section(gui, x, y, w, "정치체제를 고르세요")
    y = gui.wrap((x, y), "한 번 선택하면 바꿀 수 없습니다. 수도에 집무실이 설치되고 정책 트리가 열립니다.",
                 w, 12, t.muted) + 12
    banned = banned_govs(f.leader)
    for spec in GOVERNMENTS:
        key = spec["key"]
        blocked = key in banned
        box = pygame.Rect(x, y, w, 110)
        gui.rect(t.panel_alt, box, radius=6)
        gui.rect(t.border, box, 1, radius=6)
        gui.text((x + 10, y + 8), spec["name"], 15, t.muted if blocked else t.text, "semibold")
        gui.wrap((x + 10, y + 35), GOV_DESCRIPTIONS[key], w - 20, 12, t.muted)
        gui.text((x + 10, y + 88), f"{GOV_OFFICES[key]} · 행정력 +{fmt_points(max(30, M.total_pop(g, f.capital)))}/턴",
                 11, t.good if not blocked else t.muted, max_w=w - 20)
        if gui.button((x + w - 76, y + 7, 66, 25), "선택 불가" if blocked else "채택",
                      enabled=not blocked, size=11, tooltip="적서차별: 군주정을 선택할 수 없습니다." if blocked else
                      "\n".join(f"{i}. {p['name']}: {p['description']}" for i, p in enumerate(POLICIES[key], 1))
                      + "\n★ " + POLICY_COMPLETION[key]["description"]):
            _result(app, g.set_player_government(key))
        y += box.h + 10
    return y


def draw_technologies(app, x, y, w, military=False):
    from ..progression import TECHS
    from .panels import section
    gui, g, t, f = app.gui, app.game, app.theme, app.game.player
    for kind, title in (("unit", "군사 유닛 현대화"), ("building", "생산 건물 확장"), ("victory", "과학승리")):
        if (kind == "unit") != military:
            continue
        y = section(gui, x, y, w, title)
        for key, tech in TECHS.items():
            if tech["kind"] != kind:
                continue
            done = key in f.techs
            cost = g.tech_cost(f.id, key)
            gui.text((x, y), tech["name"], 13, t.good if done else t.text, "semibold", max_w=w - 78)
            gui.text((x, y + 21), "연구 완료" if done else f"과학력 {cost:,.0f}", 11, t.good if done else t.muted)
            if gui.button((x + w - 70, y, 70, 29), "완료" if done else "해금", "default" if done else "primary",
                          enabled=not done and f.sci_points >= cost, size=12,
                          tooltip="보유 유닛에도 즉시 적용됩니다." if done and kind == "unit" else
                          f"과학력 {cost:,.0f} 소비"):
                _result(app, g.unlock_tech(f.id, key))
            y = gui.wrap((x, y + 40), tech["description"], w, 11, t.muted) + 14
    return y


def draw_great_people(app, x, y, w):
    from ..progression import GREAT_PEOPLE
    from .panels import section
    gui, g, t, f = app.gui, app.game, app.theme, app.game.player
    rid = app.sel if app.sel in g.regions and g.regions[app.sel].owner == f.id else f.capital
    y = gui.wrap((x, y), f"초빙 지역: {g.world.node_name(rid)} · 지도에서 내 지역을 선택하면 바뀝니다.",
                 w, 12, t.muted) + 12
    y = section(gui, x, y, w, "위인 초빙")
    for kind, spec in GREAT_PEOPLE.items():
        cost = g.great_person_cost(f.id, kind)
        can, why = g.can_recruit_great_person(f.id, kind, rid)
        currency = "과학력" if spec["currency"] == "sci_points" else "행정력"
        great_person_badge(gui.screen, kind, gui.P(x + 10, y + 11), app.faction_rgb(f.id), gui.u)
        gui.text((x + 27, y), spec["name"], 13, weight="semibold", max_w=w - 100)
        gui.text((x + 27, y + 22), f"{currency} {cost:,.0f}", 11, t.muted)
        if gui.button((x + w - 70, y, 70, 29), "초빙", "primary", enabled=can, size=12, tooltip=why):
            _result(app, g.recruit_great_person(f.id, kind, rid))
        y = gui.wrap((x, y + 43), spec["description"], w, 11, t.muted) + 5
        if not can:
            y = gui.wrap((x, y), why, w, 11, t.warn) + 4
        y += 12
    y = section(gui, x, y, w, "활동 중인 위인")
    own = [gp for gp in g.great_people if gp["owner"] == f.id]
    if not own:
        y = gui.wrap((x, y), "초빙한 위인이 없습니다.", w, 12, t.muted) + 10
    for gp in own:
        y = draw_person(app, x, y, w, gp, show_location=True)
    return y


def draw_person(app, x, y, w, gp, show_location=False):
    from ..progression import GREAT_PEOPLE
    gui, g, t = app.gui, app.game, app.theme
    spec = GREAT_PEOPLE[gp["kind"]]
    great_person_badge(gui.screen, gp["kind"], gui.P(x + 10, y + 11), app.faction_rgb(gp["owner"]), gui.u)
    gui.text((x + 27, y), f"{spec['name']} {gp['name']}", 13, weight="semibold", max_w=w - 28)
    y += 24
    if show_location:
        if gui.button((x, y, w, 25), g.world.node_name(gp["loc"]), "ghost", size=11,
                      tooltip="위인이 있는 지역으로 지도를 옮깁니다."):
            app.sel = gp["loc"]
            app.map.center_on(gp["loc"])
        y += 29
    y = gui.wrap((x, y), spec["description"], w, 11, t.muted) + 6
    if gp["owner"] != g.player_id:
        return y + 10
    moving = getattr(app, "gp_move_pick", None) == gp["id"]
    if gui.button((x, y, w, 27), "이동 취소 (Esc)" if moving else "이동할 내 지역 선택", size=12):
        app.gp_move_pick = None if moving else gp["id"]
    y += 32
    if moving:
        y = gui.wrap((x, y), "지도에서 이동할 내 지역을 누르세요. 우클릭 또는 Esc로 취소합니다.", w, 11, t.accent) + 6
    if gp["kind"] in ("scientist", "chancellor"):
        if gui.button((x, y, w, 27), "위인 소모 · 현재 지역 공사 단축", "primary", size=12):
            _result(app, g.activate_great_person(gp["id"], "project"))
        y += 32
    if gp["kind"] == "scientist":
        if gui.button((x, y, w, 27), "위인 소모 · 국가 과학력 8턴분 획득", size=12):
            _result(app, g.activate_great_person(gp["id"], "science"))
        y += 32
    elif gp["kind"] == "artist":
        if gui.button((x, y, w, 27), "공연 · 지역 +25 / 전국 +8 / 피로 −10", "primary", size=11):
            _result(app, g.activate_great_person(gp["id"]))
        y += 32
    return y + 10


def draw_region_people(app, x, y, w, rid, controls=True):
    from .panels import section
    people = app.game.great_people_at(rid)
    if not people:
        return y
    y = section(app.gui, x, y + 5, w, "지역의 위인")
    for gp in list(people):
        if controls:
            y = draw_person(app, x, y, w, gp)
        else:
            from ..progression import GREAT_PEOPLE
            y = app.gui.wrap((x, y), f"{GREAT_PEOPLE[gp['kind']]['name']} {gp['name']}", w, 12) + 5
    return y


def draw_map_people(app, display_locations):
    """군기가 없는 지역에도 위인을 표시하며, 시야 밖 정보는 숨긴다."""
    from ..progression import GREAT_PEOPLE
    g, gui, mv = app.game, app.gui, app.map
    groups = {}
    for gp in g.great_people:
        if gp["owner"] == g.player_id or g.is_visible(g.player_id, gp["loc"]) or app.fog_reveal:
            groups.setdefault(display_locations.get(gp["loc"], gp["loc"]), []).append(gp)
    app._great_person_hits = []
    for loc, people in groups.items():
        x, y = mv.label_screen(loc)
        if not mv.view.collidepoint(x, y):
            continue
        width = min(8, len(people))
        for index, gp in enumerate(people):
            center = (x + (index % 8 - (width - 1) / 2) * 21 * gui.u,
                      y - (14 + (index // 8) * 21) * gui.u)
            rect = great_person_badge(gui.screen, gp["kind"], center, app.faction_rgb(gp["owner"]), gui.u,
                                      getattr(app, "gp_move_pick", None) == gp["id"])
            app._great_person_hits.append((rect, gp["id"]))
            if gui.input_enabled and rect.collidepoint(gui.mouse_phys):
                gui.tooltip = f"{GREAT_PEOPLE[gp['kind']]['name']} {gp['name']}\n{g.world.node_name(gp['loc'])}"
