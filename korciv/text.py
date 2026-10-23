"""한국어 문구 도우미(v1.3.1): 받침에 맞는 조사를 붙인다.

    josa("석유", "이/가")   → "석유가"
    josa("전기", "을/를")   → "전기를"
    josa("서울", "으로/로") → "서울로"   (ㄹ 받침은 '로')
    josa("12", "이/가")     → "12가"     (숫자는 읽는 소리로: 십이)
    josa("금강산(강원)", "은/는") → "금강산(강원)은"  (닫는 괄호·따옴표는 건너뛰고 앞 글자로)

'이(가)'처럼 괄호로 두 조사를 함께 쓰지 않도록 화면·알림 문구에서 쓴다. pygame 없이 엔진에서도 쓴다.
"""
from __future__ import annotations

# 조사 쌍 → (받침 있을 때, 받침 없을 때). 어느 순서로 써도 된다
_PAIRS = {}
for _a, _b in (("이", "가"), ("을", "를"), ("은", "는"), ("과", "와"), ("으로", "로"), ("이나", "나"),
               ("이랑", "랑"), ("아", "야"), ("이라", "라"), ("이며", "며"), ("이고", "고"), ("이다", "다"),
               ("으로서", "로서"), ("으로써", "로써"), ("이었다", "였다"), ("이에요", "예요")):
    _PAIRS[f"{_a}/{_b}"] = _PAIRS[f"{_b}/{_a}"] = (_a, _b)

_SKIP = set(")]}」』》〉>'\"’”. ·…")
# 숫자 끝자리 읽는 소리의 받침: 0 영 1 일 2 이 3 삼 4 사 5 오 6 육 7 칠 8 팔 9 구 (ㄹ 은 8)
_DIGIT = {"0": 21, "1": 8, "2": 0, "3": 16, "4": 0, "5": 0, "6": 1, "7": 8, "8": 8, "9": 0}
# 10·100·1000·10000 처럼 0으로 끝나면 십(ㅂ)·백(ㄱ)·천(ㄴ)·만(ㄴ)
_TENS = {1: 17, 2: 1, 3: 4}
# 영문 끝 글자: l·r(엘·알 → ㄹ), m·n(엠·엔 → 받침), 그 밖은 받침 없음으로 본다
_LATIN = {"l": 8, "r": 8, "m": 16, "n": 4}


def jongseong(word) -> int | None:
    """마지막 글자의 받침 번호(0 = 받침 없음, 8 = ㄹ). 알 수 없으면 None."""
    s = str(word).rstrip()
    while s and s[-1] in _SKIP:
        s = s[:-1].rstrip()
    if not s:
        return None
    ch = s[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28
    if ch.isdigit() and ch in _DIGIT:
        n = s.replace(",", "")
        digits = n[len(n.rstrip("0123456789")):]
        if ch == "0" and digits.strip("0"):
            zeros = len(digits) - len(digits.rstrip("0"))
            return _TENS.get(zeros, 4)
        return _DIGIT[ch]
    if ch.isascii() and ch.isalpha():
        return _LATIN.get(ch.lower(), 0)
    if ch == "%":
        return 0                                   # 퍼센트
    return None


def particle(word, pair: str) -> str:
    """word 뒤에 붙일 조사만(예: particle("서울", "이/가") → "이")."""
    with_b, without_b = _PAIRS[pair]
    j = jongseong(word)
    if j is None:
        return without_b
    if with_b.startswith("으로"):
        return with_b if j not in (0, 8) else without_b    # ㄹ 받침은 '로'
    return with_b if j else without_b


def josa(word, pair: str) -> str:
    """word 에 받침에 맞는 조사를 붙인 문자열(예: josa("석유", "이/가") → "석유가")."""
    return f"{word}{particle(word, pair)}"


def fmt_points(value: float, signed=False) -> str:
    """표시만 소수 둘째 자리까지. 실제 자원과 생산량은 반올림하지 않는다."""
    if abs(value) < .005:
        value = 0.0
    return format(value, "+,.2f" if signed else ",.2f").rstrip("0").rstrip(".")
