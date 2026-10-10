"""국기: 배경 무늬 + 문양 + 색 세 가지(배경 색1·색2, 문양 색). pygame 없이 쓰는 데이터 부분.

국기 = {"bg": 배경 키, "c1": (r,g,b), "c2": (r,g,b), "em": 문양 키, "ec": (r,g,b), "ec2": (r,g,b)[, "preset": 역사 국기 키]}
배경 색 2는 단색이 아닌 배경에, 문양 색 2는 두 색 문양(TWO_TONE_EMBLEMS)에만 쓰인다.
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
    ("none", "없음"), ("taegeuk", "태극"), ("disc", "원"), ("star5", "별"), ("diamond", "마름모"), ("shield", "방패"),
    ("crown", "왕관"), ("pine", "소나무"), ("flower", "무궁화"), ("wave", "물결"), ("mountain", "산"), ("cloud", "구름"),
    ("manji", "만자(卍)"), ("hexagram", "육망성"), ("cross", "십자"), ("crescent_star", "별과 초승달"), ("om", "옴(ॐ)"),
    ("yinyang", "도교 태극"),
    ("dragon", "용"), ("tiger", "호랑이"), ("phoenix", "봉황"), ("cheonma", "천마"), ("samjogo", "삼족오"),
)
# 편집 창 줄 배치(줄마다 6칸)
EMBLEM_ROWS = (
    ("none", "taegeuk", "disc", "star5", "diamond", "shield"),
    ("crown", "pine", "flower", "wave", "mountain", "cloud"),
    ("manji", "hexagram", "cross", "crescent_star", "om", "yinyang"),
    ("dragon", "tiger", "phoenix", "cheonma", "samjogo"),
)
MASK_EMBLEMS = {"pine", "flower", "phoenix", "cloud", "om", "tiger", "dragon", "cheonma", "samjogo"}
TWO_TONE_EMBLEMS = {"taegeuk", "yinyang", "flower"}      # 문양 색 2를 쓰는 문양   # assets/emblems/<키>.png

# 역사 국기: 고르면 배경·문양·색 대신 그대로 쓴다
PRESETS = (("taegeukgi", "태극기"), ("ingonggi", "인공기"), ("eogi", "조선 어기"), ("goryeo", "고려 의장기"))

BG_KEYS = [k for k, _ in BACKGROUNDS]
EMBLEM_KEYS = [k for k, _ in EMBLEMS]
PRESET_KEYS = [k for k, _ in PRESETS]
# 예전 저장 파일의 키
ALIASES = {"star6": "hexagram", "diag": "diag_up", "nordic": "cross", "canton": "quarters", "chevron": "v2",
           "crescent": "crescent_star", "samtaegeuk": "taegeuk", "triangle": "mountain", "hexagon": "diamond",
           "arrow": "cloud", "bolt": "cloud"}


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
    for k, d in (("c1", (40, 90, 200)), ("c2", (255, 255, 255)), ("ec", (255, 255, 255)), ("ec2", (0, 71, 160))):
        c = f.get(k, d)
        f[k] = tuple(max(0, min(255, int(v))) for v in (list(c) + [0, 0, 0])[:3])
    return f


WHITE, BLACK = (255, 255, 255), (0, 0, 0)
AI_PATTERN_BGS = [k for k in BG_KEYS if k not in ("solid", "border")]


def _darker(c, k=0.45):
    return tuple(int(v * (1 - k)) for v in c)


def default_flag(color_hex: str, seed) -> dict:
    """AI·반란 세력의 기본 국기(같은 seed 면 항상 같다). 게임 난수에는 손대지 않는다.
    - 배경: 단색 25% · 윤곽선 25% · 나머지 무늬 50%, 배경 색 1은 세력 색, 배경 색 2는 흰색
    - 단색·윤곽선: 문양 하나('없음' 제외), 문양 색 1 흰색
      (꽃 가운데 = 배경 색 1, 도교 태극 색 2 = 검정, 태극 아래쪽 = 배경 색 1을 어둡게)
    - 나머지 무늬: 문양 없음
    - 역사 국기는 쓰지 않는다(플레이어 전용)."""
    rng = random.Random(f"flag:{seed}")
    c1 = hex2rgb(color_hex)
    roll = rng.random()
    if roll < 0.25:
        bg = "solid"
    elif roll < 0.5:
        bg = "border"
    else:
        bg = rng.choice(AI_PATTERN_BGS)
    # 문양 색 2는 지금 문양이 한 색이어도 미리 알맞은 값을 넣어 둔다(편집 창에서 두 색 문양으로 바꿔도 보이게)
    fl = {"bg": bg, "c1": c1, "c2": WHITE, "em": "none", "ec": WHITE, "ec2": _darker(c1)}
    if bg in ("solid", "border"):
        em = rng.choice(EMBLEM_KEYS[1:])
        fl["em"] = em
        fl["ec2"] = {"flower": c1, "yinyang": BLACK}.get(em, _darker(c1))
    return fl


def random_flag(rng=None) -> dict:
    """국기 만들기 [무작위]: 선명한 색 하나를 고른 뒤 AI 국기 규칙을 따른다."""
    import colorsys
    rng = rng or random.Random()
    r, g, b = colorsys.hsv_to_rgb(rng.random(), rng.uniform(0.55, 0.9), rng.uniform(0.45, 0.85))
    return default_flag(rgb2hex((r * 255, g * 255, b * 255)), rng.random())


def uses_c2(fl) -> bool:
    return fl.get("bg") != "solid"


def uses_ec(fl) -> bool:
    return fl.get("em") != "none"


def uses_ec2(fl) -> bool:
    return fl.get("em") in TWO_TONE_EMBLEMS


def faction_flag(f) -> dict:
    """세력의 국기: 직접 만든 국기가 있으면 그것, 없으면 기본 국기."""
    fl = getattr(f, "flag", None)
    return normalize(fl) if fl else default_flag(f.color, f"{f.id}:{f.name}")
