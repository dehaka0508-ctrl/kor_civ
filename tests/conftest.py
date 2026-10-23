"""공통 시험 설정."""
import pytest

from korciv import slots


@pytest.fixture(autouse=True)
def grow_slots_for_setup(monkeypatch):
    """건물 슬롯(v1.3.8): 예전 시험은 r.b[키] = 단계 로 상황을 만든다. 빈 칸이 없으면 칸을 늘려 그대로 넣는다
    (게임 규칙 자체를 보는 시험은 monkeypatch 로 다시 False 로 둔다)."""
    monkeypatch.setattr(slots, "GROW_WHEN_FULL", True)
