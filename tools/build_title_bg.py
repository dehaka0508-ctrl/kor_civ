"""시작 화면 배경 그림 만들기: 쪽빛 밤하늘 + 달(왼쪽)·해(오른쪽) + 수묵 산수 능선(안개) + 금색 한반도 윤곽 + 구름무늬.
korciv/assets/ui/title_bg.jpg 로 저장한다(게임은 이 그림을 불러와 창 크기에 맞춰 쓴다).

사용: python3 tools/build_title_bg.py
"""
from __future__ import annotations

import math
import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import numpy as np  # noqa: E402
import pygame  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BASE_W, BASE_H = 1920, 1200
OUT = os.path.join(ROOT, "korciv", "assets", "ui", "title_bg.jpg")


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _noise(w, h, seed, strength=1.0):
    """한지 결 비슷한 잡음(1.0 주변 값, (w, h) 순서)."""
    rng = np.random.default_rng(seed)
    out = np.zeros((w, h), np.float32)
    for cell, amp in ((3, 0.025), (12, 0.03), (60, 0.035), (220, 0.03)):
        sw, sh = max(2, w // cell + 2), max(2, h // cell + 2)
        n = (rng.random((sw, sh)) * 255).astype(np.uint8)
        s = pygame.surfarray.make_surface(np.repeat(n[..., None], 3, 2))
        s = pygame.transform.smoothscale(s, (w, h))
        out += (pygame.surfarray.array3d(s)[..., 0].astype(np.float32) / 255 - 0.5) * 2 * amp
    return 1.0 + out * strength


def _ridge(w, seed, base, amp, rough=0.42, octaves=5):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, w)
    y = np.zeros(w)
    a, f = amp, 1.6
    for _ in range(octaves):
        ph = rng.random() * math.tau
        y += a * np.sin(x * f * math.tau + ph) * (0.6 + 0.4 * np.sin(x * f * 2.3 + ph * 2))
        a *= rough
        f *= 2.1
    return base - np.abs(y) * 1.25 + amp * 0.3


def _cloud(surf, cx, cy, s, flip=False):
    """구름무늬(운문): 겹친 둥근 덩어리 + 말린 꼬리, 금색 외곽선."""
    g = pygame.Surface((int(360 * s), int(160 * s)), pygame.SRCALPHA)
    blobs = [(80, 90, 34), (125, 70, 44), (180, 78, 38), (225, 95, 30), (150, 105, 34), (100, 110, 26)]
    fill = (*_mix(_rgb("#AEBBD0"), _rgb("#1E3550"), 0.35), 255)
    line = (*_rgb("#E2C58A"), 255)
    for x, y, r in blobs:
        pygame.draw.circle(g, line, (int(x * s), int(y * s)), int(r * s))
    for x, y, r in blobs:
        pygame.draw.circle(g, fill, (int(x * s), int(y * s)), int(r * s - 2))
    pts = []
    for i in range(70):
        t = i / 69
        a = math.pi * 0.2 + t * math.pi * 2.6
        rr = (30 - t * 22) * s
        pts.append((int(248 * s + 40 * s * t + math.cos(a) * rr), int(100 * s + math.sin(a) * rr)))
    pygame.draw.lines(g, line, False, pts, 2)
    tail = [(int((60 - i * 1.2) * s), int((118 + math.sin(i / 6) * 6) * s)) for i in range(40)]
    pygame.draw.lines(g, line, False, tail, 2)
    if flip:
        g = pygame.transform.flip(g, True, False)
    g.set_alpha(85)
    surf.blit(g, (cx - g.get_width() / 2, cy - g.get_height() / 2))


def _peninsula(surf, mapview, w, h):
    """금색 실선 한반도(시군구 경계까지 아주 옅게) — 오른쪽에 크게."""
    g = pygame.Surface((w, h), pygame.SRCALPHA)
    s = 1.08 * h / 900
    cx, cy = 300, 420
    gold, gold_lt = _rgb("#C29A55"), _rgb("#E2C58A")
    for rid, arr, bbox in mapview.polys:
        pts = ((arr - (cx, cy)) * s + (w / 2 + w * 0.24, h / 2)).tolist()
        if len(pts) > 2:
            pygame.draw.polygon(g, (*gold, 10), pts)
            pygame.draw.aalines(g, (*gold_lt, 34), True, pts)
    surf.blit(g, (0, 0))


def _render(mapview, seed=2, clouds=True, sun=True):
    w, h = BASE_W, BASE_H
    k = h / 900                                            # 1440×900 기준으로 잡은 크기를 비례해서 키운다
    X, Y = np.mgrid[0:w, 0:h].astype(np.float32)          # (w, h) 순서(pygame 배열과 같다)
    yy = Y / h
    top, mid, bot = (np.array(_rgb(c), np.float32) for c in ("#0B1424", "#1B3150", "#3B5674"))
    t1 = np.clip(yy / 0.62, 0, 1)[..., None]
    t2 = np.clip((yy - 0.62) / 0.38, 0, 1)[..., None]
    img = (top * (1 - t1) + mid * t1) * (1 - t2) + bot * t2
    mx, my = w * 0.20, h * 0.20
    sx, sy = w * 0.80, h * 0.20
    d = np.sqrt((X - mx) ** 2 + (Y - my) ** 2) / k
    img += (np.array(_rgb("#E9D9A8"), np.float32) - img) * (np.exp(-d / 260) * 0.22)[..., None]
    if sun:
        d = np.sqrt((X - sx) ** 2 + (Y - sy) ** 2) / k
        img += (np.array(_rgb("#D8643F"), np.float32) - img) * (np.exp(-d / 240) * 0.24)[..., None]
    # 수묵 능선 5겹: 능선 쪽이 짙고 아래로 갈수록 안개에 묻힌다(먼 산은 옅게)
    layers = [(0.56, 60, "#3E5878", 0.55), (0.65, 70, "#2F4766", 0.6), (0.74, 75, "#223652", 0.68),
              (0.84, 70, "#162740", 0.75), (0.94, 60, "#0D1829", 0.85)]
    mist = np.array(_rgb("#7F97B2"), np.float32)
    inkc = np.array(_rgb("#0A1220"), np.float32)
    for i, (b, amp, c, dens) in enumerate(layers):
        r = _ridge(w, seed * 10 + i, h * b, amp * k)[:, None].astype(np.float32)
        inside = Y > r
        depth = np.clip((Y - r) / ((110 + i * 25) * k), 0, 1)
        kk = (1 - depth[..., None]) ** 1.3 * dens + (1 - dens) * 0.35
        layer = np.array(_rgb(c), np.float32) * kk + mist * (1 - kk)
        edge = np.exp(-np.clip(Y - r, 0, None) / (3.0 * k))[..., None] * 0.35
        layer = layer * (1 - edge) + inkc * edge
        img = np.where(inside[..., None], layer, img)
        fog = np.exp(-np.clip(r - Y, 0, None) / (40 * k)) * (Y < r) * 0.22
        img += (mist - img) * fog[..., None]
    img *= _noise(w, h, seed + 30, 0.7)[..., None]
    surf = pygame.surfarray.make_surface(np.clip(img, 0, 255).astype(np.uint8))
    rng = random.Random(seed)
    for _ in range(180):                                   # 별
        x, y = rng.random() * w, rng.random() * h * 0.5
        a = rng.randint(40, 160)
        if a > 140:
            pygame.draw.circle(surf, _mix((255, 255, 255), _rgb("#E2C58A"), 0.3), (int(x), int(y)), max(1, int(k)))
        else:
            surf.fill(_mix(_rgb("#0B1424"), (255, 255, 255), a / 255), (int(x), int(y), max(1, int(k)), max(1, int(k))))
    if mapview is not None:
        _peninsula(surf, mapview, w, h)
    for (cx, cy), col, glow in (((mx, my), "#EADBAA", "#F1E3B5"), ((sx, sy), "#C8432E", "#E0704A")):
        if (cx, cy) == (sx, sy) and not sun:
            continue
        R = int(120 * k)
        g = pygame.Surface((2 * R, 2 * R), pygame.SRCALPHA)
        for rr, a in ((110, 10), (85, 18), (66, 30)):
            pygame.draw.circle(g, (*_rgb(glow), a), (R, R), int(rr * k))
        pygame.draw.circle(g, (*_rgb(col), 238), (R, R), int(52 * k))
        surf.blit(g, (cx - R, cy - R))
    if clouds:
        for (cx, cy, s, flip) in ((w * 0.11, h * 0.31, 0.85, False), (w * 0.91, h * 0.53, 0.75, True)):
            _cloud(surf, cx, cy, s * k, flip)
    return surf


def main():
    pygame.init()
    pygame.display.set_mode((8, 8))
    from korciv.data import load_world
    from korciv.ui.mapview import MapView
    surf = _render(MapView(load_world()))
    pygame.image.save(surf, OUT)
    print(f"{OUT} ({os.path.getsize(OUT):,} bytes)")


if __name__ == "__main__":
    main()
