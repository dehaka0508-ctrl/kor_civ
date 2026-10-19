"""한국어 조사 자동 판별(v1.3.1)과 '이(가)'식 괄호 병기 제거."""
import pathlib
import re

from korciv import negotiation as NG
from korciv.text import josa, particle


def test_josa_by_final_consonant():
    assert josa("석유", "이/가") == "석유가" and josa("전기", "이/가") == "전기가" and josa("석탄", "이/가") == "석탄이"
    assert josa("특산물", "을/를") == "특산물을" and josa("전기", "을/를") == "전기를"
    assert josa("대한", "와/과") == "대한과" and josa("고구려", "과/와") == "고구려와"
    assert josa("조선", "은/는") == "조선은" and josa("신라", "은/는") == "신라는"
    # 으로/로: ㄹ 받침은 '로'
    assert josa("서울", "으로/로") == "서울로" and josa("부산", "으로/로") == "부산으로" and josa("제주", "으로/로") == "제주로"


def test_josa_numbers_brackets_latin():
    # 숫자는 읽는 소리로: 1(일)·3(삼)·6(육)·10(십)·100(백)·1,000(천)은 받침, 2·4·5·9는 받침 없음
    assert [particle(n, "이/가") for n in ("1", "2", "3", "4", "6", "9", "10", "100", "1,000", "1,002")] == \
        ["이", "가", "이", "가", "이", "가", "이", "이", "이", "가"]
    assert particle("1", "으로/로") == "로" and particle("3", "으로/로") == "으로"
    # 닫는 괄호·따옴표는 건너뛴다
    assert josa("금강산(강원)", "은/는") == "금강산(강원)은" and josa("「쌀」", "이/가") == "「쌀」이"
    assert josa("AI", "이/가") == "AI가" and josa("URL", "을/를") == "URL을"


def test_no_parenthesized_particles_in_player_text():
    """화면·알림 문구에 '이(가)'·'을(를)'·'와(과)'·'은(는)'·'(으)로'가 남아 있지 않다."""
    root = pathlib.Path(__file__).resolve().parent.parent / "korciv"
    bad = re.compile(r"이\(가\)|을\(를\)|와\(과\)|과\(와\)|은\(는\)|\(으\)로")
    hits = []
    for f in root.rglob("*.py"):
        if f.name == "text.py":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if bad.search(line):
                hits.append(f"{f.name}:{i}")
    assert not hits, hits


def test_negotiation_nothing_to_give_message(monkeypatch):
    """'내줄 석유이 없습니다'·'내줄 전기이 없습니다' 같은 비문이 나오지 않는다."""
    from test_engine import new_game
    g = new_game(player_start="S002", n_enemies=1)
    monkeypatch.setattr(NG, "supply_total", lambda g_, fid, res: 0)
    msgs = {res: NG.reserve(g, 1, 0, res, 3, True)[2] for res in ("oil", "coal", "elec")}
    assert msgs == {"oil": "내줄 석유가 없습니다", "coal": "내줄 석탄이 없습니다", "elec": "내줄 전기가 없습니다"}
