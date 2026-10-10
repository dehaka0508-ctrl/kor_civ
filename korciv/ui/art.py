"""국기·지도자 초상화 그리기."""
from __future__ import annotations

import math
import os

import pygame

from ..flags import MASK_EMBLEMS, normalize

SS = 3                                   # 국기 슈퍼샘플링 배율(가장자리 매끄럽게)
_flag_cache: dict = {}
_portrait_src: dict = {}
_portrait_cache: dict = {}
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
PORTRAIT_DIR = os.path.join(ASSETS, "portraits")
_masks: dict = {}
_presets: dict = {}
# 마스크 문양의 크기(문양 반지름 R 대비 상자 한 변)
MASK_BOX = {"pine": 2.2, "cloud": 2.4, "om": 2.1, "tiger": 2.2, "dragon": 2.2, "cheonma": 2.6, "samjogo": 2.3}
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


def _mask(key):
    if key not in _masks:
        try:
            _masks[key] = pygame.image.load(os.path.join(ASSETS, "emblems", key + ".png"))
        except Exception:
            _masks[key] = None
    return _masks[key]


def _preset_image(key):
    if key not in _presets:
        try:
            _presets[key] = pygame.image.load(os.path.join(ASSETS, "flags", key + ".png"))
        except Exception:
            _presets[key] = None
    return _presets[key]


def draw_emblem(s, key, cx, cy, R, fl):
    """투명 레이어 s 에 문양을 그린다(오려내기는 알파 0으로 칠해서)."""
    ec = fl["ec"]
    hole = (0, 0, 0, 0)
    W = max(1, int(R * 0.2))
    if key in MASK_EMBLEMS:
        m = _mask(key)
        if m is None:
            return
        side = max(1, int(R * MASK_BOX.get(key, 2.2)))
        img = pygame.transform.smoothscale(m, (side, side))
        img.fill((*ec, 255), special_flags=pygame.BLEND_RGBA_MULT)
        s.blit(img, (int(cx - side / 2), int(cy - side / 2)))
    elif key == "disc":
        pygame.draw.circle(s, ec, (cx, cy), int(R * 0.8))
    elif key == "ring":
        pygame.draw.circle(s, ec, (cx, cy), int(R * 0.85), max(1, int(R * 0.32)))
    elif key == "star5":
        pygame.draw.polygon(s, ec, _star(cx, cy, R))
    elif key == "hexagram":                    # 두 정삼각형 윤곽이 겹친 육망성
        # 굵은 선 윤곽은 뾰족한 꼭짓점이 갈라지므로, 꽉 찬 삼각형에서 안쪽 삼각형을 오려 낸 띠로 그린다
        w = R * 0.16
        for rot in (-math.pi / 2, math.pi / 2):
            tri = pygame.Surface(s.get_size(), pygame.SRCALPHA)
            pygame.draw.polygon(tri, ec, _ngon(cx, cy, R, 3, rot=rot))
            pygame.draw.polygon(tri, (0, 0, 0, 0), _ngon(cx, cy, R - 2 * w, 3, rot=rot))
            s.blit(tri, (0, 0))
    elif key == "crescent_star":
        x0 = cx - R * 0.2
        pygame.draw.circle(s, ec, (int(x0), cy), int(R * 0.8))
        pygame.draw.circle(s, hole, (int(x0 + R * 0.3), cy), int(R * 0.66))
        pygame.draw.polygon(s, ec, _star(cx + R * 0.55, cy, R * 0.32))
    elif key == "taegeuk":                     # 태극기의 태극: 위 문양 색 1, 아래 문양 색 2
        b = fl["ec2"]
        r = int(R * 0.85)
        pygame.draw.circle(s, b, (cx, cy), r)
        pygame.draw.circle(s, ec, (cx, cy), r, draw_top_left=True, draw_top_right=True)
        pygame.draw.circle(s, ec, (cx - r // 2, cy), r // 2)
        pygame.draw.circle(s, b, (cx + r // 2, cy), r // 2)
    elif key == "yinyang":                     # 도교 태극(음양): 좌우로 나뉘고 점이 박힌다
        b = fl["ec2"]
        r = int(R * 0.85)
        pygame.draw.circle(s, b, (cx, cy), r)
        pygame.draw.circle(s, ec, (cx, cy), r, draw_top_left=True, draw_bottom_left=True)
        pygame.draw.circle(s, ec, (cx, cy - r // 2), r // 2)
        pygame.draw.circle(s, b, (cx, cy + r // 2), r // 2)
        pygame.draw.circle(s, b, (cx, cy - r // 2), max(1, r // 7))
        pygame.draw.circle(s, ec, (cx, cy + r // 2), max(1, r // 7))
        pygame.draw.circle(s, ec, (cx, cy), r, max(1, r // 18))
    elif key == "manji":                       # 卍: 똑바로 세운 왼쪽 방향(불교 만자)
        t = R * 0.2
        a = R * 0.8

        def bar(x0, y0, x1, y1):
            pygame.draw.rect(s, ec, pygame.Rect(min(x0, x1) - t / 2, min(y0, y1) - t / 2,
                                                abs(x1 - x0) + t, abs(y1 - y0) + t))
        bar(cx, cy - a, cx, cy + a)
        bar(cx - a, cy, cx + a, cy)
        bar(cx, cy - a, cx - a, cy - a)        # 위 팔 → 왼쪽
        bar(cx + a, cy, cx + a, cy - a)        # 오른 팔 → 위
        bar(cx, cy + a, cx + a, cy + a)        # 아래 팔 → 오른쪽
        bar(cx - a, cy, cx - a, cy + a)        # 왼 팔 → 아래
    elif key == "cross":                       # 스위스 국기처럼 굵은 십자
        t = R * 0.56
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
    elif key == "flower":
        for i in range(5):
            a = -math.pi / 2 + i * 2 * math.pi / 5
            pygame.draw.circle(s, ec, (int(cx + R * 0.5 * math.cos(a)), int(cy + R * 0.5 * math.sin(a))), int(R * 0.42))
        pygame.draw.circle(s, fl["ec2"], (cx, cy), int(R * 0.25))


def _draw_ingonggi(s, W, H):
    """인공기: 파랑·흰·빨강·흰·파랑 가로줄, 왼쪽 흰 원 안에 빨간 별."""
    blue, red, white = (2, 79, 162), (237, 28, 39), (255, 255, 255)
    s.fill(blue)
    s.fill(white, (0, H * 0.165, W, H * 0.67))
    s.fill(red, (0, H * 0.19, W, H * 0.62))
    cx, cy, r = W / 3, H / 2, H * 0.22
    pygame.draw.circle(s, white, (int(cx), int(cy)), int(r))
    pygame.draw.polygon(s, red, _star(cx, cy, r * 0.97))


def render_flag(flag, w, h) -> pygame.Surface:
    """국기를 w×h 픽셀 Surface 로."""
    fl = normalize(flag)
    preset = fl.get("preset")
    key = (preset, fl["bg"], fl["c1"], fl["c2"], fl["em"], fl["ec"], fl["ec2"], w, h)
    surf = _flag_cache.get(key)
    if surf is not None:
        return surf
    if preset:
        img = _preset_image(preset)
        if img is not None:
            out = pygame.transform.smoothscale(img, (w, h))
        else:
            s = pygame.Surface((w * SS, h * SS))
            _draw_ingonggi(s, w * SS, h * SS)
            out = pygame.transform.smoothscale(s, (w, h))
    else:
        W, H = w * SS, h * SS
        s = pygame.Surface((W, H))
        c1, c2 = fl["c1"], fl["c2"]
        bg = fl["bg"]
        s.fill(c1)
        R = H * 0.3                                  # 문양 크기(가운데)
        if bg == "h2":
            s.fill(c2, (0, H // 2, W, H - H // 2))
        elif bg == "v2":
            s.fill(c2, (W // 2, 0, W - W // 2, H))
        elif bg == "h3":
            s.fill(c2, (0, H // 3, W, H - 2 * (H // 3)))
        elif bg == "v3":
            s.fill(c2, (W // 3, 0, W - 2 * (W // 3), H))
        elif bg == "diag_up":                        # 왼쪽 아래 → 오른쪽 위 대각선
            pygame.draw.polygon(s, c2, [(W, 0), (W, H), (0, H)])
        elif bg == "diag_down":                      # 왼쪽 위 → 오른쪽 아래 대각선
            pygame.draw.polygon(s, c2, [(0, 0), (W, H), (0, H)])
        elif bg == "cross":                          # 잉글랜드(성 조지) 십자
            t = H * 0.2
            s.fill(c2, (W / 2 - t / 2, 0, t, H))
            s.fill(c2, (0, H / 2 - t / 2, W, t))
        elif bg == "quarters":
            s.fill(c2, (W // 2, 0, W - W // 2, H // 2))
            s.fill(c2, (0, H // 2, W // 2, H - H // 2))
        elif bg == "border":
            s.fill(c2)
            m = int(H * 0.1)
            s.fill(c1, (m, m, W - 2 * m, H - 2 * m))
            R = H * 0.26
        if fl["em"] != "none":
            layer = pygame.Surface((W, H), pygame.SRCALPHA)
            draw_emblem(layer, fl["em"], int(W / 2), int(H / 2), R, fl)
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
    """지도자 초상화 파일: <지도자 키(3글자)>.png (예: 세종대왕 sej.png)."""
    if not leader_key or "/" in leader_key or "." in leader_key:
        return None
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


# ------------------------------------------------------------------ 화면 장식(쪽빛 띠·아이콘)
_band_cache: dict = {}


def indigo_band(w, h, top=(30, 53, 80), bottom=(17, 30, 49), lattice=True):
    """쪽빛 띠(실제 픽셀): 세로 그라데이션 + 옅은 창살 무늬. 크기별로 한 번만 만든다."""
    key = (w, h, top, bottom, lattice)
    s = _band_cache.get(key)
    if s is None:
        s = pygame.Surface((max(1, w), max(1, h)))
        for y in range(h):
            s.fill(_mix(top, bottom, y / max(1, h - 1)), (0, y, w, 1))
        if lattice:
            lat = pygame.Surface((w, h), pygame.SRCALPHA)
            g = max(8, int(h * 0.36))
            for x in range(0, w, g):
                pygame.draw.line(lat, (255, 255, 255, 9), (x, 0), (x, h))
            for y in range(0, h, g):
                pygame.draw.line(lat, (255, 255, 255, 9), (0, y), (w, y))
            s.blit(lat, (0, 0))
        if len(_band_cache) > 40:
            _band_cache.clear()
        _band_cache[key] = s
    return s


def star_points(cx, cy, r, inner=0.42):
    return _star(cx, cy, r, 5, inner)


def ui_icon(surf, kind, center, col, k=1.0):
    """상단 바·패널용 단색 아이콘(실제 픽셀 좌표, 크기 배율 k)."""
    x, y = center
    w2 = max(1, int(2 * k))
    dark = _mix(col, (17, 30, 49), 0.6)
    if kind == "coin":                                # 엽전
        pygame.draw.circle(surf, col, (x, y), int(8 * k))
        pygame.draw.rect(surf, dark, (x - 3 * k, y - 3 * k, 6 * k, 6 * k))
    elif kind == "rice":                              # 쌀가마
        pygame.draw.ellipse(surf, col, (x - 8 * k, y - 6 * k, 16 * k, 14 * k))
        pygame.draw.polygon(surf, col, [(x - 4 * k, y - 5 * k), (x, y - 10 * k), (x + 4 * k, y - 5 * k)])
        pygame.draw.line(surf, dark, (x - 7 * k, y), (x + 7 * k, y), 1)
        pygame.draw.line(surf, dark, (x - 3 * k, y - 5 * k), (x + 3 * k, y - 5 * k), w2)
    elif kind == "face":
        pygame.draw.circle(surf, col, (x, y), int(8.5 * k), w2)
        pygame.draw.circle(surf, col, (int(x - 3 * k), int(y - 2 * k)), max(1, int(1.4 * k)))
        pygame.draw.circle(surf, col, (int(x + 3 * k), int(y - 2 * k)), max(1, int(1.4 * k)))
        pygame.draw.arc(surf, col, (x - 4.5 * k, y - 3 * k, 9 * k, 8 * k), math.pi * 1.15, math.pi * 1.85, w2)
    elif kind == "tax":                               # 저울
        pygame.draw.line(surf, col, (x, y - 8 * k), (x, y + 7 * k), w2)
        pygame.draw.line(surf, col, (x - 8 * k, y - 5 * k), (x + 8 * k, y - 5 * k), w2)
        pygame.draw.line(surf, col, (x - 5 * k, y + 7 * k), (x + 5 * k, y + 7 * k), w2)
        for sx in (-1, 1):
            pygame.draw.arc(surf, col, (x + sx * 7 * k - 4 * k, y - 2 * k, 8 * k, 6 * k), math.pi, 2 * math.pi, w2)
    elif kind == "swords":
        pygame.draw.line(surf, col, (x - 7 * k, y - 7 * k), (x + 7 * k, y + 7 * k), w2)
        pygame.draw.line(surf, col, (x + 7 * k, y - 7 * k), (x - 7 * k, y + 7 * k), w2)
        pygame.draw.line(surf, col, (x - 7 * k, y + 3 * k), (x - 3 * k, y + 7 * k), w2)
        pygame.draw.line(surf, col, (x + 7 * k, y + 3 * k), (x + 3 * k, y + 7 * k), w2)
    elif kind == "pause":
        pygame.draw.rect(surf, col, (x - 5 * k, y - 6 * k, 3.5 * k, 12 * k))
        pygame.draw.rect(surf, col, (x + 1.5 * k, y - 6 * k, 3.5 * k, 12 * k))
    elif kind == "flag":
        pygame.draw.line(surf, col, (x - 5 * k, y - 8 * k), (x - 5 * k, y + 8 * k), w2)
        pygame.draw.polygon(surf, col, [(x - 4 * k, y - 8 * k), (x + 7 * k, y - 5 * k), (x - 4 * k, y - 1 * k)])
    elif kind == "people":
        for dx in (-5, 5):
            pygame.draw.circle(surf, col, (int(x + dx * k), int(y - 4 * k)), int(3 * k))
            pygame.draw.ellipse(surf, col, (x + dx * k - 5 * k, y, 10 * k, 9 * k))
    elif kind == "hammer":
        pygame.draw.line(surf, col, (x - 6 * k, y + 7 * k), (x + 3 * k, y - 2 * k), max(2, int(2.5 * k)))
        pygame.draw.polygon(surf, col, [(x - 1 * k, y - 8 * k), (x + 7 * k, y), (x + 9 * k, y - 2 * k), (x + 1 * k, y - 10 * k)])
    elif kind == "scroll":
        pygame.draw.rect(surf, col, (x - 7 * k, y - 6 * k, 14 * k, 12 * k), w2)
        for i in range(3):
            pygame.draw.line(surf, col, (x - 4 * k, y - 3 * k + i * 3 * k), (x + 4 * k, y - 3 * k + i * 3 * k), 1)
    elif kind == "shield":
        pygame.draw.polygon(surf, col, [(x - 7 * k, y - 8 * k), (x + 7 * k, y - 8 * k), (x + 7 * k, y), (x, y + 9 * k),
                                        (x - 7 * k, y)], w2)
    elif kind == "coal":
        pygame.draw.polygon(surf, col, [(x - 8 * k, y + 5 * k), (x - 5 * k, y - 2 * k), (x - 1 * k, y - 4 * k),
                                        (x + 2 * k, y + 1 * k), (x - 1 * k, y + 6 * k)])
        pygame.draw.polygon(surf, col, [(x + 1 * k, y + 6 * k), (x + 3 * k, y - 3 * k), (x + 7 * k, y - 6 * k),
                                        (x + 9 * k, y + 1 * k), (x + 6 * k, y + 6 * k)])
    elif kind == "box":
        pygame.draw.rect(surf, col, (x - 7 * k, y - 5 * k, 14 * k, 11 * k), w2)
        pygame.draw.line(surf, col, (x - 7 * k, y - 1 * k), (x + 7 * k, y - 1 * k), w2)
