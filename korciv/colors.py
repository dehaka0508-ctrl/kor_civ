"""한지 테마 국가 색(v1.3.13): 지정 팔레트와 AI 번호 순서를 유지한다.

플레이어의 사용자 국기 색은 보존한다. 정확히 겹치는 AI 칸만 남은 고정 팔레트 색으로 대체한다.
반란국도 지정 팔레트만 사용하며, 다 썼을 때는 적게 쓰인 색을 재사용한다.
지도 채색 함수와 색차 진단 함수는 엔진·미리보기에서 공통으로 쓴다.
"""
from __future__ import annotations

import math

from . import config as C

COLOR_SCHEMA = 2

# 지도에 칠하는 모습(v1.3.1): 밝은 테마는 채도를 조금 빼고 한지색에 섞고, 어두운 테마는 흰색에 조금 섞는다.
# 화면(app.owner_fill)과 색 배정이 같은 값을 쓴다 — 색차는 '지도에 보이는 색'끼리 잰다
MAP_PAPER = "#EFE6D2"
MAP_WASH = 0.38        # 한지색에 섞는 비율(v1.3.0까지 0.45: 색이 많이 바래 나라끼리 헷갈렸다)
MAP_DESAT = 0.12       # 채도를 빼는 비율(v1.3.0까지 0.2)
DARK_LIFT = 0.3        # 어두운 테마: 흰색에 섞는 비율


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


def pick(taken, palette=None) -> str:
    """지정 순서의 미사용 색을 우선. 팔레트를 다 쓴 경우 최소 사용 횟수의 색을 재사용한다."""
    taken = [t.upper() for t in taken if t]
    pal = list(dict.fromkeys(p.upper() for p in (C.FACTION_COLORS if palette is None else palette)))
    if not pal:
        raise ValueError("국가 색 팔레트가 비어 있습니다.")
    return next((p for p in pal if p not in taken), None) or min(pal, key=taken.count)


def assign(n, fixed=(), palette=None) -> list:
    """고정 칸은 보존하고 빈 칸만 팔레트 순서로 채운다. 색차순 재정렬·새 색 생성 없음."""
    out = [(c.upper() if c else None) for c in list(fixed)[:n]]
    out += [None] * max(0, n - len(out))
    taken = [c for c in out if c]
    for i in range(n):
        if out[i] is None:
            out[i] = pick(taken, palette)
            taken.append(out[i])
    return out


def nation_colors(n_ai, player_hex=None) -> list:
    """[플레이어, AI 1, …] 고정 순서. 사용자 국기와 겹치는 칸만 남은 팔레트 색으로 대체한다."""
    n_ai = max(0, min(C.MAX_ENEMIES, int(n_ai)))
    player_hex = (player_hex or C.FACTION_COLORS[0]).upper()
    fixed = [player_hex] + [c if c != player_hex else None for c in C.FACTION_COLORS[1:n_ai + 1]]
    return assign(1 + n_ai, fixed)
