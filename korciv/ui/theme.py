"""색·글꼴 토큰 (기획서 13절 시각 디자인)."""
from __future__ import annotations

import os

import pygame

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
FONT_FILES = {"regular": "Pretendard-Regular.ttf", "semibold": "Pretendard-SemiBold.ttf",
              "bold": "Pretendard-Bold.ttf",
              "serif": "NanumMyeongjo-Bold.ttf",         # 제목·이름 등 명조(나눔명조, OFL)
              "title": "NanumMyeongjo-ExtraBold.ttf"}    # 큰 제목·국가명·버튼 글씨
SERIF_WEIGHTS = ("serif", "title")
# 화면 장식에 쓰는 한자(명조 한자 글꼴 NotoSerifKR-Hanja-Subset.otf 에 들어 있는 글자, tools/build_serif_font.py)
SOLAR_TERMS = (("소한", "小寒"), ("대한", "大寒"), ("입춘", "立春"), ("우수", "雨水"), ("경칩", "驚蟄"), ("춘분", "春分"),
               ("청명", "淸明"), ("곡우", "穀雨"), ("입하", "立夏"), ("소만", "小滿"), ("망종", "芒種"), ("하지", "夏至"),
               ("소서", "小暑"), ("대서", "大暑"), ("입추", "立秋"), ("처서", "處暑"), ("백로", "白露"), ("추분", "秋分"),
               ("한로", "寒露"), ("상강", "霜降"), ("입동", "立冬"), ("소설", "小雪"), ("대설", "大雪"), ("동지", "冬至"))
UI_HANJA = "".join(h for _, h in SOLAR_TERMS) + "朝報北建國號旗君主天下形勢封地"


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
    """고지도 + 단청 색: 한지(패널), 쪽빛(주 버튼·상단 바), 주홍(위험·턴 종료), 금(테두리·장식), 먹(글자)."""

    def __init__(self, dark=False):
        self.set_dark(dark)

    def set_dark(self, dark):
        self.dark = dark
        # 어두운 모드와 상관없이 같은 장식 색
        self.indigo = hex2rgb("#1E3550")
        self.indigo_dk = hex2rgb("#111E31")
        self.indigo_lt = hex2rgb("#2E4C70")
        self.gold = hex2rgb("#C29A55")
        self.gold_lt = hex2rgb("#E2C58A")
        self.vermilion = hex2rgb("#B5382A")
        self.jade = hex2rgb("#2F7D62")
        self.ink = hex2rgb("#2B2620")
        if not dark:
            self.bg = hex2rgb("#EFE6D2")
            self.panel = hex2rgb("#F7F1E3")
            self.panel_alt = hex2rgb("#EBE1CB")
            self.text = hex2rgb("#2B2620")
            self.muted = hex2rgb("#75695A")
            self.border = hex2rgb("#CDBB92")
            self.sea = hex2rgb("#BFD0CA")
            self.sea_line = hex2rgb("#A7BDB8")
            self.sea_ink = hex2rgb("#4C6B6E")
            self.paper = hex2rgb("#EFE6D2")
            self.neutral = hex2rgb("#E6DCC4")
            self.unexplored = hex2rgb("#CFC8B8")
            self.shadow = (40, 25, 10, 45)
            self.accent = self.indigo
            self.good = hex2rgb("#2F7D62")
            self.bad = hex2rgb("#B5382A")
        else:
            self.bg = hex2rgb("#141A24")
            self.panel = hex2rgb("#1D2532")
            self.panel_alt = hex2rgb("#27303F")
            self.text = hex2rgb("#ECE4D2")
            self.muted = hex2rgb("#A59C8A")
            self.border = hex2rgb("#5A5238")
            self.sea = hex2rgb("#1B2B35")
            self.sea_line = hex2rgb("#2A3F4B")
            self.sea_ink = hex2rgb("#8FB0B3")
            self.paper = hex2rgb("#1A202A")
            self.neutral = hex2rgb("#3A3830")
            self.unexplored = hex2rgb("#2B2B2A")
            self.shadow = (0, 0, 0, 90)
            self.accent = hex2rgb("#3B5E8C")
            self.good = hex2rgb("#4FAF86")
            self.bad = hex2rgb("#E0604E")
        self.warn = hex2rgb("#C77A1A")
        self.province_line = hex2rgb("#8A8F98")
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
# 명조(serif·title)로 쓰는 장식 한자(UI_HANJA)는 명조 한자 글꼴(Noto Serif KR 부분집합)로 그린다.
CJK_FALLBACK = "NotoSansCJKsc-Subset.otf"
SERIF_HANJA = "NotoSerifKR-Hanja-Subset.otf"
_UI_HANJA_SET = set(UI_HANJA)
_CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FA1F))


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in _CJK_RANGES)


def _cjk_font(size: int, part: str = "", weight: str = "regular"):
    px = font_px(size)
    name = CJK_FALLBACK
    if part and weight in SERIF_WEIGHTS and all(ch in _UI_HANJA_SET for ch in part):
        name = SERIF_HANJA
    key = (px, name)
    f = _fonts.get(key)
    if f is None:
        path = os.path.join(FONT_DIR, name)
        f = pygame.font.Font(path, px) if os.path.exists(path) else None
        if f is None and name != CJK_FALLBACK:
            f = _cjk_font(size)
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
        pw, ph = (_cjk_font(size, part, weight) if c else font(size, weight)).size(part)
        w, h = w + pw, max(h, ph)
    return w / u, h / u


def render_text(text: str, size: int, color, weight="regular"):
    """실제 픽셀 크기의 글자 이미지."""
    key = (text, font_px(size), tuple(color), weight)
    s = _text_cache.get(key)
    if s is None:
        if _needs_fallback(text):
            base = font(size, weight)
            parts = [((_cjk_font(size, part, weight) if c else base), part) for c, part in _runs(text)]
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


def solar_term(month: int, week: int):
    """달·주로 어림한 24절기 (한글, 한자). 매달 1~2주는 앞 절기, 3주부터는 뒤 절기."""
    i = (month - 1) * 2 + (0 if week <= 2 else 1)
    return SOLAR_TERMS[i % 24]


_paper_cache: dict = {}


def paper_texture(dark=False, size=384):
    """한지 결(타일). 곱하기(BLEND_RGB_MULT)로 덮는다: 255 = 그대로, 낮을수록 어둡게."""
    key = (dark, size)
    s = _paper_cache.get(key)
    if s is None:
        import random
        rnd = random.Random(7)
        s = pygame.Surface((size, size))
        s.fill((255, 255, 255))
        for cell, amp in ((48, 5), (12, 4), (3, 3)):
            n = size // cell + 1
            small = pygame.Surface((n, n))
            for yy in range(n):
                for xx in range(n):
                    v = 255 - int(rnd.random() * amp)
                    small.set_at((xx, yy), (v, v, v))
            big = pygame.transform.smoothscale(small, (size + cell, size + cell))
            s.blit(big, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
            # 결 이음매가 보이지 않게 위·왼쪽 가장자리를 맞춘다
        fib = pygame.Surface((size, size))
        fib.fill((255, 255, 255))
        for _ in range(size * size // 700):
            x, y = rnd.random() * size, rnd.random() * size
            ang = rnd.random() * 3.1416
            L = rnd.uniform(3, 14)
            v = rnd.choice((242, 248))
            import math
            pygame.draw.line(fib, (v, v, v), (x, y), (x + math.cos(ang) * L, y + math.sin(ang) * L))
        s.blit(fib, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        if dark:
            s.fill((255, 255, 255), special_flags=pygame.BLEND_RGB_MAX)  # 어두운 모드는 결을 쓰지 않는다
        _paper_cache[key] = s
    return s


def fmt_money(v: float) -> str:
    if abs(v) >= 1e8:
        return f"{v/1e8:,.2f}조"
    if abs(v) >= 1e4:
        return f"{v/1e4:,.1f}억"
    return f"{v:,.0f}만"


def fmt_num(v: float, digits=0) -> str:
    return f"{v:,.{digits}f}"
