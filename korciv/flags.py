"""국기: 배경 무늬 + 문양 + 색 세 가지(배경 색1·색2, 문양 색). pygame 없이 쓰는 데이터 부분.

국기 = {"bg": 배경 키, "c1": (r,g,b), "c2": (r,g,b), "em": 문양 키, "ec": (r,g,b)[, "preset": 역사 국기 키]}
플레이어는 시작 화면에서 직접 만들고, AI·반란 세력은 세력 색으로 정해진 기본 국기를 쓴다.
"""
from __future__ import annotations

import random

# 배경 무늬: 키, 이름 (편집 창에 5×2로 놓인다)
BACKGROUNDS = (
    ("solid", "단색"),
    ("h2", "상하 이등분"),
    ("v2", "좌우 이등분"),
    ("v3", "세로 삼등분"),
    ("h3", "가로 삼등분"),
    ("diag_up", "우상향 대각선"),
    ("diag_down", "우하향 대각선"),
    ("cross", "잉글랜드식 십자"),
    ("quarters", "가로세로 4등분"),
    ("border", "윤곽선"),
)

# 문양: 키, 이름 (편집 창에 6×4로 놓인다). "none" 포함 24칸.
EMBLEMS = (
    # 도형
    ("none", "없음"), ("disc", "원"), ("ring", "고리"), ("taegeuk", "태극"), ("star5", "오각별"),
    ("shield", "방패"), ("crown", "왕관"), ("flower", "꽃"), ("pine", "소나무"), ("saltire", "X자"),
    ("diamond", "마름모"), ("wave", "물결"), ("mountain", "산"), ("bolt", "번개"),
    # 종교
    ("manji", "만자(卍)"), ("hexagram", "육망성"), ("cross", "십자"), ("crescent_star", "초승달과 별"),
    ("om", "옴(ॐ)"), ("yinyang", "도교 태극"),
    # 동물
    ("tiger", "호랑이 머리"), ("dragon", "용"), ("cheonma", "천마(천마도)"), ("samjogo", "삼족오"),
)
MASK_EMBLEMS = {"pine", "om", "tiger", "dragon", "cheonma", "samjogo"}   # assets/emblems/<키>.png

# 역사 국기: 고르면 배경·문양·색 대신 그대로 쓴다
PRESETS = (("taegeukgi", "태극기"), ("ingonggi", "인공기"), ("eogi", "조선 어기"), ("goryeo", "고려 의장기"))

BG_KEYS = [k for k, _ in BACKGROUNDS]
EMBLEM_KEYS = [k for k, _ in EMBLEMS]
PRESET_KEYS = [k for k, _ in PRESETS]
# 예전 저장 파일의 키
ALIASES = {"star6": "hexagram", "diag": "diag_up", "nordic": "cross", "canton": "quarters", "chevron": "v2",
           "crescent": "crescent_star", "samtaegeuk": "taegeuk", "triangle": "mountain", "hexagon": "diamond",
           "arrow": "bolt"}


def hex2rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb2hex(c) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(int(v) for v in c))


def normalize(flag) -> dict:
    """빠진 키·잘못된 값을 채워 넣은 국기."""
    f = dict(flag or {})
    for k in ("bg", "em"):
        f[k] = ALIASES.get(f.get(k), f.get(k))
    if f.get("preset") not in PRESET_KEYS:
        f.pop("preset", None)
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
    return {"bg": rng.choice(["solid", "solid", "h2", "v3", "h3", "border", "quarters", "cross", "diag_up"]),
            "c1": c1, "c2": dark if light else white,
            "em": rng.choice(EMBLEM_KEYS[1:]), "ec": dark if light else white}


def faction_flag(f) -> dict:
    """세력의 국기: 직접 만든 국기가 있으면 그것, 없으면 기본 국기."""
    fl = getattr(f, "flag", None)
    return normalize(fl) if fl else default_flag(f.color, f"{f.id}:{f.name}")
