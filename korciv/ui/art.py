"""국기·지도자 초상화 그리기."""
from __future__ import annotations

import math
import os

import pygame

from ..flags import normalize

SS = 3                                   # 국기 슈퍼샘플링 배율(가장자리 매끄럽게)
_flag_cache: dict = {}
_portrait_src: dict = {}
_portrait_cache: dict = {}
PORTRAIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "portraits")
PORTRAIT_EXTS = (".png", ".jpg", ".jpeg", ".webp")


# ------------------------------------------------------------------ 국기
def _mix(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def _star(cx, cy, r, n=5, inner=0.382, rot=-math.pi / 2):
    pts = []
    for i in range(2 * n):
        rr = r if i % 2 == 0 else r * inner
        a = rot + i * math.pi / n
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def _ngon(cx, cy, r, n, rot=-math.pi / 2):
    return [(cx + r * math.cos(rot + 2 * math.pi * i / n), cy + r * math.sin(rot + 2 * math.pi * i / n))
            for i in range(n)]


def _contrast(fl):
    """문양 보조 색: 배경 색2가 배경 색1과 같으면 문양 색을 어둡게/밝게 바꾼 색."""
    c1, c2, ec = fl["c1"], fl["c2"], fl["ec"]
    if c2 != c1 and c2 != ec:
        return c2
    return _mix(ec, (0, 0, 0) if sum(ec) > 380 else (255, 255, 255), 0.6)


def draw_emblem(s, key, cx, cy, R, fl):
    """투명 레이어 s 에 문양을 그린다(오려내기는 알파 0으로 칠해서)."""
    ec = fl["ec"]
    hole = (0, 0, 0, 0)
    W = max(1, int(R * 0.2))
    if key == "disc":
        pygame.draw.circle(s, ec, (cx, cy), int(R * 0.8))
    elif key == "ring":
        pygame.draw.circle(s, ec, (cx, cy), int(R * 0.8), max(1, int(R * 0.22)))
    elif key == "star5":
        pygame.draw.polygon(s, ec, _star(cx, cy, R))
    elif key == "star6":
        pygame.draw.polygon(s, ec, _ngon(cx, cy, R, 3))
        pygame.draw.polygon(s, ec, _ngon(cx, cy, R, 3, rot=math.pi / 2))
    elif key == "crescent":
        pygame.draw.circle(s, ec, (cx, cy), int(R * 0.85))
        pygame.draw.circle(s, hole, (int(cx + R * 0.32), int(cy - R * 0.05)), int(R * 0.72))
    elif key == "crescent_star":
        x0 = cx - R * 0.2
        pygame.draw.circle(s, ec, (int(x0), cy), int(R * 0.8))
        pygame.draw.circle(s, hole, (int(x0 + R * 0.3), cy), int(R * 0.66))
        pygame.draw.polygon(s, ec, _star(cx + R * 0.55, cy, R * 0.32))
    elif key == "taegeuk":
        b = _contrast(fl)
        r = int(R * 0.85)
        pygame.draw.circle(s, b, (cx, cy), r)
        pygame.draw.circle(s, ec, (cx, cy), r, draw_top_left=True, draw_top_right=True)
        pygame.draw.circle(s, ec, (cx - r // 2, cy), r // 2)
        pygame.draw.circle(s, b, (cx + r // 2, cy), r // 2)
    elif key == "samtaegeuk":
        b = _contrast(fl)
        cols = (ec, b, _mix(ec, b, 0.5))
        r = R * 0.85
        for i, col in enumerate(cols):
            a0 = -math.pi / 2 + i * 2 * math.pi / 3
            pts = [(cx, cy)] + [(cx + r * math.cos(a0 + k * (2 * math.pi / 3) / 16),
                                 cy + r * math.sin(a0 + k * (2 * math.pi / 3) / 16)) for k in range(17)]
            pygame.draw.polygon(s, col, pts)
        for i, col in enumerate(cols):
            a = -math.pi / 2 + i * 2 * math.pi / 3
            pygame.draw.circle(s, col, (int(cx + r * 0.5 * math.cos(a)), int(cy + r * 0.5 * math.sin(a))), int(r * 0.5))
    elif key == "cross":
        t = R * 0.36
        pygame.draw.rect(s, ec, (cx - t / 2, cy - R * 0.9, t, R * 1.8))
        pygame.draw.rect(s, ec, (cx - R * 0.9, cy - t / 2, R * 1.8, t))
    elif key == "saltire":
        t = R * 0.26
        for sgn in (1, -1):
            d = R * 0.75
            ux, uy = d, sgn * d
            n = (t / math.hypot(ux, uy))
            px, py = -uy * n, ux * n
            pygame.draw.polygon(s, ec, [(cx - ux + px, cy - uy + py), (cx + ux + px, cy + uy + py),
                                        (cx + ux - px, cy + uy - py), (cx - ux - px, cy - uy - py)])
    elif key == "diamond":
        pygame.draw.polygon(s, ec, [(cx, cy - R), (cx + R * 0.65, cy), (cx, cy + R), (cx - R * 0.65, cy)])
    elif key == "triangle":
        pygame.draw.polygon(s, ec, _ngon(cx, cy + R * 0.15, R, 3))
    elif key == "hexagon":
        pygame.draw.polygon(s, ec, _ngon(cx, cy, R * 0.9, 6, rot=0))
    elif key == "shield":
        w = R * 0.75
        pts = [(cx - w, cy - R * 0.85), (cx + w, cy - R * 0.85)]
        for k in range(13):
            a = k / 12 * math.pi
            pts.append((cx + w * math.cos(a), cy - R * 0.1 + R * 0.95 * math.sin(a)))
        pygame.draw.polygon(s, ec, pts)
    elif key == "crown":
        w, h = R * 0.95, R * 0.75
        pts = [(cx - w, cy + h * 0.6), (cx - w, cy - h), (cx - w / 2, cy - h * 0.1), (cx, cy - h * 1.1),
               (cx + w / 2, cy - h * 0.1), (cx + w, cy - h), (cx + w, cy + h * 0.6)]
        pygame.draw.polygon(s, ec, pts)
        pygame.draw.rect(s, ec, (cx - w, cy + h * 0.7, 2 * w, h * 0.35))
    elif key == "mountain":
        w = R
        pygame.draw.polygon(s, ec, [(cx - w, cy + R * 0.6), (cx - w * 0.35, cy - R * 0.75), (cx + w * 0.05, cy - R * 0.1),
                                    (cx + w * 0.45, cy - R * 0.5), (cx + w, cy + R * 0.6)])
    elif key == "wave":
        for j in (-1, 0, 1):
            pts = [(cx - R + k * 2 * R / 24, cy + j * R * 0.55 + R * 0.18 * math.sin(k / 24 * 4 * math.pi))
                   for k in range(25)]
            pygame.draw.lines(s, ec, False, pts, W)
    elif key == "bolt":
        pygame.draw.polygon(s, ec, [(cx + R * 0.15, cy - R), (cx - R * 0.55, cy + R * 0.12), (cx - R * 0.02, cy + R * 0.12),
                                    (cx - R * 0.2, cy + R), (cx + R * 0.55, cy - R * 0.15), (cx + R * 0.02, cy - R * 0.15)])
    elif key == "flower":
        for i in range(5):
            a = -math.pi / 2 + i * 2 * math.pi / 5
            pygame.draw.circle(s, ec, (int(cx + R * 0.5 * math.cos(a)), int(cy + R * 0.5 * math.sin(a))), int(R * 0.42))
        pygame.draw.circle(s, _contrast(fl), (cx, cy), int(R * 0.25))
    elif key == "arrow":
        t = R * 0.32
        pygame.draw.polygon(s, ec, [(cx, cy - R), (cx + R * 0.75, cy - R * 0.1), (cx + t / 2, cy - R * 0.1),
                                    (cx + t / 2, cy + R), (cx - t / 2, cy + R), (cx - t / 2, cy - R * 0.1),
                                    (cx - R * 0.75, cy - R * 0.1)])


def render_flag(flag, w, h) -> pygame.Surface:
    """국기를 w×h 픽셀 Surface 로."""
    fl = normalize(flag)
    key = (fl["bg"], fl["c1"], fl["c2"], fl["em"], fl["ec"], w, h)
    surf = _flag_cache.get(key)
    if surf is not None:
        return surf
    W, H = w * SS, h * SS
    s = pygame.Surface((W, H))
    c1, c2 = fl["c1"], fl["c2"]
    bg = fl["bg"]
    s.fill(c1)
    ecx, ecy, R = W / 2, H / 2, H * 0.3          # 문양 위치·크기
    if bg == "h2":
        s.fill(c2, (0, H // 2, W, H - H // 2))
    elif bg == "v2":
        s.fill(c2, (W // 2, 0, W - W // 2, H))
    elif bg == "h3":
        s.fill(c2, (0, H // 3, W, H - 2 * (H // 3)))
    elif bg == "v3":
        s.fill(c2, (W // 3, 0, W - 2 * (W // 3), H))
    elif bg == "diag":
        pygame.draw.polygon(s, c2, [(W, 0), (W, H), (0, H)])
    elif bg == "nordic":
        t = H * 0.2
        s.fill(c2, (W * 0.36 - t / 2, 0, t, H))
        s.fill(c2, (0, H / 2 - t / 2, W, t))
        ecx, ecy, R = W * 0.36, H / 2, H * 0.14
    elif bg == "border":
        s.fill(c2)
        m = int(H * 0.1)
        s.fill(c1, (m, m, W - 2 * m, H - 2 * m))
        R = H * 0.26
    elif bg == "canton":
        s.fill(c2, (0, 0, W * 0.42, H * 0.5))
        ecx, ecy, R = W * 0.21, H * 0.25, H * 0.17
    elif bg == "chevron":
        pygame.draw.polygon(s, c2, [(0, 0), (W * 0.42, H / 2), (0, H)])
        ecx, ecy, R = W * 0.14, H / 2, H * 0.15
    if fl["em"] != "none":
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        draw_emblem(layer, fl["em"], int(ecx), int(ecy), R, fl)
        s.blit(layer, (0, 0))
    out = pygame.transform.smoothscale(s, (w, h))
    pygame.draw.rect(out, (0, 0, 0), out.get_rect(), 1)
    if len(_flag_cache) > 400:
        _flag_cache.clear()
    _flag_cache[key] = out
    return out


def draw_flag(gui, rect, flag):
    """논리 좌표 rect 에 국기를 그린다(3:2 비율 권장)."""
    pr = gui.R(rect)
    gui.screen.blit(render_flag(flag, pr.w, pr.h), pr.topleft)


# ------------------------------------------------------------------ 초상화
def portrait_path(leader_key):
    for ext in PORTRAIT_EXTS:
        p = os.path.join(PORTRAIT_DIR, leader_key + ext)
        if os.path.exists(p):
            return p
    return None


def _portrait_source(leader_key):
    if leader_key not in _portrait_src:
        p = portrait_path(leader_key)
        img = None
        if p:
            try:
                img = pygame.image.load(p)
            except Exception:
                img = None
        _portrait_src[leader_key] = img
    return _portrait_src[leader_key]


def draw_portrait(gui, rect, leader_key, theme):
    """논리 좌표 rect(세로 3:4)에 초상화. 파일이 없으면 빈 틀(실루엣)을 그린다."""
    pr = gui.R(rect)
    img = _portrait_source(leader_key)
    if img is not None:
        key = (leader_key, pr.w, pr.h)
        surf = _portrait_cache.get(key)
        if surf is None:
            iw, ih = img.get_size()
            k = max(pr.w / iw, pr.h / ih)            # 꽉 채우고 가운데를 잘라 낸다
            sw, sh = max(1, round(iw * k)), max(1, round(ih * k))
            big = pygame.transform.smoothscale(img.convert_alpha() if pygame.display.get_surface() else img, (sw, sh))
            surf = big.subsurface(((sw - pr.w) // 2, (sh - pr.h) // 2, pr.w, pr.h)).copy()
            _portrait_cache[key] = surf
        gui.screen.blit(surf, pr.topleft)
        pygame.draw.rect(gui.screen, theme.border, pr, 1)
        return True
    r = pygame.Rect(rect)
    gui.rect(theme.panel_alt, r, radius=6)
    col = _mix(theme.panel_alt, theme.muted, 0.45)
    gui.circle(col, (r.centerx, r.y + r.h * 0.38), r.w * 0.2)
    gui.rect(col, (r.centerx - r.w * 0.32, r.y + r.h * 0.62, r.w * 0.64, r.h * 0.38), radius=int(r.w * 0.3))
    pygame.draw.rect(gui.screen, theme.border, gui.R(r), 1, border_radius=int(6 * gui.u))
    gui.text((r.centerx, r.bottom - 8), "초상화 없음", 10, theme.muted, anchor="midbottom")
    return False
