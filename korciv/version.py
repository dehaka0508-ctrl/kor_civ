"""게임 버전.

규칙 (주.부.수)
- 수(세 번째): 이어서 플레이할 수 있는 패치(UI 개선·버그 수정 등) → 예전 세이브를 그대로 불러올 수 있다.
- 부(두 번째): 이어서 플레이할 수 없는 내용 패치(밸런스·지역 정보 등) → 수 0으로.
- 주(첫 번째): 게임을 크게 바꾸는 중대한 업데이트 → 부·수 0으로.
세이브 파일에는 항상 버전을 적고, 주·부가 같은 세이브만 [이어하기]에 보인다.
"""
VERSION = "1.24.0"
RELEASE_DATE = "2026-10-08"


def parse(v):
    try:
        major, minor, patch = (int(x) for x in str(v).split("."))
        return major, minor, patch
    except (TypeError, ValueError):
        return None


def compatible(v) -> bool:
    """이 버전의 세이브를 지금 게임에서 이어서 할 수 있는가(주·부가 같으면 가능)."""
    p, cur = parse(v), parse(VERSION)
    return p is not None and p[:2] == cur[:2]
