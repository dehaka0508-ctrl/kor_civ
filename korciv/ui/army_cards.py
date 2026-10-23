"""지역 부대 카드(v1.3.12): 지역을 누르면 그 지역의 부대가 왼쪽 아래에 카드 패처럼 펼쳐진다.

- 쉴 때는 카드 윗부분(머리띠·대표 병종·유닛 수)만 화면 아래에서 비죽 나와 있고, 부채꼴로 살짝 기울어 있다.
- 커서를 올리면 그 카드가 패에서 뽑듯 위로 올라오며 똑바로 서고, 커서를 떼면 제자리로 돌아간다.
- 내 부대 카드를 누르면 그 부대를 고르고 [부대] 탭을 연다(고른 카드는 조금 올라와 있다).
- 다른 지역을 누르면 지난 카드는 아래로 내려가고 새 카드가 차례로 올라온다.
"""
from __future__ import annotations

import math

import pygame

from .. import config as C
from ..flags import faction_flag
from ..state import NEUTRAL
from .art import indigo_band, render_flag
from .theme import mix, paper_texture, render_text, ui_scale

CARD_W, CARD_H = 116, 164         # 카드 크기(논리 좌표)
PEEK = 76                          # 쉴 때 화면 아래에서 보이는 높이
LIFT = CARD_H + 14 - PEEK          # 커서를 올리면 이만큼 올라와 카드 전체가 보인다
HAND_X = 14                        # 패 왼쪽 끝
HAND_W = 430                       # 패가 차지하는 최대 폭
MAX_CARDS = 24
PAD = 8                            # 카드 그림 둘레 여백(빛·그림자)
SEL_LIFT = 0.05                    # 고른 카드가 올라와 있는 정도
SPEED_LIFT, SPEED_X, SPEED_IN, SPEED_OUT = 16.0, 12.0, 11.0, 14.0
DEAL_GAP_MS = 45                   # 새 카드가 차례로 올라오는 간격
DOMAIN_NAMES = {"land": "육군", "naval": "해군", "air": "공군"}


def _ease(v, target, speed, dt):
    """지수 감쇠로 target 에 다가간다(프레임 속도와 상관없이 같은 빠르기)."""
    return target + (v - target) * math.exp(-speed * dt)


class _Card:
    __slots__ = ("aid", "x", "lift", "appear", "born", "leaving", "surf", "key", "rest", "rot")

    def __init__(self, aid, x, born):
        self.aid = aid
        self.x = x
        self.lift = 0.0
        self.appear = 0.0
        self.born = born
        self.leaving = False
        self.surf = None
        self.key = None
        self.rest = (x, 0.0, 0.0)      # 쉴 때 (가운데 x, 기울기°, 아래로 처지는 정도)
        self.rot = None                # (각도, 배율, 카드 키, Surface): 같은 모양이면 다시 돌리지 않는다


class ArmyHand:
    """왼쪽 아래 부대 카드 패(상태·애니메이션). app.hand 로 하나만 쓴다."""

    def __init__(self):
        self.node = None
        self.cards: list[_Card] = []
        self.hover = None
        self.t_last = None
        self.surf_cache: dict = {}
        self.rects: list = []          # 이번 프레임 (논리 사각형, 부대 id) — 시험·입력용

    def covers(self, pos) -> bool:
        """지난 프레임에 그린 카드가 pos(논리 좌표)를 덮고 있는가."""
        return any(r.collidepoint(pos) for r, _ in self.rects)

    # ------------------------------------------------------------ 보여 줄 부대
    @staticmethod
    def visible_armies(app):
        g = app.game
        node = app.sel
        if g is None or node is None:
            return []
        pid = g.player_id
        mine_here = any(a.owner == pid for a in g.armies_at(node))
        if not (mine_here or app.fog_reveal or g.is_visible(pid, node)):
            return []
        arms = [a for a in g.armies_at(node) if not a.empty() and (a.owner == pid or g.is_visible(pid, node)
                                                                   or app.fog_reveal)]
        arms.sort(key=lambda a: (a.owner != pid, a.owner, g.army_sort_key(a)))
        return arms[:MAX_CARDS]

    # ------------------------------------------------------------ 카드 그림
    def card_surface(self, app, a, selected):
        g = app.game
        t = app.theme
        u = ui_scale()
        pid = g.player_id
        acted = a.owner == pid and g.army_acted(a.id)
        fought = acted and g.army_fought(a.id)
        name = "중립" if a.owner == NEUTRAL else g.seen_name(a.owner)
        key = (a.id, a.owner, tuple(sorted((k, n) for k, n in a.units.items() if n)),
               tuple(sorted((k, round(v, 1)) for k, v in a.dmg.items())), acted, fought, bool(a.order), a.goto,
               selected, t.dark, round(u, 3), name)
        s = self.surf_cache.get(key)
        if s is None:
            if len(self.surf_cache) > 200:
                self.surf_cache.clear()
            s = self.surf_cache[key] = _render_card(app, a, selected, acted, fought, name)
        return s, key

    # ------------------------------------------------------------ 그리기·입력
    def draw(self, app):
        gui = app.gui
        now = pygame.time.get_ticks()
        dt = 0.0 if self.t_last is None else max(0.0, min(0.05, (now - self.t_last) / 1000))
        self.t_last = now
        g = app.game
        pid = g.player_id
        sw, sh = app.lsize()
        u = ui_scale()
        arms = self.visible_armies(app)
        ids = [a.id for a in arms]
        by_id = {a.id: a for a in arms}
        # 다른 지역을 골랐으면 지난 카드는 모두 내려 보낸다
        if app.sel != self.node:
            for c in self.cards:
                c.leaving = True
            self.node = app.sel
            self.hover = None
        live = {c.aid: c for c in self.cards if not c.leaving}
        for c in live.values():
            if c.aid not in by_id:
                c.leaving = True            # 합치기·이동 등으로 이 지역에서 사라진 부대
        n = len(arms)
        sp = min(CARD_W * 0.86, (HAND_W - CARD_W) / max(1, n - 1)) if n > 1 else 0
        step = min(3.2, 10.0 / max(1, n - 1)) if n > 1 else 0.0
        mid = (n - 1) / 2
        k = 0
        for i, aid in enumerate(ids):
            d = i - mid
            rest = (HAND_X + CARD_W / 2 + i * sp, -d * step, min(14.0, abs(d) ** 1.6 * 2.0))
            c = live.get(aid)
            if c is None:
                c = _Card(aid, rest[0], now + k * DEAL_GAP_MS)
                k += 1
                self.cards.append(c)
            c.rest = rest
        order = {aid: i for i, aid in enumerate(ids)}
        self.cards = [c for c in self.cards if not (c.leaving and c.appear < 0.02)]
        # 커서가 올라간 카드: 올라와 있는 카드는 제자리 칸까지 포함해 머무르게(떨림 방지)
        hover = None
        stand = [c for c in self.cards if not c.leaving]
        stand.sort(key=lambda c: (c.lift > 0.3, order.get(c.aid, 0)), reverse=True)
        cur = next((c for c in stand if c.aid == self.hover), None)
        if cur is not None and (gui.hover(self._rect(cur, sh)) or gui.hover(self._rest_rect(cur, sh))):
            hover = cur.aid
        else:
            for c in stand:
                if gui.hover(self._rect(c, sh)):
                    hover = c.aid
                    break
        self.hover = hover
        # 애니메이션
        for c in self.cards:
            if c.leaving:
                c.appear = _ease(c.appear, 0.0, SPEED_OUT, dt)
                c.lift = _ease(c.lift, 0.0, SPEED_LIFT, dt)
                continue
            if now >= c.born:
                c.appear = _ease(c.appear, 1.0, SPEED_IN, dt)
            target = 1.0 if c.aid == hover else (SEL_LIFT if c.aid == app.sel_army else 0.0)
            c.lift = _ease(c.lift, target, SPEED_LIFT, dt)
            c.x = _ease(c.x, c.rest[0], SPEED_X, dt)
            if dt == 0.0:                 # 첫 프레임(시험 등): 바로 제자리
                c.x = c.rest[0]
        # 그리기(아래 카드부터, 올라온 카드는 맨 위)
        self.rects = []
        draw = sorted(self.cards, key=lambda c: (not c.leaving, c.lift > 0.3, order.get(c.aid, -1)))
        for c in draw:
            a = by_id.get(c.aid)
            if a is not None and not c.leaving:
                c.surf, c.key = self.card_surface(app, a, a.id == app.sel_army)
            if c.surf is None:
                continue
            self._blit(app, c, sh, u)
            if not c.leaving:
                r = self._rect(c, sh)
                self.rects.append((r, c.aid))
                gui.block(r)
                if c.aid == hover:
                    gui.block(self._rest_rect(c, sh))
        # 누르기
        if hover is not None and gui.clicked:
            a = by_id.get(hover)
            gui.clicked = False
            if a is not None and a.owner == pid:
                app.sel_army = a.id
                app.split = {}
                app.left_open, app.left_tab, app.tab = True, "region", "army"
            elif a is not None:
                app.toast(f"{'중립' if a.owner == NEUTRAL else g.seen_name(a.owner)} 부대 · {a.label()}")

    # ------------------------------------------------------------ 자리 계산
    @staticmethod
    def _top(c, sh):
        return sh - PEEK + c.rest[2] * (1 - c.lift) - LIFT * c.lift + (1 - c.appear) * (PEEK + 30)

    def _rect(self, c, sh):
        return pygame.Rect(int(c.x - CARD_W / 2), int(self._top(c, sh)), CARD_W, CARD_H)

    @staticmethod
    def _rest_rect(c, sh):
        return pygame.Rect(int(c.rest[0] - CARD_W / 2), int(sh - PEEK + c.rest[2]), CARD_W, PEEK)

    def _blit(self, app, c, sh, u):
        hover_k = max(0.0, (c.lift - SEL_LIFT) / (1 - SEL_LIFT))
        ang = c.rest[1] * (1 - min(1.0, c.lift * 1.6))
        sc = 1.0 + 0.05 * hover_k
        cx = c.x * u
        cy = (self._top(c, sh) + CARD_H / 2) * u
        # 그림자(올라올수록 넓고 옅게)
        sh_s = _shadow_surface(u)
        off = int((3 + 9 * hover_k) * u)
        sh_s.set_alpha(int(150 - 60 * hover_k))
        app.screen.blit(sh_s, sh_s.get_rect(center=(int(cx + off * 0.4), int(cy + off))))
        if abs(ang) < 0.05 and abs(sc - 1) < 1e-3:
            img = c.surf
        elif c.rot and c.rot[:3] == (round(ang, 1), round(sc, 3), c.key):
            img = c.rot[3]
        else:
            img = pygame.transform.rotozoom(c.surf, round(ang, 1), round(sc, 3))
            c.rot = (round(ang, 1), round(sc, 3), c.key, img)
        app.screen.blit(img, img.get_rect(center=(int(cx), int(cy))))


_shadow_cache: dict = {}


def _shadow_surface(u):
    key = round(u, 3)
    s = _shadow_cache.get(key)
    if s is None:
        w, h = int((CARD_W + 2 * PAD) * u), int((CARD_H + 2 * PAD) * u)
        small = pygame.Surface((max(4, w // 6), max(4, h // 6)), pygame.SRCALPHA)
        sw_, sh_ = small.get_size()
        pygame.draw.rect(small, (20, 14, 8, 120), (2, 2, sw_ - 4, sh_ - 4), border_radius=3)
        s = pygame.transform.smoothscale(pygame.transform.smoothscale(small, (sw_ // 2 + 1, sh_ // 2 + 1)), (w, h))
        _shadow_cache.clear()
        _shadow_cache[key] = s
    return s


def _icon_big(key, color, px):
    """병종 아이콘을 크게(4배로 그려 줄여 매끈하게)."""
    from .panels import unit_icon
    ss = 4
    big = pygame.Surface((px * ss, px * ss), pygame.SRCALPHA)
    unit_icon(big, key, (px * ss // 2, px * ss // 2 + int(px * ss * 0.04)), color, px * ss / 15)
    return pygame.transform.smoothscale(big, (px, px))


def _text(surf, s, size, color, weight, pos, anchor="topleft", max_w=None):
    img = render_text(s, size, color, weight)
    if max_w and img.get_width() > max_w:
        while len(s) > 1 and render_text(s + "…", size, color, weight).get_width() > max_w:
            s = s[:-1]
        img = render_text(s + "…", size, color, weight)
    r = img.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
    surf.blit(img, r)
    return r


def _render_card(app, a, selected, acted, fought, owner_name):
    """카드 한 장(실제 픽셀, 둘레 PAD 여백 포함): 한지 바탕 · 쪽빛 머리띠(국기·병과·상태) · 대표 병종 메달 ·
    유닛 수 · 병종 구성 · 체력 막대 · 전력."""
    g = app.game
    t = app.theme
    u = ui_scale()

    def P(v):
        return int(round(v * u))
    W, H, pad = P(CARD_W), P(CARD_H), P(PAD)
    surf = pygame.Surface((W + 2 * pad, H + 2 * pad), pygame.SRCALPHA)
    card = pygame.Rect(pad, pad, W, H)
    rad = P(7)
    pid = g.player_id
    mine = a.owner == pid
    fcol = (128, 128, 124) if a.owner == NEUTRAL else app.faction_rgb(a.owner)
    if acted:
        fcol = mix(fcol, (150, 150, 150), 0.55)
    ink, paper = t.text, (247, 241, 227)
    # 고른 카드: 금빛 번짐
    if selected:
        glow = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        for i, al in ((4, 40), (3, 60), (2, 90)):
            pygame.draw.rect(glow, (*t.gold_lt, al), card.inflate(P(i * 2), P(i * 2)), border_radius=rad + P(i))
        surf.blit(glow, (0, 0))
    # 바탕: 한지
    body = pygame.Surface(card.size, pygame.SRCALPHA)
    pygame.draw.rect(body, (*t.panel, 255), body.get_rect(), border_radius=rad)
    if not t.dark:
        tex = paper_texture()
        layer = pygame.Surface(card.size)
        for yy in range(0, card.h, tex.get_height()):
            for xx in range(0, card.w, tex.get_width()):
                layer.blit(tex, (xx, yy))
        body.blit(layer, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    # 머리띠(쪽빛 + 왼쪽 세력 색 띠)
    hh = P(30)
    band = indigo_band(card.w, hh, t.indigo, t.indigo_dk, lattice=False)
    body.blit(band, (0, 0))
    pygame.draw.rect(body, fcol, (0, 0, P(5), hh))
    pygame.draw.line(body, t.gold, (0, hh), (card.w, hh), max(1, P(1.5)))
    mask = pygame.Surface(card.size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=rad)
    body.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surf.blit(body, card.topleft)
    x0, y0 = card.x, card.y
    # 머리띠 내용: 국기 · 병과(타국은 나라 이름) · 상태 도장
    if a.owner != NEUTRAL:
        fl = render_flag(faction_flag(g.factions[a.owner]), P(21), P(14))
        surf.blit(fl, (x0 + P(10), y0 + P(8)))
        pygame.draw.rect(surf, mix(t.gold, t.indigo, 0.3), (x0 + P(10), y0 + P(8), P(21), P(14)), 1)
    title = DOMAIN_NAMES[a.domain()] if mine else owner_name
    badge = None
    if mine and acted:
        badge = ("전투" if fought else "완료", t.vermilion)
    elif mine and (a.order or a.goto):
        badge = ("이동", t.jade)
    tw_max = card.w - P(38) - (P(30) if badge else P(8))
    _text(surf, title, 12, paper, "title", (x0 + P(36), y0 + hh / 2 + P(1)), "midleft", tw_max)
    if badge:
        br = pygame.Rect(0, 0, P(28), P(16))
        br.midright = (card.right - P(6), y0 + hh // 2)
        pygame.draw.rect(surf, badge[1], br, border_radius=P(3))
        pygame.draw.rect(surf, mix(badge[1], (255, 255, 255), 0.45), br, 1, border_radius=P(3))
        _text(surf, badge[0], 9, (255, 255, 255), "bold", br.center, "center")
    # 대표 병종 메달 + 유닛 수
    main = g.army_icon_unit(a)
    mc = (x0 + P(26), y0 + hh + P(22))
    mr = P(17)
    pygame.draw.circle(surf, mix(fcol, (30, 25, 20), 0.15), mc, mr)
    pygame.draw.circle(surf, t.gold, mc, mr, max(1, P(1.6)))
    pygame.draw.circle(surf, mix(t.gold, fcol, 0.5), mc, mr - P(4), 1)
    ic = _icon_big(main, (255, 255, 255), P(28))
    surf.blit(ic, ic.get_rect(center=mc))
    kinds = [k for k in C.UNIT_ORDER if a.units.get(k, 0) > 0]
    cr = _text(surf, f"{a.count()}", 18, ink, "bold", (x0 + P(50), mc[1] - P(7)), "midleft")
    _text(surf, "유닛", 9, t.muted, "semibold", (cr.right + P(3), cr.bottom - P(4)), "bottomleft")
    sub = a.spec(main)["name"] + (f" 외 {len(kinds) - 1}" if len(kinds) > 1 else "")
    _text(surf, sub, 10, t.muted, "semibold", (x0 + P(51), mc[1] + P(10)), "midleft", card.right - P(6) - (x0 + P(51)))
    # 구분선
    dy = y0 + P(PEEK + 2)
    pygame.draw.line(surf, mix(t.gold, t.panel, 0.25), (x0 + P(10), dy), (card.right - P(10), dy), 1)
    # 병종 구성(최대 4줄)
    from .panels import unit_icon
    yy = dy + P(6)
    for kk in kinds[:4]:
        unit_icon(surf, kk, (x0 + P(17), yy + P(7)), mix(ink, t.panel, 0.15), 0.8 * u)
        _text(surf, a.spec(kk)["name"], 11, ink, "semibold", (x0 + P(28), yy + P(7)), "midleft", P(56))
        _text(surf, f"×{a.units[kk]}", 11, ink, "bold", (card.right - P(11), yy + P(7)), "midright")
        yy += P(14)
    if len(kinds) > 4:
        _text(surf, f"그 외 {len(kinds) - 4}종", 10, t.muted, "semibold", (x0 + P(28), yy + P(6)), "midleft")
    # 체력 막대
    hp = sum(a.hp_left(k) for k in kinds)
    hp_max = sum(a.hp_max(k) for k in kinds) or 1
    frac = max(0.0, min(1.0, hp / hp_max))
    by = card.bottom - P(36)
    _text(surf, "체력", 9, t.muted, "semibold", (x0 + P(11), by + P(3)), "midleft")
    bar = pygame.Rect(x0 + P(34), by, card.right - P(11) - (x0 + P(34)), P(6))
    pygame.draw.rect(surf, mix(t.border, t.panel, 0.4), bar, border_radius=P(3))
    hcol = t.good if frac >= 0.6 else (t.warn if frac >= 0.3 else t.bad)
    pygame.draw.rect(surf, hcol, (bar.x, bar.y, max(P(3), int(bar.w * frac)), bar.h), border_radius=P(3))
    # 아래: 전력 · 부대 번호
    fy = card.bottom - P(17)
    if mine or app.fog_reveal:
        _text(surf, f"전력 {g.army_power(a):,.0f}", 10, t.muted, "semibold", (x0 + P(11), fy), "midleft")
    if mine:
        _text(surf, f"#{a.id}", 10, mix(t.gold, ink, 0.35), "bold", (card.right - P(11), fy), "midright")
    # 테두리: 금테 + 안쪽 실선 + 모서리 꺾쇠
    edge = t.vermilion if selected else mix(t.gold, ink, 0.15)
    pygame.draw.rect(surf, edge, card, max(1, P(2.2 if selected else 1.4)), border_radius=rad)
    inner = card.inflate(-P(7), -P(7))
    inner.y = y0 + hh + P(4)
    inner.h = card.bottom - P(4) - inner.y
    pygame.draw.rect(surf, mix(t.gold, t.panel, 0.45), inner, 1, border_radius=max(0, rad - P(3)))
    sz, w2 = P(7), max(1, P(1.3))
    oc = mix(t.gold, ink, 0.25)
    for cx, cy, sx, sy in ((inner.x, inner.bottom - 1, 1, -1), (inner.right - 1, inner.bottom - 1, -1, -1)):
        pygame.draw.lines(surf, oc, False, [(cx + sx * sz, cy), (cx, cy), (cx, cy + sy * sz)], w2)
    return surf
