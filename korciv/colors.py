"""국가 색 배정(v1.3.1): 지각적 색차(CIEDE2000)가 큰 색부터 고른다.

- 플레이어가 고른 국기 색(player_color)을 포함해 이미 쓰는 색과 가장 멀리 떨어진 팔레트 색을 하나씩 그리디로 고른다.
- 팔레트 색이 모두 가까우면(살아 있는 나라가 아주 많을 때) 색 공간을 촘촘히 훑어 가장 먼 새 색을 만든다.
- 중립 지역 바탕(한지색)·미탐색 지역과 헷갈리지 않도록 그 색들도 피한다.
- 색차는 지도에 칠해지는 모습(한지에 번진 색, 밝은·어두운 테마 둘 다)끼리 잰다.
pygame 없이 엔진(game.py)과 화면(시작 설정 미리보기)이 같은 결과를 쓰도록 순수 파이썬으로 둔다.
"""
from __future__ import annotations

import colorsys
import functools
import math

from . import config as C

# 지도에 칠하는 모습(v1.3.1): 밝은 테마는 채도를 조금 빼고 한지색에 섞고, 어두운 테마는 흰색에 조금 섞는다.
# 화면(app.owner_fill)과 색 배정이 같은 값을 쓴다 — 색차는 '지도에 보이는 색'끼리 잰다
MAP_PAPER = "#EFE6D2"
MAP_WASH = 0.38        # 한지색에 섞는 비율(v1.3.0까지 0.45: 색이 많이 바래 나라끼리 헷갈렸다)
MAP_DESAT = 0.12       # 채도를 빼는 비율(v1.3.0까지 0.2)
DARK_LIFT = 0.3        # 어두운 테마: 흰색에 섞는 비율
# 국가 색이 피해야 할 바탕색: (밝은 테마) 중립 지역·한지·미탐색, (어두운 테마) 중립 지역·미탐색
RESERVED_LIGHT = ("#E6DCC4", "#EFE6D2", "#CFC8B8")
RESERVED_DARK = ("#3A3830", "#2B2B2A")
MIN_DE = 10.0          # 지도에 보이는 두 나라 색이 이보다 가까우면 헷갈린다(CIEDE2000)
RESERVED_DE = 14.0     # 바탕색과는 이만큼 떨어져야 한다


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb2hex(c):
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(v)))) for v in c))


def _lin(v):
    v /= 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def lab(c):
    """sRGB(0~255 또는 '#RRGGBB') → CIE L*a*b*(D65)."""
    if isinstance(c, str):
        c = hex2rgb(c)
    r, g, b = (_lin(float(v)) for v in c)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(c1, c2) -> float:
    """CIEDE2000 색차(사람 눈에 보이는 차이). 1 ≈ 겨우 구분, 20 이상이면 뚜렷이 다른 색. '#RRGGBB'·(r, g, b)."""
    return de_lab(lab(c1), lab(c2))


def de_lab(l1, l2) -> float:
    """두 L*a*b* 색의 CIEDE2000 색차."""
    L1, a1, b1 = l1
    L2, a2, b2 = l2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)
    Lm, Cmp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hm = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hm = (h1p + h2p) / 2
    else:
        hm = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hm - 30)) + 0.24 * math.cos(math.radians(2 * hm))
         + 0.32 * math.cos(math.radians(3 * hm + 6)) - 0.20 * math.cos(math.radians(4 * hm - 63)))
    dth = 30 * math.exp(-(((hm - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cmp ** 7 / (Cmp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lm - 50) ** 2 / math.sqrt(20 + (Lm - 50) ** 2)
    Sc = 1 + 0.045 * Cmp
    Sh = 1 + 0.015 * Cmp * T
    Rt = -math.sin(math.radians(2 * dth)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def map_fill_light(c):
    """밝은 테마 지도에 칠해지는 국가 색(채도 MAP_DESAT 만큼 빼고 한지색에 MAP_WASH 만큼 섞음)."""
    c = hex2rgb(c) if isinstance(c, str) else c
    g = sum(c) / 3
    c = tuple(v + (g - v) * MAP_DESAT for v in c)
    return _mix(c, hex2rgb(MAP_PAPER), MAP_WASH)


def map_fill_dark(c):
    """어두운 테마 지도에 칠해지는 국가 색(흰색에 DARK_LIFT 만큼 섞음)."""
    c = hex2rgb(c) if isinstance(c, str) else c
    return _mix(c, (255, 255, 255), DARK_LIFT)


_LAB = {}


def _labs(h):
    """(밝은 테마 지도 색, 어두운 테마 지도 색)의 L*a*b*."""
    h = h.upper()
    v = _LAB.get(h)
    if v is None:
        v = _LAB[h] = (lab(map_fill_light(h)), lab(map_fill_dark(h)))
    return v


_RES = None


def _gap(h, taken) -> float:
    """지도에 보이는 h 와 이미 쓰는 색들 사이의 가장 작은 색차(두 테마 중 작은 쪽). 바탕색과의 거리는
    RESERVED_DE 를 MIN_DE 로 환산해 함께 본다."""
    global _RES
    if _RES is None:
        _RES = ([lab(x) for x in RESERVED_LIGHT], [lab(x) for x in RESERVED_DARK])
    lh, dh = _labs(h)
    g = 999.0
    for t in taken:
        lt, dt = _labs(t)
        g = min(g, de_lab(lh, lt), de_lab(dh, dt))
    r = min(min(de_lab(lh, x) for x in _RES[0]), min(de_lab(dh, x) for x in _RES[1])) * (MIN_DE / RESERVED_DE)
    return min(g, r)


def min_gap(colors) -> float:
    """색 목록에서 가장 가까운 두 색의 (지도에 보이는) 색차."""
    cs = [c.upper() for c in colors if c]
    best = 999.0
    for i, a in enumerate(cs):
        for b in cs[i + 1:]:
            la, da = _labs(a)
            lb, db = _labs(b)
            best = min(best, de_lab(la, lb), de_lab(da, db))
    return best


_GRID = None


def _grid():
    """팔레트가 모자랄 때 쓸 후보 색: 색상 10°·채도·명도 몇 단계(너무 밝거나 어두운 색은 뺀다)."""
    global _GRID
    if _GRID is None:
        out = []
        for hue in range(0, 360, 10):
            for s in (0.5, 0.65, 0.8):
                for v in (0.45, 0.6, 0.72, 0.85):
                    out.append(rgb2hex(tuple(x * 255 for x in colorsys.hsv_to_rgb(hue / 360, s, v))))
        _GRID = out
    return _GRID


def pick(taken, palette=None) -> str:
    """이미 쓰는 색(taken)과 가장 멀리 떨어진 색 하나. 팔레트에서 MIN_DE 이상 떨어진 색이 있으면 그중 가장 먼 것,
    없으면 후보 격자까지 넓혀 가장 먼 색."""
    taken = [t.upper() for t in taken if t]
    pal = [p for p in (palette or C.FACTION_COLORS) if p.upper() not in taken]
    best = max(pal, key=lambda p: (_gap(p, taken), -pal.index(p)), default=None)
    if best is not None and _gap(best, taken) >= MIN_DE:
        return best
    cand = [g for g in _grid() if g not in taken]
    alt = max(cand, key=lambda p: _gap(p, taken))
    if best is None or _gap(alt, taken) > _gap(best, taken):
        return alt
    return best


def assign(n, fixed=(), palette=None) -> list:
    """n 개 국가 색. fixed 는 이미 정해진 색(예: 플레이어 국기 색) — 그대로 두고 나머지를 그리디로 채운다.
    fixed 의 None 칸은 새로 고른다."""
    fixed = list(fixed) + [None] * n
    out = [c for c in fixed[:n]]
    taken = [c for c in out if c]
    for i in range(n):
        if out[i] is None:
            out[i] = pick(taken, palette)
            taken.append(out[i])
    return out


def nation_colors(n_ai, player_hex=None) -> list:
    """새 판의 국가 색 [플레이어, AI 1, …, AI n]. 플레이어 색(국기 배경 색 1 또는 기본 파랑)과 이미 고른 AI 색 모두에서
    가장 먼 팔레트 색을 차례로 고른다(시작 설정 미리보기와 게임이 같은 결과, 같은 입력은 기억해 둔다)."""
    return list(_nation_colors(int(n_ai), (player_hex or C.FACTION_COLORS[0]).upper()))


@functools.lru_cache(maxsize=64)
def _nation_colors(n_ai, player_hex) -> tuple:
    return tuple(assign(1 + n_ai, [player_hex]))
