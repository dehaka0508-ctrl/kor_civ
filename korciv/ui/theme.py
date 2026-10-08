"""색·글꼴 토큰 (기획서 13절 시각 디자인)."""
from __future__ import annotations

import os

import pygame

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
FONT_FILES = {"regular": "Pretendard-Regular.ttf", "semibold": "Pretendard-SemiBold.ttf",
              "bold": "Pretendard-Bold.ttf"}


def hex2rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(c1, c2, t: float):
    """t=0 → c1, t=1 → c2"""
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def desaturate(c, amount):
    grey = sum(c) / 3
    return tuple(int(round(v + (grey - v) * amount)) for v in c)


class Theme:
    def __init__(self, dark=False):
        self.set_dark(dark)

    def set_dark(self, dark):
        self.dark = dark
        if not dark:
            self.bg = hex2rgb("#FAFAF7")
            self.panel = hex2rgb("#FFFFFF")
            self.panel_alt = hex2rgb("#F4F5F7")
            self.text = hex2rgb("#1F2328")
            self.muted = hex2rgb("#6B7078")
            self.border = hex2rgb("#E3E5E8")
            self.sea = hex2rgb("#DCE6EE")
            self.sea_line = hex2rgb("#C5D3DE")
            self.paper = hex2rgb("#EEF1EC")
            self.neutral = hex2rgb("#F4F1EA")
            self.unexplored = hex2rgb("#D6D5D2")
            self.shadow = (0, 0, 0, 20)
        else:
            self.bg = hex2rgb("#16181C")
            self.panel = hex2rgb("#1F2227")
            self.panel_alt = hex2rgb("#272B31")
            self.text = hex2rgb("#E8EAED")
            self.muted = hex2rgb("#9AA0A8")
            self.border = hex2rgb("#343840")
            self.sea = hex2rgb("#1D2C3A")
            self.sea_line = hex2rgb("#2A3D4F")
            self.paper = hex2rgb("#1A1D21")
            self.neutral = hex2rgb("#3A3935")
            self.unexplored = hex2rgb("#2B2B2A")
            self.shadow = (0, 0, 0, 60)
        self.accent = hex2rgb("#2F6FDE")
        self.good = hex2rgb("#2B8A3E")
        self.bad = hex2rgb("#C92A2A")
        self.warn = hex2rgb("#E67700")
        self.province_line = hex2rgb("#8A8F98")
        self.do8_line = hex2rgb("#5C5F66")
        self.happy_neg = hex2rgb("#C92A2A")
        self.happy_mid = hex2rgb("#F1F3F5") if not dark else hex2rgb("#3A3D42")
        self.happy_pos = hex2rgb("#2F9E44")


# UI 배율: 화면 요소는 논리 좌표로 배치하고 그릴 때 u 배 한다(창 크기에 맞춤).
# 글자는 버튼·패널보다 FONT_BOOST 만큼 더 키운다(글자 2.5배 : 버튼 2배 = 1.25).
UI = {"u": 1.0}
FONT_BOOST = 1.25

_fonts: dict = {}
_text_cache: dict = {}


def set_ui_scale(u: float):
    if abs(UI["u"] - u) > 1e-6:
        UI["u"] = u
        _fonts.clear()
        _text_cache.clear()


def ui_scale() -> float:
    return UI["u"]


def font_px(size: float) -> int:
    return max(6, int(round(size * UI["u"] * FONT_BOOST)))


def font(size: int, weight: str = "regular") -> pygame.font.Font:
    """실제 픽셀 크기로 만든 글꼴(논리 크기 size 기준)."""
    px = font_px(size)
    key = (px, weight)
    f = _fonts.get(key)
    if f is None:
        f = pygame.font.Font(os.path.join(FONT_DIR, FONT_FILES[weight]), px)
        _fonts[key] = f
    return f


# Pretendard 에는 한자가 없어서, 한자(외국 지도자 대사)만 보조 글꼴(Noto Sans CJK SC 부분집합)로 그린다.
CJK_FALLBACK = "NotoSansCJKsc-Subset.otf"
_CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FA1F))


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in _CJK_RANGES)


def _cjk_font(size: int):
    px = font_px(size)
    key = (px, "cjk")
    f = _fonts.get(key)
    if f is None:
        path = os.path.join(FONT_DIR, CJK_FALLBACK)
        f = pygame.font.Font(path, px) if os.path.exists(path) else None
        _fonts[key] = f
    return f


def _runs(text: str):
    """(한자 여부, 문자열) 구간들."""
    out = []
    for ch in text:
        c = is_cjk(ch)
        if out and out[-1][0] == c:
            out[-1][1] += ch
        else:
            out.append([c, ch])
    return out


def _needs_fallback(text: str) -> bool:
    return any(is_cjk(ch) for ch in text) and _cjk_font(14) is not None


def measure(text: str, size: int, weight: str = "regular"):
    """글자 폭·높이(논리 좌표)."""
    u = UI["u"]
    if not _needs_fallback(text):
        w, h = font(size, weight).size(text)
        return w / u, h / u
    w = h = 0
    for c, part in _runs(text):
        pw, ph = (_cjk_font(size) if c else font(size, weight)).size(part)
        w, h = w + pw, max(h, ph)
    return w / u, h / u


def render_text(text: str, size: int, color, weight="regular"):
    """실제 픽셀 크기의 글자 이미지."""
    key = (text, font_px(size), tuple(color), weight)
    s = _text_cache.get(key)
    if s is None:
        if _needs_fallback(text):
            base = font(size, weight)
            parts = [((_cjk_font(size) if c else base), part) for c, part in _runs(text)]
            surfs = [(f, f.render(part, True, color)) for f, part in parts]
            asc = max(f.get_ascent() for f, _ in surfs)
            desc = max(-f.get_descent() for f, _ in surfs)
            s = pygame.Surface((sum(t.get_width() for _, t in surfs), asc + desc), pygame.SRCALPHA)
            x = 0
            for f, t in surfs:
                s.blit(t, (x, asc - f.get_ascent()))     # 기준선 맞춤
                x += t.get_width()
        else:
            s = font(size, weight).render(text, True, color)
        if len(_text_cache) > 6000:
            _text_cache.clear()
        _text_cache[key] = s
    return s


def fmt_money(v: float) -> str:
    if abs(v) >= 1e8:
        return f"{v/1e8:,.2f}조"
    if abs(v) >= 1e4:
        return f"{v/1e4:,.1f}억"
    return f"{v:,.0f}만"


def fmt_num(v: float, digits=0) -> str:
    return f"{v:,.{digits}f}"
