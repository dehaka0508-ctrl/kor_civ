"""지도자 대사(팝업): korciv/data/leader_lines.json (원본 엑셀 → tools/import_leader_lines.py)."""
from __future__ import annotations

import json
import os

KINDS = ("meet", "friend", "war", "denounce", "alliance", "peace", "defeated", "victory")
TITLES = {"meet": "첫 만남", "friend": "우호 선언", "war": "전쟁 발발", "denounce": "비난",
          "alliance": "동맹 체결", "peace": "휴전", "defeated": "멸망", "victory": "패배"}
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "leader_lines.json")
_lines = None


def lines() -> dict:
    global _lines
    if _lines is None:
        try:
            with open(_PATH, encoding="utf-8") as f:
                _lines = json.load(f)
        except OSError:
            _lines = {}
    return _lines


def line(leader_key: str, kind: str) -> str:
    return lines().get(leader_key, {}).get(kind, "")


def language(leader_key: str) -> str:
    return lines().get(leader_key, {}).get("lang", "")
