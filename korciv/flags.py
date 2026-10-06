"""국기: 배경 무늬 + 문양 + 색 세 가지(배경 색1·색2, 문양 색). pygame 없이 쓰는 데이터 부분.

국기 = {"bg": 배경 키, "c1": (r,g,b), "c2": (r,g,b), "em": 문양 키, "ec": (r,g,b)}
플레이어는 시작 화면에서 직접 만들고, AI·반란 세력은 세력 색으로 정해진 기본 국기를 쓴다.
"""
from __future__ import annotations

import random

# 배경 무늬: 키, 이름
BACKGROUNDS = (
    ("solid", "단색"),
    ("h2", "가로 2분할"),
    ("v2", "세로 2분할"),
    ("h3", "가로 3줄"),
    ("v3", "세로 3줄"),
    ("diag", "대각선"),
    ("nordic", "북유럽 십자"),
    ("border", "테두리"),
    ("canton", "좌상단 칸"),
    ("chevron", "왼쪽 삼각형"),
)

# 문양 (임시 목록 — 확정 전): 키, 이름. "none" 은 문양 없음으로 20종에 넣지 않는다.
EMBLEMS = (
    ("none", "없음"),
    ("disc", "원(태양)"),
    ("ring", "고리"),
    ("star5", "오각별"),
    ("star6", "육각별"),
    ("crescent", "초승달"),
    ("crescent_star", "초승달과 별"),
    ("taegeuk", "태극"),
    ("samtaegeuk", "삼태극"),
    ("cross", "십자"),
    ("saltire", "X자"),
    ("diamond", "마름모"),
    ("triangle", "삼각형"),
    ("hexagon", "육각형"),
    ("shield", "방패"),
    ("crown", "왕관"),
    ("mountain", "산"),
    ("wave", "물결"),
    ("bolt", "번개"),
    ("flower", "꽃(무궁화)"),
    ("arrow", "화살표"),
)
BG_KEYS = [k for k, _ in BACKGROUNDS]
EMBLEM_KEYS = [k for k, _ in EMBLEMS]


def hex2rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb2hex(c) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(int(v) for v in c))


def normalize(flag) -> dict:
    """빠진 키·잘못된 값을 채워 넣은 국기."""
    f = dict(flag or {})
    if f.get("bg") not in BG_KEYS:
        f["bg"] = "solid"
    if f.get("em") not in EMBLEM_KEYS:
        f["em"] = "none"
    for k, d in (("c1", (40, 90, 200)), ("c2", (255, 255, 255)), ("ec", (255, 255, 255))):
        c = f.get(k, d)
        f[k] = tuple(max(0, min(255, int(v))) for v in (list(c) + [0, 0, 0])[:3])
    return f


def default_flag(color_hex: str, seed) -> dict:
    """세력 색에서 만든 기본 국기(같은 seed 면 항상 같다). 게임 난수에는 손대지 않는다."""
    rng = random.Random(f"flag:{seed}")
    c1 = hex2rgb(color_hex)
    light = sum(c1) / 3 > 150
    white, dark = (255, 255, 255), (30, 30, 40)
    return {"bg": rng.choice(["solid", "solid", "h2", "v3", "border", "canton", "chevron", "nordic"]),
            "c1": c1, "c2": dark if light else white,
            "em": rng.choice(EMBLEM_KEYS[1:]), "ec": dark if light else white}


def faction_flag(f) -> dict:
    """세력의 국기: 직접 만든 국기가 있으면 그것, 없으면 기본 국기."""
    fl = getattr(f, "flag", None)
    return normalize(fl) if fl else default_flag(f.color, f"{f.id}:{f.name}")
